# ADB Visual Tool - 开发规范文档

> 适用范围：本仓库 `adbtools/` 包下除 `venv/`、`build/`、`dist/`、`platform-tools/` 外的全部源代码。

---

## 1. 目录与命名规范

### 1.1 目录结构（固定不变）

```
adbtools/
├── adb_gui_interactive.py   # 入口（仅组装 + main()）
├── core/                    # 零 GUI 依赖的基础能力
│   ├── utils.py             # 纯函数 / 常量 / Worker 池
│   ├── config.py            # 配置文件读写
│   └── adb_client.py        # 所有 ADB 子进程调用的唯一入口
├── services/                # 业务服务（允许 import PyQt5.QtCore 的 QThread/QObject/pyqtSignal）
│   ├── device_service.py    # 设备刷新 + 连接 + DeviceInfo 缓存
│   ├── file_service.py      # 传输 / 目录加载 Worker
│   ├── terminal_service.py # 终端 QProcess 交互
│   ├── scrcpy_service.py    # scrcpy 启停（QProcess）
│   └── logcat_service.py    # logcat 录制 + 级别过滤（QProcess）
├── ui/                      # GUI 展示（允许 import PyQt5.QtWidgets/Gui）
│   ├── main_window.py
│   ├── widgets/             # 原子控件：ConsoleEdit / FileTreeWidget / ...
│   └── panels/              # 组合面板
│       ├── dock_panel_manager.py    # QDockWidget 统一管理
│       ├── terminal_tab.py
│       ├── file_explorer.py
│       ├── scrcpy_control_panel.py
│       └── logcat_panel.py
└── docs/                    # PRD / 架构 / 规范 / 设计 / API 文档
```

### 1.2 文件 / 类 / 函数命名

| 对象 | 规范 | 正例 | 反例 |
|---|---|---|---|
| 模块 | 全小写 + 蛇形 | `terminal_service.py` | `TerminalService.py`、`term-svc.py` |
| 类 | 大驼峰 (Pascal) | `FileExplorer`、`AdbClient` | `fileExplorer`、`adb_client` |
| 函数/方法 | 蛇形 + 动词开头 | `load_directory()`、`get_current_serial()` | `LoadDir()`、`dirLoad()` |
| 私有成员 | 单下划线前缀 | `_cancelled`、`_on_dir_loaded()` | `__cancelled`（双下划线防继承不推荐） |
| 常量 | 全大写下划线 | `CONFIG_FILE`、`COLOR_SUCCESS` | `configFile`、`successColor` |
| QThread Worker 类 | 以 `Worker` 结尾 | `DeviceRefreshWorker` | `DeviceRefresh`、`RefreshWorkerThread` |
| Qt 槽函数（UI 内部） | 以 `_on_` 或 `handle_` 开头 | `_on_devices_found()`、`handle_finished()` | `devicesFound()` |

### 1.3 import 规范

所有 `import` 必须按以下分组，组间空 1 行，组内按字母序：

1. 标准库 (`sys`, `os`, `subprocess`, `json`, `re`, ...)
2. 第三方库 (`PyQt5.*`)
3. 同项目相对 import（推荐显式相对，`from ..core.xxx import Yyy`）

✅ 正确示例：
```python
import os
import subprocess
from collections import deque

from PyQt5.QtCore import QProcess, Qt
from PyQt5.QtWidgets import QWidget

from ...core.utils import COLOR_ERROR, get_startup_info
from ...core.adb_client import AdbClient
```

❌ 禁止：
```python
from .terminal_service import *     # 禁止星号
import sys, os, json                # 禁止一行多个标准库
import adbtools.core.utils          # 禁止绝对根导入，UI→core 必须相对
```

---

## 2. 分层边界 & 禁止事项

### 2.1 各层允许/禁止清单（强制执行）

| 层 | 允许 import | 禁止 import / 使用 |
|---|---|---|
| `core/` | 标准库 | **禁止任何 `PyQt5.QtWidgets/Gui`**（utils 可 `from PyQt5.QtCore import QThread` 仅限 Worker 池辅助函数） |
| `services/` | 标准库 + `PyQt5.QtCore` + `core/*` | **禁止 `PyQt5.QtWidgets/Gui`**、禁止 import `ui/*`、禁止弹 `QMessageBox`（所有消息转为 callback / signal） |
| `ui/widgets/` | Qt 全套 + `core/utils` (颜色常量) / `services/*` (回调对象引用) | 禁止直接 `subprocess.run(['adb'...])`（必须走 service） |
| `ui/panels/` | Qt 全套 + `services/*` + `core/config` | 禁止直接触碰 adb 命令字符串（必须走 service 方法） |
| `ui/main_window.py` | Qt 全套 + 任意 service / panel / widget / core.config | 禁止实例化 Worker（必须走 service.refresh_devices() 等封装） |
| 入口 `adb_gui_interactive.py` | `core.adb_client`、`ui.main_window` | 禁止放任何业务逻辑，`main()` 只做三件事：装 excepthook / 建 QApplication / 建 AdbTool + show() |

