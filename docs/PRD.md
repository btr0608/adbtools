# ADB Visual Tool - 产品需求文档 (PRD)

## 1. 文档信息

| 项 | 内容 |
|---|---|
| 产品名称 | ADB Visual Tool - Ultimate Shell |
| 版本 | v2.2（稳定性 & 全盘搜索增强版） |
| 目标用户 | Android 开发者 / 测试人员 / 需要图形化管理安卓设备的工程师 |
| 文档状态 | 已实现（持续迭代） |

---

## 2. 产品背景与目标

### 2.1 背景
ADB (Android Debug Bridge) 是 Android 开发调试的核心工具，但其命令行形态对非重度用户存在学习门槛，且文件管理、多终端、投屏等常见操作需频繁切换命令窗口，效率低下。

### 2.2 目标
- 将高频 ADB 操作 100% 图形化，零命令即可完成 90% 日常任务
- 保持原生 ADB / scrcpy 全部能力，高级用户仍可通过内置终端自由输入命令
- **架构目标**：v2.0 必须完成「GUI 展示层 ↔ 业务服务层 ↔ 核心能力层」三层解耦，为后续扩展（Logcat、截图、APK 管理等）提供干净基础

---

## 3. 功能范围（FRS）

### 3.1 设备管理模块

| 编号 | 功能 | 描述 | 优先级 |
|---|---|---|---|
| DM-01 | 设备列表刷新 | 点击「🔄 刷新列表」或启动时自动执行 `adb devices`，展示所有已连接设备及状态 | P0 |
| DM-02 | 当前设备切换 | 下拉框选择设备后，终端、文件浏览器、自定义命令均自动切换到目标设备 | P0 |
| DM-03 | 无线 ADB 连接 | 输入 `IP:Port`（正则 `^\d{1,3}(\.\d{1,3}){3}:\d{1,5}$`），执行 `adb connect`，含 15s 超时与格式校验；**已连接设备时自动隐藏输入框** | P1 |
| DM-04 | 连接状态反馈 | 连接成功弹 Info，失败 / 超时 / 未找到 adb 均弹 Warning 并附中文说明 | P1 |
| DM-05 | 设备元数据富化 | 每台设备自动查询 `model` / `android_version` / `root_state`，下拉框显示 `设备名 (IP:端口) Android xx`；DeviceService 内置缓存，断开/重连时失效 | P1 |

### 3.2 文件浏览器模块

| 编号 | 功能 | 描述 | 优先级 |
|---|---|---|---|
| FE-01 | 目录浏览 | 左侧面板默认 `/sdcard/`，执行 `adb shell ls -l <path>` 解析名称/类型/大小/权限，支持文件夹/链接图标区分 | P0 |
| FE-02 | 目录导航 | 「⬆️ 上一级」按钮、双击文件夹进入、路径输入框回车跳转、返回根目录时隐藏「..」 | P0 |
| FE-03 | 异步下载（另存为） | 右键文件或双击文件 → `QFileDialog.getSaveFileName` → 后台 `adb pull`，成功/失败消息同步到终端 | P0 |
| FE-04 | 异步上传（拖拽入） | 本地文件拖入树视图 → 后台 `adb push` 到当前路径，成功后自动刷新目录 | P0 |
| FE-05 | 拖拽出设备 | 按住设备文件拖动 → 自动 `adb pull` 到系统 temp 目录 → 触发 `QDrag` 复制到资源管理器 | P1 |
| FE-06 | 重命名 / 删除 | 右键菜单执行 `adb shell mv / rm -rf`，删除需二次确认 | P1 |
| FE-07 | 加载保护 | 正在加载时禁用刷新按钮并显示「⏳ 加载中...」占位；切换目录自动取消前一次异步请求 | P1 |
| FE-08 | 文件名搜索过滤 | 文件列表顶部新增搜索框，对当前目录文件名做实时内存过滤（不区分大小写）；递归搜索留接口 | P2 |
| FE-09 | 传输进度条 | 上传/下载开始时在文件面板顶部显示 indeterminate 进度条，传输结束自动隐藏，替代纯终端文字日志 | P2 |
| FE-10 | 右键菜单扩展 | 在原「另存为/重命名/删除」基础上新增「上传文件 / 新建文件夹 / 新建文件 / 刷新」共 6+ 项 | P2 |
| FE-11 | **全盘文件搜索（v2.2 新增）** | 搜索框左侧模式下拉，提供「当前目录过滤（即时）」与「/ 根目录全盘搜索（find+grep 实现，排除 /proc /sys 等虚拟目录提速，最多 500 条截断）」两种模式；搜索结果按 is_dir 图标显示，目录可双击跳转 | P1 |
| FE-12 | **文件/文件夹上传解耦（v2.2 新增）** | 右键菜单「上传到设备...」拆分为层级子菜单：「📄 文件...（getOpenFileNames 多选）」/「📁 文件夹...（getExistingDirectory 单目录递归）」；adb push 原生支持递归目录；避免单菜单项跨平台行为不一致 | P1 |
| FE-13 | **多文件批量下载（v2.3 新增）** | 文件树支持 Ctrl+点击 / Shift+点击 多选；多选时右键菜单显示「📥 下载 N 项到本地...」；选择目标目录后所有选中项并发 `adb pull`；进度条使用活跃传输计数器，仅当全部完成时隐藏 | P1 |

