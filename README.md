# aT (ADB Visual Tool) - Ultimate Shell 📱

aT（ADB Visual Tool）是一款基于 Python 和 PyQt5 开发的现代化、非阻塞式 ADB 可视化管理工具。它将复杂的终端命令与直观的图形界面（GUI）完美结合，专为 Android 开发者、测试工程师和逆向人员设计。

## ✨ 核心特性

* **🖥️ 交互式多标签终端**
  * 支持无缝的多标签页管理，所有底层进程独立运行。
  * 完美支持中文（增量解码，彻底杜绝输出断帧乱码）。
  * 支持键盘快捷键：`↑` `↓` 历史记录翻阅，`Ctrl+C` / `Ctrl+V` 快捷复制粘贴。
* **📁 异步文件资源管理器**
  * 彻底告别加载卡顿，千万级目录依然丝滑。
  * 支持精准的**软链接 (Symlink)** 解析与导航。
  * **拖拽传输**：支持从电脑直接拖拽文件推送至设备，或按住文件拖拽拉取到本地电脑。
  * 双击文件快速下载，支持右键菜单（重命名、删除、另存为）。
  * **✅ v2.2 新增：文件 & 文件夹独立上传**：右键菜单分离为「文件...」和「文件夹...」两个子项，`adb push` 原生支持递归目录。
  * **✅ v2.2 新增：全盘文件搜索**：搜索框双模式——「当前目录过滤（即时内存）」与「/ 根目录全盘搜索（adb find + grep 实现，自动排除 /proc /sys 等虚拟目录提速）」。
  * **✅ v2.3 新增：多文件批量下载**：文件树支持 Ctrl+点击 / Shift+点击 多选，右键菜单一键并发下载多个文件/文件夹到同一本地目录。
* **🌐 智能设备管理**
  * 自动获取并区分在线/离线设备状态。
  * 内置**无线 ADB (IP:Port)** 一键连接功能。
* **🛠️ 自定义快捷命令**
  * 支持自定义常用指令并保存为快捷按钮。
  * 支持**多行批处理**，点击一次按顺序执行多条指令，数据持久化保存于本地配置中。
* **📹 Logcat 日志录制**
  * 一键启动/停止 logcat 录制（`-v time` 时间戳格式）。
  * 按级别实时过滤显示（V/D/I/W/E/F），关键字二次过滤。
  * **✅ v2.2 增强**：停止后弹窗显示**保存路径 + 文件大小**；首行乱码彻底修复（每次启动重置增量解码器）；停止崩溃竞态修复。
* **🖼️ Scrcpy 投屏控制**
  * 一键启动 scrcpy 投屏到独立 SDL 窗口。
  * 分辨率 / 最大帧率 / 视频码率 / 音频开关等参数面板内联配置，无需弹窗。
  * **✅ v2.2 增强**：主动停止投屏不再误报「进程崩溃」；参数预览显示完整默认值（如 `--max-fps=60`）。
* **🎨 UI 交互增强**
  * **✅ v2.2 Bug 修复**：自定义命令管理对话框「新增 / 保存修改 / 完成并退出」按钮默认启用，不再灰掉。

## 🚀 快速上手

1. 确保电脑已安装 ADB 并配置了环境变量（或者将 `adb.exe` 放在本工具同级目录下）。
2. 使用数据线或无线网络连接 Android 设备。
3. 打开软件，在左侧选择对应的设备。
4. 下方文件树即可浏览 Android 目录，右侧为对应的交互式终端。

## ⌨️ 快捷键指南

| 快捷键 | 功能说明 |
| :--- | :--- |
| `Enter` | 执行终端命令 |
| `↑` / `↓` | 翻阅终端执行过的历史命令 |
| `Ctrl + C` | 选中文本时为复制；未选中时发送 `^C` 终止当前命令 |
| `Ctrl + V` | 粘贴剪贴板文本 |

---

## 📋 版本更新日志

### v2.2.0（2026-08-25）——稳定性 & 体验集中修复

