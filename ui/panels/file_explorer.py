import os
from typing import Callable, Optional

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QProgressBar,
    QPushButton, QTreeWidgetItem, QVBoxLayout, QWidget
)

from ...core.utils import COLOR_ERROR, COLOR_SUCCESS, COLOR_SYSTEM, format_size
from ...services.file_service import FileService
from ..theme import Buttons, IconHelper, Icons, Palette, make_section_header
from ..widgets.file_tree_widget import FileTreeWidget


SEARCH_SCOPE_CURRENT = "current"
SEARCH_SCOPE_ROOT = "root"

SCOPE_OPTIONS = [
    (SEARCH_SCOPE_CURRENT, "当前目录", None),
    (SEARCH_SCOPE_ROOT, "/ 全盘", "/"),
]


class FileExplorer(QWidget):
    def __init__(
        self,
        file_service: FileService,
        get_current_terminal_cb: Callable[[], Optional[QWidget]],
    ):
        super().__init__()
        self.file_service = file_service
        self.get_current_terminal = get_current_terminal_cb
        self._is_search_result_mode = False
        self._search_results: list = []
        self._active_transfers = 0  # 活跃传输计数，支持批量并发
        self._success_count = 0    # 本批次成功数（仅在全部完成时汇总打印）
        self._fail_count = 0       # 本批次失败数

        # 搜索过滤防抖 timer（200ms）
        self._filter_timer = QTimer(self)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(200)
        self._filter_timer.timeout.connect(self._apply_search_filter)

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(12, 10, 12, 10)
        self.main_layout.setSpacing(8)

        # 区块标题：文件背包 / INVENTORY（图标 + 虚线分隔）
        self.main_layout.addWidget(
            make_section_header("文件背包 / INVENTORY", Icons.FOLDER)
        )

        # 顶部操作区：路径 + 搜索 合并为单行
        self.top_card = QWidget()
        self.top_card.setStyleSheet("background: transparent;")
        top_layout = QHBoxLayout(self.top_card)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(8)

        # [↑] [路径输入框] [刷新] [搜索] [过滤框] [当前目录▼] — 单行水平排列
        self.up_btn = QPushButton()
        self.up_btn.setIcon(IconHelper.icon(Icons.UP, 16))
        self.up_btn.setStyleSheet(Buttons.ghost(padding="2px", icon_size="16px"))
        self.up_btn.setToolTip("返回上级目录")
        self.up_btn.setFixedSize(30, 30)

        self.path_input = QLineEdit(self.file_service.current_path)
        self.path_input.setToolTip("当前目录路径，回车跳转")

        self.refresh_btn = QPushButton()
        self.refresh_btn.setIcon(IconHelper.icon(Icons.REFRESH, 16))
        self.refresh_btn.setStyleSheet(Buttons.ghost(padding="2px", icon_size="16px"))
        self.refresh_btn.setToolTip("刷新当前目录")
        self.refresh_btn.setFixedSize(30, 30)

        self.search_btn = QPushButton()
        self.search_btn.setIcon(IconHelper.icon(Icons.SEARCH, 16))
        self.search_btn.setStyleSheet(Buttons.ghost(padding="2px", icon_size="16px"))
        self.search_btn.setToolTip("执行搜索")
        self.search_btn.setFixedSize(30, 30)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("过滤...")
        self.search_input.setToolTip("当前目录模式即时过滤，全盘模式回车搜索")

        self.scope_combo = QComboBox()
        for key, label, _ in SCOPE_OPTIONS:
            self.scope_combo.addItem(label, key)
        self.scope_combo.setFixedWidth(140)
        self.scope_combo.setToolTip("选择搜索范围")
        self.scope_combo.currentIndexChanged.connect(self._on_scope_changed)

        self.cancel_search_btn = QPushButton()
        self.cancel_search_btn.setIcon(IconHelper.icon(Icons.CLOSE, 16))
        self.cancel_search_btn.setCursor(Qt.PointingHandCursor)
        self.cancel_search_btn.setStyleSheet(Buttons.danger_ghost(padding="2px", icon_size="16px"))
        self.cancel_search_btn.setVisible(False)
        self.cancel_search_btn.setToolTip("取消搜索")
        self.cancel_search_btn.setFixedSize(30, 30)
        self.cancel_search_btn.clicked.connect(self._cancel_global_search)

        top_layout.addWidget(self.up_btn)
        top_layout.addWidget(self.path_input, 3)
        top_layout.addWidget(self.refresh_btn)
        top_layout.addWidget(self.search_btn)
        top_layout.addWidget(self.search_input, 2)
        top_layout.addWidget(self.scope_combo)
        top_layout.addWidget(self.cancel_search_btn)

        self.main_layout.addWidget(self.top_card)

        # 传输进度条（隐藏，传输时显示）
        self.transfer_progress = QProgressBar()
        self.transfer_progress.setVisible(False)
        self.transfer_progress.setTextVisible(True)
        self.transfer_progress.setFixedHeight(16)
        self.main_layout.addWidget(self.transfer_progress)

        self.tree = FileTreeWidget(self)
        self.tree.setHeaderLabels(["名称", "类型", "大小", "权限"])
        self.main_layout.addWidget(self.tree, 1)

        # 搜索状态行（放在 tree 下方，全局搜索进度/状态反馈）
        status_row = QHBoxLayout()
        status_row.setSpacing(6)
        self.search_status_label = QLabel("")
        self.search_status_label.setStyleSheet(
            f"color: {COLOR_SYSTEM}; font-size: 9pt; padding: 2px 4px;"
        )
        self.search_progress = QProgressBar()
        self.search_progress.setRange(0, 0)
        self.search_progress.setFixedHeight(10)
        self.search_progress.setTextVisible(False)
        self.search_progress.setVisible(False)
        status_row.addWidget(self.search_status_label, 1)
        status_row.addWidget(self.search_progress)
        self.main_layout.addLayout(status_row)

        # SVG 图标
        self._icon_dir = IconHelper.icon(Icons.FOLDER, 18)
        self._icon_file = IconHelper.icon(Icons.FILE, 18)
        self._icon_link = IconHelper.icon(Icons.FILE, 18)

        self.up_btn.clicked.connect(self.go_up_level)
        self.refresh_btn.clicked.connect(self.load_directory)
        self.path_input.returnPressed.connect(self.load_directory)
        self.tree.itemDoubleClicked.connect(self.on_item_double_clicked)
        self.search_input.returnPressed.connect(self._do_search)
        self.search_input.textChanged.connect(self._on_search_text_changed)
        self.search_btn.clicked.connect(self._do_search)

        self.file_service.dir_loaded_cb = self._on_dir_loaded
        self.file_service.transfer_finished_cb = self._on_transfer_finished
        self.file_service.transfer_started.connect(self._on_transfer_started)
        self.file_service.set_multi_drag_target_cb(self.tree.start_drag_after_pull_multi)
        self.file_service.global_search_done_cb = self._on_global_search_done

        self._set_search_scope_hint()

    def _current_scope_key(self) -> str:
        idx = self.scope_combo.currentIndex()
        return self.scope_combo.itemData(idx) if idx >= 0 else SEARCH_SCOPE_CURRENT

    def _current_scope_root(self) -> Optional[str]:
        key = self._current_scope_key()
        for k, _, root in SCOPE_OPTIONS:
            if k == key:
                return root
        return None

    def _set_search_scope_hint(self):
        key = self._current_scope_key()
        if key == SEARCH_SCOPE_CURRENT:
            self.search_input.setPlaceholderText("过滤当前目录文件名（即时）...")
            self.search_btn.setEnabled(False)
            self.search_btn.setToolTip("当前目录下输入即过滤，无需点击")
        else:
            root = self._current_scope_root() or ""
            self.search_input.setPlaceholderText(f"在 {root} 中搜索（回车或点按钮）...")
            self.search_btn.setEnabled(True)
            self.search_btn.setToolTip(f"在 {root} 中递归搜索")

    def _on_scope_changed(self):
        self._set_search_scope_hint()
        keyword = self.search_input.text().strip()
        if self._current_scope_key() == SEARCH_SCOPE_CURRENT:
            self._apply_search_filter()
        elif keyword:
            self._do_search()

    def _on_search_text_changed(self):
        """输入框变化 — 当前目录模式走 200ms 防抖，全盘模式不触发。"""
        if self._current_scope_key() == SEARCH_SCOPE_CURRENT:
            self._filter_timer.start()  # 重置 timer

    def _do_search(self):
        keyword = self.search_input.text().strip()
        key = self._current_scope_key()
        if key == SEARCH_SCOPE_CURRENT:
            self._apply_search_filter()
            return
        root = self._current_scope_root()
        if not root or not keyword:
            return
        # UI 状态
        self.search_status_label.setText(f"正在 {root} 中搜索 \"{keyword}\" ...")
        self.search_status_label.setStyleSheet(f"color: {COLOR_SYSTEM}; font-size: 9pt; padding: 2px 4px;")
        self.search_progress.setVisible(True)
        self.search_btn.setEnabled(False)
        self.cancel_search_btn.setVisible(True)
        self.tree.clear()
        self.tree.addTopLevelItem(QTreeWidgetItem([f"正在搜索 \"{keyword}\" ...", "", "", ""]))
        self._is_search_result_mode = False
        self._search_results = []
        self.file_service.start_global_search(root, keyword)

    def _cancel_global_search(self):
        self.file_service.cancel_global_search()
        self.search_progress.setVisible(False)
        self.cancel_search_btn.setVisible(False)
        self.search_btn.setEnabled(True)
        self.search_status_label.setText("搜索已取消")
        self.search_status_label.setStyleSheet(f"color: {COLOR_ERROR}; font-size: 9pt; padding: 2px 4px;")
        self.tree.clear()

    def _on_global_search_done(self, results: list, error: str, truncated: bool, elapsed: float):
        self.search_progress.setVisible(False)
        self.cancel_search_btn.setVisible(False)
        self.search_btn.setEnabled(True)

        self.tree.setUpdatesEnabled(False)
        self.tree.clear()

        if error:
            self.search_status_label.setText(error)
            self.search_status_label.setStyleSheet(f"color: {COLOR_ERROR}; font-size: 9pt; padding: 2px 4px;")
            self.tree.addTopLevelItem(QTreeWidgetItem([error, "", "", ""]))
            self.tree.setUpdatesEnabled(True)
            return

        self._search_results = results
        self._is_search_result_mode = True

        # 返回上一层目录：如果没有匹配结果
        if not results:
            self.search_status_label.setText(f"未找到匹配文件（用时 {elapsed}s）")
            self.search_status_label.setStyleSheet(f"color: {COLOR_SYSTEM}; font-size: 9pt; padding: 2px 4px;")
            self.tree.addTopLevelItem(QTreeWidgetItem(["(未找到匹配文件)", "", "", ""]))
            self.tree.setUpdatesEnabled(True)
            return

        tree_items = []
        for data in results:
            full_path = data["path"]
            name = data["name"]
            # 类型列显示 [搜索结果] + 目录
            type_text = f"[结果] Dir" if data["is_dir"] else "[结果] File"
            item = QTreeWidgetItem([full_path, type_text, "", ""])
            item.setToolTip(0, f"完整路径: {full_path}\n双击跳转到所在目录")
            item.setData(0, Qt.UserRole, full_path)
            if data["is_dir"]:
                item.setIcon(0, self._icon_dir)
            else:
                item.setIcon(0, self._icon_file)
            tree_items.append(item)

        self.tree.addTopLevelItems(tree_items)

        status_parts = [f"找到 {len(results)} 个匹配项", f"用时 {elapsed}s"]
        if truncated:
            status_parts.append("已超过 500 条，仅显示前 500 条（建议缩小关键词）")
            self.search_status_label.setStyleSheet(f"color: #E5C07B; font-size: 9pt; padding: 2px 4px;")
        else:
            self.search_status_label.setStyleSheet(f"color: {COLOR_SUCCESS}; font-size: 9pt; padding: 2px 4px;")
        self.search_status_label.setText("  |  ".join(status_parts))

        self.tree.setUpdatesEnabled(True)

    def _on_transfer_started(self, description: str):
        """传输开始：显示 indeterminate 进度条。"""
        self._active_transfers += 1
        self.transfer_progress.setRange(0, 0)
        self.transfer_progress.setFormat(f" {description}...")
        self.transfer_progress.setVisible(True)

    def reload(self):
        self.load_directory()

    def go_up_level(self):
        # 如果当前是搜索结果模式，按上一级回到 normal 浏览
        if self._is_search_result_mode:
            self._is_search_result_mode = False
            self.load_directory()
            return
        if self.file_service.current_path != "/":
            parent = os.path.dirname(self.file_service.current_path.rstrip('/'))
            if not parent.endswith('/'):
                parent += '/'
            self.path_input.setText(parent)
            self.load_directory()

    def load_directory(self):
        self._is_search_result_mode = False
        self._search_results = []
        self.search_status_label.setText("")
        path = self.path_input.text().strip()
        self.refresh_btn.setEnabled(False)
        self.tree.clear()
        self.tree.addTopLevelItem(QTreeWidgetItem(["加载中...", "", "", ""]))
        self.file_service.load_directory(path)

    def _on_dir_loaded(self, items_data: list, error_msg: str):
        self.tree.setUpdatesEnabled(False)
        self.tree.clear()
        self.refresh_btn.setEnabled(True)

        if error_msg:
            self.tree.addTopLevelItem(QTreeWidgetItem([error_msg, "", "", ""]))
            self.tree.setUpdatesEnabled(True)
            return

        if self.file_service.current_path != "/":
            self.tree.addTopLevelItem(QTreeWidgetItem(["..", "Dir", "", ""]))

        items_data.sort(key=lambda x: (not x['is_dir'], x['name'].lower()))

        tree_items = []
        for data in items_data:
            is_link = data['perms'].startswith('l')
            item_type = "Link" if is_link else ("Dir" if data['is_dir'] else "File")

            size_formatted = ""
            if item_type == "File":
                try:
                    size_formatted = format_size(int(data['size']))
                except ValueError:
                    size_formatted = data['size']

            item = QTreeWidgetItem([data['name'], item_type, size_formatted, data['perms']])
            item.setData(0, Qt.UserRole, data['name'])
            # UserRole+1 存原始字节数（文件），供传输进度/速率统计使用
            raw_size = 0
            if item_type == "File":
                try:
                    raw_size = int(data['size'])
                except (ValueError, TypeError):
                    raw_size = 0
            item.setData(0, Qt.UserRole + 1, raw_size)

            if is_link:
                item.setIcon(0, self._icon_link)
            elif data['is_dir']:
                item.setIcon(0, self._icon_dir)
            else:
                item.setIcon(0, self._icon_file)
            tree_items.append(item)

        self.tree.addTopLevelItems(tree_items)
        self._apply_search_filter()
        self.tree.setUpdatesEnabled(True)

    def _apply_search_filter(self):
        """当前目录模式下的内存过滤。全局搜索模式不处理。"""
        if self._is_search_result_mode:
            return
        keyword = self.search_input.text().strip().lower()
        if not keyword:
            for i in range(self.tree.topLevelItemCount()):
                self.tree.topLevelItem(i).setHidden(False)
            if self._current_scope_key() == SEARCH_SCOPE_CURRENT and self.search_status_label.text():
                self.search_status_label.setText("")
            return
        count_visible = 0
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            if item.text(0) == "..":
                item.setHidden(True)
                continue
            matched = keyword in item.text(0).lower()
            item.setHidden(not matched)
            if matched:
                count_visible += 1
        self.search_status_label.setText(f"已过滤，显示 {count_visible}/{self.tree.topLevelItemCount()} 项")
        self.search_status_label.setStyleSheet(f"color: {COLOR_SYSTEM}; font-size: 9pt; padding: 2px 4px;")

    def _on_transfer_finished(
        self, refresh: bool, local_path: str, success: bool, summary: str
    ):
        """单个传输完成回调。

        refresh=True 表示是上传（push），目录应在**全部传输完成时**统一刷新一次，
        不在每个文件完成时都 reload。
        """
        self._active_transfers = max(0, self._active_transfers - 1)
        terminal = self.get_current_terminal()
        file_name = os.path.basename(local_path)

        if success:
            self._success_count += 1
        else:
            self._fail_count += 1
            # 失败才即时打印（不刷屏）
            if terminal:
                terminal.print_system_msg(
                    f"[失败] {file_name} -> {summary}", COLOR_ERROR
                )

        # 全部传输完成时：汇总打印 + 目录刷新（仅一次）
        if self._active_transfers == 0:
            self.transfer_progress.setRange(0, 100)
            self.transfer_progress.setVisible(False)
            if terminal and (self._success_count > 0 or self._fail_count > 0):
                parts = []
                if self._success_count > 0:
                    parts.append(f"{self._success_count} 成功")
                if self._fail_count > 0:
                    parts.append(f"{self._fail_count} 失败")
                label = "、".join(parts)
                color = COLOR_SUCCESS if self._fail_count == 0 else COLOR_ERROR
                terminal.print_system_msg(f"[传输完成] {label}", color)
            # 批量上传结束后刷新一次目录（之前每文件都刷，N 次 ls 调用）
            if refresh and self._success_count > 0:
                self.load_directory()
            self._success_count = 0
            self._fail_count = 0

    def on_item_double_clicked(self, item: QTreeWidgetItem, _column: int):
        name_or_path = item.text(0)
        if self._is_search_result_mode:
            # 搜索结果模式：双击跳转到对应目录
            full_path = item.data(0, Qt.UserRole) or name_or_path
            type_text = item.text(1)
            is_dir = "Dir" in type_text or full_path.endswith('/')
            if is_dir:
                target_dir = full_path
            else:
                target_dir = os.path.dirname(full_path)
            if not target_dir.endswith('/'):
                target_dir += '/'
            self.path_input.setText(target_dir)
            self._is_search_result_mode = False
            QTimer.singleShot(0, self.load_directory)
            return
        # normal 浏览模式
        if name_or_path == "..":
            QTimer.singleShot(0, self.go_up_level)
        elif item.text(1) in ("Dir", "Link"):
            self.path_input.setText(self.file_service.current_path + name_or_path + "/")
            QTimer.singleShot(0, self.load_directory)
        elif item.text(1) == "File":
            self.tree.download_item(item)