### 3.3 多终端模块

| 编号 | 功能 | 描述 | 优先级 |
|---|---|---|---|
| TM-01 | 多面板终端 | 「➕ 新终端」按钮新建面板（QDockWidget 形态），面板自动编号 `Terminal N`，关闭主窗口自动 kill 正在运行的 QProcess | P0 |
| TM-02 | 交互式终端 | 终端自带提示符 `> [设备名 Android xx] adb -s <serial> `，支持上下键翻历史命令、Home 跳输入起点、Ctrl+C 中断前台进程、Ctrl+V 粘贴 | P0 |
| TM-03 | 命令队列 | 粘贴或外部传入多行命令（`\n` 分隔）自动进入 deque 队列逐条串行执行 | P1 |
| TM-04 | 进程管理 | 运行中显示「✹ 强制结束进程」按钮，点击清空队列并 `QProcess.kill()`，红色告警消息提示 | P1 |
| TM-05 | 终端 scrcpy 通路 | 命令以 `scrcpy` 开头时，TerminalService 发 `scrcpy_requested(list)` 信号，主窗口转发到 `ScrcpyService` 启动独立窗口（不占终端 QProcess） | P1 |
| TM-06 | ANSI 过滤 + 颜色输出 | stdout 默认灰、stderr 红、系统消息黄、成功绿，自动剥离 ANSI 转义码防止乱码 | P2 |
| TM-07 | 终端命令自动补 -s | 用户输入 `adb <子命令>`（如 `adb root` / `adb install`）时，`AdbClient.build_terminal_args` 自动前置 `-s <serial>`，已显式含 `-s` 时不重复添加 | P2 |

### 3.4 自定义命令模块

| 编号 | 功能 | 描述 | 优先级 |
|---|---|---|---|
| CC-01 | 命令按钮栏 | 横向滚动条展示所有自定义按钮，点击即把对应 cmd 文本注入当前活动终端 | P0 |
| CC-02 | 命令管理对话框 | 新增 / 保存修改 / 删除 / 上移 / 下移，支持多行命令文本框，内置使用帮助弹窗 | P0 |
| CC-03 | 持久化存储 | 读写 `~/.adb_visual_cmds.json`，默认 4 条（Root / shell / remount / devices），写入失败弹 Warning | P0 |
| CC-04 | **对话框按钮默认启用（v2.2 Bug 修复）** | 自定义命令管理对话框「新增 / 保存修改 / 完成并退出」三个主按钮默认 enabled=True，不得默认禁用（原 v2.1 错误默认 False 导致全部灰掉无法点击） | P0（Bug 修复） |

### 3.5 稳定性与全局体验

