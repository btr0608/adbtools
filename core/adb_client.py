import os
import re
import shlex
import shutil
import subprocess
import sys
from typing import Callable, Dict, List, Optional, Tuple, Any

from .utils import decode_bytes, get_startup_info

IP_PORT_RE = re.compile(r'^\d{1,3}(\.\d{1,3}){3}:\d{1,5}$')


def _candidate_adb_dirs() -> List[str]:
    dirs = []
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(sys.executable)
        dirs.append(exe_dir)
        dirs.append(os.path.join(exe_dir, 'dist'))
        # onefile 模式：PyInstaller 解压到临时目录 _MEIPASS，资源在 _MEIPASS/dist
        if hasattr(sys, '_MEIPASS'):
            dirs.append(sys._MEIPASS)
            dirs.append(os.path.join(sys._MEIPASS, 'dist'))
    core_dir = os.path.dirname(os.path.abspath(__file__))
    pkg_dir = os.path.dirname(core_dir)
    project_root = os.path.dirname(pkg_dir)
    dirs.extend([
        project_root,
        pkg_dir,
        os.path.join(pkg_dir, "dist"),
        os.path.join(pkg_dir, "platform-tools"),
        os.path.join(pkg_dir, "platform-tools", "platform-tools"),
    ])
    seen = set()
    result = []
    for d in dirs:
        try:
            real = os.path.realpath(d)
        except OSError:
            continue
        if not real or real in seen or not os.path.isdir(real):
            continue
        seen.add(real)
        result.append(real)
    return result


def find_adb_binary() -> Tuple[str, Optional[str]]:
    exe_name = "adb.exe" if os.name == 'nt' else "adb"
    for d in _candidate_adb_dirs():
        candidate = os.path.join(d, exe_name)
        if os.path.isfile(candidate):
            return candidate, d
    on_path = shutil.which("adb")
    if on_path:
        return on_path, None
    return "adb", None