### 2.2 依赖方向检查（提交前自查命令）

```powershell
# 应无任何输出
grep -rn "from.*ui" adbtools/core/ adbtools/services/
grep -rn "import subprocess" adbtools/ui/      # UI 层禁止直接 subprocess（含 scrcpy/logcat 调用必须走对应 service）
```

---

## 3. 代码风格

### 3.1 格式约定

- **行宽**：120 字符（软上限，长字符串拼接可例外但避免超过 150）
- **缩进**：4 空格，禁止 TAB
- **空行**：
  - 顶层类 / 函数定义之间：**2 空行**
  - 类内方法之间：**1 空行**
  - 逻辑段落之间：1 空行
- **行尾**：不得有空格；文件末尾保留 1 空行
- **字符串**：短字符串用双引号；正则 / 路径含反斜杠用 `r"raw string"`；多行拼接优先 f-string + 括号隐式续行

### 3.2 类型注解 (Type Hints)

**要求对所有 public 方法/函数加注解**，private 方法推荐。

✅ 必须：
```python
def list_dir(self, path: str, timeout: int = 15) -> Tuple[List[Dict[str, Any]], str]: ...
def get_current_serial(self) -> Optional[str]: ...
```

❌ 不要：
```python
def list_dir(self, path, timeout=15): ...
```

### 3.3 函数大小硬限制

| 类别 | 硬上限 | 超限处理 |
|---|---|---|
| 普通方法 | 60 行 | 拆私有方法 |
| 入口 / 初始化 | 100 行 | 拆 `init_device_toolbar / init_splitter / ...` 子方法 |
| 单文件行数 | 300 行（推荐上限） / 500 行（硬上限） | 再拆子模块（如 widgets 拆成多个） |

---

## 4. Qt 开发专项规范

### 4.1 pyqtSignal 定义

- **必须定义在类体顶部**，不可在 `__init__` 中动态赋值
- 同文件多个同构类共享相同信号 → 合并父类 Mixin 或各自声明，禁止"None + 首次实例化注入"套路（ConsoleEdit v2.0 已按此重写）

```python
class ConsoleEdit(QTextEdit):
    execute_cmd_signal = pyqtSignal(str)       # ✅
    ctrl_c_signal = pyqtSignal()               # ✅

    def __init__(self, parent=None):
        super().__init__(parent)
        ...
```

### 4.2 QThread Worker 生命周期

所有 Worker 必须通过 `core.utils.start_worker(worker)` 启动，禁止手动 `worker.start()`，原因：
1. 统一加入 `_workers` 集合，防止 GC 提前回收
2. 统一 `finished → deleteLater` 防泄漏

取消判断统一用 `safe_is_running(worker)`，包一层 try/except `RuntimeError`（PyQt 常见 C++ 对象已析构异常）。

### 4.3 QMessageBox 使用边界

`QMessageBox.warning / information / critical / question` 仅允许出现位置：
- `ui/widgets/*` 的用户交互失败处理
- `ui/main_window.py` 的设备连接 / 退出确认 / 命令保存失败
- 入口的 `global_exception_handler`

**services / core 层一律禁止弹框**，错误信息通过返回值 `(success, msg)` 或 pyqtSignal 参数向上抛。

### 4.4 Windows 子进程防黑框 & 编码统一

所有 `subprocess.*` 必须注入 `startupinfo=get_startup_info()`。

**subprocess 编码统一硬约束（v2.2 强制执行，违反打回）**：
| 场景 | 必须参数 | 原因 |
|---|---|---|
| `subprocess.run/check_output(..., text=True)` | `encoding='utf-8', errors='replace'` 同时显式指定 | 中文 Windows 默认 GBK code page，缺省解码会抛 `UnicodeDecodeError`；`errors='replace'` 保证流程不中断 |
| `subprocess.check_output(...)` 二进制模式（无 text） | 后续统一走 `core.utils.decode_bytes(raw)`，禁止自行 `.decode('utf-8')` | `decode_bytes` 内建 UTF-8 → GBK 回退逻辑，覆盖含中文路径的 ls/自定义命令输出 |
| 返回值字符串操作前（如 `.strip()` / `.splitlines()`） | 必须先判 `result is not None` | subprocess 异常时 check_output 可能返回 None，直接字符串方法会抛 `AttributeError: 'NoneType' object has no attribute 'strip'` |

