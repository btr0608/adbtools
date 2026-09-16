import os
import shutil
import tempfile
from functools import partial
from typing import Callable, Optional

from PyQt5.QtCore import QObject, QThread, pyqtSignal

from ..core.adb_client import AdbClient
from ..core.utils import start_worker


class AdbTransferWorker(QThread):
    finished = pyqtSignal(str, bool, str)
    progress = pyqtSignal(int, int)   # (done_bytes, total_bytes)；total=0 表示总量未知

    def __init__(self, adb_client: AdbClient, cmd: list, file_path: str,
                 direction: str = "down", total_bytes: int = 0):
        super().__init__()
        self.adb_client = adb_client
        self.cmd = cmd
        self.file_path = file_path
        self.direction = direction      # "up" 上传 / "down" 下载
        self.total_bytes = max(0, int(total_bytes or 0))

    def run(self):
        # 下载时以本地落盘文件作为进度兜底（adb 输出被管道缓冲也能平滑刷新）
        watch = self.file_path if self.direction == "down" and self.total_bytes else None
        success, summary = self.adb_client.run_transfer_streaming(
            self.cmd,
            total_bytes=self.total_bytes,
            on_progress=lambda done, total: self.progress.emit(int(done), int(total)),
            watch_local_path=watch,
        )
        if success and self.total_bytes:
            self.progress.emit(self.total_bytes, self.total_bytes)
        self.finished.emit(self.file_path, success, summary)


class PullAndDragWorker(QThread):
    pull_done = pyqtSignal(str, bool, str)
    progress = pyqtSignal(int, int)

    def __init__(self, adb_client: AdbClient, cmd: list, local_tmp_path: str,
                 total_bytes: int = 0):
        super().__init__()
        self.adb_client = adb_client
        self.cmd = cmd
        self.local_tmp_path = local_tmp_path
        self.total_bytes = max(0, int(total_bytes or 0))

    def run(self):
        watch = self.local_tmp_path if self.total_bytes else None
        success, summary = self.adb_client.run_transfer_streaming(
            self.cmd,
            total_bytes=self.total_bytes,
            on_progress=lambda done, total: self.progress.emit(int(done), int(total)),
            watch_local_path=watch,
        )
        if success and self.total_bytes:
            self.progress.emit(self.total_bytes, self.total_bytes)
        self.pull_done.emit(self.local_tmp_path, success, summary)


class DirLoadWorker(QThread):
    load_done = pyqtSignal(list, str)

    def __init__(self, adb_client: AdbClient, path: str):
        super().__init__()
        self.adb_client = adb_client
        self.path = path
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        if self._cancelled:
            return
        items, error_msg = self.adb_client.list_dir(self.path)
        if not self._cancelled:
            self.load_done.emit(items, error_msg)


class ShellCommandWorker(QThread):
    """异步执行单条 adb shell 命令（mkdir / touch / mv / rm 等）。"""
    command_done = pyqtSignal(str, bool, str)
    # (shell_cmd, ok, output_or_error)

    def __init__(self, adb_client: AdbClient, shell_cmd: str):
        super().__init__()
        self.adb_client = adb_client
        self.shell_cmd = shell_cmd

    def run(self):
        ok, output = self.adb_client.run_shell_capture(self.shell_cmd)
        self.command_done.emit(self.shell_cmd, ok, output)


class GlobalSearchWorker(QThread):
    """全盘 find 搜索后台线程。"""
    search_done = pyqtSignal(list, str, bool, float)  # (results, error, truncated, elapsed_sec)

    def __init__(self, adb_client: AdbClient, root: str, keyword: str):
        super().__init__()
        self.adb_client = adb_client
        self.root = root
        self.keyword = keyword
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        if self._cancelled:
            return
        import time
        t0 = time.perf_counter()
        results, error, truncated = self.adb_client.find_files(
            self.root, self.keyword,
            max_results=500, timeout=30,
        )
        elapsed = round(time.perf_counter() - t0, 2)
        if self._cancelled:
            self.search_done.emit([], "已取消", False, elapsed)
            return
        self.search_done.emit(results, error, truncated, elapsed)


