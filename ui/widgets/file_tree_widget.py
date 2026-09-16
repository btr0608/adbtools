import os
import shutil

from PyQt5.QtCore import QMimeData, QPoint, QUrl, Qt
from PyQt5.QtGui import QDrag
from PyQt5.QtWidgets import (
    QApplication, QFileDialog, QMenu, QMessageBox,
    QTreeWidget, QTreeWidgetItem
)

from ...core.utils import (
    COLOR_ERROR, COLOR_SUCCESS, ensure_trailing_slash, safe_shell_quote,
    start_worker
)
from ..dialogs.create_path_dialog import CreatePathDialog
from ..dialogs.rename_dialog import RenameDialog
from ..theme import IconHelper, Icons


class FileTreeWidget(QTreeWidget):
    def __init__(self, explorer):
        super().__init__()
        self.explorer = explorer
        self.drag_start_pos: QPoint = None
        self._drag_pull_started = False  # 防重入：拖拽拉取只启动一次
        self.setAcceptDrops(True)
        self.setDragEnabled(True)
        self.setDropIndicatorShown(True)
        self.setSelectionMode(QTreeWidget.ExtendedSelection)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)

    def _set_action_icon(self, action, name: str, size: int = 16):
        """给 QAction/QMenu 设置 SVG 图标。"""
        action.setIcon(IconHelper.icon(name, size))

    def show_context_menu(self, pos):
        item = self.itemAt(pos)
        selected_items = self.selectedItems()
        menu = QMenu(self)

        # 多选且有有效项时，显示批量下载
        multi_selected = (
            item and item.text(0) != ".."
            and len(selected_items) > 1
            and all(i.text(0) != ".." for i in selected_items)
        )
        if multi_selected:
            download_action = menu.addAction(f"下载 {len(selected_items)} 项到本地...")
            self._set_action_icon(download_action, Icons.DOWNLOAD)
            menu.addSeparator()
            rename_action = delete_action = None
        elif item and item.text(0) != "..":
            download_action = menu.addAction("下载到本地...")
            self._set_action_icon(download_action, Icons.DOWNLOAD)
            menu.addSeparator()
            rename_action = menu.addAction("重命名")
            self._set_action_icon(rename_action, Icons.RENAME)
            delete_action = menu.addAction("删除")
            self._set_action_icon(delete_action, Icons.DELETE)
            menu.addSeparator()
            # .apk 文件额外显示"安装到此设备"
            install_apk_action = None
            name = item.text(0).lower()
            if name.endswith('.apk'):
                install_apk_action = menu.addAction("安装到此设备")
                self._set_action_icon(install_apk_action, Icons.TOOLBOX_PLUS)
        else:
            download_action = rename_action = delete_action = install_apk_action = None

        # 上传：文件多选 / 文件夹递归，清晰分两个子项
        upload_menu = menu.addMenu("上传到设备")
        self._set_action_icon(upload_menu, Icons.UPLOAD)
        upload_file_action = upload_menu.addAction("文件...（多选）")
        self._set_action_icon(upload_file_action, Icons.FILE)
        upload_folder_action = upload_menu.addAction("文件夹...（整个递归）")
        self._set_action_icon(upload_folder_action, Icons.FOLDER)

        new_folder_action = menu.addAction("新建文件夹")
        self._set_action_icon(new_folder_action, Icons.FOLDER)
        new_file_action = menu.addAction("新建文件")
        self._set_action_icon(new_file_action, Icons.FILE)
        menu.addSeparator()
        refresh_action = menu.addAction("刷新")
        self._set_action_icon(refresh_action, Icons.REFRESH)

        action = menu.exec_(self.mapToGlobal(pos))
        if action is None:
            return
        if action == download_action:
            if multi_selected:
                self.download_items(selected_items)
            else:
                self.download_item(item)
        elif action == rename_action:
            self.rename_item(item)
        elif action == delete_action:
            self.delete_item(item)
        elif action == install_apk_action:
            self.install_device_apk(item)
        elif action == upload_file_action:
            self.upload_files()
        elif action == upload_folder_action:
            self.upload_folder()
        elif action == new_folder_action:
            self.create_remote_path(is_dir=True)
        elif action == new_file_action:
            self.create_remote_path(is_dir=False)
        elif action == refresh_action:
            self.explorer.reload()

    def create_remote_path(self, is_dir: bool):
        """新建文件夹或空文件（异步，不阻塞 UI）。"""
        current_path = ensure_trailing_slash(self.explorer.file_service.current_path)
        dlg = CreatePathDialog(self, current_path, is_dir=is_dir)
        if dlg.exec_() != CreatePathDialog.Accepted:
            return
        name = dlg.get_new_name()
        if not name:
            return
        full = current_path + name
        if is_dir:
            cmd = f'mkdir -p {safe_shell_quote(full)}'
            desc = f"新建文件夹 {name}"
        else:
            cmd = f'touch {safe_shell_quote(full)}'
            desc = f"新建文件 {name}"

        # 禁用右键菜单防重入（简单做法：整个 tree 临时禁用）
        self.setEnabled(False)

        def on_done(ok: bool, output: str):
            self.setEnabled(True)
            if ok:
                terminal = self.explorer.get_current_terminal()
                if terminal:
                    terminal.print_system_msg(
                        f"[成功] {desc}", COLOR_SUCCESS,
                    )
                self.explorer.reload()
            else:
                QMessageBox.warning(
                    self, "操作失败",
                    f"{desc} 失败：\n{output}\n\n可能因为权限不足或 adb 未就绪。"
                )

        self.explorer.file_service.run_shell_async(cmd, on_done)

    def rename_item(self, item: QTreeWidgetItem):
        old_name = item.text(0)
        is_dir = item.text(1) in ("Dir", "Link")
        current_path = ensure_trailing_slash(self.explorer.file_service.current_path)

        dlg = RenameDialog(self, current_path, old_name, is_dir=is_dir)
        if dlg.exec_() != RenameDialog.Accepted:
            return
        new_name = dlg.get_new_name()
        if not new_name:
            return

        old_full = current_path + old_name
        new_full = current_path + new_name
        cmd = f'mv {safe_shell_quote(old_full)} {safe_shell_quote(new_full)}'

        self.setEnabled(False)

        def on_done(ok: bool, output: str):
            self.setEnabled(True)
            if ok:
                terminal = self.explorer.get_current_terminal()
                if terminal:
                    terminal.print_system_msg(
                        f"[成功] 重命名 {old_name} → {new_name}", COLOR_SUCCESS,
                    )
                self.explorer.reload()
            else:
                QMessageBox.warning(
                    self, "重命名失败",
                    f"无法将 '{old_name}' 重命名为 '{new_name}'：\n{output}"
                )

        self.explorer.file_service.run_shell_async(cmd, on_done)

    def delete_item(self, item: QTreeWidgetItem):
        name = item.text(0)
        type_str = "文件夹" if item.text(1) in ("Dir", "Link") else "文件"
        reply = QMessageBox.question(
            self, "确认删除",
            f"确定要永久删除{type_str} '{name}' 吗？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return
        full = ensure_trailing_slash(self.explorer.file_service.current_path) + name
        cmd = f'rm -rf {safe_shell_quote(full)}'

        self.setEnabled(False)

        def on_done(ok: bool, output: str):
            self.setEnabled(True)
            if ok:
                terminal = self.explorer.get_current_terminal()
                if terminal:
                    terminal.print_system_msg(
                        f"[成功] 已删除 {type_str} {name}", COLOR_SUCCESS,
                    )
                self.explorer.reload()
            else:
                QMessageBox.warning(
                    self, "删除失败",
                    f"无法删除 '{name}'：\n{output}\n\n可能因为权限不足。"
                )

        self.explorer.file_service.run_shell_async(cmd, on_done)

    def install_device_apk(self, item: QTreeWidgetItem):
        """设备上的 .apk 文件：直接 adb install /sdcard/xxx.apk。"""
        import subprocess
        from PyQt5.QtCore import QThread, pyqtSignal
        from ...core.utils import get_startup_info

        name = item.text(0)
        current_path = ensure_trailing_slash(self.explorer.file_service.current_path)
        remote_path = current_path + name

        terminal = self.explorer.get_current_terminal()
        if terminal:
            terminal.print_system_msg(f"[安装 APK] {name} (设备端) ...")

        adb_client = self.explorer.file_service.adb_client

        class InstallWorker(QThread):
            done = pyqtSignal(bool, str, str)

            def run(self_inner):
                try:
                    cmd = adb_client._build_cmd('install', '-r', remote_path)
                    r = subprocess.run(cmd, capture_output=True, text=True,
                                       encoding='utf-8', errors='replace', timeout=120,
                                       startupinfo=get_startup_info(), cwd=adb_client.adb_home)
                    out = (r.stdout or "") + (r.stderr or "")
                    if r.returncode == 0 and "Success" in out:
                        self_inner.done.emit(True, name, "")
                    else:
                        self_inner.done.emit(False, name, out.strip() or "安装失败")
                except subprocess.TimeoutExpired:
                    self_inner.done.emit(False, name, "安装超时（>120s）")
                except Exception as e:
                    self_inner.done.emit(False, name, str(e))

        worker = InstallWorker()
        worker.done.connect(self._on_install_device_apk_done)
        start_worker(worker)

    def _on_install_device_apk_done(self, ok: bool, name: str, error: str):
        terminal = self.explorer.get_current_terminal()
        if ok:
            if terminal:
                terminal.print_system_msg(f"[安装成功] {name}", COLOR_SUCCESS)
            QMessageBox.information(self, "安装成功", f"{name} 已成功安装到设备")
        else:
            if terminal:
                terminal.print_system_msg(f"[安装失败] {name}: {error}", COLOR_ERROR)
            QMessageBox.warning(self, "安装失败", f"{name}\n\n{error}")

    def download_item(self, item: QTreeWidgetItem):
        name = item.text(0)
        is_dir = item.text(1) in ("Dir", "Link")
        if is_dir:
            save_dir = QFileDialog.getExistingDirectory(self, "选择保存位置")
            if not save_dir:
                return
            save_path = os.path.join(save_dir, name)
        else:
            save_path, _ = QFileDialog.getSaveFileName(self, "保存文件到...", name)
            if not save_path:
                return
        terminal = self.explorer.get_current_terminal()
        if terminal:
            terminal.print_system_msg(f"[后台下载] 开始拉取 {name} 到本地...")
        total_bytes = item.data(0, Qt.UserRole + 1) or 0
        self.explorer.file_service.download_item(name, save_path, total_bytes=total_bytes)

    def download_items(self, items: list):
        """批量下载多个选中项到同一本地目录。"""
        save_dir = QFileDialog.getExistingDirectory(self, "选择保存目录（所有文件将下载到此目录）")
        if not save_dir:
            return
        terminal = self.explorer.get_current_terminal()
        count = 0
        for item in items:
            name = item.text(0)
            if name == "..":
                continue
            count += 1
            save_path = os.path.join(save_dir, name)
            total_bytes = item.data(0, Qt.UserRole + 1) or 0
            self.explorer.file_service.download_item(name, save_path, total_bytes=total_bytes)
        if terminal:
            terminal.print_system_msg(f"[批量下载] 已提交 {count} 项到 {save_dir} ...")

    def upload_files(self):
        """多选本地文件上传到当前设备目录。"""
        paths, _ = QFileDialog.getOpenFileNames(self, "选择要上传的文件（可多选）")
        if not paths:
            return
        terminal = self.explorer.get_current_terminal()
        if terminal:
            terminal.print_system_msg(f"[后台上传] 提交 {len(paths)} 个文件到设备...")
        for path in paths:
            self.explorer.file_service.upload_local_file(path)

    def upload_folder(self):
        """选择本地文件夹并递归上传到当前设备目录。"""
        path = QFileDialog.getExistingDirectory(self, "选择要上传的文件夹")
        if not path:
            return
        terminal = self.explorer.get_current_terminal()
        if terminal:
            terminal.print_system_msg(f"[后台上传] 开始推送文件夹 {os.path.basename(path)} 到设备...")
        self.explorer.file_service.upload_local_file(path)

    # ================= 拖拽上传：本地 → 设备 =================
    def dragEnterEvent(self, event):
        event.accept() if event.mimeData().hasUrls() else event.ignore()

    def dragMoveEvent(self, event):
        event.accept() if event.mimeData().hasUrls() else event.ignore()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        terminal = self.explorer.get_current_terminal()
        if not urls:
            return
        count = 0
        for url in urls:
            local_path = url.toLocalFile()
            if not os.path.exists(local_path):
                continue
            count += 1
            self.explorer.file_service.upload_local_file(local_path)
        if terminal and count > 0:
            terminal.print_system_msg(f"[后台上传] 提交 {count} 项到设备...")
        event.accept()

    # ================= 拖拽下载：设备 → 本地（支持多选） =================
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_start_pos = event.pos()
            self._drag_pull_started = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not (event.buttons() & Qt.LeftButton) or not self.drag_start_pos:
            return
        if self._drag_pull_started:
            return  # 拉取已启动，忽略后续 mouseMoveEvent（防刷屏）
        if (event.pos() - self.drag_start_pos).manhattanLength() < QApplication.startDragDistance():
            return

        # 收集要拉取的项目：优先用选中项（多选拖拽），否则用当前 item
        selected = self.selectedItems()
        drag_items = []
        if selected and len(selected) > 1:
            drag_items = [i for i in selected if i.text(0) != ".."]
        else:
            item = self.itemAt(self.drag_start_pos)
            if not item or item.text(0) == "..":
                return
            drag_items = [item]

        if not drag_items:
            return

        names = [i.text(0) for i in drag_items]
        sizes = {
            i.text(0): (i.data(0, Qt.UserRole + 1) or 0)
            for i in drag_items
        }

        terminal = self.explorer.get_current_terminal()
        if len(names) == 1:
            if terminal:
                terminal.print_system_msg(f"[拉取准备] 正在下载 {names[0]} 到本地缓存区...")
        else:
            if terminal:
                terminal.print_system_msg(f"[拉取准备] 正在下载 {len(names)} 个文件到本地缓存区...")

        # 启动批量拖拽拉取（内部每个文件独立 worker，全部完成后回调 start_drag_after_pull_multi）
        self._drag_pull_started = True
        self.explorer.file_service.pull_multiple_for_drag(names, sizes)

    def start_drag_after_pull_multi(self, tmp_paths: list, tmp_dir: str = None):
        """全部文件拉取完成后启动一次 QDrag（支持多项）。

        tmp_dir: 本批次临时目录路径，QDrag 结束后自动清理。
        """
        valid_paths = [p for p in tmp_paths if os.path.exists(p)]
        if not valid_paths:
            # 没有有效文件，直接清理临时目录
            if tmp_dir:
                shutil.rmtree(tmp_dir, ignore_errors=True)
            return

        terminal = self.explorer.get_current_terminal()
        if terminal:
            terminal.print_system_msg(
                f"[下载成功] {len(valid_paths)} 个文件已就绪，拖动到目标位置即可复制",
                COLOR_SUCCESS,
            )

        drag = QDrag(self)
        mime_data = QMimeData()
        urls = [QUrl.fromLocalFile(p) for p in valid_paths]
        mime_data.setUrls(urls)
        drag.setMimeData(mime_data)
        drag.exec_(Qt.CopyAction)

        # 拖拽结束后清理临时目录（无论成功/取消）
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)