**长驻子进程（scrcpy / logcat）必须使用 `QProcess`**，不能用 `subprocess.Popen`，原因：
1. QProcess 的 `finished` / `errorOccurred` 信号可与 Qt 事件循环联动，避免句柄泄漏
2. 可在主窗口关闭时统一 `kill()` + `waitForFinished()`
3. 无需 `CREATE_NEW_CONSOLE` —— scrcpy 自带 SDL 窗口、logcat 不需要窗口

历史例外 `_launch_scrcpy` 已在 v2.1 重构中删除，由 `ScrcpyService.launch()` 替代。当前**全仓库不再使用 `CREATE_NEW_CONSOLE`**。

---

### 4.5 QProcess 生命周期硬约束（v2.2 新增）

#### 4.5.1 防御式 None 检查（任何 QProcess 访问前必做）
**代码审查红线**：任何形如 `self._process.state()` / `self._process.kill()` / `w.process.write()` 的调用，必须先判对象不为 None。

✅ 正确写法（所有 services + main_window closeEvent 必须统一）：
```python
def is_running(self) -> bool:
    return self._process is not None and self._process.state() == QProcess.Running

def stop(self):
    if self._process and self._process.state() != QProcess.NotRunning:
        self._process.kill()
```

❌ 禁止写法：
```python
def is_running(self) -> bool:
    return self._process.state() == QProcess.Running  # 崩溃：_process 可能被回调置 None
```

**典型触发场景**：`stop_recording() → kill() → waitForFinished() → 同步触发 _on_finished（置 _process=None）→ 返回后再访问 state()` 形成竞态。

#### 4.5.2 主动停止 vs 异常崩溃区分
所有基于 QProcess 的**长驻服务**（ScrcpyService、LogcatService，未来可能的 ScreenService 等）必须实现以下模式：

```python
class XxxService(QObject):
    def __init__(self, adb_client):
        super().__init__()
        self._process: Optional[QProcess] = None
        self._stop_requested = False  # 必加字段

    def stop(self) -> None:
        if self._stop_requested:   # 幂等：重复调用直接返回
            return
        self._stop_requested = True
        if self._process is not None and self._process.state() == QProcess.Running:
            self._process.kill()
            self._process.waitForFinished(2000)
            # 若仍未退出可二次 kill + wait
        self._process = None       # 保证最终清理

    def _on_error(self, err):
        if self._stop_requested:   # 主动 kill() 触发 Crashed 是正常行为，不要报错
            return
        # ... 正常错误处理

    def _on_finished(self, exit_code, status):
        if self._stop_requested:   # 主动 stop → 不判定"启动失败"
            self._process = None
            self.xxx_finished.emit(exit_code)
            return
        # ... 正常退出 / 异常退出判定
```

#### 4.5.3 从 QtCore 导入 QProcess
`QProcess` 属于 `PyQt5.QtCore`，**禁止从 `PyQt5.QtWidgets` 导入**（后者不包含 QProcess，会抛 ImportError）。正确写法：
```python
from PyQt5.QtCore import Qt, QProcess
```
状态比较使用 `QProcess.Running` / `QProcess.NotRunning` 枚举常量，禁止硬编码数字 `2` 等。

---

### 4.6 Logcat 解码器生命周期（v2.2 新增）
`LogcatService` 使用的 `codecs.getincrementaldecoder('utf-8')` 是**有状态对象**，每次 `start_recording()` 必须重新实例化，禁止复用上次录制的解码器。原因：残留的半字节（多字节 UTF-8 序列中间截断）会导致新录制首行乱码（如 `"锘..."` 开头）。

✅ 正确：
```python
def start_recording(self, serial, target_dir):
    ...
    self._decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
    self._process.start(...)
```

---

## 5. 错误处理规范

### 5.1 分级

| 场景 | 处理方式 |
|---|---|
| 用户操作前置条件不符（如 QInputDialog 取消、保存路径为空） | `return` 静默不报错 |
| 业务操作失败（adb push 失败、权限不足） | service 返回 `(False, reason)`，UI 弹 QMessageBox.warning 并同步终端红字 |
| 未捕获异常 | `sys.excepthook` 兜底，绝不闪退，弹窗含完整 traceback |
| `FileNotFoundError` (adb 不存在) | 统一提示「未找到 adb，请检查环境变量」 |

