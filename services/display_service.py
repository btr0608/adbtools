"""DisplayService — 多屏幕枚举与别名管理（实车/台架 4~8 屏架构核心）。

职责：
- 后台线程跑 adb shell dumpsys SurfaceFlinger --display-id 枚举所有 display
- 缓存 display_list（id + 分辨率 + 别名）
- QSettings 持久化别名（按 display id 存）
- 失败时允许手动输入 display id
- 只在设备连上/手动刷新时枚举，不做定时器轮询
- 断连重连时清空缓存重查

被 scrcpy 投屏面板、截图面板等共享，避免各自检测。
"""

import re
import subprocess
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from PyQt5.QtCore import QObject, QSettings, QThread, pyqtSignal

from ..core.adb_client import AdbClient
from ..core.utils import get_startup_info


@dataclass
class DisplayInfo:
    """单个 display 的元信息。"""
    display_id: str           # "0", "1", "0x1" 等
    resolution: str = ""     # "1920x720" 格式，可能为空
    alias: str = ""           # 用户别名，如 "中控"、"仪表"；为空时用默认
    is_primary: bool = False  # 是否默认主屏（dumpsys 里标 default 的那个）

    @property
    def display_name(self) -> str:
        """显示名：优先用户别名，否则默认 '屏幕{N}'。"""
        if self.alias:
            return self.alias
        return f"屏幕{self.display_id}"

    @property
    def label(self) -> str:
        """下拉框显示文本：'别名 分辨率' 或 '屏幕0 1920x720'。"""
        name = self.display_name
        if self.resolution:
            return f"{name} {self.resolution}"
        return name


class DisplayEnumerationWorker(QThread):
    """异步枚举 display 列表。"""

    displays_found = pyqtSignal(list)  # List[DisplayInfo]
    failed = pyqtSignal(str)            # 错误信息

    def __init__(self, adb_client: AdbClient, serial: str):
        super().__init__()
        self.adb_client = adb_client
        self.serial = serial

    def run(self):
        try:
            cmd = self.adb_client._build_cmd(
                'shell', 'dumpsys SurfaceFlinger --display-id',
                serial_override=self.serial,
            )
            r = subprocess.run(
                cmd, capture_output=True, text=True,
                encoding='utf-8', errors='replace', timeout=10,
                startupinfo=get_startup_info(), cwd=self.adb_client.adb_home,
            )
            raw = (r.stdout or r.stderr or "").strip()
            if not raw:
                # 有些系统不支持 --display-id，降级尝试 dumpsys display
                cmd2 = self.adb_client._build_cmd(
                    'shell', 'dumpsys display',
                    serial_override=self.serial,
                )
                r2 = subprocess.run(
                    cmd2, capture_output=True, text=True,
                    encoding='utf-8', errors='replace', timeout=10,
                    startupinfo=get_startup_info(), cwd=self.adb_client.adb_home,
                )
                raw = (r2.stdout or r2.stderr or "").strip()
            displays = _parse_displays(raw)
            self.displays_found.emit(displays)
        except subprocess.TimeoutExpired:
            self.failed.emit("枚举 display 超时（10s）")
        except FileNotFoundError:
            self.failed.emit("未找到 adb 可执行文件")
        except Exception as e:
            self.failed.emit(f"枚举 display 失败: {e}")


def _parse_displays(raw: str) -> List[DisplayInfo]:
    """解析 dumpsys SurfaceFlinger --display-id 输出。

    典型输出格式（Android 10+）：
      Display 0: 1920x720 (default)
      Display 1: 1280x720

    旧格式（Android 7-9）：
      Display 0
      Display 1

    另一种格式（某些厂商）：
      Physical display #0: 1920x720
      DisplayDevice{... displayId=1 ...} 1280x720

    返回: List[DisplayInfo]
    """
    results: List[DisplayInfo] = []
    seen_ids = set()

    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue

        display_id: Optional[str] = None
        resolution: str = ""
        is_primary = False

        # 格式 1: "Display N: WxH (default)" / "Display N: WxH"
        m = re.match(r'Display\s+(\d+)\s*[:：]\s*(\d+x\d+)', line, re.IGNORECASE)
        if m:
            display_id = m.group(1)
            resolution = m.group(2)
            if '(default)' in line.lower() or 'default' in line.lower():
                is_primary = True

        # 格式 2: "Display N" (纯数字 id)
        if display_id is None:
            m2 = re.match(r'Display\s+(\d+)\s*$', line, re.IGNORECASE)
            if m2:
                display_id = m2.group(1)

        # 格式 3: "Physical display #N: WxH"
        if display_id is None:
            m3 = re.match(r'Physical\s+display\s+#?(\d+)\s*[:：]\s*(\d+x\d+)', line, re.IGNORECASE)
            if m3:
                display_id = m3.group(1)
                resolution = m3.group(2)

        # 格式 4: "DisplayDevice{... displayId=N ...}" + 分辨率
        if display_id is None:
            m4 = re.search(r'displayId\s*[=:]\s*(\d+)', line, re.IGNORECASE)
            if m4:
                display_id = m4.group(1)
                m4r = re.search(r'(\d+x\d+)', line)
                if m4r:
                    resolution = m4r.group(1)

        # 格式 5: 纯十六进制 id "0x1" "0x2"
        if display_id is None:
            m5 = re.match(r'^(0x[0-9a-fA-F]+)$', line)
            if m5:
                display_id = m5.group(1)

        if display_id and display_id not in seen_ids:
            seen_ids.add(display_id)
            results.append(DisplayInfo(
                display_id=display_id,
                resolution=resolution,
                is_primary=is_primary or len(results) == 0,  # 第一个默认 primary
            ))

    # 如果什么都没解析到，尝试把整段输出当作一个 display
    if not results and raw:
        results.append(DisplayInfo(
            display_id="0",
            resolution="",
            is_primary=True,
        ))

    return results


