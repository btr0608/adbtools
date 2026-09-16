import os
import time
from typing import Dict, List, Optional

from PyQt5.QtCore import QObject, QProcess, pyqtSignal

from ..core.adb_client import AdbClient


class ScrcpyService(QObject):
    """scrcpy 启停服务：单屏/多屏统一管理。

    架构：
    - 单屏模式：_process 指向主进程（与旧版兼容）
    - 多屏模式：_processes 字典持有多个 QProcess，key=display_id
    - is_running() 只要有任何进程在跑就返回 True
    - stop() kill 所有进程
    """

    scrcpy_started = pyqtSignal()
    scrcpy_finished = pyqtSignal(int)   # exit_code（主进程）
    scrcpy_error = pyqtSignal(str)
    # 多屏专用
    multi_started = pyqtSignal(int)           # 启动了 N 个屏
    multi_finished = pyqtSignal(str, int)     # (display_id, exit_code)

    def __init__(self, adb_client: AdbClient):
        super().__init__()
        self.adb_client = adb_client
        self._process: Optional[QProcess] = None          # 主进程（兼容单屏）
        self._processes: Dict[str, QProcess] = {}          # display_id → QProcess
        self._last_cmd: List[str] = []
        self._start_time: float = 0.0
        self._stop_requested = False
        self._is_multi = False                              # 当前是否多屏模式

    # ── 状态查询 ──

    def is_running(self) -> bool:
        if self._process and self._process.state() == QProcess.Running:
            return True
        return any(p.state() == QProcess.Running for p in self._processes.values())

    def is_multi_mode(self) -> bool:
        return self._is_multi

    def active_display_ids(self) -> List[str]:
        """返回当前正在运行的 display_id 列表。"""
        return [
            did for did, p in self._processes.items()
            if p.state() == QProcess.Running
        ]

    # ── 单屏启动（兼容旧接口） ──

    def launch(self, serial: Optional[str], params: List[str]) -> bool:
        """启动 scrcpy。serial 由调用方传入（避免依赖 adb_client 当前 serial）。"""
        if self.is_running():
            return False
        self._stop_requested = False
        self._is_multi = False
        return self._spawn_single(serial, params)

    def _spawn_single(self, serial: Optional[str], params: List[str]) -> bool:
        """内部：启动单个 scrcpy 进程。"""
        scrcpy_path = self.adb_client.find_scrcpy(["scrcpy"] + params)
        if scrcpy_path is None:
            self.scrcpy_error.emit(
                "[错误] 找不到 scrcpy.exe\n"
                "[建议] 请将下载好的 scrcpy 文件夹直接放到本软件所在目录下即可。"
            )
            return False

        # 检查 scrcpy-server 是否在同目录
        server_found = any(
            os.path.exists(os.path.join(os.path.dirname(scrcpy_path), name))
            for name in ("scrcpy-server", "scrcpy-server.jar", "scrcpy-server.apk")
        )
        if not server_found:
            self.scrcpy_error.emit(
                f"[警告] scrcpy.exe 已找到 ({scrcpy_path})，但同目录下未发现 scrcpy-server 文件。\n"
                "[建议] scrcpy-server.jar / scrcpy-server 必须与 scrcpy.exe 放在同一目录，\n"
                "否则投屏可能无法启动。请从 scrcpy 官方发布包中获取。"
            )

        cmd = [scrcpy_path]
        if serial:
            cmd.extend(["-s", serial])
        cmd.extend(params)
        self._last_cmd = cmd

        self._process = QProcess(self)
        self._process.setProcessChannelMode(QProcess.SeparateChannels)
        self._process.finished.connect(self._on_finished)
        self._process.errorOccurred.connect(self._on_error)
        self._start_time = time.time()
        self._process.start(cmd[0], cmd[1:])

        if not self._process.waitForStarted(3000):
            err_msg = self._process.errorString() if self._process else "进程启动超时"
            self.scrcpy_error.emit(f"scrcpy 启动失败：{err_msg}")
            self._process = None
            return False

        self.scrcpy_started.emit()
        return True

    # ── 多屏启动 ──

    def launch_all(self, serial: Optional[str], displays: List[Dict],
                   base_params: List[str]) -> int:
        """为每个 display 各开一个 scrcpy 窗口。

        Args:
            serial: adb 设备 serial
            displays: List[Dict]，每项含 display_id, alias/label
            base_params: 基础 scrcpy 参数（不含 --display-id）

        Returns:
            成功启动的数量；0 表示全部失败
        """
        if self.is_running():
            return 0
        self._stop_requested = False
        self._is_multi = True

        scrcpy_path = self.adb_client.find_scrcpy(["scrcpy"] + base_params)
        if scrcpy_path is None:
            self.scrcpy_error.emit(
                "[错误] 找不到 scrcpy.exe，无法启动多屏投屏"
            )
            return 0

        started = 0
        for d in displays:
            display_id = d.get('display_id', '')
            if not display_id:
                continue
            # 构造每个屏的独立参数
            params = list(base_params)
            params.append(f"--display-id={display_id}")
            alias = d.get('alias') or d.get('label') or f"屏幕{display_id}"
            params.append(f"--window-title={alias}")

            cmd = [scrcpy_path]
            if serial:
                cmd.extend(["-s", serial])
            cmd.extend(params)

            proc = QProcess(self)
            proc.setProcessChannelMode(QProcess.SeparateChannels)
            proc.finished.connect(
                lambda code, status, did=display_id: self._on_multi_finished(did, code)
            )
            proc.errorOccurred.connect(
                lambda err, did=display_id: self._on_multi_error(did, err)
            )
            proc.start(cmd[0], cmd[1:])

            if proc.waitForStarted(3000):
                self._processes[display_id] = proc
                started += 1
            else:
                err_msg = proc.errorString()
                self.scrcpy_error.emit(
                    f"多屏投屏: 屏幕{display_id} 启动失败 - {err_msg}"
                )

        if started > 0:
            self.multi_started.emit(started)
            self.scrcpy_started.emit()
        return started

    # ── 停止 ──

    def stop(self) -> None:
        """非阻塞停止：设置标记后直接 kill()，不 waitForFinished 避免 UI 卡顿。"""
        if self._stop_requested:
            return
        self._stop_requested = True
        # 单屏
        if self._process and self._process.state() == QProcess.Running:
            self._process.kill()
        # 多屏
        for proc in self._processes.values():
            if proc.state() == QProcess.Running:
                proc.kill()

    # ── 单屏回调 ──

    def _on_finished(self, exit_code: int, _exit_status=None):
        if self._stop_requested:
            self._process = None
            self.scrcpy_finished.emit(exit_code)
            return
        elapsed = time.time() - self._start_time if self._start_time else 0
        if elapsed < 2.0 and exit_code != 0:
            err_output = ""
            if self._process:
                err_output = bytes(self._process.readAllStandardError()).decode(
                    'utf-8', errors='replace'
                ).strip()
                if err_output:
                    lines = err_output.splitlines()
                    err_output = '\n'.join(lines[-5:])
            msg = f"scrcpy 启动失败（运行 {elapsed:.1f}s，退出码 {exit_code}）"
            if err_output:
                msg += f"\n\n错误输出：\n{err_output}"
            else:
                msg += "\n\n可能原因：\n"
                msg += "  1) 设备未通过 USB 调试授权\n"
                msg += "  2) adb 版本与 scrcpy 版本不兼容\n"
                msg += "  3) 设备上的 scrcpy-server 无法推送/执行\n"
            self.scrcpy_error.emit(msg)
        self._process = None
        self.scrcpy_finished.emit(exit_code)

    def _on_error(self, _error: QProcess.ProcessError):
        if self._stop_requested:
            return
        msg = self._process.errorString() if self._process else "unknown"
        self.scrcpy_error.emit(f"scrcpy 进程错误：{msg}")

    # ── 多屏回调 ──

    def _on_multi_finished(self, display_id: str, exit_code: int):
        self._processes.pop(display_id, None)
        self.multi_finished.emit(display_id, exit_code)
        # 如果全部进程都退出了，发一个总的 finished 信号
        if not self._processes and not self._process:
            self._is_multi = False
            self.scrcpy_finished.emit(exit_code)

    def _on_multi_error(self, display_id: str, _error: QProcess.ProcessError):
        if self._stop_requested:
            return
        self.scrcpy_error.emit(f"多屏投屏: 屏幕{display_id} 进程错误")
