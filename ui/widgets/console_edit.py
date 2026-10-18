import re

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QPainter, QTextCharFormat, QTextCursor
from PyQt5.QtWidgets import QTextEdit

from ...core.utils import COLOR_DEFAULT, COLOR_PROMPT, COLOR_SYSTEM
from ..theme import Fonts, terminal_style


class ConsoleEdit(QTextEdit):
    execute_cmd_signal = pyqtSignal(str)
    ctrl_c_signal = pyqtSignal()
    ctrl_d_signal = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(terminal_style())
        # 终端字体：Zpix 同时支持英文和中文的像素字体，10pt 比正文 9pt 大一号
        # 用 Zpix 而非 VT323 是因为 VT323 没有中文，Qt fallback 到雅黑时无法继承
        # styleStrategy（PreferBitmap+NoAntialias），会导致中文被抗锯齿污染。
        # 关键：font-family / font-size 已从 terminal_style() 删除，确保 setFont
        # 不被 QSS 创建的 QFont 覆盖。
        term_font = QFont("Zpix", 10)
        term_font.setStyleHint(QFont.Monospace)
        term_font.setStyleStrategy(
            QFont.PreferBitmap | QFont.NoAntialias | QFont.NoSubpixelAntialias
        )
        term_font.setBold(False)
        self.setFont(term_font)
        self.setAcceptRichText(False)
        self.setUndoRedoEnabled(False)
        self.document().setMaximumBlockCount(5000)
        self.ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
        self.history = []
        self.history_idx = 0
        self._device_label = None   # 由 TerminalTab 注入：如 "MuMu (Android 15)"
        self._scanline_enabled = True
        # 输入区起点（绝对字符下标）。文档裁剪（maximumBlockCount）或内容
        # 增删时通过 contentsChange 信号自动修正，避免下标失效导致输出覆盖命令行
        self.input_start = 0
        self.document().contentsChange.connect(self._on_contents_change)

    def _on_contents_change(self, pos: int, chars_removed: int, chars_added: int):
        """文档变更前（旧坐标系）触发：维持输入区起点跟随其之前的增删。"""
        if pos >= self.input_start:
            return
        removed_before = min(chars_removed, self.input_start - pos)
        self.input_start = max(0, self.input_start - removed_before + chars_added)

    def set_device_label(self, label: str):
        """注入设备显示标签（model + Android 版本），由 TerminalTab 调用。"""
        self._device_label = label

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self._scanline_enabled:
            return
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.Antialiasing, False)
        pen = painter.pen()
        pen.setWidth(1)
        pen.setColor(QColor(255, 255, 255, 8))
        painter.setPen(pen)
        rect = self.viewport().rect()
        for y in range(rect.top(), rect.bottom(), 3):
            painter.drawLine(rect.left(), y, rect.right(), y)
        painter.end()

    def _fmt(self, color: str) -> QTextCharFormat:
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        return fmt

    def _set_color(self, color: str):
        self.setCurrentCharFormat(self._fmt(color))

    def _reset_color(self):
        self._set_color(COLOR_DEFAULT)

    def reset_prompt(self, serial=None):
        self.moveCursor(QTextCursor.End)
        # 若最后一个文本块非空（上一行没有以换行收尾），先补一个换行
        if self.document().lastBlock().text():
            self.insertPlainText('\n')
        self._set_color(COLOR_PROMPT)
        label = self._device_label or ""
        if serial:
            # 形如：> [MuMu (Android 15)] adb -s 127.0.0.1:16384
            prefix = f"[{label}] " if label else ""
            self.insertPlainText(f"> {prefix}adb -s {serial} ")
        else:
            self.insertPlainText("> adb ")
        self._reset_color()
        self.input_start = self.textCursor().position()

    def write_output(self, text: str, color: str = None):
        text = self.ansi_escape.sub('', text)
        # 仅截取用户尚未提交的输入行（O(输入长度)），
        # 避免旧实现每次输出都 toPlainText() 全文档（O(n)，高频时卡顿）
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.setPosition(self.input_start, QTextCursor.KeepAnchor)
        current_input = cursor.selectedText().replace('\u2029', '\n')
        cursor.removeSelectedText()

        self._set_color(color if color else COLOR_DEFAULT)
        self.insertPlainText(text)
        self._reset_color()
        # 输出已插入到输入区之前，输入区起点移动到当前末尾
        self.input_start = self.textCursor().position()

        if current_input:
            self.insertPlainText(current_input)

        self.moveCursor(QTextCursor.End)
        self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())

    def insert_colored_text(self, text: str, color: str = COLOR_SYSTEM):
        self._set_color(color)
        self.insertPlainText(text)
        self._reset_color()
        self.input_start = self.textCursor().position()

    def _replace_current_input(self, text: str):
        cursor = self.textCursor()
        cursor.setPosition(self.input_start)
        cursor.movePosition(QTextCursor.End, QTextCursor.KeepAnchor)
        cursor.removeSelectedText()

        self._reset_color()
        self.insertPlainText(text)

    def keyPressEvent(self, event):
        cursor = self.textCursor()
        mod, key = event.modifiers(), event.key()

        if mod & Qt.ControlModifier and key == Qt.Key_C:
            self.copy() if cursor.hasSelection() else self.ctrl_c_signal.emit()
            return

        if mod & Qt.ControlModifier and key == Qt.Key_D:
            self.ctrl_d_signal.emit()
            return

        if mod & Qt.ControlModifier and key == Qt.Key_V:
            if cursor.position() < self.input_start:
                cursor.movePosition(QTextCursor.End)
                self.setTextCursor(cursor)
            self.paste()
            return

        if key in (Qt.Key_Backspace, Qt.Key_Left, Qt.Key_Delete):
            if cursor.hasSelection():
                if cursor.selectionStart() < self.input_start:
                    return
            elif cursor.position() <= self.input_start:
                return

        if key == Qt.Key_Up:
            if self.history and self.history_idx > 0:
                self.history_idx -= 1
                self._replace_current_input(self.history[self.history_idx])
            return

        if key == Qt.Key_Down:
            if self.history and self.history_idx < len(self.history):
                self.history_idx += 1
                if self.history_idx < len(self.history):
                    self._replace_current_input(self.history[self.history_idx])
                else:
                    self._replace_current_input("")
            return

        if key in (Qt.Key_Return, Qt.Key_Enter):
            cursor.movePosition(QTextCursor.End)
            self.setTextCursor(cursor)
            cmd = self.toPlainText()[self.input_start:].strip()

            if cmd and (not self.history or self.history[-1] != cmd):
                self.history.append(cmd)
            self.history_idx = len(self.history)

            self.insertPlainText('\n')
            self.input_start = self.textCursor().position()
            self.execute_cmd_signal.emit(cmd)
            return

        if key == Qt.Key_Home:
            cursor.setPosition(self.input_start)
            self.setTextCursor(cursor)
            return

        if cursor.position() < self.input_start:
            cursor.movePosition(QTextCursor.End)
            self.setTextCursor(cursor)

        self._reset_color()
        super().keyPressEvent(event)
