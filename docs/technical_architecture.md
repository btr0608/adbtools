# ADB Visual Tool - 技术架构文档

## 1. 总体架构总览

本产品采用 **三层单向依赖 + 服务回调** 架构，自底向上分别为：核心能力层 (core) → 业务服务层 (services) → 图形展示层 (ui)。所有依赖方向严格自下而上，**UI 层绝不可直接调用 subprocess / adb 命令**。

```
┌───────────────────────────────────────────────────────────────────┐
│                        adb_gui_interactive.py                      │
│                      （入口：QApp + 异常钩子 + 组装）              │
└──────────────────────────────┬────────────────────────────────────┘
                               │ 组装 & 注入
┌──────────────────────────────▼────────────────────────────────────┐
│                         UI 层 (ui/)                                │
│  ┌──────────────┐ ┌───────────────┐ ┌──────────────────────────┐ │
│  │ main_window  │ │ panels/       │ │ widgets/                 │ │
│  │ AdbTool      │ │ TerminalTab   │ │ ConsoleEdit              │ │
│  │ (QMainWindow │ │ FileExplorer  │ │ FileTreeWidget           │ │
│  │  + DockManager│ │ LogcatPanel  │ │ CommandManagerDialog     │ │
│  │  + statusBar)│ │ ScrcpyCtrl   │ │                          │ │
│  └──────┬───────┘ │ DockPanelMgr │ └────────────┬─────────────┘ │
│         │ 信号/回调       │ pyqtSignal             │ 用户事件     │
└─────────┼─────────────────┼────────────────────────┼──────────────┘
          ▼                 ▼                        ▼
┌───────────────────────────────────────────────────────────────────┐
│                    业务服务层 (services/)                          │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────┐ │
│  │ device_svc   │ │ file_service │ │ terminal_svc │ │ scrcpy   │ │
│  │ + DeviceInfo │ │ + 3 QThread  │ │ + 5 signal    │ │ _service │ │
│  │ + _cache     │ │ + transfer_  │ │ + scrcpy_req  │ │ + QProc  │ │
│  │ + 2 QThread  │ │   started    │ │               │ ├──────────┤ │
│  └──────┬───────┘ └──────┬───────┘ └──────┬────────┘ │ logcat   │ │
│         │                │                │          │ _service │ │
│         │                │                │          │ + QProc  │ │
│         │                │                │          └────┬─────┘ │
└─────────┼────────────────┼────────────────┼───────────────┼───────┘
          ▼                ▼                ▼               ▼
┌───────────────────────────────────────────────────────────────────┐
│                    核心能力层 (core/)                              │
│  ┌──────────────┐  ┌───────────────┐  ┌────────────────────────┐ │
│  │ utils.py     │  │ config.py     │  │ adb_client.py          │ │
│  │ 工具函数     │  │ 配置持久化    │  │ AdbClient 门面          │ │
│  │ 颜色常量     │  │ JSON读写      │  │ 所有 adb subprocess    │ │
│  │ Worker池     │  │               │  │ scrcpy 路径发现        │ │
│  │ format_size  │  │               │  │ get_device_info        │ │
│  │              │  │               │  │ find_files 全盘搜索    │ │
│  └──────────────┘  └───────────────┘  └────────────────────────┘ │
└───────────────────────────────────────────────────────────────────┘
```

---

## 2. 架构原则

| 编号 | 原则 | 说明 | 违反时的 CI/审查红线 |
|---|---|---|---|
| AR-01 | 单向依赖 | 依赖方向仅为 `ui → services → core`，services 不得 import ui，core 不得 import services/ui | grep 反向 import 立即打回 |
| AR-02 | 无 UI 可测 | core/services 除 QThread/QProcess 信号外，实例化不依赖 QApplication | 新功能必须能在 `pytest` 中独立创建对象 |
| AR-03 | 门面模式 | 所有 adb / subprocess 调用必须经由 `AdbClient`，禁止散落 | `grep -rn "subprocess.run\|check_output" adbtools/` 除 `core/adb_client.py` 外应为 0；scrcpy 启动改用 `QProcess`，不再用 `subprocess.Popen` |
| AR-04 | 异步不阻塞 UI | 任何可能超过 200ms 的操作必须走 QThread Worker 或 QProcess 异步信号 | services 层方法同步返回仅允许 `AdbClient.run_shell_blocking`（短命令）；scrcpy/logcat 用 QProcess 信号驱动 |
| AR-05 | 回调 > 继承 | services 对外暴露接口优先使用「传入 callback / pyqtSignal」，UI 不得通过继承 service 类覆写逻辑 | service 类禁止被 UI 子类化 |
| AR-06 | Dock 优先 | 多面板一律走 `DockPanelManager.add_panel`，禁止再新建 `QTabWidget` | 需要拖出独立窗口的特性才能落地 |