class FileService(QObject):
    transfer_started = pyqtSignal(str)   # 操作描述，如 "上传 xxx.apk"

    def __init__(self, adb_client: AdbClient):
        super().__init__()
        self.adb_client = adb_client
        self.current_path = "/sdcard/"
        self._dir_worker: Optional[DirLoadWorker] = None
        self._search_worker: Optional[GlobalSearchWorker] = None
        self._drag_workers: list[PullAndDragWorker] = []  # 拖拽拉取 workers（防 GC）
        # 多选拖拽拉取的内部追踪状态
        self._multi_drag_count: int = 0
        self._multi_drag_done: int = 0
        self._multi_drag_results: list = []   # 成功的本地临时路径列表
        self._multi_drag_tmp_dir: Optional[str] = None  # 本批次临时目录路径（用于清理）
        self._multi_drag_target_cb: Optional[Callable[[list, Optional[str]], None]] = None
        self.dir_loaded_cb: Optional[Callable[[list, str], None]] = None
        self.transfer_finished_cb: Optional[Callable[[str, bool, str, bool], None]] = None
        self.global_search_done_cb: Optional[Callable[[list, str, bool, float], None]] = None

    def set_multi_drag_target_cb(self, cb: Callable[[list, Optional[str]], None]):
        """注册批量拖拽拉取全部完成后的回调。
        回调签名: (valid_local_paths: list, tmp_dir_to_cleanup: str | None)
        UI 层需在拖拽结束后 shutil.rmtree(tmp_dir_to_cleanup)。
        """
        self._multi_drag_target_cb = cb

    def load_directory(self, path: str):
        if not path.endswith('/'):
            path += '/'
        self.current_path = path

        serial = self.adb_client.serial
        if not serial:
            if self.dir_loaded_cb:
                self.dir_loaded_cb([], "未选择设备")
            return

        from ..core.utils import safe_is_running
        if safe_is_running(self._dir_worker):
            self._dir_worker.cancel()
            try:
                self._dir_worker.load_done.disconnect()
            except TypeError:
                pass
        self._dir_worker = None

        self._dir_worker = DirLoadWorker(self.adb_client, self.current_path)
        if self.dir_loaded_cb:
            self._dir_worker.load_done.connect(self.dir_loaded_cb)
        start_worker(self._dir_worker)

    def run_shell_async(self, shell_cmd: str, on_done: Optional[Callable[[bool, str], None]] = None):
        """异步执行 adb shell 命令。on_done(ok, output_or_error) 在主线程回调。"""
        worker = ShellCommandWorker(self.adb_client, shell_cmd)
        if on_done:
            worker.command_done.connect(lambda _cmd, ok, out: on_done(ok, out))
        # 不存引用：QThread 会在 finished 后自动清理（start_worker 里 connect destroy）
        start_worker(worker)

    def download_item(self, name: str, save_path: str, total_bytes: int = 0):
        remote_path = self.current_path + name
        cmd = self.adb_client.build_pull_cmd(remote_path, save_path)
        worker = AdbTransferWorker(self.adb_client, cmd, save_path,
                                   direction="down", total_bytes=total_bytes)
        if self.transfer_finished_cb:
            worker.finished.connect(
                partial(self.transfer_finished_cb, False)
            )
        self.transfer_started.emit(f"下载 {name}")
        start_worker(worker)

    def upload_local_file(self, local_path: str):
        cmd = self.adb_client.build_push_cmd(local_path, self.current_path)
        total_bytes = 0
        if os.path.isfile(local_path):
            try:
                total_bytes = os.path.getsize(local_path)
            except OSError:
                total_bytes = 0
        worker = AdbTransferWorker(self.adb_client, cmd, local_path,
                                   direction="up", total_bytes=total_bytes)
        if self.transfer_finished_cb:
            worker.finished.connect(
                partial(self.transfer_finished_cb, True)
            )
        self.transfer_started.emit(f"上传 {os.path.basename(local_path)}")
        start_worker(worker)

    def pull_multiple_for_drag(self, names: list, sizes: Optional[dict] = None):
        """多选拖拽下载：为每个 name 启动独立 Worker，全部完成后回调 multi_drag_cb。

        每批使用独立的临时目录，避免同名文件与历史批次互相覆盖。
        sizes 为 {name: 字节数}，用于聚合进度；缺省时该文件进度走忙碌态。
        回调拿到 tmp_dir_to_cleanup，UI 层需在 QDrag.exec_() 返回后 shutil.rmtree 清理。
        """
        # 清理上次可能残留的状态
        self._multi_drag_count = len(names)
        self._multi_drag_done = 0
        self._multi_drag_results = []
        self._drag_workers.clear()
        sizes = sizes or {}

        target_cb = self._multi_drag_target_cb
        batch_dir = tempfile.mkdtemp(prefix="adbvisual_drag_")
        self._multi_drag_tmp_dir = batch_dir

        for name in names:
            local_tmp_path = os.path.join(batch_dir, name)
            cmd = self.adb_client.build_pull_cmd(self.current_path + name, local_tmp_path)
            total_bytes = int(sizes.get(name, 0) or 0)
            worker = PullAndDragWorker(self.adb_client, cmd, local_tmp_path,
                                       total_bytes=total_bytes)

            def on_done(path, ok, summary, _name=name):
                if ok:
                    self._multi_drag_results.append(path)
                self._multi_drag_done += 1
                if self._multi_drag_done >= self._multi_drag_count:
                    # 全部完成：清空 workers 列表（避免 GC 持有引用）
                    self._drag_workers.clear()
                    dir_to_clean = self._multi_drag_tmp_dir
                    self._multi_drag_tmp_dir = None
                    if target_cb:
                        target_cb(list(self._multi_drag_results), dir_to_clean)

            worker.pull_done.connect(on_done)
            self._drag_workers.append(worker)  # 防止 GC 提前回收未启动的 Worker
            start_worker(worker)

    def cancel_global_search(self):
        from ..core.utils import safe_is_running
        if safe_is_running(self._search_worker):
            self._search_worker.cancel()
            try:
                self._search_worker.search_done.disconnect()
            except TypeError:
                pass
        self._search_worker = None

    def start_global_search(self, root: str, keyword: str):
        """启动全盘搜索。root 如 '/sdcard' 或 '/'。"""
        self.cancel_global_search()
        self._search_worker = GlobalSearchWorker(self.adb_client, root, keyword)
        if self.global_search_done_cb:
            self._search_worker.search_done.connect(self.global_search_done_cb)
        start_worker(self._search_worker)
