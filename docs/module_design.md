# ADB Visual Tool - 模块详细设计文档

> 本文档对 `core/`、`services/`、`ui/` 每一个模块做类/函数级的职责、状态机、关键算法、交互时序说明。配套 API 列表见 `api_reference.md`。

---

## 1. Core 层详细设计

### 1.1 core/utils.py

**文件**：[utils.py](file:///d:/testpy/adbtools/adbtools/core/utils.py)

#### 职责
- 存放跨层复用的**纯函数**与常量
- 管理全局 QThread 池 (`_workers`)，避免 Worker 被 GC 提前回收

#### 常量
| 名称 | 值 | 用途 |
|---|---|---|
| COLOR_DEFAULT | `#d4d4d4` | 终端默认文字颜色（VS Code 深灰） |
| COLOR_PROMPT | `#569cd6` | 提示符蓝 |
| COLOR_SYSTEM | `#dcdcaa` | 系统通知黄（scrcpy 启动、上传开始等） |
| COLOR_ERROR | `#f44747` | 错误红 |
| COLOR_SUCCESS | `#4CAF50` | 成功绿 |

#### 关键函数

| 函数 | 签名 | 行为 |
|---|---|---|
| `get_startup_info()` | `() -> subprocess.STARTUPINFO` | Windows 下 `STARTF_USESHOWWINDOW`，其他系统空 SI。所有 `subprocess.*` 必传。 |
| `decode_bytes(raw)` | `(bytes) -> str` | UTF-8 解码 → 失败回退 GBK `errors='replace'`。统一 `adb shell ls -l` 等含中文路径的字节流输出。 |
| `extract_rate_summary(text)` | `(str) -> str` | 取 `adb pull/push` 输出最后一非空行，终端消息展示速率摘要。 |
| `format_size(n)` | `(int) -> str` | B/KB/MB/GB/TB 五档自适应 1 位小数。阈值：`<1024` B → `<1024²` KB → `<1024³` MB → `<1024⁴` GB → else TB。文件树「大小」列显示。<br>⚠️ v2.1 曾缺少 GB 分支导致 TB 错标为 GB，v2.2 已修复。 |
| `start_worker(w)` | `(QThread) -> None` | 加入 `_workers` 集合，`finished → discard + deleteLater` 后调用 `w.start()`。**所有 QThread Worker 唯一启动方式。** |
| `safe_is_running(w)` | `(QThread) -> bool` | 包 `try/except RuntimeError`，防御 Qt C++ 对象已被底层析构仍在 Python 侧引用的情况。 |

---

### 1.2 core/config.py

**文件**：[config.py](file:///d:/testpy/adbtools/adbtools/core/config.py)

#### 数据模型

```python
Command = Dict[str, str]   # {"name": str, "cmd": str}
```

- `CONFIG_FILE`: `~/.adb_visual_cmds.json`
- `DEFAULT_COMMANDS`: Root / shell / remount / devices 四条种子命令

#### 关键行为

| 函数 | 失败策略 | 备注 |
|---|---|---|
| `load_commands() -> List[Command]` | 文件缺失 / JSON 损坏 → 返回 `DEFAULT_COMMANDS` 副本 | 每次必返回 list，上层不需要判空 |
| `save_commands(commands) -> bool` | `OSError`（磁盘满/权限）→ 返回 False，不抛 | 由 UI 层决定是否弹 warning |

---

### 1.3 core/adb_client.py

**文件**：[adb_client.py](file:///d:/testpy/adbtools/adbtools/core/adb_client.py)

#### 类：`AdbClient` — ADB 子进程门面（核心中的核心）

##### 构造
```python
AdbClient(serial_getter: Optional[Callable[[], Optional[str]]] = None)
```
- `serial_getter`：动态从 UI 下拉框拿当前选中 serial 的回调。UI 启动后由主窗口覆盖赋值（lambda 闭包）。

##### 内部帮助：`_build_cmd(*args) -> List[str]`
```
['adb'] + (['-s', serial] if serial else []) + args
```
所有对外方法最终都走到这里，serial 注入唯一收口。

##### 对外方法一览（语义分组）

| 分组 | 方法 | 实现 | 异常/返回 |
|---|---|---|---|
| **设备管理** | `list_devices()` | `subprocess.check_output(['adb','devices'], timeout=10, encoding='utf-8', errors='replace')` | 解析首行后；任何异常 → `([], reason)`；同时返回中文状态提示 |
|  | `connect(target)` | `adb connect <target>` 15s 超时 | `(success: bool, message: str)` |
|  | `get_device_info(serial)` | 三条 `run_shell_blocking` 查 `getprop ro.product.model` / `getprop ro.build.version.release` / `which su`；每条 5s 超时 | `(info_dict, msg)`；`info_dict = {serial, model, android_version, root_state}`，失败字段为空串 |
| **文件查询** | `list_dir(path, timeout=15)` | `adb shell ls -l <path>` 后 parse 8 列 | `(items[{'name','is_dir','perms','size'}], error_str)`，链接名截断 ` -> ` 之前 |
|  | `find_files(root, keyword, max_results=500, timeout=30)` | **全盘搜索**：`find {root} ... -prune ... -print 2>/dev/null \| grep -i '{kw}' \| head`。根目录 `/` 默认排除 /proc /sys /dev 等虚拟目录。is_dir 字段通过**批量 shell for 循环 + `[ -d "$p" ]`** 一次 adb 往返判断（前 200 条）。 | `(results, error, truncated)`。`results[i] = {path, name, is_dir}`；`error` 为空代表成功；`truncated=True` 代表超过 `max_results` 被 head 截断。 |
| **传输** | `build_pull_cmd(r,l)` <br> `build_push_cmd(l,r)` <br> `run_transfer(cmd)` | 先 `build_*_cmd` 拿列表；`run_transfer` 用 `subprocess.run(capture_output=True, encoding='utf-8', errors='replace')` 组合 stdout+stderr 最后一行 | 成功返回 `(True, summary)` |
| **shell 短命令** | `run_shell_blocking(shell_cmd)` | `adb shell <shell_cmd>` + `check=True` + `startupinfo`。**stdout/stderr 全部重定向到 `subprocess.DEVNULL`（v2.2 起）**，避免输出泄漏到终端 Tab。 | 失败抛 `subprocess.CalledProcessError`，由 UI 弹 warning |
| **终端长交互** | `build_terminal_args(cmd_str)` | 去掉可选的 `adb ` 前缀；单传 `shell` 补 `-t -t`；**仅当 args 不含 `-s` 且 serial 非空**时前置 `-s <serial>` | 返回 `("adb", args: list)` 给 QProcess.start |
| **scrcpy 发现** | `find_scrcpy(cmd_parts)` <br> `build_scrcpy_cmd(cmd_parts)` | 策略 1：同目录下的 `scrcpy(.exe)`；策略 2：同目录含 "scrcpy" 子文件夹里找；PyInstaller frozen 走 `sys.executable` dir | `None` 代表未找到，上层显示中文引导 |

#### 关键算法：`list_dir` 解析
```
输入行（adb shell ls -l）:
  drwxrwx--x  4 root sdcard_rw     4096 2024-01-02 15:20 Download
  lrwxrwxrwx  1 root root           21 2024-01-01 08:00 sdcard -> /storage/self/primary
解析：
  parts = line.split(maxsplit=7)  # 8 段
  perms = parts[0]
  size_str = parts[4].isdigit() ? parts[4] : "0"
  name = parts[7].rstrip('\r')
  is_dir = perms[0] == 'd' || (perms[0] == 'l' && name.contains(' -> '))
```

---

## 2. Services 层详细设计

### 2.1 services/device_service.py

**文件**：[device_service.py](file:///d:/testpy/adbtools/adbtools/services/device_service.py)

#### 类图

```
DeviceInfo (dataclass)
├─ serial: str
├─ state: str
├─ model: str = ""
├─ android_version: str = ""
├─ root_state: str = ""
├─ __iter__() → yield serial, state     # 向后兼容元组解包
└─ display_text() → "MuMu (127.0.0.1:16384) Android 15"

DeviceService
├─ adb_client: AdbClient      (注入)
├─ _refresh_callback: Optional[Callable[[list, str], None]]
├─ _connect_callback: Optional[Callable[[bool,str], None]]
├─ _cache: Dict[str, DeviceInfo]            # serial → 富化信息
├─ set_refresh_callback(cb)
├─ set_connect_callback(cb)
├─ get_device_info(serial, fetch_if_missing=True) → Optional[DeviceInfo]   # 命中缓存直接返回
├─ invalidate(serial=None)                  # 失效单台或全部
├─ refresh_devices()        → 启动 DeviceRefreshWorker
└─ connect_network_device(target) → 启动 AdbConnectWorker

QThread Workers:
  DeviceRefreshWorker(adb_client, device_service)  → devices_found.emit(List[DeviceInfo], msg)
  AdbConnectWorker     → connect_done.emit(success, message)
```

#### 时序：`refresh_devices`（带富化）

```
AdbTool.refresh_devices()
  └─ refresh_dev_btn.setEnabled(False)
  └─ DeviceService.refresh_devices()
       └─ new DeviceRefreshWorker(adb_client, device_service)
       └─ worker.devices_found → AdbTool._on_devices_found
       └─ start_worker(worker)
            └─ run(): adb_client.list_devices()
                 └─ 对每个 serial 调 device_service.get_device_info(serial, fetch_if_missing=True)
                      └─ 缓存命中直接返回；否则调 adb_client.get_device_info(serial) 并存缓存
                 └─ devices_found.emit(List[DeviceInfo], msg)
AdbTool._on_devices_found(devices):
  └─ combo blockSignals 填 display_text() 再恢复
  └─ _toggle_wireless_input_visibility()   # 有设备时隐藏 IP 输入框
  └─ _sync_terminal_device_labels()        # 注入 model+Android 到所有 TerminalTab 的 prompt
  └─ _update_status_bar()                  # 联动底部状态栏
  └─ FileExplorer.load_directory()
```

---

### 2.2 services/file_service.py

**文件**：[file_service.py](file:///d:/testpy/adbtools/adbtools/services/file_service.py)

#### 类：`FileService` — 文件操作状态容器

##### 状态成员
| 字段 | 类型 | 作用 |
|---|---|---|
| `current_path` | `str` | 当前浏览路径，默认 `/sdcard/`，每次 `load_directory(path)` 规范为 `/` 结尾 |
| `_dir_worker` | `Optional[DirLoadWorker]` | 上一次目录加载请求，新请求需 cancel 并 disconnect |
| `_drag_worker` | `Optional[PullAndDragWorker]` | 拖拽进行中标志；safe_is_running 防止重复拉取 |
| `dir_loaded_cb` / `transfer_finished_cb` / `pull_for_drag_cb` | Callable | 结果回调（注入），FileExplorer 在 `__init__` 中绑定自己的方法 |
| `transfer_started` | `pyqtSignal(str)` | 传输开始时 emit（"上传 xxx.apk" / "下载 xxx"），UI 显示 indeterminate 进度条 |
| `_active_transfers` | `int` | **v2.3 新增**：FileExplorer 中的活跃传输计数器，每次 `_on_transfer_started` 递增，`_on_transfer_finished` 递减，归零时隐藏进度条。支持批量并发传输的进度条管理 |

##### 对外 5 个操作

| 方法 | 行为 |
|---|---|
| `load_directory(path)` | 规范化 `/` 结尾；取消上次 `_dir_worker`；构造新 DirLoadWorker；UI 应先清树 + 禁用刷新按钮 |
| `run_shell_blocking(shell_cmd)` | 透传 AdbClient；rename / delete 同步执行 |
| `download_item(name, save_path)` | build_pull_cmd → AdbTransferWorker → finished → transfer_finished_cb(refresh=False)。**v2.3**：可被 `download_items` 批量调用，每次启动独立 Worker 线程并发执行 |
| `upload_local_file(local_path)` | build_push_cmd → AdbTransferWorker → finished → transfer_finished_cb(refresh=True)。支持 `upload_files` 多选逐个调用并发执行 |
| `pull_for_drag(name) -> local_tmp_path` | pull 到 `tempfile.gettempdir()/name`；finished 走 `pull_for_drag_cb(path,ok,summary,name)` → FileTreeWidget 再 `QDrag` |

#### 状态机：目录加载

```
     Idle ─ load_directory(p) ─▶ Loading
      ▲                          │
      │                          ├── _cancelled = True ─▶ Idle (丢弃结果)
      │                          │
      │                          └── 成功/超时/异常 ─ load_done.emit(items, err) ─▶ Idle
      │                                                                              │
      └──────────────────────── FileExplorer._on_dir_loaded 刷新树 ◀──────────────────┘
```

---

### 2.3 services/terminal_service.py

**文件**：[terminal_service.py](file:///d:/testpy/adbtools/adbtools/services/terminal_service.py)

#### 类：`TerminalService(QObject)` — 单个终端标签状态机

##### 5 个对外信号 (pyqtSignal)

| 信号 | 参数 | 触发时机 |
|---|---|---|
| `output_written` | `(text: str, color: Optional[str])` | QProcess stdout/stderr 到达 |
| `system_msg` | `(msg: str, color: str)` | 外部命令回显 / 强制结束告警等 |
| `prompt_reset` | 无 | 一条命令完成、需要重新打印 `> adb -s xx ` |
| `state_changed` | `(is_running: bool)` | QProcess.stateChanged 转 bool，驱动 kill_btn 显隐 |
| `scrcpy_requested` | `(cmd_parts: list)` | 用户在终端输入 `scrcpy` 开头命令，主窗口转发到 `ScrcpyService` |

##### 绑定 QProcess：`bind_process(process, decoder_out, decoder_err)`
- TerminalTab 在构造后调用一次。内部挂 4 个槽：readyReadSO / readyReadSE / finished / stateChanged
- `codecs.getincrementaldecoder('utf-8')(errors='replace')` 做增量解码，避免 `readAll` 切中 UTF-8 多字节中间致乱码

##### 命令调度核心：`run_command(cmd_str, from_external=False)`

```
if cmd_str == "":
    # v2.2 起：必须先判 self.process is not None，再访问 .state()
    self.process and self.process.state() == Running ? write('\n') : prompt_reset
elif self.process and self.process.state() == Running:
    from_external ? system_msg(cmd_str+'\n', COLOR_SYSTEM)
    process.write((cmd_str + '\n').encode())
else:
    cmds = cmd_str.strip().split('\n')  逐行去空
    cmd_queue.extend(cmds)
    Idle ? _process_next_queue_command(is_first=True) : NOP (下一次 finished 自动接力)
```

**⚠️ v2.2 硬约束**：run_command / send_ctrl_c / kill_process 三个入口所有 `self.process.state()` 访问前必须判 `self.process is not None`。原因：终端 QProcess 在启动失败或刚构造未 bind 时为 None，直接访问 `.state()` 会抛 `AttributeError: 'NoneType' object has no attribute 'state'`。

##### `send_ctrl_c` & `kill_process`（v2.2 加固）
| 方法 | 行为 |
|---|---|
| `send_ctrl_c()` | `if self.process and self.process.state() == QProcess.Running:` → `output_written.emit("^C\n", COLOR_SYSTEM)` → `process.write(b'\x03')`；否则静默 return。 |
| `kill_process()` | 1) `cmd_queue.clear()` 清空后续队列；2) `if self.process and self.process.state() == QProcess.Running:` → `process.kill()`；3) `system_msg.emit("[强制结束] 进程及后续队列已被手动终止！", COLOR_ERROR)`。 |

##### `_process_next_queue_command(is_first, from_external)` 内部分支：

```
cmd_parts = shlex.split(cmd_str)
if cmd_parts[0].lower() contains "scrcpy":
    scrcpy_requested.emit(cmd_parts)   # 转发到上层，prompt_reset + 自触发 finished
    return
program, args = adb_client.build_terminal_args(cmd_str)
process.start(program, args)
```

##### 命令队列状态机（简化）

```
            Idle ─ run_command(多行) ─▶ enqueue → Idle'
             │  ▲
             ▼  │
        Running │ (process finished)
          │    │
          ▼    │
      pop from cmd_queue → process.start → Running
          │
          └── 队列为空 → prompt_reset → Idle
```

---

### 2.4 services/scrcpy_service.py

**文件**：[scrcpy_service.py](file:///d:/testpy/adbtools/adbtools/services/scrcpy_service.py)

#### 类：`ScrcpyService(QObject)` — scrcpy 启停服务

##### 3 个对外信号

| 信号 | 参数 | 触发时机 |
|---|---|---|
| `scrcpy_started` | 无 | `QProcess.start` 调用后立即 emit |
| `scrcpy_finished` | `(exit_code: int)` | scrcpy 退出 |
| `scrcpy_error` | `(msg: str)` | `QProcess.errorOccurred` 触发 |

##### 状态成员
| 字段 | 作用 |
|---|---|
| `_process: Optional[QProcess]` | scrcpy 进程句柄，持久化保存以支持 stop / is_running |
| `_last_cmd: List[str]` | 最近一次启动的完整命令，便于诊断 |
| `_stop_requested: bool` | **v2.2 新增**：区分「用户主动 stop()」与「进程异常崩溃」，避免 kill() 触发的 Crashed 错误被误报。stop() 首行置 True，_on_error / _on_finished 中读取。 |

##### 行为契约

| 方法 | 行为 |
|---|---|
| `is_running() -> bool` | **防御式 None 检查**：`self._process is not None and self._process.state() == QProcess.Running`。不可简写（竞态回调可能中途置 None）。 |
| `launch(serial, params: List[str]) -> bool` | 调 `AdbClient.find_scrcpy` 找 exe → 构造 `[scrcpy_path, -s, serial, *params]` → `QProcess.start` → `scrcpy_started.emit()`；找不到 emit `scrcpy_error` |
| `stop()` | 若已 `_stop_requested` 直接返回（幂等）；`_stop_requested = True`；`is_running()` 时执行 `kill() → waitForFinished(2000)`；若仍 Running 再 kill 一次；最后 `self._process = None` 确保清理。 |

##### 回调分支（v2.2 修正）
| 回调 | 处理逻辑 |
|---|---|
| `_on_finished(exit_code, _exit_status)` | 若 `_stop_requested`：`_process = None` → `scrcpy_finished.emit(exit_code)` 直接返回（不判定启动失败）。否则按 exit_code / _last_cmd 判断是否启动失败 → `scrcpy_error` + `scrcpy_finished`。 |
| `_on_error(_error)` | 若 `_stop_requested`：**直接 return**（用户主动 kill() 触发 Crashed 是正常现象，不要误报）；否则 `scrcpy_error.emit(f"scrcpy 进程错误：{msg}")`。 |

##### 关键决策
- scrcpy 自带 SDL 窗口，QProcess 启动后仍弹独立窗口，**不依赖 `CREATE_NEW_CONSOLE`**。
- `QProcess.finished` / `errorOccurred` 直挂到信号，状态变化由 UI 订阅更新按钮文字。
- **\_stop_requested + 防御式 None 检查是 v2.2 的强制模式**，后续所有 QProcess 长驻服务必须照搬。

---

### 2.5 services/logcat_service.py

**文件**：[logcat_service.py](file:///d:/testpy/adbtools/adbtools/services/logcat_service.py)

#### 类：`LogcatService(QObject)` — logcat 录制服务

##### 4 个对外信号

| 信号 | 参数 | 触发时机 |
|---|---|---|
| `recording_started` | `(filename: str)` | `QProcess.start` 调用后立即 emit |
| `recording_stopped` | `(filename: str, file_size: int)` | **v2.2 改签名**：logcat 进程退出（用户 stop 或异常），携带保存路径与文件大小（字节）。UI 端用于弹"录制完成，保存至 xxx (大小 y.y MB)"。 |
| `line_received` | `(level: str, msg: str)` | `readyReadStandardOutput` 解析每行 |
| `error` | `(msg: str)` | `QProcess.errorOccurred` 触发 |

##### 状态成员
| 字段 | 作用 |
|---|---|
| `_process: Optional[QProcess]` | logcat 进程句柄 |
| `_file` | 本地日志文件句柄，缓冲 1 行即 flush |
| `_current_filename: str` | 当前录制文件完整路径，UI 用于状态栏显示 |
| `_level_filter: Set[str]` | 空 = 不过滤；非空 = 仅写这些级别到文件 |
| `_decoder` | UTF-8 增量解码器（处理多字节边界）。**v2.2 起每次 start_recording 重新实例化**，避免残留半字节致首行乱码。 |
| `_stop_requested: bool` | **v2.2 新增**：同 ScrcpyService，区分主动 stop 与异常崩溃。 |

##### 行为契约

| 方法 | 行为 |
|---|---|
| `is_recording() -> bool` | **防御式 None 检查**：`self._process is not None and self._process.state() == QProcess.Running`。 |
| `current_filename() -> str` | 返回当前录制文件路径（停止后返回空串） |
| `set_level_filter(levels: Set[str])` | 实时调整过滤；空集合 = 全级别 |
| `start_recording(serial, target_dir) -> bool` | 1) 已录制返回 False；2) serial 为空 → error 返回 False；3) `os.makedirs(target_dir, exist_ok=True)`；4) 生成 `logcat_YYYYMMDD_HHMMSS.log` → 打开文件；5) **重置 `_decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')`**（v2.2 新增步骤，必做）；6) 构造 `[adb, -s, serial, logcat, -v, time]` → `QProcess.start` → `recording_started.emit(full_path)` 并返回 True。 |
| `stop_recording()` | **v2.2 修正竞态**：`_stop_requested = True`；`if self._process and self._process.state() != QProcess.NotRunning:` → `terminate()`；必要时 `waitForFinished(3000)`；未运行 → 直接 `_close_file()`。**所有 `_process` 访问前先判 None**。 |

