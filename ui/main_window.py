import ctypes
import ctypes.wintypes
import os
import re
import sys
from datetime import datetime
from functools import partial
from typing import Optional

from PyQt5.QtCore import QEvent, QMimeData, QPoint, QRect, QSettings, Qt, QProcess, QThread, QTimer, QUrl, pyqtSignal
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QMainWindow,
    QMessageBox, QPushButton, QScrollArea, QSplitter, QStackedWidget,
    QTabBar, QTabWidget, QToolButton, QVBoxLayout, QWidget
)

from ..core.adb_client import AdbClient
from ..core.adb_runner import AdbRunner
from ..core.config import APP_NAME, APP_VERSION, load_commands, save_commands
from ..core.skill_plugin import PluginContext, SkillRegistry
from ..core.utils import COLOR_ERROR, COLOR_SUCCESS
from ..core.skills.builtin import AppManagementSkill, LogcatSkill, ScrcpySkill, ScreenshotSkill
from ..services.device_service import DeviceDetectorWorker, DeviceStateCheckWorker, DeviceService, DeviceInfo
from ..services.file_service import FileService
from ..services.logcat_service import LogcatService
from ..services.scrcpy_service import ScrcpyService
from ..services.system_monitor_service import SystemMonitorService
from ..services.terminal_service import TerminalService
from ..ui.panels.file_explorer import FileExplorer
from ..ui.panels.logcat_panel import LogcatPanel
from ..ui.panels.scrcpy_control_panel import ScrcpyControlPanel
from ..ui.panels.terminal_tab import TerminalTab
from ..ui.theme import (
    Buttons, Fonts, IconHelper, Icons, Palette, apply_card,
    cmd_chip_style, make_section_header, skill_item_style,
    stat_pill_style, title_font, titlebar_button_style
)
from ..ui.widgets.command_manager_dialog import CommandManagerDialog

class _WindowButton(QPushButton):
    """标题栏窗口控制按钮：悬浮时可切换高亮图标（如关闭按钮悬浮变白）。

    尺寸和图标像素对齐：按钮 38×30，图标 16px（与 SVG viewBox 整数对齐，
    避免 subpixel blur）。
    """

    def __init__(self, normal_pm, hover_pm=None, parent=None):
        super().__init__(parent)
        self.setFixedSize(38, 32)
        self._hover_icon = None
        self.set_icons(normal_pm, hover_pm)

    def set_icons(self, normal_pm, hover_pm=None):
        self._normal_icon = QIcon(normal_pm)
        self._hover_icon = QIcon(hover_pm) if hover_pm is not None else None
        self.setIcon(self._normal_icon)

    def enterEvent(self, event):
        if self._hover_icon is not None:
            self.setIcon(self._hover_icon)
        super().enterEvent(event)

    def leaveEvent(self, event):
        if self._hover_icon is not None:
            self.setIcon(self._normal_icon)
        super().leaveEvent(event)


class PixelTitleBar(QWidget):
    """无边框窗口的像素风标题栏（对应原型图顶部 titlebar）。

    左侧像素标题，右侧最小化/最大化/关闭按钮。
    窗口拖拽、双击最大化、Aero 磁吸、边缘缩放由主窗口 eventFilter
    手写实现。
    """

    def __init__(self, window: "AdbTool", parent=None):
        super().__init__(parent)
        self._win = window
        apply_card(self, "titlebar")
        self.setFixedHeight(48)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 6, 10, 6)
        layout.setSpacing(10)

        # 左侧：设备图标 + 像素标题
        title_box = QWidget()
        title_box.setStyleSheet("background: transparent;")
        title_row = QHBoxLayout(title_box)
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(8)
        title_icon = QLabel()
        title_icon.setPixmap(IconHelper.pixmap(Icons.DEVICE, 22))
        title_icon.setStyleSheet("border: none; background: transparent;")
        title_label = QLabel(f"{APP_NAME} v{APP_VERSION}")
        title_label.setFont(title_font(10))
        title_label.setStyleSheet(
            f"color: {Palette.PRIMARY_DARK}; background: transparent;"
        )
        title_row.addWidget(title_icon)
        title_row.addWidget(title_label)
        layout.addWidget(title_box)
        layout.addStretch()

        # 窗口控制按钮：最小化 / 最大化 / 关闭
        self.min_btn = _WindowButton(
            IconHelper.pixmap(Icons.WINDOW_MIN, 16, Palette.TEXT)
        )
        self.min_btn.setToolTip("最小化")
        self.min_btn.setStyleSheet(titlebar_button_style())
        self.min_btn.clicked.connect(window.showMinimized)

        self.max_btn = _WindowButton(
            IconHelper.pixmap(Icons.WINDOW_MAX, 16, Palette.TEXT),
            IconHelper.pixmap(Icons.WINDOW_MAX, 16, Palette.PRIMARY_DARK),
        )
        self.max_btn.setToolTip("最大化")
        self.max_btn.setStyleSheet(titlebar_button_style())
        self.max_btn.clicked.connect(self._toggle_max)

        self.close_btn = _WindowButton(
            IconHelper.pixmap(Icons.CLOSE, 16, Palette.ERROR_DARK),
            IconHelper.pixmap(Icons.CLOSE, 16, "#FFFFFF"),
        )
        self.close_btn.setToolTip("关闭")
        self.close_btn.setStyleSheet(titlebar_button_style(danger=True))
        self.close_btn.clicked.connect(window.close)

        layout.addWidget(self.min_btn)
        layout.addWidget(self.max_btn)
        layout.addWidget(self.close_btn)

        self._max_pm = IconHelper.pixmap(Icons.WINDOW_MAX, 16, Palette.TEXT)
        self._max_hover_pm = IconHelper.pixmap(Icons.WINDOW_MAX, 16, Palette.PRIMARY_DARK)
        self._restore_pm = IconHelper.pixmap(Icons.WINDOW_RESTORE, 16, Palette.TEXT)
        self._restore_hover_pm = IconHelper.pixmap(
            Icons.WINDOW_RESTORE, 16, Palette.PRIMARY_DARK
        )

    def _toggle_max(self):
        if self._win.isMaximized():
            self._win.showNormal()
        else:
            self._win.showMaximized()

    def update_max_state(self, maximized: bool):
        """最大化/还原切换后同步按钮图标与提示。"""
        if maximized:
            self.max_btn.set_icons(self._restore_pm, self._restore_hover_pm)
            self.max_btn.setToolTip("还原")
        else:
            self.max_btn.set_icons(self._max_pm, self._max_hover_pm)
            self.max_btn.setToolTip("最大化")


