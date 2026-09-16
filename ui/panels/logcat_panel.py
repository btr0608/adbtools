import os
from typing import List, Optional, Set, Tuple

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor, QTextCharFormat, QTextCursor
from PyQt5.QtWidgets import (
    QCheckBox, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton,
    QStackedWidget, QVBoxLayout, QWidget
)

from ...core.adb_client import AdbClient
from ...core.utils import COLOR_DEFAULT, COLOR_ERROR, COLOR_SUCCESS, COLOR_SYSTEM, start_worker
from ...services.logcat_service import LogcatService
from ..theme import (
    Buttons, IconHelper, Icons, Palette, field_label_style, log_view_style,
    make_section_header
)


LEVEL_COLORS = {
    "V": COLOR_DEFAULT,
    "D": "#56B6C2",
    "I": COLOR_SUCCESS,
    "W": "#E5C07B",
    "E": COLOR_ERROR,
    "F": "#E06C75",
    "S": "#888888",
}


class LogcatPanel(QWidget):
    """Logcat 选项与日志显示控件：紧凑布局，集成在右侧技能子面板中。"""

    MAX_LOG_CACHE = 5000

    def __init__(self, logcat_service: LogcatService, get_serial_cb, adb_client: AdbClient = None, parent=None):
        super().__init__(parent)
        self.logcat_service = logcat_service
        self.get_serial_cb = get_serial_cb
        self.adb_client = adb_client

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(12, 10, 12, 10)
        self.main_layout.setSpacing(8)

        self.main_layout.addWidget(
            make_section_header("日志捕获 / LOGCAT", Icons.LOGCAT)
        )

        # 标签过滤
        tag_row = QHBoxLayout()
        tag_label = QLabel("标签过滤")
        tag_label.setStyleSheet(field_label_style())
        tag_row.addWidget(tag_label)
        self.tag_input = QLineEdit()
        self.tag_input.setPlaceholderText("多个标签用逗号分隔")
        self.tag_input.setToolTip("仅显示包含指定标签的日志（逗号分隔）")
        tag_row.addWidget(self.tag_input, 1)
        self.main_layout.addLayout(tag_row)

        # 包名过滤（新增）
        pkg_row = QHBoxLayout()
        pkg_label = QLabel("包名过滤")
        pkg_label.setStyleSheet(field_label_style())
        pkg_row.addWidget(pkg_label)
        self.pkg_input = QLineEdit()
        self.pkg_input.setPlaceholderText("输入包名后回车")
        self.pkg_input.setToolTip("按包名过滤 logcat，需应用已启动")
        self.pkg_input.returnPressed.connect(self._apply_package_filter)
        pkg_row.addWidget(self.pkg_input, 1)
        self.main_layout.addLayout(pkg_row)

        # 级别过滤（多选复选框）
        level_row = QHBoxLayout()
        level_row.setSpacing(8)
        level_label = QLabel("级别过滤")
        level_label.setStyleSheet(field_label_style())
        level_row.addWidget(level_label)
        self._level_checkboxes: dict = {}
        for letter in ("V", "D", "I", "W", "E", "F", "S"):
            cb = QCheckBox(letter)
            cb.setFixedWidth(38)
            cb.setToolTip(f"显示 {LEVEL_COLORS.get(letter, COLOR_DEFAULT)} 级别日志")
            cb.stateChanged.connect(self._update_level_filter)
            self._level_checkboxes[letter] = cb
            level_row.addWidget(cb)
        level_row.addStretch(1)
        self.main_layout.addLayout(level_row)
        # 默认选中 W/E/F（匹配原 Warn+ 预设）
        for letter in ("W", "E", "F"):
            self._level_checkboxes[letter].setChecked(True)

        # 控制按钮
        btn_row = QHBoxLayout()
        self.start_btn = QPushButton(" 开始")
        self.start_btn.setIcon(IconHelper.icon(Icons.PLAY, 16))
        self.start_btn.setStyleSheet(Buttons.primary(icon_size="16px"))
        self.start_btn.setToolTip("开始录制 logcat")
        self.start_btn.clicked.connect(self._toggle_recording)

        self.clear_btn = QPushButton(" 清空")
        self.clear_btn.setIcon(IconHelper.icon(Icons.CLOSE, 16))
        self.clear_btn.setStyleSheet(Buttons.ghost(icon_size="16px"))
        self.clear_btn.setToolTip("清空当前日志视图")
        self.clear_btn.clicked.connect(self.clear_log)

        self.save_btn = QPushButton(" 保存")
        self.save_btn.setIcon(IconHelper.icon(Icons.SAVE, 16))
        self.save_btn.setStyleSheet(Buttons.secondary(icon_size="16px"))
        self.save_btn.setToolTip("将当前视图日志保存到本地")
        self.save_btn.clicked.connect(self._save_current_log)

        btn_row.addWidget(self.start_btn)
        btn_row.addWidget(self.clear_btn)
        btn_row.addWidget(self.save_btn)
        self.main_layout.addLayout(btn_row)

        # 日志视图 + 空状态提示（QStackedWidget 切换）
        self.log_stack = QStackedWidget()

        self.empty_label = QLabel("（未捕获日志 — 点击\"开始\"启动）")
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setStyleSheet(
            f"color: #6a6a5a; background: {Palette.TERMINAL_BG}; font-size: 9pt;"
            f"border: 3px solid {Palette.BORDER_STRONG}; border-radius: 2px; padding: 6px;"
        )

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(5000)  # 限制 5000 行防止内存爆
        self.log_view.setStyleSheet(log_view_style())
        self.log_view.setMinimumHeight(120)

        self.log_stack.addWidget(self.empty_label)
        self.log_stack.addWidget(self.log_view)
        self.log_stack.setCurrentIndex(0)
        self.main_layout.addWidget(self.log_stack, 1)

        self.logcat_service.recording_started.connect(self._on_recording_started)
        self.logcat_service.recording_stopped.connect(self._on_recording_stopped)
        self.logcat_service.line_received.connect(self._on_line_received)
        self.logcat_service.error.connect(self._on_error)

        self._keyword = ""
        self._log_cache: List[Tuple[str, str]] = []
        self._pending_lines: List[Tuple[str, str]] = []

        self._keyword_debounce = QTimer(self)
        self._keyword_debounce.setSingleShot(True)
        self._keyword_debounce.setInterval(200)
        self._keyword_debounce.timeout.connect(self._apply_filter_and_render)
        self.tag_input.textChanged.connect(self._on_keyword_changed)

        self._flush_timer = QTimer(self)
        self._flush_timer.setInterval(200)  # 200ms 批量刷新
        self._flush_timer.timeout.connect(self._flush_pending_lines)
        self._flush_timer.start()

        self._scroll_timer = QTimer(self)
        self._scroll_timer.setSingleShot(True)
        self._scroll_timer.setInterval(50)
        self._scroll_timer.timeout.connect(self._scroll_to_bottom)

        # 初始化级别过滤：默认 checkbox 的 stateChanged 已在 connect 之后 setChecked，
        # 这里显式再同步一次，确保服务端过滤与勾选状态一致
        self._update_level_filter()

    def _selected_levels(self) -> Set[str]:
        return {lvl for lvl, cb in self._level_checkboxes.items() if cb.isChecked()}

    def _update_level_filter(self):
        self.logcat_service.set_level_filter(self._selected_levels())
        # 级别变更后，对已缓存日志即时重渲染
        if hasattr(self, "_log_cache"):
            self._apply_filter_and_render()

    def _on_keyword_changed(self, text: str):
        self._keyword = text.strip().lower()
        self._keyword_debounce.start()

    def _apply_filter_and_render(self):
        self.log_view.setUpdatesEnabled(False)
        self.log_view.clear()
        if self._log_cache:
            levels = self._selected_levels()
            # 从最新日志向前收集，最多渲染与视图块上限一致的条数，
            # 避免对 50k 缓存全量插入（视图本身也只保留 10000 块）
            matched = []
            for level, msg in reversed(self._log_cache):
                if level not in levels or not self._passes_filter(level, msg):
                    continue
                matched.append((level, msg))
                if len(matched) >= self.log_view.maximumBlockCount():
                    break
            cursor = self.log_view.textCursor()
            for level, msg in reversed(matched):
                color = LEVEL_COLORS.get(level, COLOR_DEFAULT)
                fmt = QTextCharFormat()
                fmt.setForeground(QColor(color))
                cursor.movePosition(QTextCursor.End)
                cursor.setCharFormat(fmt)
                cursor.insertText(msg + "\n")
            self.log_view.setTextCursor(cursor)
        self.log_view.setUpdatesEnabled(True)
        self._schedule_scroll_to_bottom()

    def _passes_filter(self, level: str, msg: str) -> bool:
        # 级别过滤（服务端也会过滤新日志，这里保证缓存重渲染时一致）
        levels = self._selected_levels()
        if levels and level not in levels:
            return False
        # tag filter: split by comma, require at least one tag present
        tags = [t.strip().lower() for t in self._keyword.split(",") if t.strip()] if self._keyword else []
        if tags:
            return any(tag in msg.lower() for tag in tags)
        return True

    def _apply_package_filter(self):
        """按包名过滤：查 pidof → 重启 logcat。"""
        pkg = self.pkg_input.text().strip()
        if not pkg:
            # 清空包名 → 清除 pid 过滤
            self.logcat_service.set_pid_filter(None)
            if self.logcat_service.is_recording():
                self.logcat_service.stop_recording()
                self._toggle_recording()
            self._append_line("[系统] 已清除包名过滤", COLOR_SYSTEM)
            return
        if not self.adb_client:
            self._append_line("[错误] 未绑定 ADB 客户端", COLOR_ERROR)
            return
        serial = self.get_serial_cb()
        if not serial:
            self._append_line("[错误] 未选择设备", COLOR_ERROR)
            return
        # 用 Worker 查 pidof
        import subprocess
        from PyQt5.QtCore import QThread, pyqtSignal
        from ...core.utils import get_startup_info

        class PidofWorker(QThread):
            result = pyqtSignal(str, str, str)  # (pkg, output, error)

            def run(self_inner):
                try:
                    cmd = self_inner.adb_client._build_cmd('shell', 'pidof', pkg)
                    r = subprocess.run(cmd, capture_output=True, text=True,
                                       encoding='utf-8', errors='replace', timeout=10,
                                       startupinfo=get_startup_info(), cwd=self_inner.adb_client.adb_home)
                    self_inner.result.emit(pkg, (r.stdout or "").strip(), "")
                except subprocess.TimeoutExpired:
                    self_inner.result.emit(pkg, "", "命令超时")
                except FileNotFoundError:
                    self_inner.result.emit(pkg, "", "未找到 adb")
                except Exception as e:
                    self_inner.result.emit(pkg, "", str(e))

        worker = PidofWorker()
        worker.adb_client = self.adb_client
        worker.result.connect(self._on_pidof_result)
        start_worker(worker)

    def _on_pidof_result(self, pkg: str, pid_str: str, error: str = ""):
        """pidof 结果回调。"""
        if error:
            self._append_line(
                f"[错误] 查询进程失败: {error}", COLOR_ERROR
            )
            return
        if not pid_str:
            self._append_line(
                f"[错误] 应用 {pkg} 未启动，请先打开 App", COLOR_ERROR
            )
            return
        # pidof 可能返回多个 PID（空格分隔），取第一个
        pid = int(pid_str.split()[0])
        self.logcat_service.set_pid_filter(pid)
        # 如果正在录制，重启以应用 --pid 参数
        if self.logcat_service.is_recording():
            self.logcat_service.stop_recording()
            self._toggle_recording()
        self._append_line(
            f"[系统] 已按包名 {pkg} (PID={pid}) 过滤 logcat", COLOR_SUCCESS
        )

    def _toggle_recording(self):
        if self.logcat_service.is_recording():
            self.logcat_service.stop_recording()
        else:
            serial = self.get_serial_cb()
            if not serial:
                self._append_line("未选择设备，无法启动 logcat", COLOR_ERROR)
                return
            target_dir = os.path.join(os.path.expanduser("~"), "adb_visual_logs")
            self.logcat_service.start_recording(serial, target_dir)

    def _on_recording_started(self, filename: str):
        self.start_btn.setText(" 停止")
        self.start_btn.setIcon(IconHelper.icon(Icons.STOP, 16))
        self.start_btn.setStyleSheet(Buttons.danger(icon_size="16px"))
        self.start_btn.setToolTip("停止当前 logcat 录制")
        self.log_stack.setCurrentIndex(1)  # 隐藏空状态，显示日志视图
        self._append_line(f"[系统] 开始录制 → {filename}", COLOR_SYSTEM)

    def _on_recording_stopped(self, filename: str, size_kb: int):
        self.start_btn.setText(" 开始")
        self.start_btn.setIcon(IconHelper.icon(Icons.PLAY, 16))
        self.start_btn.setStyleSheet(Buttons.primary(icon_size="16px"))
        self.start_btn.setToolTip("开始录制 logcat")
        if filename:
            size_str = f"（{size_kb} KB）" if size_kb else ""
            self._append_line(f"[系统] 录制已停止，日志已保存：{filename}{size_str}", COLOR_SUCCESS)
        else:
            self._append_line("[系统] 录制已停止", COLOR_SYSTEM)

    def _on_line_received(self, level: str, msg: str):
        self._log_cache.append((level, msg))
        if len(self._log_cache) > self.MAX_LOG_CACHE:
            self._log_cache = self._log_cache[-self.MAX_LOG_CACHE:]
        self._pending_lines.append((level, msg))

    def _flush_pending_lines(self):
        if not self._pending_lines:
            return
        self.log_view.setUpdatesEnabled(False)
        cursor = self.log_view.textCursor()
        for level, msg in self._pending_lines:
            if not self._passes_filter(level, msg):
                continue
            color = LEVEL_COLORS.get(level, COLOR_DEFAULT)
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(color))
            cursor.movePosition(QTextCursor.End)
            cursor.setCharFormat(fmt)
            cursor.insertText(msg + "\n")
        self.log_view.setTextCursor(cursor)
        self.log_view.setUpdatesEnabled(True)
        self._pending_lines.clear()
        self._schedule_scroll_to_bottom()

    def _schedule_scroll_to_bottom(self):
        self._scroll_timer.start()

    def _scroll_to_bottom(self):
        scrollbar = self.log_view.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _on_error(self, msg: str):
        self._append_line(f"[错误] {msg}", COLOR_ERROR)

    def _append_line(self, text: str, color: str):
        self.log_view.setUpdatesEnabled(False)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        cursor = self.log_view.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.setCharFormat(fmt)
        cursor.insertText(text + "\n")
        self.log_view.setTextCursor(cursor)
        self.log_view.setUpdatesEnabled(True)
        self._schedule_scroll_to_bottom()

    def clear_log(self):
        """清空日志视图与缓存。"""
        self.log_view.clear()
        self._log_cache.clear()
        self._pending_lines.clear()
        # 未在录制时，清空后恢复空状态提示
        if not self.logcat_service.is_recording():
            self.log_stack.setCurrentIndex(0)

    def _save_current_log(self):
        """将当前视图中的日志保存到用户选择的文件。"""
        from PyQt5.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(
            self, "保存日志", "logcat_view.log", "日志文件 (*.log);;所有文件 (*.*)"
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.log_view.toPlainText())
            self._append_line(f"[系统] 日志已保存：{path}", COLOR_SUCCESS)
        except OSError as e:
            self._append_line(f"[错误] 保存失败：{e}", COLOR_ERROR)
