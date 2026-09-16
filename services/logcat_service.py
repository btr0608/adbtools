import codecs
import os
import re
from datetime import datetime
from typing import Optional, Set, Tuple

from PyQt5.QtCore import QObject, QProcess, pyqtSignal

from ..core.adb_client import AdbClient
from ..core.utils import decode_bytes, get_startup_info


# logcat 行首格式（-v time）: "08-24 19:23:39.061 W/BSClock  ( 835): message"
# 级别字符在时间戳之后、斜杠之前。Android logcat 标准级别：V/D/I/W/E/F/S
LOG_LEVELS = {"V": "Verbose", "D": "Debug", "I": "Info", "W": "Warn", "E": "Error", "F": "Fatal", "S": "Silent"}
LEVEL_LINE_RE = re.compile(r'\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\.\d{3}\s+([VDIWEFS])/')


class LogcatService(QObject):
    """logcat 录制服务：用 QProcess 持续抓取 logcat 输出，写入本地文件并按级别过滤转发。"""

    recording_started = pyqtSignal(str)   # filename
    recording_stopped = pyqtSignal(str, int)  # (filename, size_kb)，filename 为空表示未生成文件
    line_received = pyqtSignal(str, str)   # (level, message)
    error = pyqtSignal(str)

    def __init__(self, adb_client: AdbClient):
        super().__init__()
        self.adb_client = adb_client
        self._process: Optional[QProcess] = None
        self._file = None
        self._current_filename: str = ""
        self._level_filter: Set[str] = set()   # 空 = 不过滤；非空 = 只保留这些级别
        self._pid_filter: Optional[int] = None  # 包名过滤对应的 PID
        self._decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
        self._stop_requested = False

    def is_recording(self) -> bool:
        return self._process is not None and self._process.state() == QProcess.Running

    def current_filename(self) -> str:
        return self._current_filename

    def set_level_filter(self, levels: Set[str]) -> None:
        """设置级别过滤。传入空集合清除过滤。levels 形如 {'W', 'E'}。"""
        self._level_filter = set(levels)

    def set_pid_filter(self, pid: Optional[int]) -> None:
        """设置按进程 PID 过滤。None 清除过滤。"""
        self._pid_filter = pid

    def start_recording(self, serial: str, target_dir: str) -> bool:
        """开始录制。生成带时间戳的日志文件；serial 为目标设备。"""
        if self.is_recording():
            return False
        if not serial:
            self.error.emit("未选择设备")
            return False
        self._stop_requested = False
        os.makedirs(target_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"logcat_{timestamp}.log"
        full_path = os.path.join(target_dir, filename)
        try:
            self._file = open(full_path, 'w', encoding='utf-8', buffering=1)
        except OSError as e:
            self.error.emit(f"无法创建日志文件: {e}")
            return False
        self._current_filename = full_path

        # 每次启动录制重置增量解码器，避免残留上一次末尾的半字节导致首行乱码
        self._decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')

        # 构造命令：adb -s <serial> logcat -v time
        # 用 -v time 让输出带时间戳，便于离线分析
        cmd = [self.adb_client.adb_path]
        if serial:
            cmd.extend(["-s", serial])
        cmd.extend(["logcat", "-v", "time"])
        if self._pid_filter:
            cmd.append(f"--pid={self._pid_filter}")

        self._process = QProcess(self)
        self._process.setProcessChannelMode(QProcess.MergedChannels)
        self._process.readyRead.connect(self._on_output)
        self._process.finished.connect(self._on_finished)
        self._process.errorOccurred.connect(self._on_error)
        self._process.start(cmd[0], cmd[1:])

        self.recording_started.emit(full_path)
        return True

    def stop_recording(self) -> None:
        """强制停止 logcat 录制。

        采用非阻塞 kill：设置 _stop_requested 标记后直接 kill()，不 waitForFinished。
        清理工作（关文件 + 发 recording_stopped）由 _on_finished / _on_error 回调完成。
        """
        if self._stop_requested:
            return
        self._stop_requested = True
        if self._process and self._process.state() == QProcess.Running:
            self._process.kill()
        # _on_finished 会处理后续清理：关文件、发 recording_stopped
        # 如果进程已退出（如录制中 adb 断开），手动补一次清理
        elif self._process is not None:
            filename, size_kb = self._close_file_and_get_info()
            self._process = None
            self.recording_stopped.emit(filename, size_kb)

    def _on_output(self):
        if not self._process or self._process.state() != QProcess.Running:
            return
        raw = self._process.readAll()
        text = self._decoder.decode(raw.data())
        if not text:
            return
        if self._file:
            try:
                self._file.write(text)
            except OSError:
                pass
        for line in text.splitlines():
            level = self._parse_level(line)
            if self._level_filter and level and level not in self._level_filter:
                continue
            self.line_received.emit(level, line)

    @staticmethod
    def _parse_level(line: str) -> str:
        m = LEVEL_LINE_RE.match(line)
        return m.group(1) if m else ""

    def _on_finished(self, _exit_code, _exit_status):
        """进程退出时统一收尾（手动 stop 或自然退出都走这里）。"""
        filename, size_kb = self._close_file_and_get_info()
        self._process = None
        self.recording_stopped.emit(filename, size_kb)

    def _on_error(self, _error: QProcess.ProcessError):
        # 用户主动调用 stop_recording() 时，kill() 会触发 Crashed 错误，这是正常现象，不要误报
        if self._stop_requested:
            return
        msg = self._process.errorString() if self._process else "unknown"
        self.error.emit(f"logcat 启动失败: {msg}")
        self._close_file_and_get_info()

    def _close_file_and_get_info(self) -> Tuple[str, int]:
        """关闭文件并返回 (文件路径, 大小KB)。"""
        filename = ""
        size_kb = 0
        if self._current_filename:
            filename = self._current_filename
            try:
                if os.path.exists(filename):
                    size_kb = max(1, round(os.path.getsize(filename) / 1024))
            except OSError:
                size_kb = 0
        if self._file:
            try:
                self._file.close()
            except OSError:
                pass
            self._file = None
        self._current_filename = ""
        return filename, size_kb