---

## 3. 技术栈选型

| 分类 | 组件 | 版本/说明 | 选择理由 |
|---|---|---|---|
| 语言 | Python | 3.9+ | 项目既有栈，PyInstaller 打包成熟 |
| GUI 框架 | PyQt5 | 5.x（venv 中已安装） | 拖拽 / QProcess / QThread 原生支持，UI 表达力强 |
| 进程 | subprocess + QProcess | 标准库 + Qt | subprocess 用于短时传输/查询；QProcess 用于长交互终端（流式 I/O） |
| 异步模型 | QThread Worker Pool + pyqtSignal | Qt 原生 | 与 Qt event loop 零阻抗匹配，避免 GIL 造成的 UI 死锁 |
| 配置存储 | JSON | `~/.adb_visual_cmds.json` | 跨平台，无需额外依赖 |
| 终端控件 | 自绘 QTextEdit 子类 (ConsoleEdit) | - | 精确控制 prompt、光标历史、ANSI 过滤 |
| 打包 | PyInstaller | 项目已有 `.spec` | 单 exe 分发，`scrcpy.exe` 与主程序同级目录自动发现 |

---

## 4. 运行时部署视图

```
[用户桌面: adb_gui_interactive.exe]
      │
      ├── QApplication (UI Thread, 唯一)
      │     └── AdbTool (QMainWindow)
      │           ├── DeviceService (+ DeviceInfo 缓存)
      │           ├── FileService (信号：目录加载/传输完成/拖拽完成/transfer_started)
      │           ├── ScrcpyService (QProcess + scrcpy_started/finished/error)
      │           ├── LogcatService (QProcess + recording_started/stopped/line_received)
      │           ├── TerminalService × N (每面板一个；信号：输出/状态/提示符/scrcpy_requested)
      │           ├── DockPanelManager (统一管理 dock 注册/移除/查找)
      │           └── statusBar (联动 4 个 service 信号)
      │
      ├── QThread Pool (start_worker / _workers set, 动态增长)
      │     ├── DeviceRefreshWorker    (10s 超时, 一次性, 富化 DeviceInfo)
      │     ├── AdbConnectWorker       (15s 超时, 一次性)
      │     ├── DirLoadWorker × 1      (可 cancel, 目录加载)
      │     ├── AdbTransferWorker × N  (pull/push, 可并行；v2.3 起支持批量多文件并发)
      │     └── PullAndDragWorker × 1  (拖拽前拉取)
      │
      └── 外部进程
            ├── adb.exe                (subprocess + QProcess)
            └── scrcpy.exe (独立 SDL 窗口，由 ScrcpyService 的 QProcess 启动，无 CREATE_NEW_CONSOLE)
```

---

## 5. 关键设计决策

### 5.1 AdbClient 为什么不用单例？
**决策：每个 Service 共享同一个 AdbClient 实例，但通过主窗口显式注入而非全局单例。**
- Rationale：`serial_getter` 是从主窗口 `QComboBox.currentData` 读取，单例会形成隐式依赖，单元测试时难以替换。注入模式下测试可直接 `AdbClient(serial_getter=lambda: "emulator-5554")`。

### 5.2 终端长交互为什么选 QProcess 而不是 subprocess + 线程？
- `QProcess.readyReadStandardOutput` 直接挂到 Qt event loop，避免「子线程读 stdout → 主线程贴 text」的跨线程队列与锁。
- `Ctrl+C` 中断 (`process.write(b'\x03')`) 仅 QProcess 写 stdin 即可完成，subprocess 在 Windows 下 GenerateConsoleCtrlEvent 有句柄继承坑。

