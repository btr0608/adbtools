from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from PyQt5.QtCore import QThread, pyqtSignal

from ..core.adb_client import AdbClient
from ..core.utils import start_worker


@dataclass
class DeviceInfo:
    """设备富信息。向后兼容 (serial, state) 元组解包：前两字段顺序固定。"""
    serial: str
    state: str
    model: str = ""
    android_version: str = ""
    root_state: str = ""
    is_emulator: bool = False       # 模拟器标记：True 表示 emulator/virtual 环境
    characteristics: str = ""       # ro.build.characteristics 原始值
    thermal_available: bool = False  # 是否有 /sys/class/thermal（真机通常有）

    def __iter__(self):
        yield self.serial
        yield self.state

    def display_text(self) -> str:
        """下拉框显示文本：设备名 (IP:端口) Android版本。"""
        label = self.model or self.serial
        tag = " [模拟器]" if self.is_emulator else ""
        text = f"{label} ({self.serial}){tag}"
        if self.android_version:
            text += f" Android {self.android_version}"
        return text


# ─────────── 设备类型检测 ───────────

# emulator 识别关键字（大小写不敏感）
_EMULATOR_KEYWORDS = ("emulator", "virtual", "generic", "sdk", "vbox", "nox", "mumu", "bluestacks", "ldplayer", "koplayer", "andy")


def _guess_emulator(model: str, characteristics: str, serial: str) -> bool:
    """综合 model / characteristics / serial 特征判断是否模拟器。"""
    serial_low = serial.lower() if serial else ""
    # serial 以 emulator- 开头 → 一定是模拟器
    if serial_low.startswith("emulator-"):
        return True
    text = f"{model} {characteristics}".lower()
    for kw in _EMULATOR_KEYWORDS:
        if kw in text:
            return True
    return False


class DeviceDetectorWorker(QThread):
    """异步探测设备类型（模拟器 / 真机）。

    执行 getprop ro.product.model + ro.build.characteristics，
    同时探测 /sys/class/thermal/ 是否存在。
    """

    result = pyqtSignal(str, bool, str, str, bool)
    # (serial, is_emulator, model, characteristics, thermal_available)

    def __init__(self, adb_client, serial: str):
        super().__init__()
        self.adb_client = adb_client
        self.serial = serial

    def run(self):
        serial = self.serial
        model = ""
        characteristics = ""
        thermal_avail = False

        try:
            import subprocess
            from ..core.utils import get_startup_info

            # model
            r = subprocess.run(
                self.adb_client._build_cmd('shell', 'getprop', 'ro.product.model', serial_override=serial),
                capture_output=True, text=True, encoding='utf-8', errors='replace',
                timeout=5, startupinfo=get_startup_info(), cwd=self.adb_client.adb_home,
            )
            model = (r.stdout or "").strip()

            # characteristics
            r = subprocess.run(
                self.adb_client._build_cmd('shell', 'getprop', 'ro.build.characteristics', serial_override=serial),
                capture_output=True, text=True, encoding='utf-8', errors='replace',
                timeout=5, startupinfo=get_startup_info(), cwd=self.adb_client.adb_home,
            )
            characteristics = (r.stdout or "").strip()

            # thermal 探测
            r = subprocess.run(
                self.adb_client._build_cmd('shell', 'ls', '/sys/class/thermal/', serial_override=serial),
                capture_output=True, text=True, encoding='utf-8', errors='replace',
                timeout=5, startupinfo=get_startup_info(), cwd=self.adb_client.adb_home,
            )
            thermal_avail = bool((r.stdout or "").strip())

        except Exception:
            pass

        is_emulator = _guess_emulator(model, characteristics, serial)
        self.result.emit(serial, is_emulator, model, characteristics, thermal_avail)


