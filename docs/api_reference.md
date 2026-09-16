# ADB Visual Tool - API / 接口文档

> 本文档按分层顺序描述所有**对外**公开 API（类、方法、信号、回调契约）。UI 控件的内部私有方法不在此列，详见 `module_design.md`。
>
> 索引：
> 1. core/utils.py
> 2. core/config.py
> 3. core/adb_client.py (AdbClient)
> 4. services/device_service.py (DeviceService / DeviceInfo)
> 5. services/file_service.py
> 6. services/terminal_service.py
> 7. services/scrcpy_service.py (ScrcpyService)
> 8. services/logcat_service.py (LogcatService)
> 9. ui/panels 对外契约 (TerminalTab / FileExplorer / ScrcpyControlPanel / LogcatPanel / DockPanelManager)
> 10. ui/main_window.py (AdbTool)
> 11. 模块间数据流总图

---

## 1. core/utils.py

模块：[utils.py](file:///d:/testpy/adbtools/adbtools/core/utils.py)

### 1.1 常量

```python
COLOR_DEFAULT = "#d4d4d4"
COLOR_PROMPT  = "#569cd6"
COLOR_SYSTEM  = "#dcdcaa"
COLOR_ERROR   = "#f44747"
COLOR_SUCCESS = "#4CAF50"
```
**说明**：唯一颜色字面值来源；UI 层禁止在代码中直接写 `"#xxxxxx"` 颜色字符串。

### 1.2 函数

| 函数 | 签名 | 说明 |
|---|---|---|
| `start_worker` | `(worker: QThread) -> None` | **唯一**允许的 QThread 启动方式。加入全局 `_workers` 防 GC；finished 后自动 `deleteLater`。 |
| `safe_is_running` | `(worker: Optional[QThread]) -> bool` | 防御式判断 QThread 是否运行；已析构的 C++ 对象不会抛 RuntimeError。 |
| `get_startup_info` | `() -> subprocess.STARTUPINFO` | Windows 下设置 `STARTF_USESHOWWINDOW` 隐藏黑框，其他系统空对象。 |
| `decode_bytes` | `(raw: bytes) -> str` | UTF-8 解码 → 失败回退 GBK (errors=replace)。 |
| `extract_rate_summary` | `(text: str) -> str` | 取最后一个非空行；用于 `adb pull/push` 的输出摘要。 |
| `format_size` | `(size_bytes: int) -> str` | **v2.2 修正为五档**：`B / KB / MB / GB / TB` 自适应，1 位小数。阈值 `<1024 / <1024² / <1024³ / <1024⁴ / else`。⚠️ v2.1 曾缺少 GB 分支导致 TB 错标为 GB，已修复。 |

---

## 2. core/config.py

模块：[config.py](file:///d:/testpy/adbtools/adbtools/core/config.py)

### 2.1 类型

```python
Command = Dict[str, str]   # 键: name (str), cmd (str)
```

### 2.2 常量

```python
CONFIG_FILE: str            # 路径: ~/.adb_visual_cmds.json
DEFAULT_COMMANDS: List[Command]
```

### 2.3 函数

| 函数 | 签名 | 返回 | 错误策略 |
|---|---|---|---|
| `load_commands` | `() -> List[Command]` | 读 JSON 或返回 `DEFAULT_COMMANDS` 副本 | 文件缺失 / JSON 损坏 → 回退默认，不抛 |
| `save_commands` | `(commands: List[Command]) -> bool` | 是否写入成功 | `OSError` → 返回 `False`，不抛 |

---

## 3. core/adb_client.py

模块：[adb_client.py](file:///d:/testpy/adbtools/adbtools/core/adb_client.py)

### 3.1 常量

```python
IP_PORT_RE: re.Pattern     # 匹配 192.168.0.10:5555
```

### 3.2 类 `AdbClient`

```python
class AdbClient:
    def __init__(self, serial_getter: Optional[Callable[[], Optional[str]]] = None) -> None: ...

    # 属性
    @property
    def serial(self) -> Optional[str]: ...
    adb_path: str                       # 解析后的 adb 可执行绝对路径（或字符串 "adb"）
    adb_home: Optional[str]             # adb 所在目录（作为 subprocess cwd）

    # — 设备管理 —
    def list_devices(self) -> Tuple[List[Tuple[str, str]], str]: ...
    def connect(self, target: str) -> Tuple[bool, str]: ...
    def get_device_info(self, serial: str) -> Tuple[Dict[str, str], str]: ...

    # — 文件查询 —
    def list_dir(self, path: str, timeout: int = 15) -> Tuple[List[Dict[str, Any]], str]: ...
    def find_files(
        self,
        root: str,
        keyword: str,
        max_results: int = 500,
        timeout: int = 30,
    ) -> Tuple[List[Dict[str, Any]], str, bool]: ...  # v2.2 新增

    # — 文件传输命令构造 —
    def build_pull_cmd(self, remote_path: str, local_path: str) -> List[str]: ...
    def build_push_cmd(self, local_path: str, remote_path: str) -> List[str]: ...
    def run_transfer(self, transfer_cmd: List[str]) -> Tuple[bool, str]: ...

    # — Shell 短命令（同步阻塞，UI 层应在 <1s 场景使用） —
    def run_shell_blocking(self, shell_cmd: str) -> None: ...

    # — 终端 QProcess 命令构造 —
    def build_terminal_args(self, cmd_str: str) -> Tuple[str, List[str]]: ...

    # — scrcpy 发现 & 组装 —
    @staticmethod
    def find_scrcpy(cmd_parts: List[str]) -> Optional[str]: ...
    def build_scrcpy_cmd(self, cmd_parts: List[str]) -> Optional[List[str]]: ...
```

#### 方法详解

| 方法 | 参数语义 | 返回值 | 抛出 |
|---|---|---|---|
| `list_devices()` | - | `([(serial, state), ...], status_msg)`；`state` 通常为 `device/offline/unauthorized`；`status_msg` 为空表示正常，否则为中文提示（无设备/未授权等） | 不抛；内部异常 → `([], reason)` |
| `connect(target)` | `target` 形如 `192.168.1.10:5555` | `(ok, message)`；message 含中文说明 | 不抛 |
| `get_device_info(serial)` | 目标设备 serial；内部临时改写 `serial_getter` 拉取 | `(info_dict, msg)`；`info_dict = {serial, model, android_version, root_state}`，失败字段为空串，`root_state` 取值为 `"已Root"`/`"未Root"`/`""` | 不抛（三条 `adb shell getprop/which su` 各 5s 超时，失败降级为空串） |
| `list_dir(path, timeout=15)` | `path` 无需 `/` 结尾，内部自行 ls | `(items, error_msg)`；`items[i] = {name: str, is_dir: bool, perms: str, size: str}`；`error_msg` 非空代表失败 | 不抛 |
| `find_files(root, keyword, max_results=500, timeout=30)` | **v2.2 新增**。`root` 搜索起点（传 `"/"` 走根目录全盘模式并自动排除虚拟目录）；`keyword` 子串关键词（grep -i 大小写不敏感）；`max_results` 结果截断阈值；`timeout` 总超时秒数。 | `(results, error, truncated)` 三元组：`results[i] = {path: str, name: str, is_dir: bool}`（is_dir 通过批量 shell 判断）；`error` 非空代表失败（中文说明）；`truncated=True` 代表命中 `max_results+1` 条后被 `head` 截断，实际结果可能更多。 | 不抛；所有 adb 调用异常均包装为 `( [], msg, False)` 返回。 |
| `build_pull_cmd(r,l)` | remote + local 绝对路径 | 完整 argv（含 `adb -s <serial> pull r l`） | 无 |
| `build_push_cmd(l,r)` | 同上 | 同上 | 无 |
| `run_transfer(cmd)` | `cmd` 为 `build_*_cmd` 产物 | `(ok, summary)`；`summary` 为 stdout/stderr 最后一行（速率摘要）。**v2.2 补充**：调用方必须确保 `subprocess.run` 传入 `encoding='utf-8', errors='replace'`（AdbClient 内部已保证）。 | 不抛 |
| `run_shell_blocking(scmd)` | `adb shell <scmd>`；例如 `mv a b` / `rm -rf x` | None。**v2.2 行为变更**：stdout/stderr 全部重定向到 `subprocess.DEVNULL`，避免输出泄漏到终端 Tab；需回显场景请走 TerminalService 通路。 | `FileNotFoundError` / `subprocess.CalledProcessError` —— UI 层需 catch 弹 warning |
| `build_terminal_args(cmd_str)` | 允许前缀 `adb `（会剥掉）；单传 `shell` 会补 `-t -t` | `("adb", args)` 直接喂 `QProcess.start` | 不抛 |
| `find_scrcpy(cmd_parts)` | `cmd_parts[0]` 是 `scrcpy` 或自定义路径 | scrcpy exe 绝对路径，找不到 → None | 不抛 |
| `build_scrcpy_cmd(cmd_parts)` | 同上 | `[scrcpy_path, -s, serial, *rest]`；找不到 → None | 不抛 |

---

## 4. services/device_service.py

模块：[device_service.py](file:///d:/testpy/adbtools/adbtools/services/device_service.py)

### 4.1 数据类 `DeviceInfo`（dataclass）

```python
@dataclass
class DeviceInfo:
    serial: str
    state: str
    model: str = ""
    android_version: str = ""
    root_state: str = ""

    def __iter__(self): ...               # 向后兼容 (serial, state) 元组解包
    def display_text(self) -> str: ...     # 下拉框文本："model (serial) Android ver"
```

**说明**：v2.1 引入；通过 `__iter__` 让旧的 `(serial, state) = info` 解包代码继续工作。

### 4.2 QThread 子类型（对外仅作信号形态声明）

```python
class DeviceRefreshWorker(QThread):
    devices_found = pyqtSignal(list, str)   # (List[DeviceInfo], status_msg)

class AdbConnectWorker(QThread):
    connect_done = pyqtSignal(bool, str)    # (success, message)
```

> **破坏性变更**：`devices_found` 信号从 `pyqtSignal(list)` 改为 `pyqtSignal(list, str)`；list 元素从元组升级为 `DeviceInfo`（仍兼容元组解包）。回调签名也同步带 `message` 参数。

### 4.3 类 `DeviceService`

```python
class DeviceService:
    def __init__(self, adb_client: AdbClient) -> None: ...

    # — 回调设置（一次性，在主窗口 __init__ 中调用） —
    def set_refresh_callback(self, cb: Callable[[list, str], None]) -> None: ...
    def set_connect_callback(self, cb: Callable[[bool, str], None]) -> None: ...

    # — 设备元数据缓存 —
    def get_device_info(self, serial: str, fetch_if_missing: bool = True) -> Optional[DeviceInfo]: ...
    def invalidate(self, serial: Optional[str] = None) -> None: ...

    # — 业务操作（异步，完成通过上面回调通知） —
    def refresh_devices(self) -> None: ...
    def connect_network_device(self, target: str) -> None: ...
```

**回调契约**：
- `refresh_cb(devices: List[DeviceInfo], message: str)` 在 UI 线程（通过 pyqtSignal）触发
- `connect_cb(success: bool, message: str)` 同上

**`get_device_info` 行为**：
- 命中缓存（`_cache[serial]`）直接返回，不触发子进程
- `fetch_if_missing=False` 时仅查缓存，未命中返回 `None`（用于状态栏快速查询，不阻塞 UI）
- `fetch_if_missing=True` 时未命中会同步调用 `AdbClient.get_device_info` 并写入缓存

**`invalidate` 行为**：传 `serial` 失效单台；传 `None` 清空整个 `_cache`。设备断开 / 重新连接后应调用。

---

## 5. services/file_service.py

模块：[file_service.py](file:///d:/testpy/adbtools/adbtools/services/file_service.py)

### 5.1 QThread 子类型

```python
class AdbTransferWorker(QThread):
    finished = pyqtSignal(str, bool, str)    # (file_path, success, summary)

class PullAndDragWorker(QThread):
    pull_done = pyqtSignal(str, bool, str)   # (local_tmp_path, success, summary)

class DirLoadWorker(QThread):
    load_done = pyqtSignal(list, str)        # (items[], error_msg)
    def cancel(self) -> None: ...            # 设置 _cancelled = True
```

### 5.2 类 `FileService`

```python
class FileService:
    def __init__(self, adb_client: AdbClient) -> None: ...

    # — 状态 —
    current_path: str                      # 当前目录，以 / 结尾；默认 /sdcard/

    # — 回调（一次性设置） —
    dir_loaded_cb: Optional[Callable[[list, str], None]]
    transfer_finished_cb: Optional[Callable[[bool, str, bool, str], None]]
        # 签名: (refresh_dir, local_path, success, summary) —— FileService 在 connect 时用 partial 把 refresh 作为位置参数绑定
    pull_for_drag_cb: Optional[Callable[[str, bool, str, str], None]]
        # 签名: (local_tmp_path, success, summary, name)

    get_terminal_cb: Optional[Callable[[], Optional[object]]]  # 已废弃，终端消息统一由 UI widget 自行取

    # — 操作 API —
    def load_directory(self, path: str) -> None: ...            # 异步
    def run_shell_blocking(self, shell_cmd: str) -> None: ...   # 同步
    def download_item(self, name: str, save_path: str) -> None: ...      # 异步；v2.3 可被批量并发调用
    def upload_local_file(self, local_path: str) -> None: ...            # 异步；支持多文件逐个调用并发
    def pull_for_drag(self, name: str) -> Optional[str]: ...             # 异步；返回规划中的 tmp_path（或 None 代表已在跑）
```

#### `transfer_finished_cb` 首参数绑定说明
在 `FileExplorer.__init__` 中通过 `partial` 把 `refresh=True/False` 柯里化，因此 UI 端实际签名为：
```python
def _on_transfer_finished(
    self,
    refresh: bool,
    local_path: str,
    success: bool,
    summary: str
) -> None: ...
```

---

## 6. services/terminal_service.py

模块：[terminal_service.py](file:///d:/testpy/adbtools/adbtools/services/terminal_service.py)

### 6.1 类 `TerminalService(QObject)`

**每个终端 Tab 一个实例**，与一个 QProcess 绑定。

```python
class TerminalService(QObject):
    # pyqtSignals（对外订阅的 UI 事件）
    output_written    = pyqtSignal(str, str)        # text, color(None=默认)
    system_msg        = pyqtSignal(str, str)        # msg, color
    prompt_reset      = pyqtSignal()                # 应打印 prompt
    state_changed     = pyqtSignal(bool)            # is_running
    scrcpy_requested  = pyqtSignal(list)            # 用户在终端输入 scrcpy 命令，转发到 ScrcpyService

    def __init__(self, adb_client: AdbClient) -> None: ...

    # — 生命周期 —
    def bind_process(
        self,
        process: QProcess,
        decoder_out: codecs.IncrementalDecoder,
        decoder_err: codecs.IncrementalDecoder,
    ) -> None: ...

    # — 操作 API —
    def run_command(self, cmd_str: str, from_external: bool = False) -> None: ...
    def run_external_command(self, cmd_str: str) -> None: ...   # 等价 run_command(cmd, from_external=True)
    def send_ctrl_c(self) -> None: ...
    def kill_process(self) -> None: ...
```

#### 行为契约
| 场景 | `run_command` 行为 |
|---|---|
| `cmd_str == ""` 且 Running | `process.write(b'\n')` 模拟回车 |
| `cmd_str == ""` 且 Idle | `prompt_reset.emit()` |
| Running 且 `from_external=True` | 先 `system_msg(cmd_str+'\n', COLOR_SYSTEM)` 回显再 stdin 注入 |
| Idle 且多行命令 | 入 deque 队列，逐条 `_process_next_queue_command` 串行 |
| 命令首段包含 `scrcpy`（忽略大小写） | **不再本地拉起 scrcpy**，改为 `scrcpy_requested.emit(cmd_parts)` 转交上层；`AdbTool._on_terminal_scrcpy_requested` 进一步转给 `ScrcpyService.launch()`，避免重复独立控制台 |

---

## 7. services/scrcpy_service.py

模块：[scrcpy_service.py](file:///d:/testpy/adbtools/adbtools/services/scrcpy_service.py)

### 7.1 类 `ScrcpyService(QObject)`

**单实例**：由 `AdbTool.__init__` 持有，整个应用唯一。负责 scrcpy 进程的启停与生命周期广播。

```python
class ScrcpyService(QObject):
    scrcpy_started  = pyqtSignal()         # 进程已 start（不代表 SDL 窗口已显示）
    scrcpy_finished = pyqtSignal(int)      # exit_code
    scrcpy_error    = pyqtSignal(str)       # 启动失败原因

    def __init__(self, adb_client: AdbClient) -> None: ...

    # — 状态查询 —
    def is_running(self) -> bool: ...

    # — 操作 —
    def launch(self, serial: Optional[str], params: List[str]) -> bool: ...
    def stop(self) -> None: ...
```

#### 行为契约
| 方法 | 行为 |
|---|---|
| `is_running()` | **v2.2 修正**：防御式实现——`self._process is not None and self._process.state() == QProcess.Running`。不可简写，竞态回调可能中途将 `_process` 置 None。 |
| `launch(serial, params)` | 1) 已运行返回 `False`；2) 通过 `AdbClient.find_scrcpy(['scrcpy'] + params)` 解析路径，找不到 → `scrcpy_error.emit(...)` 并返回 `False`；3) 构造 `[scrcpy_path, -s, serial, *params]`（serial 为 None 时跳过 `-s`）；4) `QProcess.start` 后立即 `scrcpy_started.emit()` 并返回 `True`。**serial 由调用方传入**，不读 `adb_client.serial`，便于跨设备调度 |
| `stop()` | **v2.2 重写**：幂等 + 标记 + 彻底清理：1) `if self._stop_requested: return`；2) `self._stop_requested = True`；3) `is_running()` 时 `kill() → waitForFinished(2000)`，若仍 NotRunning 再 `kill() → waitForFinished(500)`；4) `self._process = None` 确保引用清空。 |

