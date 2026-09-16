from PyQt5.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout
)

from ...core.utils import is_valid_filename
from .dialog_styles import (
    STATUS_ERROR_QSS, STATUS_NEUTRAL_QSS, STATUS_SUCCESS_QSS,
    create_primary_button, create_secondary_button, setup_dialog_window
)
from ..theme import IconHelper, Icons


class CreatePathDialog(QDialog):
    """自定义新建文件/文件夹对话框。

    特性：
    - 显示所在目录上下文，实时预览目标路径
    - 实时验证非法字符
    - 共享样式表（按钮、状态颜色）
    """

    def __init__(self, parent, current_path: str, is_dir: bool = False):
        super().__init__(parent)
        self._current_path = current_path
        self._is_dir = is_dir
        self._new_name = None

        kind = "文件夹" if is_dir else "文件"
        setup_dialog_window(self, f"新建{kind}")

        dir_label = QLabel(f"所在目录: {current_path}")
        dir_label.setStyleSheet(STATUS_NEUTRAL_QSS)

        input_label = QLabel(f"{kind}名称:")
        self._edit = QLineEdit("")
        self._edit.setClearButtonEnabled(True)
        self._edit.setPlaceholderText(f"请输入{kind}名称（不含路径）")
        self._edit.textChanged.connect(self._on_text_changed)

        self._status = QLabel("")

        self._ok_btn = create_primary_button("创建", enabled=False)
        self._ok_btn.setIcon(IconHelper.icon(Icons.ADD, 16))
        self._ok_btn.clicked.connect(self._accept)

        cancel_btn = create_secondary_button("取消")
        cancel_btn.setIcon(IconHelper.icon(Icons.CLOSE, 16))
        cancel_btn.clicked.connect(self.reject)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch(1)
        btn_layout.addWidget(self._ok_btn)
        btn_layout.addWidget(cancel_btn)

        layout = QVBoxLayout(self)
        layout.addWidget(dir_label)
        layout.addWidget(input_label)
        layout.addWidget(self._edit)
        layout.addWidget(self._status)
        layout.addLayout(btn_layout)

        self._edit.setFocus()

    def _on_text_changed(self, text: str):
        if not text or not text.strip():
            self._status.setText("")
            self._ok_btn.setEnabled(False)
            return

        if not is_valid_filename(text):
            self._status.setText(
                "名称包含非法字符（\\ / : * ? \" < > |）或无效名称"
            )
            self._status.setStyleSheet(STATUS_ERROR_QSS)
            self._ok_btn.setEnabled(False)
            return

        target = self._current_path.rstrip("/") + "/" + text
        self._status.setText(f"目标: {target}")
        self._status.setStyleSheet(STATUS_SUCCESS_QSS)
        self._ok_btn.setEnabled(True)

    def _accept(self):
        name = self._edit.text().strip()
        if is_valid_filename(name):
            self._new_name = name
            self.accept()

    def get_new_name(self) -> str:
        return self._new_name
