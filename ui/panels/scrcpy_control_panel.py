"""scrcpy 投屏选项面板 — 多屏架构版。

核心变化：
- 不再自己跑 dumpsys，改由 DisplayService 统一枚举
- 支持多屏：投屏所有屏 复选框（单屏时隐藏）
- 屏幕下拉框旁加刷新按钮 + 铅笔（重命名别名）按钮
- 枚举失败时下拉框允许手动输入 display id
"""

from typing import List, Optional

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QCheckBox, QComboBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPushButton, QSpinBox, QVBoxLayout, QWidget
)

from ..theme import (
    Buttons, IconHelper, Icons, Palette, field_label_style, make_section_header
)

DEFAULT_FPS = 60
DEFAULT_BITRATE = 8


class ScrcpyControlPanel(QWidget):
    """scrcpy 投屏选项控件：紧凑布局，多屏感知。"""

    # 多屏启动信号（传屏列表 + 基础参数）
    multi_start_requested = pyqtSignal(list, list)

    def __init__(self, parent=None):
        super().__init__(parent)

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(12, 10, 12, 10)
        self.main_layout.setSpacing(8)

        self.main_layout.addWidget(
            make_section_header("投屏设置 / SCREEN OPTIONS", Icons.SCREEN_MIRROR)
        )

        # ── 屏幕选择行（始终显示，失败时自动切手动输入） ──
        row_display = QHBoxLayout()
        row_display.setSpacing(6)
        disp_label = QLabel("屏幕")
        disp_label.setStyleSheet(field_label_style())
        row_display.addWidget(disp_label)

        self.display_combo = QComboBox()
        self.display_combo.setEditable(True)  # 枚举失败时允许手动输入
        self.display_combo.setToolTip(
            "选择要投屏的屏幕（多屏时列出所有；枚举失败可手动输入 display id）"
        )
        row_display.addWidget(self.display_combo, 1)

        # 刷新屏列表按钮
        self.refresh_disp_btn = QPushButton()
        self.refresh_disp_btn.setIcon(IconHelper.icon(Icons.REFRESH, 14))
        self.refresh_disp_btn.setStyleSheet(Buttons.ghost(padding="2px", icon_size="14px"))
        self.refresh_disp_btn.setToolTip("刷新屏列表")
        self.refresh_disp_btn.setFixedSize(26, 26)
        self.refresh_disp_btn.setCursor(Qt.PointingHandCursor)
        row_display.addWidget(self.refresh_disp_btn)

        # 铅笔按钮（重命名别名）
        self.rename_disp_btn = QPushButton()
        self.rename_disp_btn.setIcon(IconHelper.icon(Icons.EDIT, 14))
        self.rename_disp_btn.setStyleSheet(Buttons.ghost(padding="2px", icon_size="14px"))
        self.rename_disp_btn.setToolTip("重命名当前屏的别名")
        self.rename_disp_btn.setFixedSize(26, 26)
        self.rename_disp_btn.setCursor(Qt.PointingHandCursor)
        row_display.addWidget(self.rename_disp_btn)

        self.main_layout.addLayout(row_display)
        self._display_row = row_display

        # 枚举状态提示
        self._disp_status_label = QLabel("（等待屏列表...）")
        self._disp_status_label.setStyleSheet(
            f"color: {Palette.TEXT_DIM}; font-size: 8pt; padding-left: 4px;"
        )
        self._disp_status_label.setVisible(False)
        self.main_layout.addWidget(self._disp_status_label)

        # ── 投屏所有屏（单屏时隐藏） ──
        self.multi_chk = QCheckBox("投屏所有屏")
        self.multi_chk.setToolTip("同时为每块屏各开一个 scrcpy 窗口")
        self.multi_chk.setVisible(False)
        self.main_layout.addWidget(self.multi_chk)

        # 常用选项
        self.stay_awake_chk = QCheckBox("保持唤醒")
        self.record_chk = QCheckBox("录制屏幕")
        self.audio_chk = QCheckBox("启用音频")
        self.audio_chk.setChecked(True)
        self.main_layout.addWidget(self.stay_awake_chk)
        self.main_layout.addWidget(self.record_chk)
        self.main_layout.addWidget(self.audio_chk)

        # 高级选项折叠/展开按钮
        self._adv_btn = QPushButton("高级选项 ▶")
        self._adv_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; border: none; color: {Palette.TEXT_DIM}; "
            f"font-size: 9pt; padding: 2px; text-align: left; }}"
            f"QPushButton:hover {{ color: {Palette.PRIMARY_DARK}; }}"
        )
        self._adv_btn.setCursor(Qt.PointingHandCursor)
        self._adv_btn.clicked.connect(self._toggle_advanced)
        self.main_layout.addWidget(self._adv_btn)

        # 高级选项容器（默认隐藏）
        self._adv_container = QWidget()
        self._adv_container.setStyleSheet("background: transparent;")
        adv_layout = QVBoxLayout(self._adv_container)
        adv_layout.setContentsMargins(0, 0, 0, 0)
        adv_layout.setSpacing(6)

        # 分辨率
        row_res = QHBoxLayout()
        res_label = QLabel("分辨率")
        res_label.setStyleSheet(field_label_style())
        row_res.addWidget(res_label)
        self.resolution_combo = QComboBox()
        self.resolution_combo.addItems(["原始", "1280", "1920", "1024"])
        row_res.addWidget(self.resolution_combo)
        adv_layout.addLayout(row_res)

        # 码率
        row_bit = QHBoxLayout()
        bit_label = QLabel("码率")
        bit_label.setStyleSheet(field_label_style())
        row_bit.addWidget(bit_label)
        self.bitrate_spin = QSpinBox()
        self.bitrate_spin.setRange(1, 100)
        self.bitrate_spin.setValue(DEFAULT_BITRATE)
        self.bitrate_spin.setSuffix(" Mbps")
        row_bit.addWidget(self.bitrate_spin)
        adv_layout.addLayout(row_bit)

        # 帧率
        row_fps = QHBoxLayout()
        fps_label = QLabel("帧率")
        fps_label.setStyleSheet(field_label_style())
        row_fps.addWidget(fps_label)
        self.fps_spin = QSpinBox()
        self.fps_spin.setRange(1, 120)
        self.fps_spin.setValue(DEFAULT_FPS)
        self.fps_spin.setSuffix(" fps")
        row_fps.addWidget(self.fps_spin)
        adv_layout.addLayout(row_fps)

        # 自定义参数
        row_extra = QHBoxLayout()
        extra_label = QLabel("自定义")
        extra_label.setStyleSheet(field_label_style())
        row_extra.addWidget(extra_label)
        self.extra_args_input = QLineEdit()
        self.extra_args_input.setPlaceholderText("--turns-off-screen-after=10s --no-control")
        self.extra_args_input.setToolTip("额外的 scrcpy 命令行参数，空格分隔")
        row_extra.addWidget(self.extra_args_input, 1)
        adv_layout.addLayout(row_extra)

        self._adv_container.setVisible(False)
        self.main_layout.addWidget(self._adv_container)

        # 启动按钮
        self.start_btn = QPushButton(" 启动投屏")
        self.start_btn.setIcon(IconHelper.icon(Icons.PLAY, 16))
        self.start_btn.setStyleSheet(Buttons.success(icon_size="16px"))
        self.start_btn.setCursor(Qt.PointingHandCursor)
        self.main_layout.addWidget(self.start_btn)

        self.main_layout.addStretch()

        # DisplayService 引用（由 main_window 通过 set_display_service 注入）
        self._display_service = None
        self._serial = None

        # 连接内部信号
        self.refresh_disp_btn.clicked.connect(self._on_refresh_display)
        self.rename_disp_btn.clicked.connect(self._on_rename_display)

    def _toggle_advanced(self):
        visible = not self._adv_container.isVisible()
        self._adv_container.setVisible(visible)
        self._adv_btn.setText("高级选项 ▼" if visible else "高级选项 ▶")

    # ── DisplayService 接口（由 main_window 调用） ──

    def set_display_service(self, display_service, serial: str = None):
        """注入 DisplayService 并连接信号。"""
        self._display_service = display_service
        self._serial = serial
        if display_service:
            display_service.displays_updated.connect(self.on_displays_updated)
            display_service.enumeration_started.connect(self._on_enum_started)
            display_service.enumeration_finished.connect(self._on_enum_finished)
            display_service.enumeration_failed.connect(self._on_enum_failed)

    def set_serial(self, serial: Optional[str]):
        self._serial = serial

    def _on_enum_started(self):
        self._disp_status_label.setText("正在检测屏列表...")
        self._disp_status_label.setVisible(True)
        self.display_combo.setEnabled(False)

    def _on_enum_finished(self):
        self._disp_status_label.setVisible(False)
        self.display_combo.setEnabled(True)

    def _on_enum_failed(self, err: str):
        self._disp_status_label.setText(f"枚举失败（可手动输入 display id）")
        self._disp_status_label.setStyleSheet(
            f"color: {Palette.ERROR}; font-size: 8pt; padding-left: 4px;"
        )
        self._disp_status_label.setVisible(True)
        self.display_combo.clear()
        self.display_combo.setEditable(True)
        self.display_combo.setEnabled(True)

    def on_displays_updated(self, displays: list):
        """DisplayService 推送新的屏列表。"""
        self._disp_status_label.setVisible(False)
        self.display_combo.clear()

        if not displays:
            # 无屏信息（设备可能没连上或枚举失败）
            self.display_combo.setEditable(True)
            self.display_combo.setEnabled(True)
            self.multi_chk.setVisible(False)
            self.rename_disp_btn.setEnabled(False)
            return

        self.display_combo.setEditable(False)  # 枚举成功则锁定选择
        self.rename_disp_btn.setEnabled(True)

        for d in displays:
            # DisplayInfo dataclass 或 dict 都支持
            if hasattr(d, 'label'):
                label = d.label
                did = d.display_id
            elif isinstance(d, dict):
                label = d.get('label') or d.get('alias') or f"屏幕{d.get('display_id', '')}"
                did = d.get('display_id', '')
            else:
                label = str(d)
                did = str(d)
            self.display_combo.addItem(label, did)

        # 多屏时显示"投屏所有屏"
        self.multi_chk.setVisible(len(displays) > 1)
        self.multi_chk.setChecked(False)

    # ── 手动操作 ──

    def _on_refresh_display(self):
        """点刷新屏列表按钮。"""
        if self._display_service and self._serial:
            self._display_service.refresh(self._serial)

    def _on_rename_display(self):
        """重命名当前屏别名。"""
        if not self._display_service:
            return
        display_id = self._current_display_id()
        if not display_id:
            return

        from PyQt5.QtWidgets import QInputDialog
        current_alias = self._display_service.get_alias(display_id)
        new_alias, ok = QInputDialog.getText(
            self, "重命名屏幕",
            f"屏幕 {display_id} 的别名:",
            text=current_alias,
        )
        if ok:
            self._display_service.set_alias(display_id, new_alias.strip())

    def _current_display_id(self) -> str:
        """获取当前选中的 display id。"""
        data = self.display_combo.currentData()
        if data:
            return str(data)
        # 手动输入模式
        text = self.display_combo.currentText().strip()
        return text

    def current_display_label(self) -> str:
        """当前屏的显示名（含别名）。"""
        if self._display_service:
            did = self._current_display_id()
            d = self._display_service.find_display(did)
            if d:
                return d.display_name
        return self.display_combo.currentText() or "主屏"

    # ── 参数读取 ──

    def get_options(self) -> List[str]:
        """返回当前设置对应的 scrcpy 参数列表（基础参数，不含 display-id）。"""
        params: List[str] = []

        res = self.resolution_combo.currentText()
        if res != "原始":
            params.extend(["-m", res])

        params.append(f"--max-fps={self.fps_spin.value()}")
        params.append(f"--video-bit-rate={self.bitrate_spin.value()}M")

        if not self.audio_chk.isChecked():
            params.append("--no-audio")

        if self.stay_awake_chk.isChecked():
            params.append("--stay-awake")

        if self.record_chk.isChecked():
            params.append("--record=scrcpy_recording.mp4")

        extra = self.extra_args_input.text().strip()
        if extra:
            params.extend(extra.split())

        return params

    def get_multi_displays(self) -> List[dict]:
        """多屏模式：返回当前所有屏的参数列表。"""
        if not self._display_service:
            return []
        return [
            {
                'display_id': d.display_id,
                'alias': d.display_name,
                'label': d.label,
                'resolution': d.resolution,
            }
            for d in self._display_service.displays
        ]

    # ── 对外状态接口 ──

    def is_multi_requested(self) -> bool:
        """用户是否勾选了"投屏所有屏"。"""
        return self.multi_chk.isVisible() and self.multi_chk.isChecked()

    def set_start_callback(self, callback):
        """供外部绑定启动按钮点击事件。"""
        self.start_btn.clicked.connect(callback)

    def set_running_state(self, running: bool):
        """根据运行状态切换按钮文案。"""
        if running:
            self.start_btn.setText(" 关闭投屏")
            self.start_btn.setIcon(IconHelper.icon(Icons.STOP, 16))
            self.start_btn.setStyleSheet(Buttons.danger(icon_size="16px"))
        else:
            self.start_btn.setText(" 启动投屏")
            self.start_btn.setIcon(IconHelper.icon(Icons.PLAY, 16))
            self.start_btn.setStyleSheet(Buttons.success(icon_size="16px"))
