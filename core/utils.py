import os
import subprocess
from typing import Optional

COLOR_DEFAULT = "#d4d4d4"
COLOR_PROMPT = "#569cd6"
COLOR_SYSTEM = "#dcdcaa"
COLOR_ERROR = "#f44747"
COLOR_SUCCESS = "#4CAF50"

_workers = set()


def start_worker(worker):
    from PyQt5.QtCore import QThread
    _workers.add(worker)

    def cleanup():
        _workers.discard(worker)
        worker.deleteLater()

    worker.finished.connect(cleanup)
    worker.start()


def safe_is_running(worker) -> bool:
    if not worker:
        return False
    try:
        return worker.isRunning()
    except RuntimeError:
        return False


def get_startup_info() -> subprocess.STARTUPINFO:
    si = subprocess.STARTUPINFO()
    if os.name == 'nt':
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    return si


def decode_bytes(raw: bytes) -> str:
    if not raw:
        return ""
    try:
        return raw.decode('utf-8')
    except UnicodeDecodeError:
        return raw.decode('gbk', errors='replace')


def extract_rate_summary(text: str) -> str:
    if not text:
        return "未知状态"
    lines = [l.strip() for l in text.replace('\r', '\n').split('\n') if l.strip()]
    return lines[-1] if lines else "完成"


def format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    elif size_bytes < 1024 * 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024 * 1024):.1f} TB"


def ensure_trailing_slash(path: str) -> str:
    """确保 Android 路径以 / 结尾。"""
    if not path:
        return "/"
    return path if path.endswith("/") else path + "/"


def safe_shell_quote(name: str) -> str:
    """用单引号安全包裹 shell 参数，处理内部单引号。"""
    escaped = name.replace("'", "'\\''")
    return f"'{escaped}'"


INVALID_FILENAME_CHARS = set('\\/:*?"<>|')


def is_valid_filename(name: str) -> bool:
    """检查文件名是否合法（不含非法字符，非空，非纯点号）。"""
    if not name or not name.strip():
        return False
    if name in (".", ".."):
        return False
    for ch in name:
        if ch in INVALID_FILENAME_CHARS:
            return False
    return True