class AdbClient:
    def __init__(self, serial_getter: Optional[Callable[[], Optional[str]]] = None):
        self._serial_getter = serial_getter
        self.adb_path, self.adb_home = find_adb_binary()

    @property
    def serial(self) -> Optional[str]:
        return self._serial_getter() if self._serial_getter else None

    def _build_cmd(self, *args: str, serial_override: Optional[str] = None) -> List[str]:
        """构造 adb 命令列表。

        Args:
            *args: adb 子命令及其参数，如 ('shell', 'ls', '/sdcard')。
            serial_override: 可选 — 调用方显式指定 serial。
                传入后跳过 _serial_getter 读取，避免并发场景下的共享状态竞态。
        """
        cmd = [self.adb_path]
        s = serial_override if serial_override is not None else self.serial
        if s:
            cmd.extend(['-s', s])
        cmd.extend(args)
        return cmd

    def list_devices(self) -> Tuple[List[Tuple[str, str]], str]:
        try:
            output = subprocess.check_output(
                [self.adb_path, 'devices'], timeout=10, stderr=subprocess.STDOUT,
                text=True, encoding='utf-8', errors='replace',
                startupinfo=get_startup_info(),
                cwd=self.adb_home,
            )
            devices: List[Tuple[str, str]] = []
            for line in output.strip().splitlines()[1:]:
                parts = line.split()
                if len(parts) >= 2:
                    devices.append((parts[0], parts[1]))
            msg = ""
            if not devices:
                msg = "未检测到设备。请确认：\n1) USB 连接后，手机弹出允许 USB 调试弹窗点击【确定】\n2) 或执行 'adb tcpip 5555' 后使用无线连接"
            elif any(state == "unauthorized" for _, state in devices):
                msg = "检测到设备但未授权【unauthorized】，请在手机上弹出的【允许 USB 调试】对话框点击【允许】。"
            return devices, msg
        except subprocess.TimeoutExpired:
            return [], "adb devices 超时（10s），请尝试在命令行执行：adb kill-server && adb start-server"
        except FileNotFoundError:
            return [], (
                f"未找到 adb 命令。请任选其一解决：\n"
                f"1) 将 adb.exe /  platform-tools 目录加入系统 PATH\n"
                f"2) 直接把 adb.exe 复制到工具目录：{os.path.dirname(os.path.dirname(os.path.abspath(__file__)))}\\dist\\ 下（与程序同目录）"
            )
        except Exception as e:
            return [], f"读取设备列表失败：{str(e)}"

    def connect(self, target: str) -> Tuple[bool, str]:
        """adb connect <ip:port>。

        注意：adb connect 即使连接失败也可能返回退出码 0，
        必须解析输出文本判断真实成败。
        """
        try:
            out = subprocess.check_output(
                [self.adb_path, 'connect', target],
                stderr=subprocess.STDOUT, text=True,
                encoding='utf-8', errors='replace',
                timeout=15, startupinfo=get_startup_info(),
                cwd=self.adb_home,
            )
            text = (out or "").strip()
            low = text.lower()
            if "connected to" in low or "already connected" in low:
                return True, text or f"已连接 {target}"
            return False, text or "连接失败（adb 未返回有效信息）"
        except subprocess.TimeoutExpired:
            return False, "连接超时（15s），请确认设备 IP 可达且手机端无线调试/adb tcpip 5555 已开启"
        except FileNotFoundError:
            return False, "未找到 adb 命令，请参考【刷新设备】的修复建议"
        except subprocess.CalledProcessError as e:
            out_text = ((e.stdout if isinstance(e.stdout, str) else "") or "").strip()
            return False, out_text or str(e)

    def disconnect(self, target: str = "") -> Tuple[bool, str]:
        """adb disconnect [ip:port]；target 为空时断开所有无线设备。"""
        cmd = [self.adb_path, 'disconnect']
        if target:
            cmd.append(target)
        try:
            out = subprocess.check_output(
                cmd, stderr=subprocess.STDOUT, text=True,
                encoding='utf-8', errors='replace',
                timeout=10, startupinfo=get_startup_info(),
                cwd=self.adb_home,
            )
            text = (out or "").strip()
            low = text.lower()
            if "error" in low or "failed" in low or "cannot" in low:
                return False, text or "断开失败"
            return True, text or f"已断开 {target or '所有无线设备'}"
        except subprocess.TimeoutExpired:
            return False, "断开超时（10s）"
        except FileNotFoundError:
            return False, "未找到 adb 命令"
        except subprocess.CalledProcessError as e:
            out_text = ((e.stdout if isinstance(e.stdout, str) else "") or "").strip()
            return False, out_text or str(e)

    _LS_LINE_RE = re.compile(
        r'^([drwxlsStT-]{10})'
        r'\s+(\d+)'
        r'\s+(\S+)'
        r'\s+(\S+)'
        r'\s+(\d+)'
        r'\s+(\w{3})'
        r'\s+(\d{1,2})'
        r'\s+(?:(\d{2}:\d{2})|(\d{4}))'
        r'\s+(.+?)(?:\s*->\s*(.+))?\s*$'
    )

    def list_dir(self, path: str, timeout: int = 15) -> Tuple[List[Dict[str, Any]], str]:
        cmd = self._build_cmd('shell', 'ls', '-l', path)
        try:
            raw = subprocess.check_output(
                cmd, stderr=subprocess.STDOUT, startupinfo=get_startup_info(), timeout=timeout,
                cwd=self.adb_home,
            )
            result = decode_bytes(raw)
            items: List[Dict[str, Any]] = []
            for line in result.splitlines():
                line = line.rstrip('\r')
                if not line or line.startswith("total"):
                    continue
                # 先合并多余空格，解决 Jan  1 双空格对齐问题
                line_clean = ' '.join(line.split())
                m = self._LS_LINE_RE.match(line_clean)
                if m:
                    # 捕获组: 1=perms,2=links,3=owner,4=group,5=size,6=month,7=day,8=time,9=year,10=name,11=target
                    perms = m.group(1)
                    size_str = m.group(5)
                    name = (m.group(10) or '').strip()
                    if not name or name in ('.', '..'):
                        continue
                    is_dir = perms.startswith('d')
                    if perms.startswith('l'):
                        is_dir = True
                    items.append({"name": name, "is_dir": is_dir, "perms": perms, "size": size_str})
                else:
                    # Fallback: 用 split 解析，防止正则漏匹配
                    parts = line.split(maxsplit=7)
                    if len(parts) >= 8:
                        perms = parts[0]
                        if not perms or perms[0] not in 'dl-':
                            continue
                        size_str = parts[4] if len(parts) > 4 and parts[4].isdigit() else "0"
                        name = parts[-1].strip()
                        if name in ('.', '..'):
                            continue
                        is_dir = perms.startswith('d')
                        if perms.startswith('l'):
                            link_parts = name.split(' -> ', 1)
                            name = link_parts[0].strip()
                            is_dir = True
                        items.append({"name": name, "is_dir": is_dir, "perms": perms, "size": size_str})
            return items, ""
        except subprocess.CalledProcessError as e:
            out = ((decode_bytes(e.stdout) if isinstance(e.stdout, (bytes, bytearray)) else str(e.stdout)) or "").strip()
            if "No such file or directory" in out or "Permission denied" in out or out:
                return [], f"无法访问目录: {out or str(e)}"
            return [], f"读取失败: {str(e)}"
        except subprocess.TimeoutExpired:
            return [], "加载超时，请检查设备连接是否稳定"
        except FileNotFoundError:
            return [], "未找到 adb 命令，请参考【刷新设备】的修复建议"
        except Exception as e:
            return [], f"读取失败: {str(e)}"

    def run_transfer(self, transfer_cmd: List[str]) -> Tuple[bool, str]:
        try:
            result = subprocess.run(
                transfer_cmd, capture_output=True, text=True,
                encoding='utf-8', errors='replace',
                startupinfo=get_startup_info(),
                cwd=self.adb_home,
            )
            res_text = f"{(result.stdout or '').strip()}\n{(result.stderr or '').strip()}".strip()
            from .utils import extract_rate_summary
            summary = extract_rate_summary(res_text) or (f"exit_code={result.returncode}" if result.returncode else "完成")
            return result.returncode == 0, summary
        except FileNotFoundError:
            return False, "未找到 adb 命令，请参考【刷新设备】的修复建议"
        except Exception as e:
            return False, str(e)

    # adb push/pull 进度行：[ 45%] /sdcard/xxx
    _ADB_PCT_RE = re.compile(r'\[\s*(\d{1,3})%\s*\]')

    def run_transfer_streaming(
        self,
        transfer_cmd: List[str],
        total_bytes: int = 0,
        on_progress: Optional[Callable[[int, int], None]] = None,
        watch_local_path: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """流式执行 adb push/pull，实时回调 (done_bytes, total_bytes)。

        进度来源（双通道兜底）：
        1. 解析 adb 输出的 `[ NN%]` 百分比行（新版 platform-tools 管道下也会输出）；
        2. 下载时若 adb 缓冲了输出，按本地落盘文件大小轮询（watch_local_path）。
        回调中字节数单调不减。total_bytes 为 0 表示总量未知（如目录递归传输）。

        输出读取使用 4096 字节缓冲（原逐字节 read(1) 在大文件传输时是瓶颈），
        缓冲中扫描 \\r / \\n 分隔符拼接完整行后再处理。
        """
        import threading
        from .utils import extract_rate_summary

        proc = None
        try:
            proc = subprocess.Popen(
                transfer_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                encoding='utf-8', errors='replace',
                startupinfo=get_startup_info(),
                cwd=self.adb_home,
            )
        except FileNotFoundError:
            return False, "未找到 adb 命令，请参考【刷新设备】的修复建议"
        except Exception as e:
            return False, str(e)

        stop_event = threading.Event()
        state = {"done": 0}

        def _emit(done: int):
            done = max(0, int(done))
            if total_bytes:
                done = min(done, total_bytes)
            if done > state["done"]:
                state["done"] = done
                if on_progress:
                    on_progress(done, total_bytes)

        # 通道 2：本地落盘文件增长轮询（仅下载、总量已知时）
        if watch_local_path and total_bytes > 0:
            def _watch_growth():
                while not stop_event.is_set():
                    try:
                        size = os.path.getsize(watch_local_path)
                        if size > 0:
                            _emit(size)
                    except OSError:
                        pass
                    stop_event.wait(0.25)

            threading.Thread(target=_watch_growth, daemon=True).start()

        # 通道 1：缓冲读取（4096 字节），扫描 \r / \n 分隔符
        lines: List[str] = []
        buf = ""
        try:
            while True:
                chunk = proc.stdout.read(4096)
                if chunk == "":
                    break
                buf += chunk
                # 从 buf 中切出完整行（\r\n / \n / \r 都算分隔符）
                while buf:
                    idx = -1
                    for sep in ('\r', '\n'):
                        i = buf.find(sep)
                        if i >= 0 and (idx == -1 or i < idx):
                            idx = i
                    if idx == -1:
                        break  # 没有完整行，等下一个 chunk
                    line = buf[:idx].strip()
                    # 跳过 \n 或 \r\n 的第二个分隔符
                    sep_char = buf[idx]
                    buf = buf[idx + 1:]
                    if sep_char == '\r' and buf.startswith('\n'):
                        buf = buf[1:]
                    if line:
                        lines.append(line)
                        m = self._ADB_PCT_RE.search(line)
                        if m and total_bytes > 0:
                            _emit(int(total_bytes * int(m.group(1)) / 100))
        finally:
            proc.wait()
            stop_event.set()

        if total_bytes > 0 and proc.returncode == 0:
            _emit(total_bytes)

        res_text = "\n".join(lines)
        summary = extract_rate_summary(res_text) or (
            f"exit_code={proc.returncode}" if proc.returncode else "完成"
        )
        return proc.returncode == 0, summary

    def get_storage_usage(self, path: str = "/sdcard", timeout: int = 10) -> Tuple[bool, int, int, int]:
        """查询指定路径所在分区容量：返回 (ok, used_pct, used_kb, total_kb)。

        使用 `df -Pk`（POSIX 固定列），兼容 Android toybox；失败返回 (False, 0, 0, 0)。
        """
        cmd = self._build_cmd('shell', 'df', '-Pk', path)
        try:
            raw = subprocess.check_output(
                cmd, stderr=subprocess.STDOUT, timeout=timeout,
                startupinfo=get_startup_info(), cwd=self.adb_home,
            )
            text = decode_bytes(raw)
            lines = [l for l in text.splitlines() if l.strip()]
            for line in lines[1:]:  # 跳过表头
                parts = line.split()
                if len(parts) >= 6 and parts[4].endswith('%'):
                    total_kb = int(parts[1])
                    used_kb = int(parts[2])
                    used_pct = int(parts[4].rstrip('%'))
                    if total_kb > 0:
                        return True, used_pct, used_kb, total_kb
            return False, 0, 0, 0
        except Exception:
            return False, 0, 0, 0

    def build_pull_cmd(self, remote_path: str, local_path: str) -> List[str]:
        return self._build_cmd('pull', remote_path, local_path)

    def build_push_cmd(self, local_path: str, remote_path: str) -> List[str]:
        return self._build_cmd('push', local_path, remote_path)

    def run_shell_blocking(self, shell_cmd: str) -> Tuple[bool, str]:
        """执行 adb shell 命令（静默模式）。返回 (ok, message)。

        注意：此方法同步阻塞，仅应在后台线程/QThread 中调用，禁止在主线程使用。
        """
        cmd = self._build_cmd('shell', shell_cmd)
        try:
            subprocess.run(
                cmd, check=True,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                startupinfo=get_startup_info(), cwd=self.adb_home,
            )
            return True, ""
        except subprocess.CalledProcessError as e:
            return False, f"命令退出码 {e.returncode}"
        except subprocess.TimeoutExpired:
            return False, "命令超时"
        except Exception as e:
            return False, str(e)

    def run_shell_capture(self, shell_cmd: str, timeout: int = 15) -> Tuple[bool, str]:
        """执行 adb shell 命令并返回 (ok, output_text)，失败时 output 包含错误信息。"""
        cmd = self._build_cmd('shell', shell_cmd)
        try:
            result = subprocess.run(
                cmd, check=True, capture_output=True, text=True,
                encoding='utf-8', errors='replace', timeout=timeout,
                startupinfo=get_startup_info(), cwd=self.adb_home,
            )
            return True, (result.stdout or "").strip()
        except subprocess.CalledProcessError as e:
            out = (e.stdout or "") + (e.stderr or "")
            return False, out.strip() or str(e)
        except subprocess.TimeoutExpired:
            return False, f"命令超时（>{timeout}s）"
        except FileNotFoundError:
            return False, "未找到 adb 命令"
        except Exception as e:
            return False, str(e)

    def find_files(
        self,
        root: str,
        keyword: str,
        max_results: int = 500,
        timeout: int = 30,
    ) -> Tuple[List[Dict[str, Any]], str, bool]:
        """全盘 find 搜索文件。

        为兼容 Android toybox find / 不同 shell 环境：
        - 不用 find -name 通配符（adb shell 引号转义易失效）
        - 改用 `find {root} ... 2>/dev/null | grep -i {kw} | head`
        - 全盘搜索（根目录）默认排除 /proc /sys /dev /acct /cgroup /config 等虚拟目录，避免无权限错误和卡顿
        - 搜索结果通过 `[ -d path ]` shell 测试批量判断 is_dir

        返回 (results, error, truncated)。
        results 每项包含 {path, name, is_dir}。
        """
        keyword = keyword.strip()
        if not keyword:
            return [], "关键词为空", False
        # grep 关键词转义单引号
        safe_kw = keyword.replace("'", "'\\''")

        # 全盘搜索（根目录 / ）：加 prune 排除系统虚拟目录，提速 + 减少权限错误
        if root == "/":
            prune_dirs = "/proc /sys /dev /acct /cgroup /config /d /debug_ramdisk /devcfg /firmware /mnt/expand /apex /data/vendor/var/run"
            prune_expr = ' '.join(
                f"-path {d} -prune -o" for d in prune_dirs.split()
            )
            shell_cmd = (
                f"find / {prune_expr} -print 2>/dev/null "
                f"| grep -i '{safe_kw}' "
                f"| head -n {max_results + 1}"
            )
        else:
            shell_cmd = (
                f"find {root} 2>/dev/null "
                f"| grep -i '{safe_kw}' "
                f"| head -n {max_results + 1}"
            )
        cmd = self._build_cmd('shell', shell_cmd)
        try:
            raw = subprocess.check_output(
                cmd, stderr=subprocess.STDOUT, startupinfo=get_startup_info(),
                timeout=timeout, cwd=self.adb_home,
            )
            output = decode_bytes(raw)
        except subprocess.TimeoutExpired:
            return [], "搜索超时（>30秒），建议缩小搜索范围到 /sdcard", False
        except FileNotFoundError:
            return [], "未找到 adb 命令，请参考【刷新设备】的修复建议", False
        except subprocess.CalledProcessError as e:
            out = ((decode_bytes(e.stdout) if isinstance(e.stdout, (bytes, bytearray)) else str(e.stdout)) or "").strip()
            return [], f"搜索失败: {out or str(e)}", False
        except Exception as e:
            return [], f"搜索失败: {str(e)}", False

        # 过滤掉常见的 "Permission denied"、"No such file or directory" 这类被合进 stdout 的错误行
        error_suffixes = ("Permission denied", "No such file or directory", "Permission denied", "Read-only file system")
        raw_paths: List[str] = []
        truncated = False
        for idx, line in enumerate(output.splitlines()):
            line = line.rstrip('\r').strip()
            if not line:
                continue
            if any(err in line for err in error_suffixes):
                continue
            if not line.startswith('/'):
                continue  # 路径必须以 / 开头才是有效搜索结果
            if idx >= max_results:
                truncated = True
                break
            raw_paths.append(line)

        # 批量判断 is_dir：在一个 shell 调用里一次性输出 "D\t/path" 或 "F\t/path"，避免多次 adb 往返
        dir_flag_map: Dict[str, bool] = {}
        if raw_paths:
            try:
                # 组装 shell：对每条路径用 test -d 判断，输出前缀标记
                safe_paths = " ".join(f"'{p.replace(chr(39), chr(39)+chr(92)+chr(39)+chr(39))}'" for p in raw_paths[:200])
                if safe_paths:
                    detect_cmd = (
                        f'for p in {safe_paths}; do if [ -d "$p" ]; then printf "D\\t%s\\n" "$p"; '
                        f'else printf "F\\t%s\\n" "$p"; fi; done 2>/dev/null'
                    )
                    check_raw = subprocess.check_output(
                        self._build_cmd('shell', detect_cmd),
                        stderr=subprocess.STDOUT, startupinfo=get_startup_info(),
                        timeout=15, cwd=self.adb_home,
                    )
                    for line in decode_bytes(check_raw).splitlines():
                        line = line.rstrip('\r')
                        if len(line) >= 3 and line[1] == '\t':
                            flag, path = line[0], line[2:]
                            dir_flag_map[path] = (flag == 'D')
            except Exception:
                # 判断失败时降级：全按文件处理，不影响结果返回
                pass

        results: List[Dict[str, Any]] = []
        for line in raw_paths:
            name = os.path.basename(line) or line
            results.append({"path": line, "name": name, "is_dir": dir_flag_map.get(line, False)})
        return results, "", truncated

    def get_device_info(self, serial: str) -> Tuple[Dict[str, str], str]:
        """查询设备元数据：model / android_version / root_state。无状态，失败降级为空串。"""
        info: Dict[str, str] = {"serial": serial, "model": "", "android_version": "", "root_state": ""}
        if not serial:
            return info, "未提供 serial"
        try:
            out = subprocess.check_output(
                self._build_cmd('shell', 'getprop ro.product.model', serial_override=serial),
                stderr=subprocess.STDOUT, timeout=5,
                startupinfo=get_startup_info(), cwd=self.adb_home,
                text=True, encoding='utf-8', errors='replace',
            )
            info["model"] = (out or "").strip()
        except Exception:
            pass
        try:
            out = subprocess.check_output(
                self._build_cmd('shell', 'getprop ro.build.version.release', serial_override=serial),
                stderr=subprocess.STDOUT, timeout=5,
                startupinfo=get_startup_info(), cwd=self.adb_home,
                text=True, encoding='utf-8', errors='replace',
            )
            info["android_version"] = (out or "").strip()
        except Exception:
            pass
        try:
            out = subprocess.check_output(
                self._build_cmd('shell', 'which su', serial_override=serial),
                stderr=subprocess.STDOUT, timeout=5,
                startupinfo=get_startup_info(), cwd=self.adb_home,
                text=True, encoding='utf-8', errors='replace',
            )
            info["root_state"] = "已Root" if (out or "").strip() else "未Root"
        except subprocess.CalledProcessError:
            info["root_state"] = "未Root"
        except Exception:
            pass
        return info, ""

    def build_terminal_args(self, cmd_str: str) -> Tuple[str, List[str]]:
        cmd = cmd_str[4:].strip() if cmd_str.startswith("adb ") else cmd_str
        try:
            args = shlex.split(cmd.replace('\\', '\\\\') if os.name == 'nt' else cmd)
        except ValueError:
            args = cmd.split()
        if len(args) == 1 and args[0] == "shell":
            args = ["shell", "-t", "-t"]
        s = self.serial
        if s and "-s" not in args:
            args = ["-s", s] + args
        return self.adb_path, args

    @staticmethod
    def find_scrcpy(cmd_parts: List[str]) -> Optional[str]:
        scrcpy_exe = cmd_parts[0]
        if os.path.isabs(scrcpy_exe):
            return scrcpy_exe
        if getattr(sys, 'frozen', False):
            base_dir = os.path.dirname(sys.executable)
            # onefile 模式：优先从 _MEIPASS 查找
            if hasattr(sys, '_MEIPASS'):
                frozen_dirs = [sys._MEIPASS, os.path.join(sys._MEIPASS, 'dist')]
                exe_name = "scrcpy.exe" if os.name == 'nt' else "scrcpy"
                for d in frozen_dirs:
                    candidate = os.path.join(d, exe_name)
                    if os.path.exists(candidate):
                        return candidate
        else:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            base_dir = os.path.dirname(base_dir)
        exe_name = "scrcpy.exe" if os.name == 'nt' else "scrcpy"
        # 1. 直接在 base_dir 下查找
        local_exe = os.path.join(base_dir, exe_name)
        if os.path.exists(local_exe):
            return local_exe
        # 2. dist/ 子目录下查找（PyInstaller 打包后布局）
        dist_exe = os.path.join(base_dir, 'dist', exe_name)
        if os.path.exists(dist_exe):
            return dist_exe
        # 3. 搜索含 "scrcpy" 的子文件夹
        try:
            for item in os.listdir(base_dir):
                item_path = os.path.join(base_dir, item)
                if "scrcpy" in item.lower() and os.path.isdir(item_path):
                    possible_exe = os.path.join(item_path, exe_name)
                    if os.path.exists(possible_exe):
                        return possible_exe
        except Exception:
            pass
        return None