**回调契约（v2.2 新增\_stop_requested 语义）**：
- `_on_error`：若 `self._stop_requested` → 直接 return（用户主动 kill() 触发 Crashed 是预期行为，不报错）；否则发 `scrcpy_error`。
- `_on_finished`：若 `self._stop_requested` → `self._process = None` → `scrcpy_finished.emit(exit_code)`（不判定失败）；否则按 exit_code 判断是否启动失败。

**与 TerminalService 的关系**：用户在终端输入 scrcpy 命令 → `TerminalService.scrcpy_requested` → `AdbTool._on_terminal_scrcpy_requested` → `ScrcpyService.launch`。ScrcpyControlPanel 的按钮直接调 `launch`/`stop`，无需经过终端。

---

## 8. services/logcat_service.py

模块：[logcat_service.py](file:///d:/testpy/adbtools/adbtools/services/logcat_service.py)

### 8.1 类 `LogcatService(QObject)`

**单实例**：由 `AdbTool.__init__` 持有。持续抓取 logcat 输出，写本地文件并按级别过滤转发到 UI。

```python
class LogcatService(QObject):
    recording_started = pyqtSignal(str)     # filename (full_path)
    recording_stopped = pyqtSignal(str, int)  # **v2.2 改签名**：(filename, file_size_bytes)；UI 显示保存路径和大小用
    line_received     = pyqtSignal(str, str)  # (level, message)；level 为 V/D/I/W/E/F/S 之一或 ""
    error             = pyqtSignal(str)

    def __init__(self, adb_client: AdbClient) -> None: ...

    # — 状态查询（均为防御式 None 检查，v2.2 加固）—
    def is_recording(self) -> bool: ...        # self._process is not None and state == Running
    def current_filename(self) -> str: ...

    # — 过滤 —
    def set_level_filter(self, levels: Set[str]) -> None: ...

    # — 生命周期 —
    def start_recording(self, serial: str, target_dir: str) -> bool: ...
    def stop_recording(self) -> None: ...
```

#### 行为契约
| 方法 | 行为 |
|---|---|
| `is_recording()` | **v2.2 修正**：`self._process is not None and self._process.state() == QProcess.Running` |
| `current_filename()` | 当前录制中的日志文件全路径；未录制返回空串 |
| `set_level_filter(levels)` | 空 set = 不过滤；非空 = 只转发 `levels` 中的级别。UI 端 checkbox 联动 |
| `start_recording(serial, target_dir)` | 1) 已录制返回 `False`；2) serial 为空 → `error.emit("未选择设备")` 并返回 `False`；3) `os.makedirs(target_dir, exist_ok=True)`；4) 生成 `logcat_YYYYMMDD_HHMMSS.log` 文件名；5) 文件打开失败 → `error.emit(...)` 并返回 `False`；6) **v2.2 新增** `self._decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')`（每次启动重置解码器，避免残留半字节首行乱码）；7) `self._stop_requested = False` 复位标记；8) 启动 `QProcess` 跑 `adb -s <serial> logcat -v time`；9) `recording_started.emit(full_path)` 并返回 `True` |
| `stop_recording()` | **v2.2 修正**：1) `self._stop_requested = True`；2) `if self._process and self._process.state() != QProcess.NotRunning:` → `terminate() + waitForFinished(3000)`；3) 未运行或已结束 → 直接 `_close_file()`；**所有 `_process` 访问前先判 None** |