**核心 Bug 修复（8+ 项）：**
1. **Logcat 停止崩溃**：`AttributeError: 'NoneType' object has no attribute 'state'` 竞态条件修复——所有 `self._process.state()` 前加 `is not None` 判断。
2. **停止录制后不提示保存路径**：`LogcatService.recording_stopped` 信号改签名为 `(filename, file_size)`，UI 端弹窗显示完整路径 + 格式大小。
3. **Scrcpy 主动停止误报错误**：引入 `_stop_requested` 标记，区分用户主动 kill() 与异常崩溃，避免"scrcpy 进程错误：Process crashed"误报。
4. **format_size GB/TB 单位换算错误**：原代码缺少 GB 判断分支（1024³），导致 2TB 文件错误显示为 "1.95 GB"；已修正为 B→KB→MB→GB→TB 完整五档。
5. **全盘搜索 is_dir 全为 False**：`find_files` 结果中的目录被误标为文件，导致无法双击进入。实现基于 `adb shell for + [ -d "$p" ]` 的**批量路径类型判断**（单次 adb 往返，最多 200 条）。
6. **自定义命令对话框按钮全灰**：`dialog_styles.create_primary_button()` 的 `enabled` 参数默认值错误为 `False` → 改为 `True`。
7. **main_window QProcess 导入错误**：`from PyQt5.QtWidgets import QProcess` → 修正为 `from PyQt5.QtCore import QProcess`（前者会抛 ImportError）。
8. **Logcat 首行乱码**：每次 `start_recording` 重新实例化 `codecs.getincrementaldecoder('utf-8')`，避免复用解码器残留半字节。
9. **TerminalService 多处 None 检查缺失**：run_command / send_ctrl_c / kill_process 三个入口统一加 `self.process is not None` 判断。
10. **run_shell_blocking 输出干扰终端**：stdout/stderr 重定向至 `subprocess.DEVNULL`，rename/delete 等短命令不再污染终端 Tab 输出。

**功能新增 & 体验优化：**
- 🎯 **全盘文件搜索功能落地**：`AdbClient.find_files("/", keyword)`；FileExplorer 搜索框新增模式下拉，精简为 2 项（当前目录过滤 + / 根目录全盘搜索），删除冗余的 /sdcard 中间选项。根目录搜索排除 /proc /sys /dev /acct /cgroup /config /apex 等 12+ 虚拟目录。
- 📂 **文件/文件夹上传解耦**：FileTreeWidget 右键菜单重构为层级结构，「上传到设备...」下分为「文件...」和「文件夹...」独立子项，避免 QFileDialog 跨平台混合模式行为不一致。
- 📊 **状态栏规范**："by Yxing" 署名改为 `statusBar().addPermanentWidget()` 右下角固定显示，样式灰字小字。
- 🎨 **scrcpy 参数 UI**：配置控件全部内联在控制面板，参数预览实时显示完整默认值（`--max-fps=60 --video-bit-rate=8M` 等），不再使用独立弹窗。
- 🔍 **find_files 命令策略**：放弃 `find -name` 通配符（adb shell 引号转义不稳定），改为 `find ... | grep -i | head` 管道模式；错误行过滤（Permission denied / No such file or directory 等）。
- 🧹 **__pycache__ 陈旧字节码提醒**：若遇到诡异 NameError/AttributeError 且代码实际正确，先清项目内 __pycache__（venv 除外）再运行。

### v2.1.0
- 架构升级：ScrcpyService / LogcatService 独立抽离，统一用 QProcess 管理长驻进程。
- DockPanelManager 替代 QTabWidget，面板可拖出副屏独立窗口。
- DeviceInfo dataclass 富化设备信息（model / Android 版本 / Root 状态）。

### v2.0.0
- 初始版本：三层架构 + 终端 / 文件管理器 / 设备管理 / 自定义命令核心功能。

---

## 📚 文档索引

| 文档 | 路径 | 说明 |
|---|---|---|
| PRD 产品需求 | `docs/PRD.md` | 功能需求、非功能需求、范围界定 |
| 技术架构 | `docs/technical_architecture.md` | 三层架构图、关键设计决策 5.1~5.13、模块契约 |
| 模块详细设计 | `docs/module_design.md` | 每个模块的类职责、状态机、关键算法、UI 交互细节 |
| API 接口参考 | `docs/api_reference.md` | 所有对外 API（类/方法/信号/回调签名）+ 行为契约 |
| 开发规范 | `docs/development_standards.md` | 命名、分层边界、Qt 规范、QProcess/subprocess 硬约束、PR Checklist |

---

## ⚖️ 开源许可证

本项目（aT / ADB Visual Tool）基于 **GNU General Public License v3 (GPL-3.0-only)** 许可证开源。