### 5.2 禁止裸 `except:`

允许的写法：
```python
try:
    ...
except subprocess.CalledProcessError as e:    # ✅ 精确
    ...
except (OSError, ValueError):                # ✅ 多种列清
    ...
except Exception:                            # ✅ 顶层兜底（但必须有注释说明原因）
    pass
```

禁止写法：
```python
except:          # ❌ 吞掉 KeyboardInterrupt / SystemExit
    pass
```

---

## 6. 配置 & 常量 & UI 约定

- **路径常量**：`CONFIG_FILE`、`IP_PORT_RE` 等集中放 `core/utils.py` 或 `core/config.py` 顶部，禁止散落在 UI 文件中
- **颜色常量**：`COLOR_DEFAULT / PROMPT / SYSTEM / ERROR / SUCCESS` 唯一来源为 `core.utils`，UI 禁止再写 `"#f44747"` 字面量
- **新的可配置项**：先加进 `config.DEFAULT_COMMANDS` 结构扩展还是新增 `xxx_CONFIG_FILE`，PR 评审必须说明

### 6.1 UI 专项约定（v2.2 新增）

#### 6.1.1 搜索范围下拉框（FileExplorer）
搜索模式下拉框**仅保留 2 个选项**，禁止冗余：
1. `当前目录过滤` — 即时内存过滤，不走 adb
2. `/ 根目录全盘搜索` — adb find+grep 实现，排除虚拟目录

删除任何其他中间选项（如历史的 `/sdcard 全盘搜索`）避免用户混淆。

#### 6.1.2 文件/文件夹上传菜单
右键菜单中的上传功能必须**分层级**，文件和文件夹分为两个独立子项：
- `上传到设备... → 📄 文件...`（QFileDialog.getOpenFileNames，多选）
- `上传到设备... → 📁 文件夹...`（QFileDialog.getExistingDirectory，单目录递归）

禁止使用单菜单项 + "混合模式"同时选文件和文件夹（跨平台 Qt 行为不一致）。

#### 6.1.3 多选批量下载（v2.3 新增）
文件树必须开启 `QTreeWidget.ExtendedSelection` 模式，支持 Ctrl+点击（追加/取消单选）和 Shift+点击（范围连选）。
- **多选时**（`selectedItems()` 长度 > 1）：右键菜单显示「📥 下载 N 项到本地...」，隐藏重命名/删除（仅单选可用）。
- **单选时**：保留原「📥 下载到本地...」+ 重命名 + 删除菜单。
- 批量下载统一选择一个目标目录（`getExistingDirectory`），逐个调用 `download_item(name, save_dir/name)` 并发执行。
- **进度条计数器**：FileExplorer 必须维护 `_active_transfers` 计数器，`_on_transfer_started` 递增、`_on_transfer_finished` 递减，仅当计数归零时才隐藏进度条。禁止在单个传输完成时直接隐藏进度条（会导致并发传输中进度条闪烁）。

#### 6.1.4 状态栏署名 & 永久控件
- 底部 `QStatusBar` 的**动态消息**（设备信息、传输进度、logcat 状态等）走 `showMessage(msg, timeout_ms)`（左侧可覆盖区）。
- **永久署名**（如 "by Yxing"）必须走 `statusBar().addPermanentWidget(widget)`（右侧永久区，不被动态消息覆盖），样式使用灰色小字（#888，12px，padding-right）。
- 其他需要常驻显示的控件（如全局 kill 按钮等）一律走 `addPermanentWidget`，不要用 `addWidget`（会被动态消息挤掉）。

#### 6.1.5 对话框按钮默认状态
`dialog_styles.create_primary_button(text, enabled=True, ...)` 的 `enabled` **默认值必须为 True**。原因：自定义命令管理对话框等场景按钮是默认启用的，若设为 False 会导致全部灰掉无法点击。仅在需要**条件激活**（如输入框为空时禁止确定）的场景才显式传 `enabled=False`，并在 UI 逻辑中动态 `setEnabled(True)`。