##### `_on_output` 解析逻辑
1. `readAll()` → `_decoder.decode`（增量 UTF-8）
2. 写入文件（原始内容，不过滤）
3. 按行解析 level（首字符 V/D/I/W/E/F/S）。**logcat -v time 格式正则：`^(\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}) +([VDIWEFS])/(.+?)\(\s*\d+\): (.*)$`**（v2.2 补全正则说明）
4. 若 `_level_filter` 非空且 level 不在集合内 → 跳过
5. 否则 `line_received.emit(level, line)`

##### `_on_finished` 清理（v2.2 修正）
1. 调用 `_close_file()` 关文件句柄
2. 计算 `file_size = os.path.getsize(filename)`（文件存在时）
3. **若 `_stop_requested`**：`recording_stopped.emit(filename, file_size)` → 正常完成
4. **若异常退出且 `_current_filename` 非空**：先 `error.emit("录制异常中断")` 再发 stopped 信号（UI 自行决定是否提示失败）
5. `self._process = None` 清理引用
6. `self._stop_requested = False` 复位（下次录制可以重新开始）

##### 关键决策
- 用 `-v time` 让输出带时间戳，便于离线分析
- 文件路径默认 `~/adb_visual_logs/`，自动 makedirs
- 过滤发生在写文件**前**（按级别），UI 端再做关键字内存过滤
- **解码器生命周期绑定录制周期**：每次 start_recording 必须 new 新的 IncrementalDecoder，这是解决"首行乱码"的唯一正确姿势。

