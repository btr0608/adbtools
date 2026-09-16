import os
import re
import shlex
from collections import deque
from typing import Callable, Optional

from PyQt5.QtCore import QObject, QProcess, pyqtSignal

from ..core.adb_client import AdbClient
from ..core.utils import COLOR_ERROR, COLOR_SUCCESS, COLOR_SYSTEM


class TerminalService(QObject):
    output_written = pyqtSignal(str, str)
    system_msg = pyqtSignal(str, str)
    prompt_reset = pyqtSignal()
    state_changed = pyqtSignal(bool)
    scrcpy_requested = pyqtSignal(list)   # 用户在终端输入 scrcpy 命令时触发，交由上层转发到 ScrcpyService

    def __init__(self, adb_client: AdbClient):
        super().__init__()
        self.adb_client = adb_client
        self.cmd_queue = deque()
        self.process: Optional[QProcess] = None
        self.decoder_out = None
        self.decoder_err = None
        self.ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')

    def bind_process(self, process: QProcess, decoder_out, decoder_err):
        self.process = process
        self.decoder_out = decoder_out
        self.decoder_err = decoder_err
        self.process.readyReadStandardOutput.connect(
            lambda: self._handle_stream(self.process.readAllStandardOutput(), is_err=False)
        )
        self.process.readyReadStandardError.connect(
            lambda: self._handle_stream(self.process.readAllStandardError(), is_err=True)
        )
        self.process.finished.connect(self._on_process_finished)
        self.process.stateChanged.connect(self._on_state_changed)

    def _handle_stream(self, raw_data, is_err: bool = False):
        decoder = self.decoder_err if is_err else self.decoder_out
        data = decoder.decode(raw_data.data()).replace('\r\n', '\n')
        if data:
            color = COLOR_ERROR if is_err else None
            self.output_written.emit(data, color)

    def _on_state_changed(self, state):
        is_running = (state == QProcess.Running)
        self.state_changed.emit(is_running)

    def _on_process_finished(self):
        if self.cmd_queue:
            self._process_next_queue_command(is_first=False)
        else:
            self.prompt_reset.emit()

    def run_command(self, cmd_str: str, from_external: bool = False):
        if not cmd_str:
            if self.process and self.process.state() == QProcess.Running:
                self.process.write(b'\n')
            else:
                self.prompt_reset.emit()
            return
        if self.process and self.process.state() == QProcess.Running:
            if from_external:
                self.system_msg.emit(cmd_str + '\n', COLOR_SYSTEM)
            self.process.write((cmd_str + "\n").encode('utf-8'))
            return
        cmds = [c.strip() for c in cmd_str.split('\n') if c.strip()]
        if not cmds:
            return
        is_idle = (not self.process or self.process.state() != QProcess.Running)
        self.cmd_queue.extend(cmds)
        if is_idle:
            self._process_next_queue_command(is_first=True, from_external=from_external)

    def send_ctrl_c(self):
        if self.process and self.process.state() == QProcess.Running:
            self.output_written.emit("^C\n", COLOR_SYSTEM)
            self.process.write(b'\x03')

    def kill_process(self):
        self.cmd_queue.clear()
        if self.process and self.process.state() == QProcess.Running:
            self.process.kill()
            self.system_msg.emit("[强制结束] 进程及后续队列已被手动终止！", COLOR_ERROR)

    def _process_next_queue_command(self, is_first: bool = False, from_external: bool = False):
        if not self.cmd_queue:
            self.prompt_reset.emit()
            return

        cmd_str = self.cmd_queue.popleft()
        if not is_first:
            self.prompt_reset.emit()

        should_echo = from_external if is_first else True
        if should_echo:
            self.system_msg.emit(cmd_str + '\n', COLOR_SYSTEM)

        try:
            cmd_parts = shlex.split(cmd_str.replace('\\', '\\\\') if os.name == 'nt' else cmd_str)
        except ValueError:
            cmd_parts = cmd_str.split()

        if not cmd_parts:
            self.prompt_reset.emit()
            self._on_process_finished()
            return

        if "scrcpy" in cmd_parts[0].lower():
            self.scrcpy_requested.emit(cmd_parts)
            self.prompt_reset.emit()
            self._on_process_finished()
            return

        program, args = self.adb_client.build_terminal_args(cmd_str)
        self.process.start(program, args)