#### 6.1.6 弹窗 UI 冗余避免原则
- **scrcpy 参数配置**：禁止独立弹窗，配置控件必须内联在 ScrcpyControlPanel 主面板内（投屏控制面板自带参数区），避免"打开弹窗 → 输参数 → 关闭弹窗 → 点击投屏"的割裂操作。
- 参数预览必须实时显示**完整默认值**（如 `--max-fps=60 --video-bit-rate=8M`），禁止只写 `(默认参数)` 四字。
- 标题区必须用 `_make_section_header()` 方法渲染（蓝色竖条 + 粗体标题 + 右分隔线），保证视觉层级分明。

---

## 7. 提交前检查清单 (PR Checklist)

- [ ] `GetDiagnostics` 结果为空，零 lint / 类型告警
- [ ] 分层边界无违反（见 2.2 自查命令）
- [ ] 所有 public 方法都有 type hints
- [ ] 新增的 ADB 调用都经过了 `AdbClient`（而非直接 subprocess）
- [ ] 新增 Worker 都用了 `start_worker`
- [ ] 没有硬编码颜色 / 路径常量到 UI 文件
- [ ] 没有新增裸 `except:`
- [ ] **（v2.2 强制）** 所有 `subprocess.*(text=True)` 都显式传了 `encoding='utf-8', errors='replace'`；二进制输出走了 `decode_bytes()`
- [ ] **（v2.2 强制）** 所有 `self._process.state()` / `.kill()` 前都判了 `self._process is not None`
- [ ] **（v2.2 强制）** QProcess 从 `PyQt5.QtCore` 导入，未从 QtWidgets 导入
- [ ] **（v2.2 强制）** QProcess 长驻服务（scrcpy/logcat 等）实现了 `_stop_requested` 模式，`_on_error` 中判了该标记
- [ ] **（v2.2 强制）** LogcatService.start_recording 每次 new 了新的 IncrementalDecoder
- [ ] **（v2.2 UI 检查）** 搜索下拉仅 2 项；上传菜单分层；状态栏署名走 addPermanentWidget；对话框按钮 enabled 默认 True
- [ ] **（v2.3 UI 检查）** 文件树开启 ExtendedSelection；多选时右键菜单显示批量下载；并发传输时进度条使用 _active_transfers 计数器而非单次隐藏
- [ ] PRD 对应功能条目已勾选或新增 NFR/范围说明

---

## 8. 版本信息 & 变更记录

| 文档版本 | 对应产品版本 | 更新日期 | 更新点摘要 | 触发原因 / 关联任务 |
|---|---|---|---|---|
| v1.0 | v2.0 / v2.1 | — | 初始版本：目录命名 / 分层边界 / Qt 规范 / 错误处理 / PR Checklist | 项目首次规范文档化 |
| v1.1 | v2.2 | 2026-08-25 | 1) §4.4 升级为「Windows 子进程防黑框 & 编码统一」，新增 subprocess 编码三大硬约束（text=True 必传 utf-8+replace / 二进制走 decode_bytes / 返回值 None 检查）<br>2) 新增 §4.5 QProcess 生命周期硬约束（4.5.1 防御式 None 检查 + 示例代码、4.5.2 \_stop_requested 主动停止模式、4.5.3 QProcess 正确导入 & 枚举常量使用）<br>3) 新增 §4.6 Logcat 解码器生命周期<br>4) §6 扩展为「配置 & 常量 & UI 约定」，新增 §6.1 UI 专项约定 5 条（搜索下拉 2 项精简、文件/文件夹上传菜单分层、状态栏永久控件署名、create_primary_button enabled 默认 True、scrcpy 参数内联+完整默认值预览+section header 视觉）<br>5) §7 PR Checklist 新增 7 条 v2.2 强制检查项 | v2.2 Bug 修复集中上线，对应修复了：logcat 停止 AttributeError、scrcpy 误报 Crashed、命令管理对话框按钮灰掉、format_size GB/TB 错算、find_files is_dir 全 False、搜索选项冗余、subprocess 中文解码崩溃、状态栏署名被覆盖、__pycache__ 陈旧字节码残留导致诡异 AttributeError 等问题。 |
| v1.2 | v2.3 | 2026-09-09 | 1) 新增 §6.1.3 多选批量下载 UI 规范（ExtendedSelection 模式、右键菜单智能切换、批量下载目录选择、_active_transfers 计数器防止进度条闪烁）<br>2) §6.1 原有小节编号顺延（6.1.3→6.1.4 状态栏署名，6.1.4→6.1.5 按钮默认状态，6.1.5→6.1.6 弹窗冗余避免）<br>3) §7 PR Checklist 新增 1 条 v2.3 UI 检查项 | 用户要求支持多文件上传终端 + 多文件下载到本地。 |

