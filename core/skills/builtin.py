"""内置 SkillPlugin 适配器（投屏 / Logcat / 应用管理 / 截图）。

每个适配器都是薄封装：复用现有 UI Panel 和 main_window 方法，
内部逻辑 0 改写。这样未来替换实现时只改一处。
"""

import os
import sys
from datetime import datetime
from typing import List, Optional

from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtCore import QUrl
from PyQt5.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QMessageBox, QPushButton, QVBoxLayout, QWidget
)

from ..skill_plugin import DEVICE_ANY, DEVICE_EMULATOR, DEVICE_REAL, SkillPlugin
from ...core.utils import COLOR_ERROR, COLOR_SUCCESS, start_worker
from ...ui.theme import (
    Buttons, IconHelper, Icons, Palette, field_label_style, make_section_header
)


# ──────────────────── 投屏（Scrcpy） ────────────────────

class ScrcpySkill(SkillPlugin):
    name = "投屏"
    icon_name = "SCREEN_MIRROR"
    category = "通用"
    supported_devices = [DEVICE_ANY]
    order = 1

    def get_panel(self) -> QWidget:
        # 懒创建：首次激活时才实例化
        if not hasattr(self, "_panel") or self._panel is None:
            from ...ui.panels.scrcpy_control_panel import ScrcpyControlPanel
            self._panel = ScrcpyControlPanel()
            # 注入 DisplayService
            ds = getattr(self.ctx, 'display_service', None)
            if ds:
                self._panel.set_display_service(ds)
        return self._panel


# ──────────────────── Logcat ────────────────────

class LogcatSkill(SkillPlugin):
    name = "Logcat"
    icon_name = "LOGCAT"
    category = "通用"
    supported_devices = [DEVICE_ANY]
    order = 2

    def get_panel(self) -> QWidget:
        if not hasattr(self, "_panel") or self._panel is None:
            from ...ui.panels.logcat_panel import LogcatPanel
            self._panel = LogcatPanel(
                self.ctx.logcat_service,
                self.ctx.get_serial_cb,
                self.ctx.adb_client,
            )
        return self._panel


# ──────────────────── 应用管理（合并安装 + 卸载，带右侧面板） ────────────────────

class AppManagementSkill(SkillPlugin):
    name = "应用管理"
    icon_name = "APP_BOX"
    category = "应用层"
    supported_devices = [DEVICE_ANY]
    order = 3

    def get_panel(self) -> QWidget:
        if not hasattr(self, "_panel") or self._panel is None:
            panel = QWidget()
            layout = QVBoxLayout(panel)
            layout.setContentsMargins(16, 16, 16, 16)
            layout.setSpacing(12)

            # 安装按钮
            install_btn = QPushButton("  安装 APK")
            install_btn.setIcon(IconHelper.icon(Icons.TOOLBOX_PLUS, 16))
            install_btn.setStyleSheet(Buttons.primary(icon_size="16px"))
            install_btn.setMinimumHeight(40)
            install_btn.setCursor(Qt.PointingHandCursor)
            install_btn.setToolTip("选择本地 APK 文件并安装到设备")
            install_btn.clicked.connect(self._install_apk)
            layout.addWidget(install_btn)

            # 卸载按钮
            uninstall_btn = QPushButton("  卸载 APK")
            uninstall_btn.setIcon(IconHelper.icon(Icons.TOOLBOX_MINUS, 16))
            uninstall_btn.setStyleSheet(Buttons.danger(icon_size="16px"))
            uninstall_btn.setMinimumHeight(40)
            uninstall_btn.setCursor(Qt.PointingHandCursor)
            uninstall_btn.setToolTip("从已安装应用列表中卸载所选包")
            uninstall_btn.clicked.connect(self._uninstall_apk)
            layout.addWidget(uninstall_btn)

            layout.addStretch()
            self._panel = panel
        return self._panel

    def _install_apk(self):
        cb = getattr(self, "_install_cb", None)
        if cb is not None:
            cb()

    def _uninstall_apk(self):
        cb = getattr(self, "_uninstall_cb", None)
        if cb is not None:
            cb()


# ──────────────────── 截图（panel 模式，支持多屏） ────────────────────