### 5.3 TerminalService 为什么一个面板一个实例？
- 多面板互相独立（状态机、QProcess、命令队列、增量解码器），共享实例会造成「面板 A 的 stderr 贴到面板 B」等串扰问题。
- 多面板通过 `MainWindow.get_current_terminal()` 桥接到左侧文件浏览器的消息输出，天然解耦。

### 5.4 ScrcpyService 为什么独立于 TerminalService？
- v2.0 中 scrcpy 启动逻辑埋在 `TerminalService._launch_scrcpy`，句柄用 `subprocess.Popen` 后即丢，无法后续 kill。
- v2.1 抽离 `ScrcpyService`，用 `QProcess` 持久化句柄，支持 `is_running()` / `stop()`；终端输入 `scrcpy` 时 TerminalService 发 `scrcpy_requested(list)` 信号，主窗口转发到 ScrcpyService。
- scrcpy 自带 SDL 窗口，QProcess 启动后仍弹独立窗口，行为不变。

### 5.5 为什么用 QDockWidget 替换 QTabWidget？
- 用户需求：投屏面板要能拖到副屏独立显示，QTabWidget 不支持拖出。
- `QDockWidget` 原生支持 `floating` 属性，拖出即变独立窗口；多个 dock `tabifyDockWidget` 在同一区域堆叠成标签页外观，行为兼容 QTabWidget。
- `DockPanelManager` 统一管理 dock 注册/移除/查找，新面板只需 `add_panel(widget, title)` 即可挂载。

### 5.6 设备元数据缓存放 DeviceService 而非 AdbClient
- AdbClient 必须保持无状态传输层；缓存属业务关注点。
- DeviceService 维护 `_cache: dict[serial, DeviceInfo]`，设备刷新时富化，断开/重连时 `invalidate(serial)` 清缓存。

### 5.7 长生命周期进程（scrcpy/logcat）的主动停止 vs 异常退出区分
**决策：引入 `_stop_requested` 布尔标记，区分「用户主动调用 stop()」和「进程崩溃/异常退出」。**
- Rationale：`QProcess.kill()` 在 Windows 下会触发 `ProcessError.Crashed` 错误信号和非 0 exit_code。若无标记，ScrcpyService/LogcatService 的 `_on_error` 与 `_on_finished` 会误报"进程崩溃/启动失败"。
- 行为：`stop()` 首行置 `_stop_requested = True`；`_on_error` 中若 `_stop_requested` 直接 return；`_on_finished` 中若 `_stop_requested` 跳过启动失败判定，仅发 finished 信号。
- **统一模式**：所有基于 QProcess 的长驻服务（ScrcpyService、LogcatService）均必须实现此标记。

### 5.8 QProcess 引用的防御式 None 检查
**决策：所有访问 `self._process.state()` / `.kill()` / 其他属性前，先判 `_process is not None`。**
- Rationale：竞态条件——`_on_finished` 回调可能在 `stop()` 方法执行过程中将 `_process` 置为 `None`，随后 `stop()` 再访问 `state()` 触发 `AttributeError: 'NoneType' object has no attribute 'state'`。典型触发链路：`stop_recording() → kill() → waitForFinished() → 回调 _on_finished(置None) → 返回后 stop() 再调 state()`。
- **硬约束**：services 层的 `is_running()` / `is_recording()` 必须写成 `self._process is not None and self._process.state() == QProcess.Running`，不可简写。

### 5.9 全盘文件搜索的 find + grep 组合策略
**决策：不使用 `find -name "*.apk"` 通配符，改用 `find ... | grep -i keyword | head` 管道。**
- Rationale：`adb shell` 对命令字符串的多层转义（Python 字符串 → adb 协议 → Android sh）极易导致 `find -name '*keyword*'` 的通配符被吞或提前展开；`find` 裸输出所有路径 + `grep -i` 做关键字匹配语义稳定，且天然支持子串匹配。
- **根目录 `/` 搜索优化**：默认排除 /proc、/sys、/dev、/acct、/cgroup、/config、/apex 等虚拟/伪文件系统，避免大量 `Permission denied` 行与超时；排除路径写死在 `find_files` 方法中。
- **is_dir 批量判断**：搜索结果的文件/目录属性，通过单次 `adb shell for p in ...; do [ -d "$p" ] ... done` 批量判断，而非每一条一次 adb 往返（默认最多处理前 200 条，避免 shell 命令行过长）。