| 编号 | 功能 | 描述 | 优先级 |
|---|---|---|---|
| UX-01 | 全局异常钩子 | `sys.excepthook = global_exception_handler`，任何未捕获异常弹 QMessageBox 而非闪退 | P0 |
| UX-02 | 退出保护 | `closeEvent` 检查仍在 Running 的终端面板，弹「有 N 个终端仍在运行，确定强制退出吗？」二次确认 | P1 |
| UX-03 | 子进程隐藏窗口 | 所有 `subprocess` 调用注入 `get_startup_info()`，Windows 下不弹黑框 | P2 |
| UX-04 | 全局状态栏 | `QMainWindow.statusBar()` 贴底显示 `设备: xxx | Android: 15 | Root: 已开启 | Scrcpy: 运行中 | Logcat: 录制中(xxx.log)`，多源信号联动 | P1 |
| UX-05 | **状态栏永久控件署名（v2.2 新增）** | 底部「by Yxing」署名等固定文案必须走 `statusBar().addPermanentWidget()`（右侧永久区），不被动态 showMessage 覆盖；样式使用灰色 12px 小字右 padding | P2（体验） |
| UX-06 | **QProcess 竞态保护（v2.2 Bug 修复）** | 所有长驻服务（Logcat / Scrcpy / Terminal）访问 `_process.state()` 前必须判 None，避免回调置 None 后的 AttributeError；长驻服务必须实现 `_stop_requested` 标记区分主动停止与异常崩溃 | P0（Bug 修复） |
| UX-07 | **subprocess 编码统一（v2.2 Bug 修复）** | 所有 `subprocess.*(text=True)` 显式传 `encoding='utf-8', errors='replace'`；二进制输出统一走 `core.utils.decode_bytes()`；避免中文 Windows GBK 环境下的 UnicodeDecodeError | P0（Bug 修复） |
| UX-08 | **format_size 单位换算修正（v2.2 Bug 修复）** | 文件大小显示必须覆盖 B→KB→MB→GB→TB 完整五档；原缺少 GB 分支导致 2TB 显示为 1.95 GB 的历史问题必须回归测试覆盖 | P1（Bug 修复） |

### 3.6 投屏控制模块

| 编号 | 功能 | 描述 | 优先级 |
|---|---|---|---|
| SC-01 | ScrcpyService 抽离 | 新建 `services/scrcpy_service.py`，用 `QProcess` 追踪 scrcpy 进程句柄，支持 `is_running()` / `stop()` | P0 |
| SC-02 | 投屏控制面板 | `ui/panels/scrcpy_control_panel.py`：分辨率限制 / 音频开关 / 额外参数输入，主按钮（启动/关闭）状态化 | P1 |
| SC-03 | 状态化按钮 | 启动后按钮变「关闭投屏」红色，结束后复位为「启动投屏」绿色 | P1 |
| SC-04 | 独立 SDL 窗口 | scrcpy 仍以独立 SDL 窗口显示（不改源码），QProcess 不依赖 `CREATE_NEW_CONSOLE` | P1 |
| SC-05 | **主动停止误报修复（v2.2 Bug 修复）** | 用户点击「关闭投屏」后，`QProcess.kill()` 触发的 Crashed 错误不得弹 Warning；实现 `_stop_requested` 标记主动忽略 | P0（Bug 修复） |
| SC-06 | **参数内联 + 完整默认值预览（v2.2 体验）** | scrcpy 所有参数配置控件必须内联在控制面板主区域（禁止独立弹窗），实时预览栏显示完整参数值如 `--max-fps=60 --video-bit-rate=8M`，禁止仅显示「(默认参数)」四字 | P1（体验） |

### 3.7 Logcat 录制模块