class AdbTool(QMainWindow):
    def __init__(self, adb_client):
        super().__init__()
        self.adb_client = adb_client
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        # 无边框窗口：像素标题栏即为窗口顶部（对齐原型图），
        # 边缘缩放 + 标题栏拖拽通过 eventFilter 手写实现（不依赖 WM_NCHITTEST）
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowSystemMenuHint
            | Qt.WindowMinMaxButtonsHint
            | Qt.WindowCloseButtonHint
        )
        self.setMinimumSize(1200, 800)
        self.resize(1400, 900)
        self._dwm_shadow_applied = False

        # ── 边缘缩放 + 标题栏拖拽 状态 ──
        self._edge = 15  # 边缘感应宽度
        # resize 方向：(left, top, right, bottom) 四个 bool 的 tuple，如 (True, False, True, False) 表示左上→右下
        self._resize_dir: Optional[tuple] = None
        self._resize_start_geo: Optional[QRect] = None
        self._resize_start_global: Optional[QPoint] = None
        # 标题栏拖拽
        self._moving = False
        self._move_start_global: Optional[QPoint] = None
        self._move_start_pos: Optional[QPoint] = None
        # 让事件过滤器拦截所有子控件的鼠标事件（不然子控件吞掉事件主窗口收不到）
        self.installEventFilter(self)

        self._settings = QSettings("Yxing", "AdbVisualTool")

        self.device_service = DeviceService(self.adb_client)
        self.file_service = FileService(self.adb_client)
        self.system_monitor = SystemMonitorService(self.adb_client)

        # 多屏枚举 + 别名管理服务
        from ..services.display_service import DisplayService
        self.display_service = DisplayService(self.adb_client, self._settings)
        self.display_service.displays_updated.connect(self._on_displays_updated)
        self.display_service.enumeration_failed.connect(self._on_display_enum_failed)

        self.device_service.set_refresh_callback(self._on_devices_found)
        self.device_service.set_connect_callback(self._on_wireless_action_done)

        # 统一监控服务：保留实例供技能插件按需调用（PluginContext 注入），
        # 标题栏血条已移除，不再做 2s 轮询（stats_updated 无人消费，不连接）
        # 设备断连检测：5s 一次 adb get-state
        self._device_state_timer = QTimer(self)
        self._device_state_timer.setInterval(5000)
        self._device_state_timer.timeout.connect(self._check_device_state)
        self._device_last_state = None  # "device" / "offline" / None
        self._device_state_started = False

        # 无线 ADB 槽位状态：_wireless_target 为当前槽位中的 ip:port（None=空槽）
        self._wireless_target = None
        self._wireless_action = None  # "connect" / "disconnect" / None

        self.custom_commands = load_commands()

        # 允许接收 .apk 拖拽到窗口
        self.setAcceptDrops(True)

        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(10)

        self._scrcpy_service = ScrcpyService(self.adb_client)
        self._logcat_service = LogcatService(self.adb_client)

        self.adb_client._serial_getter = self.get_current_serial

        # AdbRunner: AdbClient 高层 facade（统一 shell/install/push/pull）
        self.adb_runner = AdbRunner(self.adb_client)

        # PluginContext: 所有插件共享的依赖注入容器
        self._plugin_ctx = PluginContext(
            adb_client=self.adb_client,
            adb_runner=self.adb_runner,
            logcat_service=self._logcat_service,
            scrcpy_service=self._scrcpy_service,
            terminal_service=None,  # 稍后 add_terminal_panel 时绑定
            file_service=self.file_service,
            system_monitor=self.system_monitor,
            display_service=self.display_service,
            get_serial_cb=self.get_current_serial,
            get_current_device_info_cb=self._get_current_device_info,
            main_window=self,
        )

        # SkillRegistry: 扫描、过滤、构建 UI
        self.skill_registry = SkillRegistry(self._plugin_ctx)
        # 提前 import 让 builtin 插件被扫描到（扫描按已导入模块走）
        from ..core.skills import builtin  # noqa: F401
        self.skill_registry.scan()

        # 存储适配器实例引用（build_skill_cards 后填充）
        self._skill_plugins: list = []

        self._build_titlebar(main_layout)
        self._build_device_party(main_layout)
        self._build_command_bar(main_layout)
        self._build_workspace(main_layout)
        self._build_status_bar()

        # 接线：状态栏联动
        self._scrcpy_service.scrcpy_started.connect(self._update_status_bar)
        self._scrcpy_service.scrcpy_finished.connect(self._on_scrcpy_finished)
        self._scrcpy_service.scrcpy_finished.connect(self._update_status_bar)
        self._logcat_service.recording_started.connect(lambda _: self._update_status_bar())
        self._logcat_service.recording_stopped.connect(self._update_status_bar)

        # 从 QSettings 恢复
        self._restore_settings()

        # 终端初始化完成后再刷新设备，避免 prompt 被多次 reset_prompt 刷屏
        self.refresh_devices()

        # ── 递归给所有子控件也装 eventFilter ──
        # 不然鼠标在标题栏/面板上时，事件被子控件吞掉，主窗口收不到 → 拖不动
        for child in self.findChildren(QWidget):
            child.installEventFilter(self)

    # ==================== QSettings 持久化 ====================
    def _restore_settings(self):
        """从 QSettings 恢复全局配置（窗口位置、大小、无线 ADB 槽位）。"""
        s = self._settings
        w = s.value("window/width", type=int)
        h = s.value("window/height", type=int)
        x = s.value("window/x", type=int)
        y = s.value("window/y", type=int)
        if w and h:
            # 确保不小于最小尺寸
            w = max(w, self.minimumWidth())
            h = max(h, self.minimumHeight())
            self.resize(w, h)
        if x is not None and y is not None:
            # 粗略防止恢复到可见区域外（多显示器/分辨率变化）
            self.move(x, y)
        wireless_ip = s.value("wireless/target", "", type=str)
        if wireless_ip and self.wireless_input:
            self.wireless_input.setText(wireless_ip)

    def _restore_device_settings(self, serial: str):
        """恢复指定设备专属配置（splitter、scrcpy 复选框）。设备切换后调用。"""
        s = self._settings
        s.beginGroup(f"device/{serial}")
        try:
            sizes = s.value("splitter/main")
            if sizes and hasattr(self, '_main_splitter'):
                if isinstance(sizes, (bytes, bytearray)):
                    import ast
                    sizes = ast.literal_eval(sizes.decode())
                if sizes:
                    self._main_splitter.setSizes([int(x) for x in sizes])
            if hasattr(self, 'scrcpy_options') and self.scrcpy_options:
                self.scrcpy_options.stay_awake_chk.setChecked(
                    s.value("scrcpy/stay_awake", False, type=bool))
                self.scrcpy_options.record_chk.setChecked(
                    s.value("scrcpy/record", False, type=bool))
                self.scrcpy_options.audio_chk.setChecked(
                    s.value("scrcpy/audio", True, type=bool))
        finally:
            s.endGroup()

    def _save_settings(self):
        """保存全局 + 按 serial 分组的配置。"""
        s = self._settings
        # ── 全局 ──
        # 最大化状态下不保存位置/尺寸，保持上次还原状态的值
        if not self.isMaximized() and not self.isFullScreen():
            s.setValue("window/width", self.width())
            s.setValue("window/height", self.height())
            s.setValue("window/x", self.x())
            s.setValue("window/y", self.y())
        if self._wireless_target:
            s.setValue("wireless/target", self._wireless_target)

        # ── 按 serial 分组 ──
        serial = self.get_current_serial() or "_default"
        s.beginGroup(f"device/{serial}")
        try:
            if hasattr(self, '_main_splitter'):
                sizes = self._main_splitter.sizes()
                s.setValue("splitter/main", sizes)
            if hasattr(self, 'scrcpy_options') and self.scrcpy_options:
                s.setValue("scrcpy/stay_awake", self.scrcpy_options.stay_awake_chk.isChecked())
                s.setValue("scrcpy/record", self.scrcpy_options.record_chk.isChecked())
                s.setValue("scrcpy/audio", self.scrcpy_options.audio_chk.isChecked())
        finally:
            s.endGroup()
        s.sync()

    # ==================== 构建标题栏 ====================
    def _build_titlebar(self, parent_layout: QVBoxLayout):
        self.title_bar = PixelTitleBar(self)
        parent_layout.addWidget(self.title_bar)

    # ==================== 无边框窗口：手写边缘缩放 + 标题栏拖拽 ====================

    def _global_to_local(self, global_pos: QPoint) -> QPoint:
        """把屏幕坐标转成主窗口客户区坐标。"""
        return self.mapFromGlobal(global_pos)

    def _hit_test_dir(self, local_pos: QPoint) -> Optional[tuple]:
        """返回 resize 方向 (left, top, right, bottom) 或 None。最大化时不缩。"""
        if self.isMaximized() or self.isFullScreen():
            return None
        x, y = local_pos.x(), local_pos.y()
        w, h = self.width(), self.height()
        e = self._edge
        left = x < e
        right = x > w - e
        top = y < e
        bottom = y > h - e
        if any([left, right, top, bottom]):
            return (left, top, right, bottom)
        return None

    @staticmethod
    def _dir_to_cursor(direction: tuple) -> Qt.CursorShape:
        left, top, right, bottom = direction
        h = (left or right)
        v = (top or bottom)
        if h and v:
            if (left and top) or (right and bottom):
                return Qt.SizeFDiagCursor   # ↖↘
            return Qt.SizeBDiagCursor       # ↗↙
        if h:
            return Qt.SizeHorCursor         # ↔
        if v:
            return Qt.SizeVerCursor         # ↕
        return Qt.ArrowCursor

    def _is_on_title_bar(self, local_pos: QPoint) -> bool:
        """鼠标在标题栏区域内（但不在窗口控制按钮上）→ 允许拖拽移动。"""
        if not hasattr(self, "title_bar"):
            return False
        # 用全局坐标判断，避免客户区 frameGeometry 与 geometry 不一致
        gp = self.mapToGlobal(local_pos)
        tb_rect = QRect(self.title_bar.mapToGlobal(QPoint(0, 0)), self.title_bar.size())
        if not tb_rect.contains(gp):
            return False
        for btn in (self.title_bar.min_btn, self.title_bar.max_btn,
                    self.title_bar.close_btn):
            btn_rect = QRect(btn.mapToGlobal(QPoint(0, 0)), btn.size())
            if btn_rect.contains(gp):
                return False
        return True

    def eventFilter(self, obj, event):
        """拦截所有子控件的鼠标事件，实现边缘缩放 + 标题栏拖拽。"""
        etype = event.type()

        # ── 动态创建的子控件也装上过滤器 ──
        if etype == QEvent.ChildAdded:
            child = event.child()
            if child and hasattr(child, "installEventFilter"):
                child.installEventFilter(self)
            return super().eventFilter(obj, event)

        # ── 按下 ──
        if etype == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            local = self._global_to_local(event.globalPos())
            direction = self._hit_test_dir(local)
            if direction is not None:
                # 边缘 → 开始 resize
                self._resize_dir = direction
                self._resize_start_geo = self.geometry()
                self._resize_start_global = event.globalPos()
                self.grabMouse()
                return True  # 吃掉，不让子控件处理
            elif self._is_on_title_bar(local):
                # 标题栏 → 开始 move
                self._moving = True
                self._move_start_global = event.globalPos()
                self._move_start_pos = self.pos()
                self.grabMouse()
                return True

        # ── 双击 ──
        elif etype == QEvent.MouseButtonDblClick and event.button() == Qt.LeftButton:
            local = self._global_to_local(event.globalPos())
            if self._is_on_title_bar(local):
                self._toggle_max()
                return True

        # ── 移动 ──
        elif etype == QEvent.MouseMove:
            if self._resize_dir is not None and self._resize_start_geo is not None:
                delta = event.globalPos() - self._resize_start_global
                geo = QRect(self._resize_start_geo)
                left, top, right, bottom = self._resize_dir
                min_w, min_h = self.minimumWidth(), self.minimumHeight()
                if left:
                    new_w = geo.width() - delta.x()
                    if new_w >= min_w:
                        geo.setX(geo.x() + delta.x())
                        geo.setWidth(new_w)
                if right:
                    new_w = geo.width() + delta.x()
                    if new_w >= min_w:
                        geo.setWidth(new_w)
                if top:
                    new_h = geo.height() - delta.y()
                    if new_h >= min_h:
                        geo.setY(geo.y() + delta.y())
                        geo.setHeight(new_h)
                if bottom:
                    new_h = geo.height() + delta.y()
                    if new_h >= min_h:
                        geo.setHeight(new_h)
                self.setGeometry(geo)
                return True
            elif self._moving and self._move_start_global is not None:
                delta = event.globalPos() - self._move_start_global
                self.move(self._move_start_pos + delta)
                return True
            # 空闲状态：更新光标
            local = self._global_to_local(event.globalPos())
            direction = self._hit_test_dir(local)
            if direction is not None:
                cursor = self._dir_to_cursor(direction)
                if self.cursor().shape() != cursor:
                    self.setCursor(cursor)
            elif self.cursor().shape() != Qt.ArrowCursor:
                self.unsetCursor()

        # ── 松开 ──
        elif etype == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
            if self._resize_dir is not None or self._moving:
                self._resize_dir = None
                self._resize_start_geo = None
                self._resize_start_global = None
                self._moving = False
                self._move_start_global = None
                self._move_start_pos = None
                self.releaseMouse()
                self.unsetCursor()
                return True

        return super().eventFilter(obj, event)

    def changeEvent(self, event):
        if event.type() == QEvent.WindowStateChange and hasattr(self, "title_bar"):
            self.title_bar.update_max_state(self.isMaximized())
        super().changeEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        self._apply_dwm_shadow()

    def _apply_dwm_shadow(self):
        """无边框窗口默认失去系统投影，用 DWM 扩展 1px 帧找回原生阴影。"""
        if self._dwm_shadow_applied or sys.platform != "win32":
            return

        class _MARGINS(ctypes.Structure):
            _fields_ = [
                ("cxLeftWidth", ctypes.c_int),
                ("cxRightWidth", ctypes.c_int),
                ("cyTopHeight", ctypes.c_int),
                ("cyBottomHeight", ctypes.c_int),
            ]

        try:
            hwnd = int(self.winId())
            margins = _MARGINS(1, 1, 1, 1)
            ctypes.windll.dwmapi.DwmExtendFrameIntoClientArea(
                hwnd, ctypes.byref(margins)
            )
            self._dwm_shadow_applied = True
        except Exception:
            pass

    # ==================== 构建设备紧凑状态条 ====================
    def _build_device_party(self, parent_layout: QVBoxLayout):
        # 紧凑状态条：无边框、无卡片背景、高度 32px
        bar = QWidget()
        bar.setFixedHeight(32)
        bar.setStyleSheet("background: transparent;")
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(4, 0, 4, 0)
        bar_layout.setSpacing(8)

        # === 左：24px 手机图标 + 设备下拉 + ROOT 标签 ===
        self.device_avatar = QLabel()
        self.device_avatar.setPixmap(
            IconHelper.pixmap(Icons.DEVICE, 24, Palette.TEXT_BTN)
        )
        self.device_avatar.setFixedSize(24, 24)
        self.device_avatar.setAlignment(Qt.AlignCenter)
        self.device_avatar.setStyleSheet("background: transparent;")

        # 设备下拉（替代纯文字 device_name_label，避免重复）
        self.device_combo = QComboBox()
        self.device_combo.setFixedWidth(140)
        self.device_combo.setToolTip("选择当前操作的 ADB 设备")
        self.device_combo.currentIndexChanged.connect(self._on_device_selected)

        self.device_stat_pill = QLabel("ROOT:未知")
        self.device_stat_pill.setStyleSheet(stat_pill_style())
        self.device_stat_pill.setVisible(False)  # 未连设备时隐藏

        self.refresh_dev_btn = QPushButton()
        self.refresh_dev_btn.setIcon(IconHelper.icon(Icons.REFRESH, 14))
        self.refresh_dev_btn.setStyleSheet(Buttons.ghost(padding="2px", icon_size="14px"))
        self.refresh_dev_btn.setToolTip("重新扫描 ADB 设备")
        self.refresh_dev_btn.setFixedSize(26, 26)
        self.refresh_dev_btn.setCursor(Qt.PointingHandCursor)
        self.refresh_dev_btn.clicked.connect(self.refresh_devices)

        bar_layout.addWidget(self.device_avatar)
        bar_layout.addWidget(self.device_combo)
        bar_layout.addWidget(self.device_stat_pill)
        bar_layout.addWidget(self.refresh_dev_btn)
        bar_layout.addStretch()

        # === 右：无线 ADB ===
        wireless_row = QHBoxLayout()
        wireless_row.setSpacing(8)
        self.wireless_pill = QLabel("EMPTY")
        self.wireless_pill.setStyleSheet(
            stat_pill_style(Palette.TEXT_LIGHT, Palette.SURFACE_DARK)
        )
        self.wireless_input = QLineEdit()
        self.wireless_input.setPlaceholderText("IP:Port")
        self.wireless_input.setMinimumWidth(180)
        self.wireless_input.setToolTip(
            "输入设备 IP 和端口，例如 192.168.0.10:5555\n"
            "不带端口时默认使用 5555；手机需开启无线调试或先 adb tcpip 5555"
        )
        self.wireless_input.returnPressed.connect(self._on_wireless_action_clicked)
        self.wireless_input.textChanged.connect(self._update_wireless_button_enabled)

        self.wireless_btn = QPushButton(" 连接")
        self.wireless_btn.setIcon(IconHelper.icon(Icons.WIRELESS, 16))
        self.wireless_btn.setStyleSheet(Buttons.secondary(icon_size="16px"))
        self.wireless_btn.setCursor(Qt.PointingHandCursor)
        self.wireless_btn.setToolTip("通过 Wi-Fi 连接设备（需输入合法 IP:Port）")
        self.wireless_btn.setEnabled(False)  # 初始无 IP，禁用
        self.wireless_btn.clicked.connect(self._on_wireless_action_clicked)

        wireless_row.addWidget(self.wireless_pill)
        wireless_row.addWidget(self.wireless_input)
        wireless_row.addWidget(self.wireless_btn)

        bar_layout.addLayout(wireless_row)
        parent_layout.addWidget(bar)

    @staticmethod
    def _normalize_wireless_target(raw: str) -> str:
        """校验并规范化 IP[:Port]；非法输入返回空串，缺端口补 5555。"""
        m = re.match(r'^(\d{1,3}(?:\.\d{1,3}){3})(?::(\d{1,5}))?$', raw.strip())
        if not m:
            return ""
        ip = m.group(1)
        if any(int(p) > 255 for p in ip.split('.')):
            return ""
        port = m.group(2)
        if port:
            port_num = int(port)
            if not 1 <= port_num <= 65535:
                return ""
            return f"{ip}:{port_num}"
        return f"{ip}:5555"

    def _update_wireless_button_enabled(self):
        """实时校验 IP 合法性：empty 状态下非法输入时禁用连接按钮。"""
        if self._wireless_target or self._wireless_action is not None:
            return  # 已连接或操作中，不归此管
        valid = bool(self._normalize_wireless_target(self.wireless_input.text()))
        self.wireless_btn.setEnabled(valid)

    def _set_wireless_state(self, state: str, target: str = None):
        """更新无线槽位 UI：empty / busy / connected。

        三态颜色（用户要求）：
          empty    → 灰（secondary），IP 非法时禁用
          connected→ 红（danger），点击表示断开
          busy     → 绿（primary），连接中/断开中
        """
        if state == "busy":
            connecting = (self._wireless_action == "connect")
            self.wireless_pill.setText("BUSY")
            self.wireless_pill.setStyleSheet(
                stat_pill_style(Palette.WARNING, Palette.SURFACE_DARK)
            )
            self.wireless_btn.setEnabled(False)
            self.wireless_btn.setText(" 连接中..." if connecting else " 断开中...")
            self.wireless_btn.setIcon(IconHelper.icon(Icons.WIRELESS, 16))
            self.wireless_btn.setStyleSheet(Buttons.primary(icon_size="16px"))
            self.wireless_btn.setToolTip("正在处理无线连接，请稍候")
            self.wireless_input.setEnabled(False)
        elif state == "connected":
            self._wireless_target = target or self._wireless_target
            self.wireless_pill.setText("ONLINE")
            self.wireless_pill.setStyleSheet(
                stat_pill_style(Palette.SUCCESS_DARK, Palette.SUCCESS_LIGHT)
            )
            self.wireless_btn.setEnabled(True)
            self.wireless_btn.setText(" 断开")
            self.wireless_btn.setIcon(IconHelper.icon(Icons.CLOSE, 16))
            self.wireless_btn.setStyleSheet(Buttons.danger(icon_size="16px"))
            self.wireless_btn.setToolTip("断开该无线设备")
            self.wireless_input.setEnabled(False)
            if target:
                self.wireless_input.setText(target)
        else:  # empty
            self._wireless_target = None
            self.wireless_pill.setText("EMPTY")
            self.wireless_pill.setStyleSheet(
                stat_pill_style(Palette.TEXT_LIGHT, Palette.SURFACE_DARK)
            )
            self.wireless_btn.setText(" 连接")
            self.wireless_btn.setIcon(IconHelper.icon(Icons.WIRELESS, 16))
            self.wireless_btn.setStyleSheet(Buttons.secondary(icon_size="16px"))
            self.wireless_btn.setToolTip("通过 Wi-Fi 连接设备（需输入合法 IP:Port）")
            self.wireless_input.setEnabled(True)
            # IP 合法性实时控制：非法时灰显禁用
            self._update_wireless_button_enabled()

    def _on_wireless_action_clicked(self):
        if self._wireless_action is not None:
            return  # 操作进行中，忽略重复点击
        if self._wireless_target:
            # 槽位有设备 → 断开
            self._wireless_action = "disconnect"
            self._set_wireless_state("busy")
            self.device_service.disconnect_network_device(self._wireless_target)
        else:
            target = self._normalize_wireless_target(self.wireless_input.text())
            if not target:
                QMessageBox.warning(
                    self, "地址无效",
                    "请输入正确的 IP:Port，例如 192.168.0.10:5555"
                )
                return
            self.wireless_input.setText(target)
            self._wireless_action = "connect"
            self._set_wireless_state("busy")
            self.device_service.connect_network_device(target)

    def _on_wireless_action_done(self, success: bool, message: str):
        action = self._wireless_action or "connect"
        self._wireless_action = None
        tab = self.get_current_terminal()
        if tab:
            verb = "无线连接" if action == "connect" else "无线断开"
            tab.print_system_msg(
                f"[{verb}] {message}", COLOR_SUCCESS if success else COLOR_ERROR
            )
        if success:
            # 成功后刷新设备列表，_on_devices_found 会把槽位同步为 ONLINE
            # （断开成功时若无线设备已消失则自动回到 EMPTY）
            self.refresh_devices()
        else:
            # 失败：恢复可操作状态；若槽位原本有设备则保持 ONLINE
            self._set_wireless_state(
                "connected" if self._wireless_target else "empty",
                self._wireless_target
            )

    def _sync_wireless_slot(self, devices: list):
        """设备列表刷新后，根据无线设备（IP:Port 序列号）同步槽位状态。"""
        if self._wireless_action is not None:
            return  # 连接/断开操作进行中，不覆盖 BUSY 状态
        wireless = []
        for d in devices:
            serial = d.serial if isinstance(d, DeviceInfo) else d[0]
            state = d.state if isinstance(d, DeviceInfo) else d[1]
            if state == "device" and re.match(
                r'^\d{1,3}(?:\.\d{1,3}){3}:\d+$', serial or ""
            ):
                wireless.append(serial)
        if wireless:
            # 优先选中与输入框一致的目标
            typed = self.wireless_input.text().strip()
            target = typed if typed in wireless else wireless[0]
            if self._wireless_target != target:
                self._set_wireless_state("connected", target)
        elif self._wireless_target is not None:
            self._set_wireless_state("empty")

    # ==================== 构建命令栏 ====================
    def _build_command_bar(self, parent_layout: QVBoxLayout):
        cmd_card = QWidget()
        apply_card(cmd_card)
        cmd_layout = QHBoxLayout(cmd_card)
        cmd_layout.setContentsMargins(10, 6, 10, 6)
        cmd_layout.setSpacing(8)

        self.add_terminal_btn = QPushButton("新建终端")
        self.add_terminal_btn.setIcon(IconHelper.icon(Icons.TERMINAL, 16))
        self.add_terminal_btn.setStyleSheet(Buttons.ghost(icon_size="16px"))
        self.add_terminal_btn.setToolTip("新建一个终端标签")
        self.add_terminal_btn.clicked.connect(lambda: self.add_terminal_panel())
        cmd_layout.addWidget(self.add_terminal_btn)

        # 自定义命令芯片容器（管理命令里新增的按钮动态生成于此）
        # 包一层横向滚动区：命令数量无上限，超出宽度时滚动而非互相挤压
        self.custom_cmd_box = QHBoxLayout()
        self.custom_cmd_box.setSpacing(8)
        self.custom_cmd_box.addStretch()  # 占位，_rebuild 时重建

        chips_host = QWidget()
        chips_host.setStyleSheet("background: transparent;")
        chips_host.setLayout(self.custom_cmd_box)

        self._cmd_scroll = QScrollArea()
        self._cmd_scroll.setWidgetResizable(True)
        self._cmd_scroll.setWidget(chips_host)
        self._cmd_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._cmd_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._cmd_scroll.setFrameShape(QFrame.NoFrame)
        self._cmd_scroll.setStyleSheet("QScrollArea { background: transparent; }")
        self._cmd_scroll.setMinimumHeight(36)

        cmd_layout.addWidget(self._cmd_scroll, 1)
        self._rebuild_custom_command_buttons()

        cmd_layout.addStretch()

        self.manage_btn = QPushButton("管理命令")
        self.manage_btn.setIcon(IconHelper.icon(Icons.SETTINGS, 16))
        self.manage_btn.setStyleSheet(Buttons.secondary(icon_size="16px"))
        self.manage_btn.setToolTip("打开自定义命令管理器")
        self.manage_btn.clicked.connect(self.open_command_manager)
        cmd_layout.addWidget(self.manage_btn)

        parent_layout.addWidget(cmd_card)

    # ==================== 构建主工作区 ====================
    def _build_workspace(self, parent_layout: QVBoxLayout):
        self._main_splitter = QSplitter(Qt.Horizontal)

        # 左列：文件 + 终端
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(10)

        self.file_explorer = FileExplorer(self.file_service, self.get_current_terminal)
        apply_card(self.file_explorer)

        self.terminal_tabs = QTabWidget()
        # 关闭按钮用自定义 widget（原生叉号在浅色像素风样式下几乎不可见）
        self.terminal_tabs.setTabsClosable(False)
        self.terminal_tabs.setMinimumHeight(320)

        left_layout.addWidget(self.file_explorer, 4)
        left_layout.addWidget(self.terminal_tabs, 6)

        # 右列：技能 + 子选项
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(10)

        skills_card = QWidget()
        apply_card(skills_card)
        skills_layout = QVBoxLayout(skills_card)
        skills_layout.setContentsMargins(12, 10, 12, 10)
        skills_layout.setSpacing(12)
        skills_layout.addWidget(
            make_section_header("技能 / SKILLS", Icons.BOLT)
        )

        # ── SkillRegistry 动态构建卡片（替代硬编码） ──
        skill_grid = QHBoxLayout()
        skill_grid.setSpacing(12)

        self.sub_options = QStackedWidget()
        apply_card(self.sub_options)

        # 给插件注入回调
        for plugin in self.skill_registry._plugin_classes:
            if plugin is AppManagementSkill:
                plugin._install_cb = self._install_apk_dialog
                plugin._uninstall_cb = self._uninstall_apk_dialog
            # ScreenshotSkill 现在是 panel 模式，自带屏幕下拉和截图按钮，
            # 不再需要 main_window 的 _take_screenshot 回调

        self._skill_buttons, self._skill_panels = self.skill_registry.build_skill_cards(
            skill_grid, self.sub_options, self
        )
        skills_layout.addLayout(skill_grid)
        right_layout.addWidget(skills_card)

        # 从适配器取回面板引用（main_window 其他地方还要用）
        scrcpy_plugin = next(
            (p for p in self.skill_registry._plugins if isinstance(p, ScrcpySkill)), None
        )
        logcat_plugin = next(
            (p for p in self.skill_registry._plugins if isinstance(p, LogcatSkill)), None
        )
        self.scrcpy_options = scrcpy_plugin.get_panel() if scrcpy_plugin else None
        self.logcat_options = logcat_plugin.get_panel() if logcat_plugin else None
        if self.scrcpy_options:
            self.scrcpy_options.set_start_callback(self._on_scrcpy_start)
            # 注入 DisplayService（多屏枚举 + 别名）
            self.scrcpy_options.set_display_service(self.display_service, self.get_current_serial())

        self._skill_plugins = self.skill_registry._plugins

        right_layout.addWidget(self.sub_options, 1)

        self._main_splitter.addWidget(left_widget)
        self._main_splitter.addWidget(right_widget)
        self._main_splitter.setSizes([1140, 320])
        self._main_splitter.setStretchFactor(0, 1)
        self._main_splitter.setStretchFactor(1, 0)

        parent_layout.addWidget(self._main_splitter, 1)

        # 添加默认终端
        self.add_terminal_panel()

    def _highlight_skill(self, index: int):
        """统一高亮某个技能按钮（替代旧 _set_active_skill 的样式硬编码）。"""
        for i, btn in enumerate(self._skill_buttons):
            btn.setStyleSheet(skill_item_style(active=(i == index)))

    def _get_current_device_info(self):
        """PluginContext 回调：返回当前选中设备的 DeviceInfo（或 None）。"""
        serial = self.get_current_serial()
        if not serial:
            return None
        # 从 device_combo 的 data 里找；更准的方式是维护一个缓存
        return getattr(self, '_current_device_info', None)

    # ==================== 状态栏 ====================
    def _build_status_bar(self):
        self.status_bar = self.statusBar()
        author_label = QLabel("by Yxing")
        author_label.setStyleSheet(
            f"color: {Palette.TEXT_LIGHT}; font-size: 8pt; padding-right: 12px; font-style: italic;"
        )
        self.status_bar.addPermanentWidget(author_label)
        self._update_status_bar()

    # ==================== 多屏枚举回调 ====================
    def _on_displays_updated(self, displays: list):
        """DisplayService 枚举结果回调。分发给 scrcpy 面板等消费者。"""
        # scrcpy 面板
        if self.scrcpy_options and hasattr(self.scrcpy_options, 'on_displays_updated'):
            self.scrcpy_options.on_displays_updated(displays)

    def _on_display_enum_failed(self, err: str):
        """多屏枚举失败：允许手动输入。"""
        from PyQt5.QtWidgets import QInputDialog, QMessageBox
        from ..core.utils import COLOR_ERROR
        if self.get_current_terminal():
            self.get_current_terminal().print_system_msg(
                f"[警告] 屏列表枚举失败: {err}（可在投屏面板手动输入 display id）",
                COLOR_ERROR
            )

    # ==================== 设备断连检测 ====================
    def _check_device_state(self):
        """5s 轮询 adb get-state（异步 Worker，不阻塞 UI）。"""
        serial = self.get_current_serial()
        if not serial:
            return
        from ..core.utils import start_worker
        worker = DeviceStateCheckWorker(self.adb_client, serial)
        worker.state_result.connect(self._on_device_state_checked)
        start_worker(worker)

    def _on_device_state_checked(self, serial: str, state: str):
        """DeviceStateCheckWorker 回调：对比状态并触发刷新。"""
        # 仅对当前选中设备的结果生效（用户可能已切换）
        if serial != self.get_current_serial():
            return
        if state != self._device_last_state:
            self._device_last_state = state
            if state == "device":
                # 恢复在线
                self.status_bar.showMessage("设备已恢复连接")
                self.device_stat_pill.setVisible(True)
                self.device_stat_pill.setText("ROOT:未知")
                self.file_explorer.load_directory()
            else:
                # 离线 / 无设备
                self.status_bar.showMessage("设备离线", 5000)
                self.device_stat_pill.setVisible(False)

    def _get_startup_info(self):
        """子进程 STARTUPINFO（隐藏控制台窗口）。"""
        from ..core.utils import get_startup_info
        return get_startup_info()

    # ==================== 设备相关 ====================
    def get_current_serial(self):
        return self._current_serial if hasattr(self, '_current_serial') else None

    def refresh_devices(self):
        self.refresh_dev_btn.setEnabled(False)
        self.device_service.refresh_devices()

    def _on_devices_found(self, devices: list, message: str = ""):
        current_serial = self.get_current_serial()
        selected_serial = None

        if devices:
            # 优先使用当前选中，否则第一个可用设备
            for info in devices:
                serial = info.serial if isinstance(info, DeviceInfo) else info[0]
                state = info.state if isinstance(info, DeviceInfo) else info[1]
                if serial == current_serial and state == "device":
                    selected_serial = serial
                    break
            if selected_serial is None:
                for info in devices:
                    serial = info.serial if isinstance(info, DeviceInfo) else info[0]
                    state = info.state if isinstance(info, DeviceInfo) else info[1]
                    if state == "device":
                        selected_serial = serial
                        break
                if selected_serial is None:
                    info = devices[0]
                    selected_serial = info.serial if isinstance(info, DeviceInfo) else info[0]

        self._current_serial = selected_serial
        # 缓存 DeviceInfo（供 PluginContext.get_current_device_info_cb）
        self._current_device_info = None
        if selected_serial:
            for info in devices:
                if isinstance(info, DeviceInfo) and info.serial == selected_serial:
                    self._current_device_info = info
                    break
            # 启动设备类型探测（模拟器 / 真机 + thermal 可用）
            self._start_device_detector(selected_serial)
            # 启动多屏枚举（后台线程，不卡 UI）
            self.display_service.start_enumeration(selected_serial)
        else:
            self.display_service.clear_cache()

        # 首次检测到设备时才启动断连检测定时器，避免启动阶段无意义的 adb 调用
        if self._current_serial and not self._device_state_started:
            self._device_state_started = True
            self._device_state_timer.start()
        self._refresh_device_combo(devices)
        self._update_device_card(devices)
        self._sync_wireless_slot(devices)
        self._sync_terminal_device_labels()
        self.file_explorer.load_directory()
        self._update_status_bar()
        self.refresh_dev_btn.setEnabled(True)

        if not self._current_serial:
            self._device_state_timer.stop()
            # 无设备 → 重置 registry 设备状态
            self.skill_registry.set_device(False, False)

        unauthorized = any(
            (i.state if isinstance(i, DeviceInfo) else i[1]) == "unauthorized"
            for i in devices
        )
        if message and (not devices or unauthorized):
            QMessageBox.warning(self, "设备提示", message)

    # ==================== 设备类型探测 ====================
    def _start_device_detector(self, serial: str):
        """异步探测设备类型（模拟器 / 真机 + thermal）。"""
        from ..core.utils import start_worker
        worker = DeviceDetectorWorker(self.adb_client, serial)
        worker.result.connect(self._on_device_detected)
        start_worker(worker)

    def _on_device_detected(self, serial: str, is_emulator: bool, model: str,
                            characteristics: str, thermal_available: bool):
        """设备类型探测回调。"""
        # 只处理当前选中的设备（防止竞态：用户快速切换设备）
        if serial != self.get_current_serial():
            return
        # 更新缓存
        if self._current_device_info:
            self._current_device_info.is_emulator = is_emulator
            self._current_device_info.characteristics = characteristics
            self._current_device_info.thermal_available = thermal_available
            if model and not self._current_device_info.model:
                self._current_device_info.model = model
        # 通知 registry → 插件可据此过滤
        self.skill_registry.set_device(is_emulator, thermal_available)

        # 恢复该设备专属的 QSettings（splitter/scrcpy 复选框）
        self._restore_device_settings(serial)

    def _refresh_device_combo(self, devices: list):
        """刷新设备下拉框，当前选中设备保持在 _current_serial。"""
        self.device_combo.blockSignals(True)
        self.device_combo.clear()

        if not devices:
            self.device_combo.addItem("未连接设备", None)
            self.device_combo.setEnabled(False)
            self.device_combo.blockSignals(False)
            return

        self.device_combo.setEnabled(True)
        for info in devices:
            serial = info.serial if isinstance(info, DeviceInfo) else info[0]
            state = info.state if isinstance(info, DeviceInfo) else info[1]
            display = info.model if isinstance(info, DeviceInfo) and info.model else serial
            if state != "device":
                display += f" [{state}]"
            self.device_combo.addItem(display, serial)

        # 选中当前设备
        current = self.get_current_serial()
        for idx in range(self.device_combo.count()):
            if self.device_combo.itemData(idx) == current:
                self.device_combo.setCurrentIndex(idx)
                break
        self.device_combo.blockSignals(False)

    def _on_device_selected(self, index: int):
        """用户手动切换设备。"""
        if index < 0:
            return
        serial = self.device_combo.itemData(index)
        if serial == self.get_current_serial():
            return
        self._current_serial = serial
        self._update_device_card([])
        self._sync_terminal_device_labels()
        self.file_explorer.load_directory()
        self._update_status_bar()
        # 切换设备后立即探测新设备类型
        if serial:
            self._start_device_detector(serial)
        else:
            self._device_last_state = None

    def _update_device_card(self, devices: list):
        if not self._current_serial:
            self.device_stat_pill.setVisible(False)
            return

        info = self.device_service.get_device_info(self._current_serial, fetch_if_missing=False)
        if info is None:
            for d in devices:
                serial = d.serial if isinstance(d, DeviceInfo) else d[0]
                if serial == self._current_serial:
                    state = d.state if isinstance(d, DeviceInfo) else d[1]
                    info = DeviceInfo(serial=serial, state=state)
                    break

        self.device_stat_pill.setVisible(True)
        if info:
            root_text = info.root_state or "未知"
            self.device_stat_pill.setText(f"ROOT:{root_text}")

    def _sync_terminal_device_labels(self):
        serial = self.get_current_serial()
        label = ""
        if serial:
            info = self.device_service.get_device_info(serial, fetch_if_missing=False)
            if info and (info.model or info.android_version):
                label_parts = []
                if info.model:
                    label_parts.append(info.model)
                if info.android_version:
                    label_parts.append(f"Android {info.android_version}")
                label = " ".join(label_parts)
        for idx in range(self.terminal_tabs.count()):
            tab = self.terminal_tabs.widget(idx)
            if isinstance(tab, TerminalTab):
                tab.update_device_label(label)

    def _update_status_bar(self, *_args) -> None:
        serial = self.get_current_serial()
        parts = []
        if serial:
            info = self.device_service.get_device_info(serial, fetch_if_missing=False)
            if info and (info.model or info.android_version):
                label = info.model or serial
                parts.append(f"设备: {label} ({serial})" + (f" Android {info.android_version}" if info.android_version else ""))
            else:
                parts.append(f"设备: {serial}")
            if info and info.root_state:
                parts.append(f"Root: {info.root_state}")
        else:
            parts.append("设备: 未选择")

        parts.append(f"Scrcpy: {'运行中' if self._scrcpy_service.is_running() else '未启动'}")
        if self._logcat_service.is_recording():
            fn = os.path.basename(self._logcat_service.current_filename()) if self._logcat_service.current_filename() else ""
            parts.append(f"Logcat: 录制中({fn})")
        else:
            parts.append("Logcat: 未录制")

        self.status_bar.showMessage("  |  ".join(parts))

    # ==================== 终端相关 ====================
    def get_current_terminal(self) -> Optional[TerminalTab]:
        current = self.terminal_tabs.currentWidget()
        return current if isinstance(current, TerminalTab) else None

    def _make_tab_close_btn(self, tab: TerminalTab) -> QPushButton:
        """Tab 右侧的关闭按钮：透明底，悬浮变红，保证在像素风样式下清晰可见。"""
        btn = QPushButton()
        btn.setIcon(IconHelper.icon(Icons.CLOSE, 12))
        btn.setFixedSize(22, 22)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setToolTip("关闭此终端")
        btn.setStyleSheet(
            f"QPushButton {{ border: none; background: transparent; icon-size: 12px; }}"
            f"QPushButton:hover {{ background-color: {Palette.ERROR_LIGHT}; border-radius: 2px; }}"
        )
        btn.clicked.connect(
            lambda: self._on_terminal_tab_close(self.terminal_tabs.indexOf(tab))
        )
        return btn

    def _next_terminal_number(self) -> int:
        """统计当前已打开终端标签占用的编号，返回最小可用编号（关闭后编号可复用）。"""
        used = set()
        for idx in range(self.terminal_tabs.count()):
            title = self.terminal_tabs.tabText(idx)
            suffix = title.rsplit(" ", 1)[-1] if title else ""
            if suffix.isdigit():
                used.add(int(suffix))
        number = 1
        while number in used:
            number += 1
        return number

    def add_terminal_panel(self) -> TerminalTab:
        number = self._next_terminal_number()
        terminal_service = TerminalService(self.adb_client)
        # 首次创建时绑定到 PluginContext（供插件使用）
        if self._plugin_ctx.terminal_service is None:
            self._plugin_ctx.terminal_service = terminal_service
        tab = TerminalTab(self.get_current_serial, terminal_service, self)
        terminal_service.scrcpy_requested.connect(self._on_terminal_scrcpy_requested)
        idx = self.terminal_tabs.addTab(tab, f"Terminal {number}")
        self.terminal_tabs.setTabIcon(idx, IconHelper.icon(Icons.TERMINAL, 16))
        self.terminal_tabs.tabBar().setTabButton(idx, QTabBar.RightSide, self._make_tab_close_btn(tab))
        self.terminal_tabs.setCurrentWidget(tab)
        return tab

    def _on_terminal_tab_close(self, index: int):
        tab = self.terminal_tabs.widget(index)
        if isinstance(tab, TerminalTab) and tab.process and tab.process.state() == QProcess.Running:
            reply = QMessageBox.question(
                self, "确认关闭",
                "该终端仍有进程在运行，确定关闭吗？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return
            tab.process.kill()
            tab.process.waitForFinished(500)
        self.terminal_tabs.removeTab(index)
        if tab is not None:
            tab.deleteLater()
        # 最后一个终端关闭后自动补一个空终端，保持控制台区域可用
        if self.terminal_tabs.count() == 0:
            self.add_terminal_panel()

    def _on_terminal_scrcpy_requested(self, cmd_parts: list):
        if self._scrcpy_service.is_running():
            tab = self.get_current_terminal()
            if tab:
                tab.print_system_msg("[警告] scrcpy 已在运行，请先关闭")
            return
        params = cmd_parts[1:] if len(cmd_parts) > 1 else []
        serial = self.get_current_serial()
        self._scrcpy_service.launch(serial, params)

    # ==================== 自定义命令 ====================
    def _rebuild_custom_command_buttons(self):
        """根据 self.custom_commands 重新生成命令栏上的快捷芯片按钮。"""
        while self.custom_cmd_box.count():
            item = self.custom_cmd_box.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        for entry in self.custom_commands or []:
            name = entry.get("name", "")
            cmd = entry.get("cmd", "")
            if not name:
                continue
            btn = QPushButton(name)
            btn.setIcon(IconHelper.icon(Icons.PLAY, 14))
            btn.setStyleSheet(cmd_chip_style())
            btn.setCursor(Qt.PointingHandCursor)
            btn.setToolTip(cmd)
            btn.clicked.connect(partial(self._run_custom_command, cmd))
            self.custom_cmd_box.addWidget(btn)
        self.custom_cmd_box.addStretch()

    def _run_custom_command(self, cmd: str):
        """把管理命令里配置的（可能多行）指令送入当前终端队列顺序执行。"""
        if not cmd:
            return
        t = self.get_current_terminal()
        if t is None:
            QMessageBox.warning(self, "无终端", "当前没有可用的终端标签页")
            return
        t.run_external_command(cmd)

    def open_command_manager(self):
        dialog = CommandManagerDialog(self, self.custom_commands)
        if dialog.exec_() == QDialog.Accepted:
            self.custom_commands = dialog.commands
            if not save_commands(self.custom_commands):
                QMessageBox.warning(self, "保存失败", "配置文件写入失败")
            self._rebuild_custom_command_buttons()

    # ==================== 投屏相关 ====================
    def _on_scrcpy_start(self):
        if self._scrcpy_service.is_running():
            self._scrcpy_service.stop()
            return
        serial = self.get_current_serial()
        if not serial:
            QMessageBox.warning(self, "未选择设备", "请先连接并选择一台设备")
            return

        if self.scrcpy_options.is_multi_requested():
            # 多屏模式：为每块屏各开一个 scrcpy 窗口
            displays = self.scrcpy_options.get_multi_displays()
            if not displays:
                QMessageBox.warning(self, "无屏信息",
                                    "屏列表枚举失败，无法投屏所有屏。请先在投屏面板手动刷新。")
                return
            base_params = self.scrcpy_options.get_options()
            started = self._scrcpy_service.launch_all(serial, displays, base_params)
            if started > 0:
                self.scrcpy_options.set_running_state(True)
                if self.get_current_terminal():
                    names = [d.get('alias', f"屏幕{d.get('display_id')}") for d in displays]
                    self.get_current_terminal().print_system_msg(
                        f"[投屏] 已启动 {started}/{len(displays)} 块屏: {', '.join(names)}"
                    )
        else:
            # 单屏模式（兼容旧逻辑）
            params = self.scrcpy_options.get_options()
            # 如果有选中的 display，加 --display-id
            display_id = self.scrcpy_options._current_display_id()
            if display_id and self.scrcpy_options.display_combo.isEnabled():
                params.append(f"--display-id={display_id}")
            self._scrcpy_service.launch(serial, params)
            self.scrcpy_options.set_running_state(True)

    def _on_scrcpy_finished(self, exit_code: int):
        self.scrcpy_options.set_running_state(False)

    # ==================== 退出处理 ====================
    def closeEvent(self, event):
        # 先保存 QSettings
        self._save_settings()

        # 停止所有定时器
        try:
            self._device_state_timer.stop()
        except Exception:
            pass

        running_tabs = []
        for idx in range(self.terminal_tabs.count()):
            tab = self.terminal_tabs.widget(idx)
            if isinstance(tab, TerminalTab) and tab.process and tab.process.state() == QProcess.Running:
                running_tabs.append(tab)
        if running_tabs:
            reply = QMessageBox.question(
                self, "确认退出",
                f"有 {len(running_tabs)} 个终端仍在运行，确定强制退出吗？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                event.ignore()
                return

        # kill 所有终端 QProcess
        for idx in range(self.terminal_tabs.count()):
            tab = self.terminal_tabs.widget(idx)
            if isinstance(tab, TerminalTab) and tab.process is not None:
                try:
                    if tab.process.state() == QProcess.Running:
                        tab.process.kill()
                        tab.process.waitForFinished(500)
                except Exception:
                    pass

        # 同步停止投屏与 logcat 录制进程，避免退出后残留子进程
        try:
            if self._logcat_service.is_recording():
                self._logcat_service.stop_recording()
        except Exception:
            pass
        try:
            if self._scrcpy_service.is_running():
                self._scrcpy_service.stop()
        except Exception:
            pass

        event.accept()

    # ==================== 截图 ====================
    def _take_screenshot(self):
        """一键截图：adb shell screencap → adb pull 到本地 shots/ 目录。"""
        serial = self.get_current_serial()
        if not serial:
            QMessageBox.warning(self, "未选择设备", "请先连接并选择一台设备")
            return

        import subprocess
        local_dir = os.path.join(os.getcwd(), "shots")
        os.makedirs(local_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        local_path = os.path.join(local_dir, f"shot_{timestamp}.png")
        remote_path = "/sdcard/_shot.png"

        terminal = self.get_current_terminal()
        if terminal:
            terminal.print_system_msg("[截图] 正在截取屏幕...")

        # 后台 QThread 执行截图（避免阻塞 UI）
        from ..core.utils import start_worker, get_startup_info

        class ScreenshotWorker(QThread):
            done = pyqtSignal(bool, str, str)  # ok, local_path, error

            def run(self_inner):
                try:
                    # 1. 设备端截图
                    cmd1 = self.adb_client._build_cmd('shell', f'screencap -p {remote_path}')
                    r1 = subprocess.run(cmd1, capture_output=True, text=True,
                                        encoding='utf-8', errors='replace', timeout=10,
                                        startupinfo=get_startup_info(), cwd=self.adb_client.adb_home)
                    if r1.returncode != 0:
                        self_inner.done.emit(False, "", f"设备端截图失败: {(r1.stderr or r1.stdout or '').strip()}")
                        return
                    # 2. pull 到本地
                    cmd2 = self.adb_client._build_cmd('pull', remote_path, local_path)
                    r2 = subprocess.run(cmd2, capture_output=True, text=True,
                                        encoding='utf-8', errors='replace', timeout=15,
                                        startupinfo=get_startup_info(), cwd=self.adb_client.adb_home)
                    if r2.returncode != 0:
                        self_inner.done.emit(False, "", f"拉取失败: {(r2.stderr or r2.stdout or '').strip()}")
                        # 3b. 拉取失败也要清理远程临时文件
                        subprocess.run(self.adb_client._build_cmd('shell', f'rm {remote_path}'),
                                       capture_output=True, timeout=3,
                                       startupinfo=get_startup_info(), cwd=self.adb_client.adb_home)
                        return
                    # 3. 清理远程文件
                    subprocess.run(self.adb_client._build_cmd('shell', f'rm {remote_path}'),
                                   capture_output=True, text=True,
                                   encoding='utf-8', errors='replace', timeout=3,
                                   startupinfo=get_startup_info(), cwd=self.adb_client.adb_home)
                    self_inner.done.emit(True, local_path, "")
                except subprocess.TimeoutExpired:
                    self_inner.done.emit(False, "", "截图超时，请检查设备连接")
                except Exception as e:
                    self_inner.done.emit(False, "", f"截图失败: {e}")

        worker = ScreenshotWorker()
        worker.adb_client = self.adb_client
        worker.done.connect(self._on_screenshot_done)
        start_worker(worker)

    def _on_screenshot_done(self, ok: bool, local_path: str, error: str):
        terminal = self.get_current_terminal()
        if ok:
            if terminal:
                terminal.print_system_msg(f"[截图成功] 已保存到 {local_path}", COLOR_SUCCESS)
            QMessageBox.information(self, "截图成功", f"已保存到:\n{local_path}")
        else:
            if terminal:
                terminal.print_system_msg(f"[截图失败] {error}", COLOR_ERROR)
            QMessageBox.warning(self, "截图失败", error)

    # ==================== APK 安装 ====================
    def _install_apk_dialog(self):
        serial = self.get_current_serial()
        if not serial:
            QMessageBox.warning(self, "未选择设备", "请先连接并选择一台设备")
            return

        paths, _ = QFileDialog.getOpenFileNames(
            self, "选择要安装的 APK 文件", "",
            "APK 文件 (*.apk);;所有文件 (*.*)"
        )
        if not paths:
            return
        for p in paths:
            self._install_apk_file(p)

    def _install_apk_file(self, local_path: str):
        """后台 QThread 执行 adb install -r。"""
        from ..core.utils import start_worker, get_startup_info
        import subprocess

        terminal = self.get_current_terminal()
        name = os.path.basename(local_path)
        if terminal:
            terminal.print_system_msg(f"[安装 APK] {name} ...")

        class InstallWorker(QThread):
            done = pyqtSignal(bool, str, str)  # ok, package_name, error

            def run(self_inner):
                try:
                    cmd = self.adb_client._build_cmd('install', '-r', local_path)
                    r = subprocess.run(cmd, capture_output=True, text=True,
                                       encoding='utf-8', errors='replace', timeout=120,
                                       startupinfo=get_startup_info(), cwd=self.adb_client.adb_home)
                    out = (r.stdout or "") + (r.stderr or "")
                    if r.returncode == 0 and "Success" in out:
                        self_inner.done.emit(True, os.path.basename(local_path), "")
                    else:
                        self_inner.done.emit(False, os.path.basename(local_path), out.strip() or "安装失败")
                except subprocess.TimeoutExpired:
                    self_inner.done.emit(False, os.path.basename(local_path), "安装超时（>120s）")
                except Exception as e:
                    self_inner.done.emit(False, os.path.basename(local_path), str(e))

        worker = InstallWorker()
        worker.adb_client = self.adb_client
        worker.done.connect(self._on_install_apk_done)
        start_worker(worker)

    def _on_install_apk_done(self, ok: bool, name: str, error: str):
        terminal = self.get_current_terminal()
        if ok:
            if terminal:
                terminal.print_system_msg(f"[安装成功] {name}", COLOR_SUCCESS)
            QMessageBox.information(self, "安装成功", f"{name} 已成功安装到设备")
        else:
            if terminal:
                terminal.print_system_msg(f"[安装失败] {name}: {error}", COLOR_ERROR)
            QMessageBox.warning(self, "安装失败", f"{name}\n\n{error}")

    # ==================== APK 卸载 ====================
    def _uninstall_apk_dialog(self):
        """列出第三方应用，弹出选择列表供卸载。"""
        serial = self.get_current_serial()
        if not serial:
            QMessageBox.warning(self, "未选择设备", "请先连接并选择一台设备")
            return

        from ..core.utils import start_worker, get_startup_info
        import subprocess

        terminal = self.get_current_terminal()
        if terminal:
            terminal.print_system_msg("[卸载 APK] 正在列出第三方应用...")

        class ListPackagesWorker(QThread):
            done = pyqtSignal(list, str)  # packages, error

            def run(self_inner):
                try:
                    cmd = self.adb_client._build_cmd('shell', 'pm list packages -3')
                    r = subprocess.run(cmd, capture_output=True, text=True,
                                       encoding='utf-8', errors='replace', timeout=10,
                                       startupinfo=get_startup_info(), cwd=self.adb_client.adb_home)
                    packages = []
                    for line in (r.stdout or "").splitlines():
                        line = line.strip()
                        if line.startswith("package:"):
                            packages.append(line[8:])
                    self_inner.done.emit(packages, "")
                except subprocess.TimeoutExpired:
                    self_inner.done.emit([], "命令超时，请检查设备连接")
                except FileNotFoundError:
                    self_inner.done.emit([], "未找到 adb 命令，请确认 adb 已正确安装")
                except Exception as e:
                    self_inner.done.emit([], f"未知错误: {e}")

        worker = ListPackagesWorker()
        worker.adb_client = self.adb_client
        worker.done.connect(self._on_list_packages_done)
        start_worker(worker)

    def _on_list_packages_done(self, packages: list, error: str):
        if error:
            QMessageBox.warning(self, "错误", f"获取应用列表失败:\n{error}")
            return
        if not packages:
            QMessageBox.information(self, "无第三方应用", "设备上没有可卸载的第三方应用")
            return

        # 弹出自定义列表对话框
        dialog = QDialog(self)
        from .dialogs.dialog_styles import setup_dialog_window
        setup_dialog_window(dialog, "选择要卸载的应用", min_width=380)
        dialog.setMinimumHeight(420)
        layout = QVBoxLayout(dialog)

        hint = QLabel(f"共 {len(packages)} 个第三方应用")
        hint.setStyleSheet(f"color: {Palette.TEXT_DIM}; font-size: 9pt;")
        layout.addWidget(hint)

        list_widget = QListWidget()
        list_widget.setStyleSheet(
            f"QListWidget {{ background: {Palette.SURFACE}; border: 3px solid {Palette.BORDER_STRONG}; "
            f"border-radius: 2px; font-family: {Fonts.UI}; font-size: 9pt; }}"
            f"QListWidget::item {{ padding: 4px; }}"
            f"QListWidget::item:selected {{ background: {Palette.PRIMARY_LIGHT}; color: {Palette.TEXT}; }}"
        )
        for pkg in packages:
            list_widget.addItem(pkg)
        layout.addWidget(list_widget, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton("取消")
        cancel_btn.setStyleSheet(Buttons.ghost(icon_size="12px"))
        cancel_btn.setToolTip("不卸载任何应用，关闭对话框")
        cancel_btn.clicked.connect(dialog.reject)
        uninstall_btn = QPushButton("卸载")
        uninstall_btn.setStyleSheet(Buttons.danger(icon_size="12px"))
        uninstall_btn.setToolTip("卸载当前选中的应用包")
        uninstall_btn.clicked.connect(dialog.accept)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(uninstall_btn)
        layout.addLayout(btn_row)

        if dialog.exec_() != QDialog.Accepted:
            return

        selected = list_widget.currentItem()
        if not selected:
            return
        pkg_name = selected.text()
        self._uninstall_apk_package(pkg_name)

    def _uninstall_apk_package(self, package_name: str):
        from ..core.utils import start_worker, get_startup_info
        import subprocess

        terminal = self.get_current_terminal()
        if terminal:
            terminal.print_system_msg(f"[卸载 APK] {package_name} ...")

        class UninstallWorker(QThread):
            done = pyqtSignal(bool, str, str)  # ok, package, error

            def run(self_inner):
                try:
                    cmd = self.adb_client._build_cmd('uninstall', package_name)
                    r = subprocess.run(cmd, capture_output=True, text=True,
                                       encoding='utf-8', errors='replace', timeout=30,
                                       startupinfo=get_startup_info(), cwd=self.adb_client.adb_home)
                    out = (r.stdout or "") + (r.stderr or "")
                    if r.returncode == 0 and "Success" in out:
                        self_inner.done.emit(True, package_name, "")
                    else:
                        self_inner.done.emit(False, package_name, out.strip() or "卸载失败")
                except subprocess.TimeoutExpired:
                    self_inner.done.emit(False, package_name, "卸载超时")
                except Exception as e:
                    self_inner.done.emit(False, package_name, str(e))

        worker = UninstallWorker()
        worker.adb_client = self.adb_client
        worker.done.connect(self._on_uninstall_done)
        start_worker(worker)

    def _on_uninstall_done(self, ok: bool, package_name: str, error: str):
        terminal = self.get_current_terminal()
        if ok:
            if terminal:
                terminal.print_system_msg(f"[卸载成功] {package_name}", COLOR_SUCCESS)
            QMessageBox.information(self, "卸载成功", f"{package_name} 已卸载")
        else:
            if terminal:
                terminal.print_system_msg(f"[卸载失败] {package_name}: {error}", COLOR_ERROR)
            QMessageBox.warning(self, "卸载失败", f"{package_name}\n\n{error}")

    # ==================== .apk 拖拽到窗口直接安装 ====================
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            # 只接受有 .apk 的拖拽
            for url in event.mimeData().urls():
                if url.toLocalFile().lower().endswith('.apk'):
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dropEvent(self, event):
        serial = self.get_current_serial()
        if not serial:
            QMessageBox.warning(self, "未选择设备", "请先连接并选择一台设备")
            return
        apk_paths = []
        for url in event.mimeData().urls():
            p = url.toLocalFile()
            if p.lower().endswith('.apk') and os.path.isfile(p):
                apk_paths.append(p)
        if not apk_paths:
            return
        for p in apk_paths:
            self._install_apk_file(p)