### 5.10 format_size 的五档单位换算
**决策：format_size 必须实现 B → KB → MB → GB → TB 完整五档，阈值按 1024 的幂次。**
- 历史问题：v2.1 初版缺少 GB 分支（1024³），导致 ≥1GB 的文件直接进入 1024⁴ 分支并错误冠以 "GB" 后缀，2TB 文件显示为 "1.95 GB"。
- 现行实现：四段 `elif`，阈值依次 `<1024`、`<1024²`、`<1024³`、`<1024⁴`，最后 `else` 为 TB。

### 5.11 subprocess 输出编码统一规则
**决策：所有 `subprocess.*` 调用（含 `check_output` / `run` / `Popen`）必须显式指定。**
- `text=True` 时：`encoding='utf-8', errors='replace'`
- 二进制模式（`check_output` 拿 bytes）：后续统一走 `core.utils.decode_bytes(raw)` 做 UTF-8 → GBK 回退解码
- Rationale：中文 Windows 默认 shell code page 为 GBK（936），adb 输出含中文路径时 `text=True` 用默认 locale 解码会抛 `UnicodeDecodeError`；`errors='replace'` 保证最坏情况下不中断流程。

### 5.12 run_shell_blocking 的 stdout/stderr 静音策略
**决策：`AdbClient.run_shell_blocking()` 将 stdout/stderr 均重定向至 `subprocess.DEVNULL`。**
- Rationale：该方法用于 rename / delete / mkdir 等短命令，无需回显；若不重定向，其输出会泄漏到当前终端 Tab 的 stdout 造成用户困惑（例如 `mv` 静默成功不应在终端多出空行）。需回显的场景应走 `TerminalService.run_external_command` 或 `build_terminal_args` + QProcess 通路。

### 5.13 Logcat 增量解码器每次启动重置
**决策：`LogcatService.start_recording()` 必须重新实例化 `codecs.getincrementaldecoder('utf-8')(errors='replace')`。**
- Rationale：若复用上次录制的解码器对象，其内部可能残留上一次末尾未完整消费的半字节（UTF-8 多字节序列中间截断），导致新录制的第一行出现乱码（常见如 `"锘` 开头）。解码器是"有状态"对象，必须按录制生命周期独立分配。

### 5.14 批量并发传输的活跃计数器（v2.3 新增）
**决策：FileExplorer 维护 `_active_transfers: int` 计数器，`_on_transfer_started` 递增、`_on_transfer_finished` 递减，仅当计数归零时才隐藏进度条。**
- Rationale：多文件批量上传/下载时，每个文件启动独立 `AdbTransferWorker` 线程并发执行。若沿用"单次传输完成即隐藏进度条"的旧逻辑，第一个文件完成时进度条就会消失，而后续文件仍在传输中，导致进度条闪烁、用户体验混乱。
- 行为：计数器使用 `max(0, count - 1)` 防止负值；归零时同时重置 `setRange(0, 100)` 并 `setVisible(False)`。

---

## 6. 模块边界与通信契约汇总