| 编号 | 功能 | 描述 | 优先级 |
|---|---|---|---|
| LC-01 | LogcatService 抽离 | 新建 `services/logcat_service.py`，用 `QProcess` 跑 `adb logcat -v time`，输出写入本地文件并按级别过滤转发 | P0 |
| LC-02 | 一键录制 | 自动生成 `logcat_YYYYMMDD_HHMMSS.log` 至 `~/adb_visual_logs/`，按钮「停止录制」变红 | P0 |
| LC-03 | 级别过滤 | 多选 V/D/I/W/E/F，过滤在写文件前生效；客户端再按关键字做实时内存过滤 | P1 |
| LC-04 | 关键字搜索 | 关键字输入框实时过滤显示（不区分大小写），不影响文件写入 | P2 |
| LC-05 | 颜色着色 | V/D/I/W/E/F 各对应独立颜色常量，E 为红色、I 为绿色、W 为黄色等 | P2 |
| LC-06 | **停止后显示保存路径+大小（v2.2 增强）** | 停止录制时弹窗提示「录制完成，保存至 C:\\Users\\xxx\\adb_visual_logs\\logcat_xxx.log（3.2 MB）」；`recording_stopped` 信号签名从 `()` 升级为 `(filename: str, file_size_bytes: int)` | P1（体验） |
| LC-07 | **首行乱码修复（v2.2 Bug 修复）** | 每次 `start_recording` 必须重新实例化增量解码器 `codecs.getincrementaldecoder('utf-8')(errors='replace')`，禁止复用旧解码器；防止上一次录制末尾残留半字节导致新录制首行出现乱码字符如「锘」 | P0（Bug 修复） |
| LC-08 | **停止崩溃竞态修复（v2.2 Bug 修复）** | 停止录制时 `self._process` 可能在 `waitForFinished` 内被回调同步置 None，返回后再访问 state() 会崩溃；所有 `_process` 访问前必须加 `is not None` 判断 | P0（Bug 修复） |

### 3.8 Dock 重构与多面板集成

| 编号 | 功能 | 描述 | 优先级 |
|---|---|---|---|
| DK-01 | QTabWidget → QDockWidget | 右侧面板改用 `QMainWindow` 原生 dock 机制，多 dock `tabifyDockWidget` 形成标签页 | P0 |
| DK-02 | 拖出独立窗口 | 任意 dock（终端/投屏/Logcat）可拖出为浮动窗口，支持多屏部署（投屏放副屏等） | P1 |
| DK-03 | DockPanelManager | 新建 `ui/panels/dock_panel_manager.py` 统一管理 dock 注册/移除/查找；`setTabPosition` 在顶部 | P1 |
| DK-04 | 三面板默认挂载 | 启动时自动挂载 Terminal / 投屏 / Logcat 三 dock，tabify 在右侧 | P0 |

---

## 4. 非功能性需求 (NFR)

| 编号 | 维度 | 指标 |
|---|---|---|
| NFR-01 | 性能 | 目录列表加载 15s 超时；`adb devices` 10s 超时；`adb connect` 15s 超时；`get_device_info` 三条 getprop 各 5s 超时；文件传输使用后台 QThread 绝不阻塞 UI 线程；**全盘根目录搜索默认 30s 超时，超过 500 条自动截断**（v2.2） |
| NFR-02 | 兼容性 | Windows 为主要平台（含 PyInstaller 打包），代码需保留 `os.name == 'nt'` 判断以便未来 Linux/macOS 适配 |
| NFR-03 | 可维护性 | 严格分层：core/services/ui 三层单向依赖，禁止 UI 直接 import subprocess 执行 adb |
| NFR-04 | 可扩展性 | 新增功能（如 截图 / APK 安装）应只需新增 `services/xxx_service.py` + `ui/panels/xxx_panel.py` + DockPanelManager 挂载，不得修改 core 层 |
| NFR-05 | 可测试性 | core 层与 services 层除 QThread 信号外应可独立实例化，支持脱离 PyQt 写单元测试 |
| NFR-06 | 解码稳健性 | 所有 adb 输出统一用 `encoding='utf-8', errors='replace'` 解码，避免 GBK 环境下含非 GBK 字节崩溃；**二进制 check_output 必须走 core.utils.decode_bytes() 做 UTF-8→GBK 回退**（v2.2 强化） |
| NFR-07 | 状态一致性 | 设备断开/重连时 `DeviceService.invalidate(serial)` 清缓存，避免显示陈旧元数据 |
| NFR-08 | **QProcess 生命周期稳健性（v2.2 新增）** | 1) 所有 `_process.state()`/`.kill()` 前判 `is not None`；2) 长驻 QProcess 服务必实现 `_stop_requested` 区分主动停止 vs 崩溃；3) QProcess 必须从 `PyQt5.QtCore` 导入，禁止从 QtWidgets 导入；4) 状态比较使用 `QProcess.Running` 枚举，禁止硬编码数字 |
| NFR-09 | **搜索结果正确性（v2.2 新增）** | `find_files` 搜索结果中的目录类型 is_dir 必须通过批量 adb shell `[ -d "$p" ]` 判断，不得硬编码 False；路径必须以 `/` 开头，Permission denied / No such file or directory 等错误行必须过滤 |
| NFR-10 | **UI 零命令弹窗原则（v2.2 新增）** | 常用参数配置（如 scrcpy）必须内联在主面板内，禁止独立弹窗割裂操作流；搜索模式选项不得冗余（同类含义的选项合并精简到 2 个以内） |
| NFR-11 | **批量并发传输安全（v2.3 新增）** | 多文件批量上传/下载时，每个文件启动独立 AdbTransferWorker 并发执行；UI 层使用 `_active_transfers` 计数器追踪活跃传输数，仅当计数归零时隐藏进度条和刷新目录；防止并发回调互相覆盖 |