---

## 3. UI 层详细设计

### 3.1 ui/widgets/console_edit.py — ConsoleEdit

**文件**：[console_edit.py](file:///d:/testpy/adbtools/adbtools/ui/widgets/console_edit.py)

#### 控件自定义点
- 继承 `QTextEdit`；`setAcceptRichText(False)`, `MaximumBlockCount(10000)`
- `self.input_start`（int）：光标位置，**区分"历史不可编辑区"与"用户输入区"的唯一分隔符**
- `self.history` / `self.history_idx`：命令历史（同 Bash 语义）

#### 关键 keyPressEvent 分支矩阵

| 按键组合 | 行为 |
|---|---|
| Ctrl + C (选中) | `copy()` 默认行为 |
| Ctrl + C (无选中) | `ctrl_c_signal.emit()` → service 写 `b'\x03'` |
| Ctrl + V | 光标在历史区 → 跳 End + paste |
| Backspace / Left / Delete | cursor < input_start 直接 return 吞掉 |
| ↑ (Up) | `history_idx -= 1` → `_replace_current_input` |
| ↓ (Down) | `history_idx += 1` → idx == len → 清空当前输入 |
| Enter / Return | 当前输入入 history（去重）→ 换行 → `execute_cmd_signal.emit(cmd)` |
| Home | 跳到 `input_start`（非文档开头） |
| 其他普通键 | 光标 < input_start 自动跳 End 后再 super() |

#### 方法：`write_output(text, color=None)` — 最常用
实现了「写入输出时不覆盖用户半行输入」的经典 trick：
1. 暂存 `current_input = toPlainText()[input_start:]`
2. `setPosition(input_start, KeepAnchor)` → `removeSelectedText()`
3. 插入彩色 `text`
4. 更新 `input_start`
5. 把 `current_input` 追回到末尾
6. 滚到底

---

### 3.2 ui/widgets/file_tree_widget.py — FileTreeWidget

**文件**：[file_tree_widget.py](file:///d:/testpy/adbtools/adbtools/ui/widgets/file_tree_widget.py)

#### 拖拽算法
```
mousePressEvent: button == Left 记录 drag_start_pos

mouseMoveEvent:
  manhattanLength < startDragDistance → return
  itemAt(pos) == None 或 ".." → return
  terminal ? print "拉取准备..."
  file_service.pull_for_drag(name)
    └─ PullAndDragWorker → pull_for_drag_cb → self.start_drag_after_pull(local_tmp_path, ok, summary, name)

start_drag_after_pull:
  success ?
    ├─ new QDrag(self)
    ├─ QMimeData.setUrls([QUrl.fromLocalFile(local_tmp_path)])
    └─ drag.exec_(CopyAction)   # 阻塞直到用户释放
  :
    terminal print "下载失败"
```

#### 右键菜单（v2.2 重构：层级结构，文件/文件夹上传分离；v2.3 新增：多选批量下载）
**顶层菜单结构**：
- 📤 **上传到设备...**
  - 📄 **文件...** → `QFileDialog.getOpenFileNames`（多选）→ 逐个 `upload_local_file`
  - 📁 **文件夹...** → `QFileDialog.getExistingDirectory` → 单个 `upload_local_file`（`adb push` 原生支持递归目录）

- 选中单文件/目录项时的右键：
  - 📥 下载到本地 → 单文件: `QFileDialog.getSaveFileName` → `download_item`；目录: `getExistingDirectory` → `download_item`
  - ✏️ 重命名 → `RenameDialog` → `run_shell_blocking('mv ...')`
  - 🗑️ 删除 → `QMessageBox.question` → `run_shell_blocking('rm -rf ...')`

- **多选时**（Ctrl+点击 / Shift+点击 选中 2+ 项，v2.3 新增）：
  - 📥 下载 N 项到本地... → `QFileDialog.getExistingDirectory` → 逐个 `download_item(name, save_dir/name)` 并发执行
  - 重命名 / 删除 在多选时隐藏（仅单选可用）

**v2.2 决策**：文件与文件夹上传分为两个独立子菜单项，避免使用 QFileDialog 的"同时选文件和文件夹"模式（该模式在不同平台/Qt 版本下行为不一致）。

**v2.3 决策**：文件树开启 `QTreeWidget.ExtendedSelection` 多选模式，支持 Ctrl+点击（追加/取消单选）和 Shift+点击（范围连选）。多选时右键菜单智能切换为批量操作，单选时保留原有单文件操作（另存为 / 重命名 / 删除）。批量下载选择一个目标目录，所有选中项并发启动独立 `AdbTransferWorker` 线程。

---

### 3.3 ui/panels/terminal_tab.py — TerminalTab

**文件**：[terminal_tab.py](file:///d:/testpy/adbtools/adbtools/ui/panels/terminal_tab.py)

#### 组装关系
```
TerminalTab (QWidget, VBox)
├─ top_layout (HBox)
│    ├─ status_label   ("状态: 待命/运行中...")
│    └─ [stretch]
│    └─ kill_btn   ("✹ 强制结束进程", 仅 Running 时可见)
└─ ConsoleEdit

TerminalTab.__init__:
  ├─ new TerminalService(adb_client)  [每Tab一个]
  ├─ new QProcess(self)
  ├─ terminal_service.bind_process(process, decoder_out, decoder_err)
  ├─ terminal.reset_prompt(get_serial_cb())
  └─ connect 6 个 signal 到 ConsoleEdit / status_label 的 slot
```

#### 回调桥
- 外部（文件浏览器 / 命令按钮）调用 `run_external_command(cmd)` → 内部调 `terminal_service.run_command(cmd, from_external=True)` 做黄色回显

---

### 3.4 ui/panels/file_explorer.py — FileExplorer

**文件**：[file_explorer.py](file:///d:/testpy/adbtools/adbtools/ui/panels/file_explorer.py)

#### 构造回调注入
```python
file_service.dir_loaded_cb        = self._on_dir_loaded
file_service.transfer_finished_cb = self._on_transfer_finished
file_service.pull_for_drag_cb     = tree.start_drag_after_pull
```

#### `_on_dir_loaded(items, error_msg)` — 树渲染
- 清空树；刷新按钮复启
- 有 error_msg → 单顶节点显示 `⚠ ${error_msg}`
- 非根目录首项插 `["..", "Dir", "", ""]`
- 排序规则：文件夹前置（`not is_dir` 0/1），再按 `name.lower()` 字典序
- 图标：`SP_DirIcon` / `SP_FileIcon` / `SP_FileLinkIcon`
- size：`format_size(int(data['size']))` 失败 → 原值展示

#### 搜索框：双模式下拉（v2.2 新增）
FileExplorer 顶栏搜索框左侧有 **模式下拉 QComboBox**，共 2 项（精简后，v2.2 已移除冗余的 /sdcard 全盘选项）：

| 选项 | 实现 | 行为 |
|---|---|---|
| **当前目录过滤** | 纯内存过滤 `tree.findItems(keyword, Qt.MatchContains | Qt.MatchRecursive, 0)` | 即时响应（无 adb 往返），仅在已加载的当前目录树内匹配。空搜索恢复显示全部节点。 |
| **/ 根目录全盘搜索** | 异步调用 `adb_client.find_files("/", keyword, max_results=500, timeout=30)` | 状态栏显示"全盘搜索中..."；完成后 tree 清空并渲染结果（每项含完整路径 + is_dir 图标），双击目录项若为 is_dir 会跳转浏览。超过 500 条时 `truncated=True`，状态栏提示"结果已截断，显示前 500 条"。**搜索命令为 `find / -prune ... -print 2>/dev/null | grep -i kw | head`**，排除 /proc /sys 等虚拟目录。 |

搜索取消（全盘搜索超时前）：FileExplorer 维护 `_search_cancelled: bool` 标记；Worker 完成回调时若已取消则丢弃结果。

---

### 3.5 ui/main_window.py — AdbTool (QMainWindow)

**文件**：[main_window.py](file:///d:/testpy/adbtools/adbtools/ui/main_window.py)

#### 生命周期步骤
```
__init__:
  1. new DeviceService / FileService  → 设置其 callback 绑定本类 _on_xxx
  2. custom_commands = load_commands()
  3. init_device_toolbar(main_layout)   ← 顶栏：📱设备下拉 + IP:Port 输入
  4. new FileExplorer(file_service, get_current_terminal) → 挂 splitter 左
  5. 右面板：命令栏(带滚动) + QTabWidget(Closable + 角按钮"+")
  6. add_terminal_tab()
  7. render_command_buttons()
  8. refresh_devices()   首次自动刷新设备
```

#### 命令按钮渲染：`render_command_buttons`
```
清空 cmd_bar_layout → 遍历 custom_commands:
  btn = QPushButton(name)
  btn.setToolTip(cmd)
  btn.clicked.connect(partial(execute_custom_command, cmd))
  → addWidget
末端 addStretch() 左对齐
```

#### `closeEvent(event)` 收尾（v2.2 加固）
```
扫描所有 Dock（通过 dock_manager.all_docks()）：
  对每个 dock.widget()：
    若 isinstance(w, TerminalTab)：
      # v2.2 修正：必须先判 w.process is not None 再访问 state()
      if w.process is not None and w.process.state() == QProcess.Running:
          running_tabs.append(w)
有 running_tabs → QMessageBox.question 二次确认：
  用户取消 → event.ignore() return
统一遍历 running_tabs：process.kill() + waitForFinished(500)
最后 event.accept()
```

**v2.2 修复点**：
1. **QProcess 导入修正**：`from PyQt5.QtCore import QProcess, Qt`（原错误从 QtWidgets 导入会抛 ImportError）
2. **常量可读性**：使用 `QProcess.Running` 枚举值替代硬编码的数字 `2`
3. **竞态 None 检查**：两处 `w.process.state()` 前先判 `w.process is not None`

#### 状态栏：永久控件署名（v2.2 规范）
- 动态消息（设备状态、传输进度、logcat 录制信息等）走 `statusBar().showMessage(msg, timeout)`（左侧区域，可被覆盖）
- **"by Yxing" 署名**走 `statusBar().addPermanentWidget(QLabel("by Yxing"))`（右侧永久区，不被动态消息覆盖），样式：padding-right: 12px; color: #888; font-size: 12px;

#### CommandManagerDialog 按钮默认启用（v2.2 修复）
自定义命令管理对话框中的「新增」「保存修改」「完成并退出」三个按钮，通过 `dialog_styles.create_primary_button()` 创建时：
- **必须指定 `enabled=True`（默认值）**（原默认值错误为 False，导致按钮全部灰掉无法点击）
- 仅在需要条件激活的场景（如路径输入框为空时禁用"确定"）才显式传 `enabled=False`
- 修复影响范围：不影响其他使用 create_primary_button 并显式设置 enabled 的对话框（路径创建、重命名等）

---

### 3.6 入口 adb_gui_interactive.py

**文件**：[adb_gui_interactive.py](file:///d:/testpy/adbtools/adbtools/adb_gui_interactive.py)

```python
def main():
    sys.excepthook = global_exception_handler   # 全局异常拦截器
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    adb_client = AdbClient(serial_getter=lambda: None)   # 占位，AdbTool 内会覆写
    window = AdbTool(adb_client)
    window.show()
    sys.exit(app.exec_())
```
- 仅 31 行，**永不放业务**

---

## 4. 版本信息 & 变更记录

| 文档版本 | 对应产品版本 | 更新日期 | 更新点摘要 | 触发原因 / 关联任务 |
|---|---|---|---|---|
| v1.0 | v2.0 / v2.1 | — | 初始版本：core / services / UI 三层模块级设计 | 项目首次详细设计文档化 |
| v1.1 | v2.2 | 2026-08-25 | **Core 层**：1) format_size 扩展为 B/KB/MB/GB/TB 五档并记录历史 Bug<br>2) AdbClient 新增 `find_files()` 全盘搜索算法（find+grep+prune+批量 is_dir 判断）语义说明<br>3) `run_shell_blocking` 标注 DEVNULL 静音策略<br>**Services 层**：4) ScrcpyService 增加 `_stop_requested` 标记 + 回调分支矩阵 + 防御式 None 检查<br>5) LogcatService `recording_stopped` 信号改签名（filename + file_size），增加 `_stop_requested`、解码器每次启动重置、\_on_finished 清理流程<br>6) TerminalService run_command/send_ctrl_c/kill_process 三处 `process.state()` 标注 None 检查硬约束<br>**UI 层**：7) FileTreeWidget 右键菜单重构为层级结构（上传→文件/文件夹分离）<br>8) FileExplorer 新增搜索双模式（当前目录内存过滤 + / 根目录全盘搜索）设计<br>9) main_window closeEvent 加固（QProcess 正确导入 + None 检查 + 枚举常量）、状态栏永久控件署名规范<br>10) CommandManagerDialog 按钮 enabled 默认值修复说明 | v2.2 Bug 修复集中上线。触发原因包含：用户报告「停止录制报错」「新增/保存按钮灰掉」「全盘搜不到文件」「文件大小显示错误」「停止录制后不显示保存路径」等 8+ 项问题。代码修复后同步沉淀到设计文档。 |
| v1.2 | v2.3 | 2026-09-09 | **UI 层**：1) FileTreeWidget 开启 `ExtendedSelection` 多选模式，新增 `download_items` 批量下载方法<br>2) 右键菜单智能切换：多选时显示「📥 下载 N 项到本地...」，单选时保留原菜单<br>3) FileExplorer 新增 `_active_transfers` 计数器，`_on_transfer_started` 递增 / `_on_transfer_finished` 递减，归零时隐藏进度条<br>**Services 层**：4) `download_item` / `upload_local_file` 标注可被批量并发调用说明 | 用户要求支持多文件上传终端 + 多文件下载到本地。 |