class ScreenshotWorker(QThread):
    """后台 QThread 执行单次截图。"""
    done = pyqtSignal(bool, str, str)  # ok, local_path, error

    def __init__(self, adb_client, remote_path: str, local_path: str,
                 display_id: str = ""):
        super().__init__()
        self.adb_client = adb_client
        self.remote_path = remote_path
        self.local_path = local_path
        self.display_id = display_id

    def run(self):
        import subprocess
        from ...core.utils import get_startup_info
        try:
            # 1. 设备端截图（支持 screencap -d <id> 指定屏幕）
            if self.display_id:
                screencap_cmd = f'screencap -d {self.display_id} -p {self.remote_path}'
            else:
                screencap_cmd = f'screencap -p {self.remote_path}'
            cmd1 = self.adb_client._build_cmd('shell', screencap_cmd)
            r1 = subprocess.run(cmd1, capture_output=True, text=True,
                                encoding='utf-8', errors='replace', timeout=10,
                                startupinfo=get_startup_info(), cwd=self.adb_client.adb_home)
            if r1.returncode != 0:
                self.done.emit(False, "", f"设备端截图失败: {(r1.stderr or r1.stdout or '').strip()}")
                return
            # 2. pull 到本地
            cmd2 = self.adb_client._build_cmd('pull', self.remote_path, self.local_path)
            r2 = subprocess.run(cmd2, capture_output=True, text=True,
                                encoding='utf-8', errors='replace', timeout=15,
                                startupinfo=get_startup_info(), cwd=self.adb_client.adb_home)
            if r2.returncode != 0:
                self.done.emit(False, "", f"拉取失败: {(r2.stderr or r2.stdout or '').strip()}")
                # 清理远程临时文件
                subprocess.run(self.adb_client._build_cmd('shell', f'rm {self.remote_path}'),
                               capture_output=True, timeout=3,
                               startupinfo=get_startup_info(), cwd=self.adb_client.adb_home)
                return
            # 3. 清理远程文件
            subprocess.run(self.adb_client._build_cmd('shell', f'rm {self.remote_path}'),
                           capture_output=True, text=True,
                           encoding='utf-8', errors='replace', timeout=3,
                           startupinfo=get_startup_info(), cwd=self.adb_client.adb_home)
            self.done.emit(True, self.local_path, "")
        except subprocess.TimeoutExpired:
            self.done.emit(False, "", "截图超时，请检查设备连接")
        except Exception as e:
            self.done.emit(False, "", f"截图失败: {e}")