class DeviceStateCheckWorker(QThread):
    """异步检查设备在线状态（adb get-state），避免主线程 5s 阻塞。"""

    state_result = pyqtSignal(str, str)  # serial, state ("device" / "offline" / "")

    def __init__(self, adb_client: AdbClient, serial: str):
        super().__init__()
        self.adb_client = adb_client
        self.serial = serial

    def run(self):
        import subprocess
        from ..core.utils import get_startup_info
        state = ""
        try:
            result = subprocess.run(
                self.adb_client._build_cmd('get-state', serial_override=self.serial),
                capture_output=True, text=True,
                encoding='utf-8', errors='replace', timeout=5,
                startupinfo=get_startup_info(), cwd=self.adb_client.adb_home,
            )
            state = (result.stdout or result.stderr or "").strip().lower()
        except Exception:
            state = ""
        self.state_result.emit(self.serial, state)


class DeviceRefreshWorker(QThread):
    devices_found = pyqtSignal(list, str)

    def __init__(self, adb_client: AdbClient, device_service: "DeviceService" = None):
        super().__init__()
        self.adb_client = adb_client
        self.device_service = device_service

    def run(self):
        devices, message = self.adb_client.list_devices()
        enriched: List[DeviceInfo] = []
        for serial, state in devices:
            info = None
            if self.device_service is not None:
                info = self.device_service.get_device_info(serial, fetch_if_missing=True)
            if info is None:
                info = DeviceInfo(serial=serial, state=state)
            else:
                info.state = state
            enriched.append(info)
        self.devices_found.emit(enriched, message)


class AdbConnectWorker(QThread):
    connect_done = pyqtSignal(bool, str)

    def __init__(self, adb_client: AdbClient, target: str, action: str = "connect"):
        super().__init__()
        self.adb_client = adb_client
        self.target = target
        self.action = action  # "connect" 或 "disconnect"

    def run(self):
        if self.action == "disconnect":
            success, message = self.adb_client.disconnect(self.target)
        else:
            success, message = self.adb_client.connect(self.target)
        self.connect_done.emit(success, message)


class DeviceService:
    def __init__(self, adb_client: AdbClient):
        self.adb_client = adb_client
        self._current_serial: Optional[str] = None
        self._refresh_callback = None
        self._connect_callback = None
        self._cache: Dict[str, DeviceInfo] = {}

    def set_refresh_callback(self, cb):
        self._refresh_callback = cb

    def set_connect_callback(self, cb):
        self._connect_callback = cb

    def get_device_info(self, serial: str, fetch_if_missing: bool = True) -> Optional[DeviceInfo]:
        """获取设备元数据，命中缓存直接返回；fetch_if_missing=False 时仅查缓存。"""
        if not serial:
            return None
        if serial in self._cache:
            return self._cache[serial]
        if not fetch_if_missing:
            return None
        info_dict, _ = self.adb_client.get_device_info(serial)
        info = DeviceInfo(
            serial=serial,
            state="device",
            model=info_dict.get("model", ""),
            android_version=info_dict.get("android_version", ""),
            root_state=info_dict.get("root_state", ""),
        )
        self._cache[serial] = info
        return info

    def invalidate(self, serial: Optional[str] = None) -> None:
        """失效缓存：传 serial 失效单台；None 失效全部。"""
        if serial is None:
            self._cache.clear()
        else:
            self._cache.pop(serial, None)

    def refresh_devices(self):
        worker = DeviceRefreshWorker(self.adb_client, self)
        if self._refresh_callback:
            worker.devices_found.connect(self._refresh_callback)
        start_worker(worker)

    def connect_network_device(self, target: str):
        worker = AdbConnectWorker(self.adb_client, target, action="connect")
        if self._connect_callback:
            worker.connect_done.connect(self._connect_callback)
        start_worker(worker)

    def disconnect_network_device(self, target: str = ""):
        worker = AdbConnectWorker(self.adb_client, target, action="disconnect")
        if self._connect_callback:
            worker.connect_done.connect(self._connect_callback)
        start_worker(worker)
