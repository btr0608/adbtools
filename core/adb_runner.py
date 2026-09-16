"""AdbRunner — AdbClient 的高层 facade。

所有业务模块应通过 AdbRunner 调用 adb，而不是手动拼 adb 命令字符串。
AdbRunner 内部持有一个 AdbClient 引用，提供面向操作的语义化 API：

    runner.shell("ls /sdcard")               # 同步，返回 (ok, output)
    runner.shell_async("pidof com.example")  # 异步，走 start_worker 模式
    runner.install("C:/apk/app.apk")         # 安装 APK
    runner.getprop("ro.product.model")       # 读属性

这个类是轻量封装，不引入新的 Worker 实现 —— 复杂操作仍由 services/ 层
的 Worker 完成。AdbRunner 只负责：
  - 统一命令入口（自动带 -s serial）
  - 超时 / 错误码 / stderr 捕获
  - 常用操作的快捷方法（install, push, pull, pidof, getprop ...）

未来新增 BSP 功能（dmesg, partition dump, flash）时，只需在这里加方法，
调用方代码不用关心 adb 命令怎么拼。
"""

from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

from .adb_client import AdbClient


class AdbRunner:
    """面向操作的 ADB facade。薄封装 AdbClient，不替换它。"""

    def __init__(self, adb_client: AdbClient):
        self.client = adb_client

    # ──────────────────── 同步 shell ────────────────────

    def shell(self, shell_cmd: str, timeout: int = 15) -> Tuple[bool, str]:
        """同步执行 adb shell，返回 (ok, output_or_error)。"""
        return self.client.run_shell_capture(shell_cmd, timeout=timeout)

    def shell_raw(self, *args: str, timeout: int = 15) -> Tuple[bool, str]:
        """同步执行 adb <args...>（不走 shell 子命令）。"""
        import subprocess
        from .utils import get_startup_info
        cmd = self.client._build_cmd(*args)
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                encoding='utf-8', errors='replace', timeout=timeout,
                startupinfo=get_startup_info(), cwd=self.client.adb_home,
            )
            out = f"{(result.stdout or '').strip()}\n{(result.stderr or '').strip()}".strip()
            return result.returncode == 0, out
        except subprocess.TimeoutExpired:
            return False, f"命令超时（>{timeout}s）"
        except Exception as e:
            return False, str(e)

    # ──────────────────── 快捷方法 ────────────────────

    def getprop(self, prop: str) -> str:
        """读取设备属性，失败返回空串。"""
        ok, out = self.shell(f"getprop {prop}", timeout=5)
        return out.strip() if ok else ""

    def pidof(self, package: str) -> Optional[int]:
        """按包名查 PID，未运行返回 None。"""
        ok, out = self.shell(f"pidof {package}", timeout=5)
        if not ok or not out.strip():
            return None
        # pidof 可能返回多个 PID（空格分隔），取第一个
        try:
            return int(out.strip().split()[0])
        except (ValueError, IndexError):
            return None

    def install(self, local_apk_path: str, reinstall: bool = True) -> Tuple[bool, str]:
        """安装本地 APK。reinstall=True 等价于 adb install -r。"""
        args: List[str] = ['install']
        if reinstall:
            args.append('-r')
        args.append(local_apk_path)
        ok, out = self.shell_raw(*args, timeout=120)
        # adb install 有时 exit code 0 但 Success 文本在 stdout
        if ok and "Success" not in out:
            return True, "Success"
        return ok, out

    def uninstall(self, package: str) -> Tuple[bool, str]:
        """卸载包名。"""
        return self.shell_raw('uninstall', package, timeout=30)

    def list_packages(self, third_party_only: bool = True) -> List[str]:
        """列出已安装包名。third_party_only=True 时等价于 adb shell pm list packages -3。"""
        flag = "-3" if third_party_only else ""
        ok, out = self.shell(f"pm list packages {flag}".strip(), timeout=10)
        if not ok:
            return []
        result: List[str] = []
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("package:"):
                result.append(line[len("package:"):])
        return result

    def push(self, local_path: str, remote_path: str) -> Tuple[bool, str]:
        """推送文件到设备（同步）。"""
        return self.shell_raw('push', local_path, remote_path, timeout=60)

    def pull(self, remote_path: str, local_path: str) -> Tuple[bool, str]:
        """从设备拉取文件（同步）。"""
        return self.shell_raw('pull', remote_path, local_path, timeout=60)

    def file_exists(self, remote_path: str) -> bool:
        """测试远程路径是否存在。"""
        ok, _ = self.shell(f"test -e {remote_path} && echo YES || echo NO", timeout=5)
        # ok=False 时说明 shell 命令执行失败（比如设备离线），保守返回 False
        return ok and _strip_last(_) == "YES"

    def thermal_zone_available(self) -> bool:
        """检测 /sys/class/thermal 是否存在（真机有，模拟器通常没有）。"""
        ok, out = self.shell("ls /sys/class/thermal/ 2>/dev/null", timeout=5)
        return ok and bool(out.strip())

    # ──────────────────── 异步便捷包装 ────────────────────

    def shell_async(
        self,
        shell_cmd: str,
        on_done: Callable[[bool, str], None],
        timeout: int = 15,
    ) -> None:
        """异步执行 adb shell，完成回调 on_done(ok, output)。"""
        from PyQt5.QtCore import QThread, pyqtSignal
        from .utils import start_worker

        class _Worker(QThread):
            done = pyqtSignal(bool, str)
            def run(self_inner):
                ok, out = self_inner.runner.shell(shell_cmd, timeout=timeout)
                self_inner.done.emit(ok, out)

        worker = _Worker()
        worker.runner = self
        worker.done.connect(on_done)
        start_worker(worker)


def _strip_last(text: str) -> str:
    return text.strip().splitlines()[-1] if text.strip() else ""