- 📄 完整许可证文本见 [LICENSE](./LICENSE)
- 📋 第三方组件清单与声明见 [NOTICE](./NOTICE)
- 🔗 GPL v3 在线版本：<https://www.gnu.org/licenses/gpl-3.0.html>

**这意味着您可以自由地：**
- ✅ 使用、复制、修改本软件
- ✅ 重新分发本软件及其源代码
- ✅ 将本软件整合进其他 GPL-3.0 兼容项目中
- ✅ 商业使用（包括销售），但必须同时提供完整源代码

**前提条件：**
- 分发本软件（或其衍生作品）时，必须以 GPL-3.0 许可证公开全部源代码
- 必须保留原始版权声明、LICENSE 和 NOTICE 文件
- 必须注明对源代码所做的修改

---

## 🧩 第三方组件声明

本项目捆绑或依赖以下第三方组件，详细许可证信息见 [NOTICE](./NOTICE)：

| 组件 | 用途 | 许可证 | 与本项目的兼容性 |
|---|---|---|---|
| [PyQt5](https://www.riverbankcomputing.com/software/pyqt/) | GUI 框架 | GPL v3 / 商业双授权 | ✅ 本项目亦为 GPL v3，兼容 |
| [scrcpy](https://github.com/Genymobile/scrcpy) | Android 屏幕镜像 | Apache 2.0 | ✅ Apache 2.0 与 GPL v3 兼容 |
| [Android Platform Tools (adb)](https://developer.android.com/tools/adb) | ADB 通信 | Apache 2.0 | ✅ Apache 2.0 与 GPL v3 兼容 |
| [PyInstaller](https://pyinstaller.org/) | 打包工具（仅构建时） | GPL v2 + 特殊例外 | ✅ 仅用于构建，非运行时 |
| [Python](https://www.python.org/) | 解释器（仅开发时） | PSF License (BSD 兼容) | ✅ 与 GPL v3 兼容 |
| [Zpix 像素字体](https://github.com/SolidH/Zpix) | UI 字体 | OFL 1.1 | ✅ OFL 与 GPL v3 兼容 |

**关于 PyQt5 与 GPL v3 的兼容性说明：**

PyQt5 的开源版本采用 GPL v3 许可证，具有"传染性"——只要分发包含 PyQt5 的二进制程序，整个程序必须以 GPL v3 或兼容许可证开源源代码。这正是本项目选择 GPL v3 作为整体许可证的原因，以保证完全合规。

---

## 🛠️ 从源码构建

```bash
# 1. 克隆仓库
git clone https://github.com/btr0608/adbtools.git
cd adbtools

# 2. 创建虚拟环境（Python 3.10+）
python -m venv venv
venv\Scripts\activate  # Windows

# 3. 安装依赖
pip install -r requirements.txt

# 4. 运行（开发模式）
python adb_gui_interactive.py

# 5. 打包为 Windows 可执行文件（OneDir 模式）
venv\Scripts\pyinstaller.exe adb_gui_interactive.spec --clean -y
# 产物输出在 dist/aT/
```

**运行时依赖二进制：**
- `adb.exe`、`AdbWinApi.dll` 等 → 从 [Android Platform Tools](https://developer.android.com/tools/releases/platform-tools) 下载，放到项目根目录
- `scrcpy.exe`、`scrcpy-server`、`SDL3.dll`、`avcodec-62.dll` 等 → 从 [scrcpy Releases](https://github.com/Genymobile/scrcpy/releases) 下载 Windows 64-bit 版本，放到项目根目录

---

## 🤝 贡献

欢迎通过 Pull Request 贡献代码。提交前请注意：

1. 本项目为 GPL v3 许可证，您提交的代码也将以同一许可证开源
2. 请遵守 [开发规范](./docs/development_standards.md) 中的命名、分层边界、Qt 规范
3. 提交信息请遵循 Conventional Commits 规范
4. 涉及 adb/scrcpy 调用的修改必须通过 QThread/QProcess，不可阻塞 UI

---

## ⚠️ 免责声明

本软件仅供合法的 Android 设备管理与调试用途。使用者需：

- 确保拥有对被调试设备的合法授权（如自有设备、测试设备、获得授权的他人设备）
- 遵守所在地区的相关法律法规（如《网络安全法》《个人信息保护法》等）
- 不得用于任何侵入他人设备、窃取数据等违法用途

本软件按"现状"（AS IS）提供，不附带任何明示或暗示的担保。作者不对任何因使用本软件造成的直接或间接损失承担责任。

