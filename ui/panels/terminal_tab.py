import codecs
from typing import Callable, Optional

from PyQt5.QtCore import QProcess, Qt
from PyQt5.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ...core.utils import COLOR_ERROR, COLOR_SYSTEM
from ...services.terminal_service import TerminalService
from ..theme import Buttons, IconHelper, Icons, Palette, status_badge_style
from ..widgets.console_edit import ConsoleEdit


class TerminalTab(QWidget):
    def __init__(self, get_serial_cb: Callable[[], Optional[str]], terminal_service: TerminalService, parent=None):
        super().__init__(parent)
        self.get_serial_cb = get_serial_cb
        self.terminal_service = terminal_service
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(6, 6, 6, 6)
        self.main_layout.setSpacing(6)

        self.top_layout = QHBoxLayout()
        self.top_layout.setContentsMargins(4, 4, 4, 4)
        self.top_layout.setSpacing(8)
        # 图标与文字分开放：QLabel 同时 setPixmap + setText 时文字会被图标覆盖
        self.status_icon = QLabel()
        self.status_icon.setPixmap(IconHelper.pixmap(Icons.TERMINAL, 14))
        self.status_icon.setStyleSheet("border: none; background: transparent;")
        self.status_label = QLabel("状态: 待命")
        self.status_label.setStyleSheet(status_badge_style(Palette.TEXT_DIM))
        self.status_label.setToolTip("当前终端进程状态")

        self.kill_btn = QPushButton(" 强制结束")
        self.kill_btn.setIcon(IconHelper.icon(Icons.STOP, 14))
        self.kill_btn.setStyleSheet(Buttons.danger(padding="3px 10px", icon_size="14px"))
        self.kill_btn.setCursor(Qt.PointingHandCursor)
        self.kill_btn.setVisible(False)
        self.kill_btn.setToolTip("终止当前运行中的命令")
        self.kill_btn.clicked.connect(self.terminal_service.kill_process)

        self.top_layout.addWidget(self.status_icon)
        self.top_layout.addWidget(self.status_label)
        self.top_layout.addStretch()
        self.top_layout.addWidget(self.kill_btn)

        self.terminal = ConsoleEdit()
        self.terminal.execute_cmd_signal.connect(self.terminal_service.run_command)
        self.terminal.ctrl_c_signal.connect(self.terminal_service.send_ctrl_c)
        self.main_layout.addLayout(self.top_layout)
        self.main_layout.addWidget(self.terminal)

        self.decoder_out = codecs.getincrementaldecoder('utf-8')(errors='replace')
        self.decoder_err = codecs.getincrementaldecoder('utf-8')(errors='replace')

        self.process = QProcess(self)
        self.terminal_service.bind_process(self.process, self.decoder_out, self.decoder_err)
        self.terminal.reset_prompt(self.get_serial_cb())

        self.terminal_service.output_written.connect(self._on_output_written)
        self.terminal_service.system_msg.connect(self._on_system_msg)
        self.terminal_service.prompt_reset.connect(self._on_prompt_reset)
        self.terminal_service.state_changed.connect(self._on_state_changed)

    def _on_output_written(self, text: str, color: str = None):
        self.terminal.write_output(text, color)

    def _on_system_msg(self, msg: str, color: str = COLOR_SYSTEM):
        self.terminal.write_output(msg + '\n', color)

    def _on_prompt_reset(self):
        self.terminal.reset_prompt(self.get_serial_cb())

    def _on_state_changed(self, is_running: bool):
        self.kill_btn.setVisible(is_running)
        if is_running:
            self.status_label.setText("状态: 运行中...")
            self.status_label.setStyleSheet(status_badge_style(Palette.ACCENT))
        else:
            self.status_label.setText("状态: 待命")
            self.status_label.setStyleSheet(status_badge_style(Palette.TEXT_DIM))

    def update_device_label(self, label: str):
        """由 main_window 在设备刷新后调用，注入到 ConsoleEdit 的 prompt 显示。"""
        # 相同标签不重置 prompt，避免重复输出
        if self.terminal._device_label == label:
            return
        self.terminal.set_device_label(label)
        self.terminal.reset_prompt(self.get_serial_cb())

    def print_system_msg(self, msg: str, color: str = COLOR_SYSTEM):
        self.terminal.write_output(msg + '\n', color)

    def run_external_command(self, cmd_str: str):
        self.terminal_service.run_command(cmd_str, from_external=True)