**输出处理**：`readyRead` 触发时增量解码（UTF-8 + errors='replace'）→ 原始内容写入文件 → 按 `splitlines` 解析每行级别（正则 `^(\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}) +([VDIWEFS])/`，对应 `-v time` 格式）→ 命中过滤的行通过 `line_received.emit(level, line)` 转发。

**退出清理（v2.2 语义）**：
- 无论正常退出/异常/主动 stop，均调 `_close_file()` 关句柄并统计 `file_size`。
- `_on_finished`：若 `_stop_requested` 且文件存在 → `recording_stopped.emit(filename, file_size)`（代表完成）；若异常中断且未请求停止 → 先 `error.emit(...)` 再发 `recording_stopped`。
- 清理末尾：`self._process = None`；`self._stop_requested = False`。

**⚠️ 破坏性变更提示（v2.1 → v2.2）**：`recording_stopped` 信号从 `()` 改为 `(str, int)`。旧槽函数签名若不接受参数会报 `TypeError`，请同步更新 UI 端 `_on_recording_stopped(filename, file_size)`。

---

## 9. UI Panels 对外契约

### 9.1 TerminalTab

模块：[terminal_tab.py](file:///d:/testpy/adbtools/adbtools/ui/panels/terminal_tab.py)

```python
class TerminalTab(QWidget):
    process: QProcess             # 主窗口 closeEvent 会读 .state() == Running 并 kill
    terminal_service: TerminalService

    def __init__(
        self,
        get_serial_cb: Callable[[], Optional[str]],
        terminal_service: TerminalService,
        parent: Optional[QWidget] = None,
    ) -> None: ...

    # — UI 可调用 API —
    def print_system_msg(self, msg: str, color: str = COLOR_SYSTEM) -> None: ...
    def run_external_command(self, cmd_str: str) -> None: ...
    def update_device_label(self, label: str) -> None: ...   # v2.1：刷新 prompt 显示的设备标签
```

**`update_device_label` 契约**：主窗口在设备刷新 / 切换后调用，把 `model Android ver` 字符串注入到 ConsoleEdit prompt，并立即 `reset_prompt` 让新标签可见。

### 9.2 FileExplorer

模块：[file_explorer.py](file:///d:/testpy/adbtools/adbtools/ui/panels/file_explorer.py)

```python
class FileExplorer(QWidget):
    file_service: FileService    # 暴露给 FileTreeWidget 读取 current_path / run_shell_blocking / etc.

    def __init__(
        self,
        file_service: FileService,
        get_current_terminal_cb: Callable[[], Optional[TerminalTab]],
    ) -> None: ...

    # — API —
    def load_directory(self) -> None: ...   # 从 path_input.text() 重新加载；切设备时主窗口直接调
    def reload(self) -> None: ...           # 等价 load_directory；供 tree 内部 rename/delete 后刷新
    def get_current_terminal(self) -> Optional[TerminalTab]: ...
```

### 9.3 DockPanelManager

模块：[dock_panel_manager.py](file:///d:/testpy/adbtools/adbtools/ui/panels/dock_panel_manager.py)

**v2.1 引入**：替代旧的 QTabWidget，用 QDockWidget 提供可拖出独立窗口的标签页外观。

```python
class DockPanelManager(QObject):
    dock_added   = pyqtSignal(QDockWidget)
    dock_removed = pyqtSignal(QDockWidget)

    def __init__(self, main_window: QMainWindow) -> None: ...

    # — 面板生命周期 —
    def add_panel(
        self,
        widget: QWidget,
        title: str,
        area: Qt.DockWidgetArea = Qt.RightDockWidgetArea,
    ) -> QDockWidget: ...
    def remove_panel(self, dock: QDockWidget) -> None: ...

    # — 查询 —
    def all_docks(self) -> List[QDockWidget]: ...
    def current_dock(self) -> Optional[QDockWidget]: ...     # 近似当前活动 dock
    def find_dock_by_widget_type(self, widget_type: type) -> Optional[QDockWidget]: ...
```

**`add_panel` 行为**：
1. 新建 QDockWidget，设置 `Movable | Closable | Floatable` 三特性
2. `addDockWidget(area, dock)` 加入主窗口
3. 若该 area 已有 dock，`tabifyDockWidget(existing, dock)` 形成标签页外观
4. `dock.show()` + `dock.raise_()` 提升为当前
5. `dock_added.emit(dock)` 通知（main_window 用此订阅 closeEvent 等）

**主窗口调用顺序**：`AdbTool.__init__` 中先创建 `DockPanelManager(self)`，再依次 `add_panel` TerminalTab / ScrcpyControlPanel / LogcatPanel。

### 9.4 ScrcpyControlPanel

模块：[scrcpy_control_panel.py](file:///d:/testpy/adbtools/adbtools/ui/panels/scrcpy_control_panel.py)

```python
class ScrcpyControlPanel(QWidget):
    def __init__(
        self,
        scrcpy_service: ScrcpyService,
        get_serial_cb: Callable[[], Optional[str]],
        parent: Optional[QWidget] = None,
    ) -> None: ...
```

**职责**：投屏启停按钮 + 分辨率 / 音频 / 额外参数配置 UI；按钮直接调 `scrcpy_service.launch / stop`；订阅 `scrcpy_started / finished / error` 信号刷新按钮文案与状态文本。**不直接执行 scrcpy**。

### 9.5 LogcatPanel

模块：[logcat_panel.py](file:///d:/testpy/adbtools/adbtools/ui/panels/logcat_panel.py)

```python
class LogcatPanel(QWidget):
    def __init__(
        self,
        logcat_service: LogcatService,
        get_serial_cb: Callable[[], Optional[str]],
        parent: Optional[QWidget] = None,
    ) -> None: ...
```

**职责**：级别 checkbox（V/D/I/W/E/F）+ 关键字实时过滤 + 录制启停按钮；按钮调 `logcat_service.start_recording(serial, ~/adb_visual_logs)` / `stop_recording`；订阅 `recording_started / stopped / line_received / error` 信号刷新视图。客户端再做关键字二次过滤，避免服务端每键击重传。

### 9.6 FileTreeWidget / ConsoleEdit / CommandManagerDialog

- 三者均是**控件级**，对外 API 主要是 Qt 事件（keyPressEvent / dropEvent / 右键菜单）与内部 UI 交互。
- 对外接口以 Qt 原生信号 + 对 explorer / service 的反向引用为主，具体见 `module_design.md` §3.1 / §3.2 / `command_manager_dialog.py`。

**v2.3 新增**：`FileTreeWidget` 开启 `ExtendedSelection` 多选模式，新增 `download_items(items: list)` 方法用于批量下载多个选中项到同一目录。右键菜单根据 `selectedItems()` 数量智能切换为单选/批量模式。

---

## 10. ui/main_window.py — AdbTool

模块：[main_window.py](file:///d:/testpy/adbtools/adbtools/ui/main_window.py)

```python
class AdbTool(QMainWindow):
    # — 服务对象引用（可注入） —
    adb_client: AdbClient
    device_service: DeviceService
    file_service: FileService
    _scrcpy_service: ScrcpyService       # v2.1
    _logcat_service: LogcatService      # v2.1
    dock_manager: DockPanelManager      # v2.1（替代旧 QTabWidget）

    # — UI 内部状态 —
    custom_commands: List[Command]   # config 加载 & 命令管理对话框读写
    file_explorer: FileExplorer
    status_bar                       # QMainWindow.statusBar() —— v2.1 全局状态栏

    def __init__(self, adb_client: AdbClient) -> None: ...

    # — 可被自动化 / 外部脚本调用的 API —
    def get_current_serial(self) -> Optional[str]: ...
    def get_current_terminal(self) -> Optional[TerminalTab]: ...
    def refresh_devices(self) -> None: ...
    def connect_network_device(self) -> None: ...   # 从 ip_input.text() 读取
    def add_terminal_panel(self) -> TerminalTab: ...     # v2.1：原 add_terminal_tab，改走 DockPanelManager
    def execute_custom_command(self, cmd: str) -> None: ...   # 调当前终端 run_external_command
    def open_command_manager(self) -> None: ...
    def render_command_buttons(self) -> None: ...
    def closeEvent(self, event: QCloseEvent) -> None: ...     # 退出保护

    # — v2.1 新增内部槽（供 service 信号联动） —
    def _on_devices_found(self, devices: list, message: str = "") -> None: ...
    def _on_device_switched(self) -> None: ...
    def _on_terminal_scrcpy_requested(self, cmd_parts: list) -> None: ...
    def _update_status_bar(self, *_args) -> None: ...
    def _sync_terminal_device_labels(self) -> None: ...
```

**v2.1 行为要点**：
- `_on_devices_found` 兼容 `DeviceInfo` 与旧的 `(serial, state)` 元组（通过 `isinstance(info, DeviceInfo)` 判断）
- `_on_terminal_scrcpy_requested` 收到 `cmd_parts` 后取 `cmd_parts[1:]` 作为 params 调 `ScrcpyService.launch`，避免终端通路与按钮通路各起一份 scrcpy
- `_update_status_bar` 由 scrcpy/logcat 的 started/finished/started/stopped 信号驱动刷新，显示「设备 model (serial) Android ver | Root: 已Root | Scrcpy: 运行中 | Logcat: 录制中(logcat_xxx.log)」
- `closeEvent` 遍历 `dock_manager.all_docks()` 收集仍在运行的 TerminalTab，确认退出后 kill

---

## 11. 模块间数据流总图

```
用户点击 [刷新设备]
  └─ AdbTool.refresh_devices()
       └─ device_service.refresh_devices()
            └─ DeviceRefreshWorker.run()
                 ├─ adb_client.list_devices()
                 │    └─ subprocess.check_output(['adb','devices'])
                 └─ 逐台 device_service.get_device_info(serial)  ← 命中缓存或拉取
                 └─ devices_found.emit(List[DeviceInfo], msg)
  └─ AdbTool._on_devices_found(devices, msg)  ← 回调
       ├─ device_combo 填充 display_text()
       └─ file_explorer.load_directory()
            └─ file_service.load_directory("/sdcard/")
                 └─ DirLoadWorker.run()
                      └─ adb_client.list_dir(path)
                           └─ subprocess.check_output(['adb','shell','ls','-l',path])
                      └─ load_done.emit(items, err)
            └─ FileExplorer._on_dir_loaded(items, err)   ← dir_loaded_cb

用户在 ConsoleEdit 回车 scrcpy 命令
  └─ ConsoleEdit.execute_cmd_signal.emit(cmd_str)
       └─ TerminalService.run_command(cmd_str)
            └─ 检测到 scrcpy → scrcpy_requested.emit(cmd_parts)
  └─ AdbTool._on_terminal_scrcpy_requested(cmd_parts)
       └─ scrcpy_service.launch(serial, cmd_parts[1:])
            ├─ adb_client.find_scrcpy(...)
            └─ QProcess.start(scrcpy_path, ['-s', serial, *params])
            └─ scrcpy_started.emit()
  └─ ScrcpyControlPanel._on_started  → 按钮切"关闭投屏"
  └─ AdbTool._update_status_bar       → Scrcpy: 运行中

用户在 LogcatPanel 点 [开始录制]
  └─ LogcatPanel._toggle_recording
       └─ logcat_service.start_recording(serial, ~/adb_visual_logs)
            ├─ open(full_path, 'w')
            └─ QProcess.start(adb_path, ['-s', serial, 'logcat', '-v', 'time'])
            └─ recording_started.emit(full_path)
  └─ LogcatPanel._on_recording_started → 按钮切"停止录制"
  └─ [QProcess 输出] readyRead → _on_output
       ├─ 写文件（原始）
       └─ line_received.emit(level, line)   ← 经级别过滤
            └─ LogcatPanel._on_line_received → 关键字过滤 → 写入 log_view
```

---

## 12. 向后兼容 & 扩展约定

- **新增 service 方法**：保持「命名动词开头 + 返回 `None` + 结果走 callback/signal」模式，避免将来同时存在同步与异步变体导致误用。
- **新增 AdbClient 方法**：必须是「**语义化**」的（例如 `screencap_png(dst:str)` 而不是 `exec_(cmd:list)`），以保证 6 个月后仍能读懂。
- **新增 pyqtSignal 参数**：**追加在最后**，不要插中间；已发布的参数顺序视为契约，变更需版本号升级。
- **所有 UI → services → core 调用链**均可通过替换 `serial_getter` / 注入 Mock 的 `AdbClient` 做单元测试，无需启动 QApplication。

---

## 13. 版本信息 & 变更记录

| 文档版本 | 对应产品版本 | 更新日期 | 更新点摘要 | 触发原因 / 关联任务 |
|---|---|---|---|---|
| v1.0 | v2.0 / v2.1 | — | 初始版本：三层全量 API 契约 + 数据流图 + 兼容性约定 | 项目首次 API 文档化 |
| v1.1 | v2.2 | 2026-08-25 | **Core API**：1) `format_size` 扩展为五档（B→TB）并记录历史 Bug<br>2) `AdbClient` 新增 `find_files(root, keyword, max_results, timeout) -> (results, error, truncated)` 签名与语义<br>3) `run_transfer` 补充 encoding 规范；`run_shell_blocking` 标注 DEVNULL 行为变更<br>**Services API**：4) `ScrcpyService.is_running()` 标注防御式 None 检查；`stop()` 重写语义 + `_stop_requested` 回调契约<br>5) `LogcatService.recording_stopped` 信号破坏性变更签名 `() -> (str, int)`，补充 `_stop_requested`、解码器重置、退出清理流程<br>6) Terminal/Logcat/Scrcpy 三个 `is_*()` 方法均标注防御式 None 检查硬约束 | v2.2 Bug 修复集中上线。触发原因：用户报告停止录制崩溃、录制完成无保存路径、scrcpy 停止误报错误、全盘搜索接口缺失、format_size 超大文件显示异常等问题。**破坏性变更提醒**：已订阅 `recording_stopped` 信号的槽函数必须同步更新签名为 `(filename: str, file_size: int)`。 |
| v1.2 | v2.3 | 2026-09-09 | **Services API**：1) `download_item` / `upload_local_file` 标注可被批量并发调用（每次启动独立 AdbTransferWorker 线程）<br>**UI API**：2) `FileTreeWidget` 新增 `ExtendedSelection` 多选模式 + `download_items(items)` 批量下载方法；3) `FileExplorer` 新增 `_active_transfers` 计数器规范 | 用户要求支持多文件上传 + 多文件下载到本地。 |

