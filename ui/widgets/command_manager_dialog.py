import copy

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog, QFormLayout, QHBoxLayout, QLabel, QListWidget, QMessageBox,
    QTextEdit, QVBoxLayout, QLineEdit
)

from ..dialogs.dialog_styles import (
    STATUS_ERROR_QSS, STATUS_SUCCESS_QSS, STATUS_WARNING_QSS,
    create_danger_button, create_primary_button, create_secondary_button,
    setup_dialog_window
)
from ..theme import IconHelper, Icons


class CommandManagerDialog(QDialog):
    def __init__(self, parent=None, commands=None):
        super().__init__(parent)
        setup_dialog_window(self, "管理自定义命令", min_width=560)
        self.resize(560, 440)
        self.commands = copy.deepcopy(commands) if commands else []
        self.main_layout = QHBoxLayout(self)
        self.main_layout.setContentsMargins(10, 10, 10, 10)
        self.main_layout.setSpacing(10)

        # 左侧命令列表：收窄到 150px
        self.list_widget = QListWidget()
        self.list_widget.setFixedWidth(150)
        self.list_widget.setStyleSheet(
            f"""
            QListWidget {{
                background-color: #FAF8F2;
                border: 2px solid #A9A59A;
                border-radius: 2px;
                font-size: 9pt;
            }}
            QListWidget::item {{
                color: #3A2F1E;
                padding: 4px 6px;
            }}
            QListWidget::item:selected {{
                background-color: #E8F0DF;
                color: #6E8A5A;
            }}
            QListWidget::item:hover {{
                background-color: #EFEBE0;
            }}
            """
        )
        self.update_list()
        self.list_widget.currentRowChanged.connect(self.load_selected)
        # 初始化后清除默认选中，让输入框保持空白，避免用户误以为在"编辑"已有项
        self.list_widget.blockSignals(True)
        self.list_widget.clearSelection()
        self.list_widget.blockSignals(False)

        self.edit_layout = QVBoxLayout()
        self.edit_layout.setSpacing(6)
        self.form_layout = QFormLayout()
        self.form_layout.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.form_layout.setFormAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.form_layout.setHorizontalSpacing(8)
        self.form_layout.setVerticalSpacing(6)

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("按钮显示名称")
        self.cmd_input = QTextEdit()
        self.cmd_input.setMinimumHeight(100)
        self.cmd_input.setMaximumHeight(100)
        self.cmd_input.setPlaceholderText(
            "支持多行输入，按顺序自动执行多条命令\n例如:\nshell svc wifi disable\nscrcpy -m 1920"
        )

        # 标签统一黑色（深棕）
        label_style = "color: #3A2F1E; font-weight: 700; font-size: 9pt;"
        name_label = QLabel("按钮名称:")
        name_label.setStyleSheet(label_style)
        cmd_label = QLabel("ADB 指令:")
        cmd_label.setStyleSheet(label_style)

        self.form_layout.addRow(name_label, self.name_input)
        self.form_layout.addRow(cmd_label, self.cmd_input)

        self._status = QLabel("")

        self.btn_layout1 = QHBoxLayout()
        self.add_btn = create_primary_button("新增")
        self.add_btn.setIcon(IconHelper.icon(Icons.ADD, 16))
        self.save_btn = create_primary_button("保存修改")
        self.save_btn.setIcon(IconHelper.icon(Icons.SAVE, 16))
        self.del_btn = create_danger_button("删除")
        self.del_btn.setIcon(IconHelper.icon(Icons.DELETE, 16))
        for btn in (self.add_btn, self.save_btn, self.del_btn):
            self.btn_layout1.addWidget(btn)

        self.btn_layout2 = QHBoxLayout()
        self.up_btn = create_secondary_button("上移")
        self.up_btn.setIcon(IconHelper.icon(Icons.MOVE_UP, 16))
        self.down_btn = create_secondary_button("下移")
        self.down_btn.setIcon(IconHelper.icon(Icons.MOVE_DOWN, 16))
        for btn in (self.up_btn, self.down_btn):
            self.btn_layout2.addWidget(btn)

        self.bottom_layout = QHBoxLayout()
        self.help_btn = create_secondary_button("使用帮助")
        self.help_btn.setIcon(IconHelper.icon(Icons.HELP, 16))
        self.close_btn = create_primary_button("完成并退出")
        self.close_btn.setIcon(IconHelper.icon(Icons.CHECK, 16))
        self.close_btn.clicked.connect(self.accept)

        self.bottom_layout.addWidget(self.help_btn)
        self.bottom_layout.addStretch()
        self.bottom_layout.addWidget(self.close_btn)

        self.edit_layout.addLayout(self.form_layout)
        self.edit_layout.addWidget(self._status)
        self.edit_layout.addLayout(self.btn_layout1)
        self.edit_layout.addLayout(self.btn_layout2)
        self.edit_layout.addStretch()
        self.edit_layout.addLayout(self.bottom_layout)

        self.main_layout.addWidget(self.list_widget, 0)  # 固定宽度，不拉伸
        self.main_layout.addLayout(self.edit_layout, 1)

        self.add_btn.clicked.connect(self.add_command)
        self.save_btn.clicked.connect(self.save_command)
        self.del_btn.clicked.connect(self.delete_command)
        self.up_btn.clicked.connect(self.move_up)
        self.down_btn.clicked.connect(self.move_down)
        self.help_btn.clicked.connect(self.show_help)

    def show_help(self):
        QMessageBox.information(
            self, "帮助说明",
            "<h3>自定义命令使用指南</h3>"
            "<p><b>1. 基础用法</b><br>无需输入 <code>adb</code>，直接输入指令即可，例如：<code>shell ls -l</code></p>"
            "<hr><p><b>2. 多行批处理</b><br>支持在指令框中换行，点击执行时会依次顺序执行所有命令。</p>"
        )

    def _set_status(self, text: str, style: str):
        self._status.setText(text)
        self._status.setStyleSheet(style)

    def update_list(self):
        self.list_widget.blockSignals(True)
        self.list_widget.clear()
        for cmd in self.commands:
            self.list_widget.addItem(cmd.get("name", "未命名"))
        self.list_widget.blockSignals(False)

    def load_selected(self, index: int):
        if 0 <= index < len(self.commands):
            self.name_input.setText(self.commands[index].get("name", ""))
            self.cmd_input.setText(self.commands[index].get("cmd", ""))
            self._set_status(f"编辑第 {index + 1} 项", STATUS_SUCCESS_QSS)

    def _get_inputs(self):
        return self.name_input.text().strip(), self.cmd_input.toPlainText().strip()

    def _find_duplicate(self, name: str, exclude_index: int = -1) -> int:
        for i, cmd in enumerate(self.commands):
            if i != exclude_index and cmd.get("name", "") == name:
                return i
        return -1

    def add_command(self):
        name, cmd = self._get_inputs()
        if not name:
            self._set_status("请输入按钮名称", STATUS_ERROR_QSS)
            self.name_input.setFocus()
            return
        if not cmd:
            self._set_status("请输入 ADB 指令", STATUS_ERROR_QSS)
            self.cmd_input.setFocus()
            return
        if self._find_duplicate(name) >= 0:
            self._set_status(f"名称「{name}」已存在，请使用不同名称", STATUS_WARNING_QSS)
            return
        self.commands.append({"name": name, "cmd": cmd})
        self.update_list()
        idx = len(self.commands) - 1
        self.list_widget.setCurrentRow(idx)
        # 清空输入框，方便用户连续新增
        self.name_input.clear()
        self.cmd_input.clear()
        self._set_status(f"已新增「{name}」（输入框已清空，可继续新增）", STATUS_SUCCESS_QSS)

    def save_command(self):
        index = self.list_widget.currentRow()
        if index < 0:
            self._set_status("请先在列表中选择要保存的命令", STATUS_WARNING_QSS)
            return
        name, cmd = self._get_inputs()
        if not name:
            self._set_status("请输入按钮名称", STATUS_ERROR_QSS)
            return
        if not cmd:
            self._set_status("请输入 ADB 指令", STATUS_ERROR_QSS)
            return
        dup_idx = self._find_duplicate(name, exclude_index=index)
        if dup_idx >= 0:
            self._set_status(
                f"名称「{name}」与第 {dup_idx + 1} 项重复", STATUS_WARNING_QSS
            )
            return
        self.commands[index] = {"name": name, "cmd": cmd}
        self.update_list()
        self.list_widget.setCurrentRow(index)
        self._set_status(f"已保存第 {index + 1} 项「{name}」", STATUS_SUCCESS_QSS)

    def delete_command(self):
        index = self.list_widget.currentRow()
        if index < 0:
            self._set_status("请先选择要删除的命令", STATUS_WARNING_QSS)
            return
        name = self.commands[index].get("name", "")
        reply = QMessageBox.question(
            self, "确认删除",
            f"确定要删除命令「{name}」吗？此操作不可撤销。",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return
        del self.commands[index]
        self.update_list()
        self.name_input.clear()
        self.cmd_input.clear()
        self._set_status(f"已删除「{name}」", STATUS_SUCCESS_QSS)

    def move_up(self):
        idx = self.list_widget.currentRow()
        if idx > 0:
            self.commands[idx], self.commands[idx - 1] = (
                self.commands[idx - 1], self.commands[idx]
            )
            self.update_list()
            self.list_widget.setCurrentRow(idx - 1)

    def move_down(self):
        idx = self.list_widget.currentRow()
        if 0 <= idx < len(self.commands) - 1:
            self.commands[idx], self.commands[idx + 1] = (
                self.commands[idx + 1], self.commands[idx]
            )
            self.update_list()
            self.list_widget.setCurrentRow(idx + 1)