| 调用者 | 被调用者 | 通信方式 | 方向 |
|---|---|---|---|
| AdbTool | DeviceService | 注入 refresh/connect callback；service 内部走 Worker 信号 | ↓ |
| AdbTool | FileService | 设置 `dir_loaded_cb / transfer_finished_cb / pull_for_drag_cb` + 接 `transfer_started` 信号 | ↓ |
| AdbTool | ScrcpyService | 注入 adb_client；接 `scrcpy_started/finished/error` → 状态栏 | ↓ |
| AdbTool | LogcatService | 注入 adb_client；接 `recording_started/stopped/line_received` → 状态栏 | ↓ |
| AdbTool | DockPanelManager | `add_panel(widget, title)` / `find_dock_by_widget_type` | ↓ |
| TerminalTab | TerminalService | 5 个 pyqtSignal（output_written / system_msg / prompt_reset / state_changed / scrcpy_requested） | ↓ |
| TerminalTab | ConsoleEdit | `set_device_label(str)` 注入 model + Android 版本 | ↓ |
| ScrcpyControlPanel | ScrcpyService | `launch(serial, params)` / `stop()` / `is_running()` | ↓ |
| LogcatPanel | LogcatService | `start_recording(serial, dir)` / `stop_recording()` / `set_level_filter` | ↓ |
| FileExplorer | FileService | `file_service.load_directory / download_item / upload_local_file / pull_for_drag / run_shell_blocking` | ↓ |
| FileExplorer | AdbClient | `find_files(root, keyword, ...)`（全盘搜索走 FileService 或直接调用） | ↓ |
| FileService | AdbClient | 普通方法调用 (`list_dir / build_pull_cmd / run_transfer`) | ↓ |
| ScrcpyService | AdbClient | `find_scrcpy / build_scrcpy_cmd` | ↓ |
| LogcatService | AdbClient | `adb_path` 属性（直接构造 `adb -s <serial> logcat -v time`） | ↓ |
| DeviceService | AdbClient | `list_devices / get_device_info` | ↓ |
| All services | utils.start_worker / safe_is_running / decode_bytes / get_startup_info | 纯函数调用 | ↓ |
| All ui | core.config.load_commands / save_commands | 纯函数调用 | ↓ |

---

## 7. 扩展路径（面向 v2.2+）

| 新功能 | 新增文件 | 零侵入说明 |
|---|---|---|
| 截图 & 录屏 | `services/screen_service.py` + `ui/panels/screen_panel.py` | AdbClient 新增 `exec_out(cmd)` 封装 `exec-out screencap`；走 `DockPanelManager.add_panel` 挂载 |
| APK 安装/卸载 | `services/apk_service.py` + Dialog | 复用 `AdbClient.run_shell_blocking(pm install ...)` 与文件上传 |
| 递归文件搜索 | ✅ 已落地（v2.2）—— `AdbClient.find_files()` + FileExplorer 搜索框下拉模式 | 提供「当前目录过滤（内存）」与「/ 根目录全盘搜索（find+grep）」两种模式 |
| Web 前端替换 GUI | `webapp/main.py` (FastAPI + WebSocket) | 复用整个 core + services，只需把 pyqtSignal 替换为 WebSocket push |

---

## 8. 版本信息 & 变更记录

| 文档版本 | 对应产品版本 | 更新日期 | 更新点摘要 | 触发原因 / 关联任务 |
|---|---|---|---|---|
| v1.0 | v2.0 | — | 初始版本：三层架构总览 + QProcess 选型 + Dock 面板 | 项目首次文档化 |
| v1.1 | v2.1 | — | 补充 DeviceInfo dataclass、DockPanelManager、ScrcpyService/LogcatService 抽离 | v2.1 架构升级 |
| v1.2 | v2.2 | 2026-08-25 | 1) 新增 5.7~5.13 共 7 条关键设计决策（\_stop_requested 标记、QProcess None 检查、find+grep 全盘搜索、format_size 五档、subprocess 编码、run_shell_blocking 静音、logcat 解码器重置）<br>2) 核心层架构图补充 find_files / format_size 职责<br>3) 模块契约补充 FileExplorer→AdbClient find_files 调用<br>4) 扩展路径标记「递归文件搜索」已落地 | v2.2 Bug 修复与全盘搜索功能上线；对应修复：logcat 停止崩溃、scrcpy 误报错误、is_dir 全 False、format_size GB/TB 错算、find_files 全盘搜不到文件等 8+ 项问题 |
| v1.3 | v2.3 | 2026-09-09 | 1) 架构图 AdbTransferWorker 标注支持批量多文件并发<br>2) 新增 5.14 批量并发传输计数器设计决策（_active_transfers 递增/递减，归零隐藏进度条） | 用户要求支持多文件上传 + 多文件下载到本地。 |