---

## 5. 用例速览

### UC-001：拖拽出一个 APK
1. 用户在文件树选中 `/sdcard/Download/foo.apk`
2. 按住左键拖出窗口边界
3. 系统静默 `adb pull` 到 `%TEMP%/foo.apk`
4. pull 成功后 QDrag 启动 CopyAction，用户释放到桌面即完成复制

### UC-002：一键无线投屏
1. 用户在 IP 输入框输入 `192.168.1.20:5555` 回车
2. 连接成功后下拉框自动出现新设备并选中，IP 输入框自动隐藏
3. 用户在「📺 投屏」面板点「🚀 启动投屏」
4. ScrcpyService 扫描到同目录 `scrcpy-win64/scrcpy.exe`，独立 SDL 窗口投屏
5. 主窗口按钮变「⏹ 关闭投屏」红色，状态栏出现 `Scrcpy: 运行中`
6. 用户拖动 dock 标题栏把投屏面板拖到副屏，主屏继续操作文件/终端

### UC-003：Logcat 一键录制 + 级别过滤
1. 用户连接设备后切到「📋 Logcat」面板
2. 勾选 E / W / F（默认已勾选），关键字留空
3. 点「🔴 开始录制」，按钮变「⏹ 停止录制」灰
4. `~/adb_visual_logs/logcat_YYYYMMDD_HHMMSS.log` 开始持续增长，仅写入 E/W/F 级别
5. 终端区按颜色实时显示日志（E 红、W 黄、F 红）
6. 点停止，文件写入结束，状态栏 `Logcat: 录制中(xxx.log)` 自动清零

### UC-004：终端命令自动补 -s
1. 用户在终端输入 `adb root` 回车
2. `build_terminal_args` 自动改写为 `adb -s 127.0.0.1:16384 root`
3. 用户输入 `adb -s emulator-5554 shell ls`（已含 `-s`）则原样发出，不重复添加

### UC-005：全盘根目录搜索 test 文件（v2.2 新增）
1. 用户连接设备后，在文件浏览器顶栏搜索模式下拉选择「/ 根目录全盘搜索」
2. 输入关键词 `test`，回车或等待 200ms 防抖
3. 状态栏显示「全盘搜索中...」，面板顶显示 indeterminate 进度条
4. adb 端实际执行：`find / -path /proc -prune -o -path /sys -prune -o ... -print 2>/dev/null | grep -i 'test' | head -n 501`
5. 30s 内返回后，文件树自动清空并渲染结果（每行为完整路径，目录项带文件夹图标可双击进入，文件项带文件图标）
6. 若命中 >500 条，状态栏提示「搜索结果已截断，仅显示前 500 条」；若超时 30s 提示「搜索超时（>30秒），建议缩小搜索范围到 /sdcard」
7. 用户可随时切换回「当前目录过滤」模式即时回到本地内存过滤模式