class DisplayService(QObject):
    """多屏幕枚举与别名管理服务。

    用法（main_window）：
        self.display_service = DisplayService(self.adb_client, self._settings)
        self.display_service.displays_updated.connect(self._on_displays_updated)
        self.display_service.start_enumeration(serial)  # 设备连上后调用
        ...
        # 手动刷新
        self.display_service.refresh(serial)
        # 重命名别名
        self.display_service.set_alias(display_id, "中控")
    """

    displays_updated = pyqtSignal(list)     # List[DisplayInfo]
    enumeration_started = pyqtSignal()
    enumeration_finished = pyqtSignal()
    enumeration_failed = pyqtSignal(str)    # 错误信息
    alias_changed = pyqtSignal(str, str)    # (display_id, new_alias)

    def __init__(self, adb_client: AdbClient, settings: QSettings):
        super().__init__()
        self.adb_client = adb_client
        self._settings = settings
        self._worker: Optional[DisplayEnumerationWorker] = None
        self._displays: List[DisplayInfo] = []
        self._serial: Optional[str] = None

    # ── 查询接口 ──

    @property
    def displays(self) -> List[DisplayInfo]:
        """当前缓存的 display 列表（可能为空）。"""
        return list(self._displays)

    def is_multi_display(self) -> bool:
        return len(self._displays) > 1

    def find_display(self, display_id: str) -> Optional[DisplayInfo]:
        for d in self._displays:
            if d.display_id == display_id:
                return d
        return None

    # ── 枚举控制 ──

    def start_enumeration(self, serial: str) -> None:
        """设备连上后异步枚举 display。serial 为空则清空缓存。"""
        if not serial:
            self.clear_cache()
            return
        self._serial = serial
        self._run_worker(serial)

    def refresh(self, serial: Optional[str] = None) -> None:
        """手动刷新屏列表（点"刷新屏列表"按钮触发）。"""
        s = serial or self._serial
        if not s:
            return
        self._run_worker(s)

    def clear_cache(self) -> None:
        """断连时清空缓存。"""
        self._displays = []
        self._serial = None
        self.displays_updated.emit([])

    def _run_worker(self, serial: str) -> None:
        if self._worker and self._worker.isRunning():
            self._worker.requestInterruption()
        self.enumeration_started.emit()
        self._worker = DisplayEnumerationWorker(self.adb_client, serial)
        self._worker.displays_found.connect(self._on_displays_found)
        self._worker.failed.connect(self._on_enum_failed)
        self._worker.finished.connect(self.enumeration_finished)
        self._worker.start()

    def _on_displays_found(self, raw_displays: List[DisplayInfo]) -> None:
        """枚举成功：合并别名后发信号。"""
        self._displays = raw_displays
        # 从 QSettings 加载别名
        for d in self._displays:
            d.alias = self._load_alias(self._serial or "", d.display_id)
        self.displays_updated.emit(self._displays)

    def _on_enum_failed(self, err: str) -> None:
        """枚举失败：保留空列表，允许手动输入。"""
        self._displays = []
        self.enumeration_failed.emit(err)
        self.displays_updated.emit([])

    # ── 别名 CRUD ──

    def _settings_group(self, serial: str) -> str:
        if not serial:
            return "displays/_default"
        return f"displays/{serial}"

    def _load_alias(self, serial: str, display_id: str) -> str:
        s = self._settings
        s.beginGroup(self._settings_group(serial))
        try:
            val = s.value(f"alias/{display_id}", "", type=str)
            return val or ""
        finally:
            s.endGroup()

    def set_alias(self, display_id: str, alias: str) -> None:
        """设置/更新别名。空串清除别名。"""
        s = self._settings
        s.beginGroup(self._settings_group(self._serial or ""))
        try:
            s.setValue(f"alias/{display_id}", alias)
            s.sync()
        finally:
            s.endGroup()
        # 同步更新缓存
        for d in self._displays:
            if d.display_id == display_id:
                d.alias = alias
                break
        self.alias_changed.emit(display_id, alias)
        self.displays_updated.emit(self._displays)

    def get_alias(self, display_id: str) -> str:
        """读取别名（优先缓存，再查 QSettings）。"""
        cached = self.find_display(display_id)
        if cached:
            return cached.alias
        return self._load_alias(self._serial or "", display_id)

    # ── 手动添加 ──

    def add_manual_display(self, display_id: str, resolution: str = "",
                           alias: str = "") -> None:
        """枚举失败时允许手动输入 display id。"""
        if not display_id:
            return
        if self.find_display(display_id):
            return
        self._displays.append(DisplayInfo(
            display_id=display_id,
            resolution=resolution,
            alias=alias,
            is_primary=(len(self._displays) == 1),
        ))
        if alias:
            self.set_alias(display_id, alias)
        self.displays_updated.emit(self._displays)