class ScreenshotSkill(SkillPlugin):
    name = "截图"
    icon_name = "CAMERA"
    category = "通用"
    supported_devices = [DEVICE_ANY]
    order = 4

    def get_panel(self) -> QWidget:
        """返回截图面板（屏幕下拉 + 两按钮 + 保存路径）。"""
        if not hasattr(self, "_panel") or self._panel is None:
            panel = QWidget()
            layout = QVBoxLayout(panel)
            layout.setContentsMargins(12, 10, 12, 10)
            layout.setSpacing(8)

            # 区块标题
            layout.addWidget(
                make_section_header("截图 / SCREENSHOT", Icons.CAMERA)
            )

            # 屏幕选择
            row_disp = QHBoxLayout()
            row_disp.setSpacing(6)
            disp_label = QLabel("屏幕")
            disp_label.setStyleSheet(field_label_style())
            row_disp.addWidget(disp_label)
            self._display_combo = QComboBox()
            self._display_combo.setEditable(True)
            self._display_combo.setToolTip("选择要截取的屏幕")
            row_disp.addWidget(self._display_combo, 1)
            layout.addLayout(row_disp)

            # 按钮行
            btn_row = QHBoxLayout()
            self._shot_current_btn = QPushButton(" 截当前屏")
            self._shot_current_btn.setIcon(IconHelper.icon(Icons.CAMERA, 16))
            self._shot_current_btn.setStyleSheet(Buttons.primary(icon_size="16px"))
            self._shot_current_btn.setCursor(Qt.PointingHandCursor)
            self._shot_current_btn.setToolTip("截取屏幕下拉框选中的单块屏，保存到 ./shots/YYYY-MM-DD/")
            self._shot_current_btn.clicked.connect(self._shot_current)
            btn_row.addWidget(self._shot_current_btn, 1)

            self._shot_all_btn = QPushButton(" 截取所有屏")
            self._shot_all_btn.setIcon(IconHelper.icon(Icons.CAMERA, 16))
            self._shot_all_btn.setStyleSheet(Buttons.secondary(icon_size="16px"))
            self._shot_all_btn.setCursor(Qt.PointingHandCursor)
            self._shot_all_btn.setToolTip("遍历所有已探测屏幕，每块屏各截一张")
            self._shot_all_btn.clicked.connect(self._shot_all)
            self._shot_all_btn.setVisible(False)  # 单屏时隐藏
            btn_row.addWidget(self._shot_all_btn, 1)
            layout.addLayout(btn_row)

            # 保存路径显示
            self._path_label = QLabel("保存路径: ./shots/")
            self._path_label.setStyleSheet(
                f"color: {Palette.TEXT_DIM}; font-size: 8pt; padding-left: 4px;"
            )
            self._path_label.setWordWrap(True)
            layout.addWidget(self._path_label)

            # ── 最近截图列表 ──
            recent_header = QLabel("最近截图")
            recent_header.setStyleSheet(
                f"color: {Palette.TEXT_DIM}; font-size: 8pt; font-weight: 700; padding-top: 6px;"
            )
            layout.addWidget(recent_header)

            self._recent_list = QListWidget()
            self._recent_list.setFixedHeight(120)
            self._recent_list.setStyleSheet(
                f"""
                QListWidget {{
                    background-color: {Palette.SURFACE};
                    border: 2px solid {Palette.BORDER_STRONG};
                    border-radius: 2px;
                    font-size: 9pt;
                }}
                QListWidget::item:selected {{
                    background-color: {Palette.PRIMARY_LIGHT};
                    color: {Palette.PRIMARY_DARK};
                }}
                QListWidget::item:hover {{
                    background-color: {Palette.SURFACE_DARK};
                }}
                """
            )
            self._recent_list.itemDoubleClicked.connect(self._open_recent)

            layout.addWidget(self._recent_list)

            # 触发一次加载
            self._scan_recent()

            layout.addStretch()
            self._panel = panel

            # 监听 DisplayService
            ds = getattr(self.ctx, 'display_service', None)
            if ds:
                ds.displays_updated.connect(self._on_displays_updated)
                self._update_display_combo(ds.displays)

        return self._panel

    # ── DisplayService 回调 ──

    def _on_displays_updated(self, displays: list):
        self._update_display_combo(displays)

    def _update_display_combo(self, displays: list):
        self._display_combo.clear()
        if not displays:
            self._display_combo.setEditable(True)
            self._shot_all_btn.setVisible(False)
            return
        self._display_combo.setEditable(False)
        for d in displays:
            if hasattr(d, 'label'):
                label = d.label
                did = d.display_id
            elif isinstance(d, dict):
                label = d.get('label') or d.get('alias') or f"屏幕{d.get('display_id', '')}"
                did = d.get('display_id', '')
            else:
                label = str(d)
                did = str(d)
            self._display_combo.addItem(label, did)
        self._shot_all_btn.setVisible(len(displays) > 1)

    # ── 截图操作 ──

    def _get_save_dir(self) -> str:
        """生成保存目录路径：./shots/YYYY-MM-DD/"""
        today = datetime.now().strftime("%Y-%m-%d")
        save_dir = os.path.join(os.getcwd(), "shots", today)
        os.makedirs(save_dir, exist_ok=True)
        self._path_label.setText(f"保存路径: {save_dir}")
        return save_dir

    def _current_display_id(self) -> str:
        data = self._display_combo.currentData()
        if data:
            return str(data)
        return self._display_combo.currentText().strip()

    def _shot_current(self):
        """截取当前选中屏。"""
        serial_cb = getattr(self.ctx, 'get_serial_cb', None)
        if not serial_cb or not serial_cb():
            MBox = getattr(self.ctx, 'main_window', None)
            QMessageBox.warning(MBox, "未选择设备", "请先连接并选择一台设备")
            return

        adb_client = getattr(self.ctx, 'adb_client', None)
        if not adb_client:
            return

        display_id = self._current_display_id()
        self._run_single_screenshot(adb_client, display_id)

    def _shot_all(self):
        """截取所有屏。"""
        serial_cb = getattr(self.ctx, 'get_serial_cb', None)
        if not serial_cb or not serial_cb():
            MBox = getattr(self.ctx, 'main_window', None)
            QMessageBox.warning(MBox, "未选择设备", "请先连接并选择一台设备")
            return

        ds = getattr(self.ctx, 'display_service', None)
        if not ds or not ds.displays:
            return

        adb_client = getattr(self.ctx, 'adb_client', None)
        if not adb_client:
            return

        for d in ds.displays:
            did = d.display_id if hasattr(d, 'display_id') else d.get('display_id', '')
            self._run_single_screenshot(adb_client, did, d)

    def _run_single_screenshot(self, adb_client, display_id: str, display_info=None):
        """后台执行单次截图。"""
        save_dir = self._get_save_dir()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # 生成文件名
        if display_info:
            alias = display_info.display_name if hasattr(display_info, 'display_name') else display_info.get('alias', f"屏幕{display_id}")
        else:
            alias = f"屏幕{display_id}" if display_id else "主屏"
        safe_alias = alias.replace(" ", "_").replace("/", "_")
        local_path = os.path.join(save_dir, f"shot_{timestamp}_{safe_alias}.png")
        remote_path = f"/sdcard/_shot_{display_id or 'main'}.png"

        terminal_cb = getattr(self, '_terminal_msg_cb', None)
        if not terminal_cb:
            mw = getattr(self.ctx, 'main_window', None)
            if mw:
                term = mw.get_current_terminal()
                if term:
                    term.print_system_msg(f"[截图] 正在截取 {alias}...")

        worker = ScreenshotWorker(adb_client, remote_path, local_path, display_id)
        worker.done.connect(lambda ok, p, e: self._on_single_done(ok, p, e, alias))
        start_worker(worker)

    def _on_single_done(self, ok: bool, local_path: str, error: str, alias: str):
        mw = getattr(self.ctx, 'main_window', None)
        if mw:
            term = mw.get_current_terminal()
            if ok:
                if term:
                    term.print_system_msg(f"[截图成功] {alias} → {local_path}", COLOR_SUCCESS)
                # 刷新最近列表
                self._scan_recent()
            else:
                if term:
                    term.print_system_msg(f"[截图失败] {alias}: {error}", COLOR_ERROR)
                QMessageBox.warning(mw, "截图失败", f"{alias}: {error}")

    # ── 最近截图列表 ──

    def _scan_recent(self):
        """扫描 ./shots/ 下最近 10 张截图，填充 QListWidget。"""
        if not hasattr(self, "_recent_list"):
            return
        self._recent_list.clear()
        shots_root = os.path.join(os.getcwd(), "shots")
        if not os.path.isdir(shots_root):
            return
        # 递归收集截图文件
        candidates = []
        for dirpath, _dirnames, filenames in os.walk(shots_root):
            for fn in filenames:
                if fn.lower().endswith((".png", ".jpg", ".jpeg")):
                    full = os.path.join(dirpath, fn)
                    try:
                        mtime = os.path.getmtime(full)
                        candidates.append((mtime, full))
                    except OSError:
                        pass
        # 按修改时间倒序，取前 10
        candidates.sort(key=lambda x: x[0], reverse=True)
        for mtime, full in candidates[:10]:
            rel = os.path.relpath(full, os.getcwd())
            ts = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
            item = QListWidgetItem(f"{ts}  {os.path.basename(full)}")
            item.setData(Qt.UserRole, full)
            item.setToolTip(rel)
            self._recent_list.addItem(item)

    def _open_recent(self, item: QListWidgetItem):
        """双击列表项 → 用系统默认查看器打开图片。"""
        full = item.data(Qt.UserRole)
        if not full or not os.path.isfile(full):
            return
        if sys.platform == "win32":
            try:
                os.startfile(full)  # type: ignore[attr-defined]
                return
            except (OSError, AttributeError):
                pass
        QDesktopServices.openUrl(QUrl.fromLocalFile(full))

    # ── 兼容旧 click-to-execute（保留 on_activate 但不再用） ──

    def on_activate(self):
        """点击技能卡片时：切到截图面板（由 SkillRegistry 的 panel 机制处理）。"""
        pass