### UC-006：Logcat 停止后确认保存位置（v2.2 新增）
1. 用户在 Logcat 面板点击「🔴 开始录制」
2. 面板按钮变「⏹ 停止录制」红色，状态栏显示「Logcat: 录制中(logcat_20260825_180356.log)」
3. 运行一段时间后用户点击「⏹ 停止录制」
4. LogcatService 调用 `terminate() + waitForFinished(3000)` 安全结束进程并关闭文件句柄
5. 信号 `recording_stopped(filename, file_size_bytes)` 触发 UI 端弹窗：
   ```
   🎉 录制完成
   文件已保存至：C:\Users\xxx\adb_visual_logs\logcat_20260825_180356.log
   文件大小：2.7 MB (2,839,552 字节)
   ```
6. 状态栏 Logcat 行清零

### UC-007：多文件批量下载（v2.3 新增）
1. 用户在文件树中 Ctrl+点击 选中多个文件和文件夹（如 `screenshot1.png`、`screenshot2.png`、`logs/`）
2. 右键菜单自动显示「📥 下载 3 项到本地...」
3. 用户选择本地保存目录（如 `D:\backup\`），系统对每个选中项启动独立 `AdbTransferWorker` 并发执行 `adb pull`
4. 进度条显示活跃传输状态，终端逐条输出每个文件的成功/失败结果
5. 所有传输完成后（`_active_transfers` 归零），进度条自动隐藏，终端汇总输出

---

## 6. 需求外范围（Not In Scope）

- 不做 iOS / HarmonyOS 设备支持
- 不做 adb 二进制的自动下载与安装
- 不做多设备并行文件传输调度器（当前设备串行）
- 不做多语言 i18n（首版仅中文）

---

## 7. 版本信息 & 变更记录

| PRD 版本 | 对应产品版本 | 更新日期 | 需求条目变更摘要 | 触发原因 / 关联任务 |
|---|---|---|---|---|
| v1.0 | v2.0 / v2.1 | — | 初始版本：设备管理/文件浏览/多终端/自定义命令/投屏/Logcat/Dock 重构 8 大功能模块 + NFR-01 ~ NFR-07 | v2.0~v2.1 核心功能落地 |
| v1.1 | v2.2 | 2026-08-25 | **功能范围新增**：FE-11 全盘文件搜索（双模式）、FE-12 文件/文件夹上传解耦、CC-04 对话框按钮默认启用（Bug）、UX-05 状态栏永久控件署名、UX-06 QProcess 竞态保护（Bug）、UX-07 subprocess 编码统一（Bug）、UX-08 format_size 单位修正（Bug）、SC-05 投屏停止误报修复（Bug）、SC-06 参数内联+完整默认值预览、LC-06 停止显示保存路径+大小、LC-07 Logcat 首行乱码修复（Bug）、LC-08 Logcat 停止崩溃修复（Bug）；共 13 条新条目。<br>**NFR 新增**：NFR-01 补全盘搜索 30s/500条 指标；NFR-06 补 decode_bytes 回退要求；新增 NFR-08 QProcess 生命周期稳健性；NFR-09 搜索结果正确性；NFR-10 UI 零命令弹窗原则。<br>**用例新增**：UC-005 全盘根目录搜索、UC-006 Logcat 停止后确认保存路径 | v2.2 用户集中反馈 10+ 项问题：停止录制崩溃、按钮灰掉、投屏停止误报错误、全盘搜索找不到文件、文件大小错标、录制无保存路径、首行乱码等；以及项目内存中沉淀的工程约束需要正式写入 PRD 作为验收标准。 |
| v1.2 | v2.3 | 2026-09-09 | **功能范围新增**：FE-13 多文件批量下载（ExtendedSelection 多选 + 并发 adb pull + 活跃传输计数器）；**NFR 新增**：NFR-11 批量并发传输安全（_active_transfers 计数器追踪）；**用例新增**：UC-007 多文件批量下载。 | 用户要求支持多文件上传终端 + 多文件下载到本地。 |

