# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for ADB Visual Tool
# 构建命令（在项目根目录执行）：
#   venv\Scripts\pyinstaller.exe adb_gui_interactive.spec --clean
#   或
#   venv\Scripts\pyinstaller.exe adb_gui_interactive.py --name aT --noconsole --onedir --add-data "dist;dist" --icon=your_icon.ico
#
# 打包后目录结构：
#   aT.exe
#   dist/                          ← 运行时 adb/scrcpy 二进制 + DLLs
#     ├── adb.exe
#     ├── scrcpy.exe
#     ├── scrcpy-server
#     ├── SDL3.dll
#     ├── avcodec-62.dll
#     ├── avformat-62.dll
#     └── ... 其他 platform-tools / scrcpy 运行时文件
#   PyQt5 的 DLL/QML/translations 会被 PyInstaller 自动收集


import os
import sys

block_cipher = None


def collect_runtime_files():
    """收集项目根目录下所有 adb/scrcpy 运行时文件（adb.exe、scrcpy.exe、DLLs 等）。"""
    base = os.path.abspath(SPECPATH)
    # 要收集的根目录（与 spec 文件同级，即项目根目录）
    runtime_files = [
        'adb.exe', 'AdbWinApi.dll', 'AdbWinUsbApi.dll',
        'fastboot.exe', 'etc1tool.exe', 'hprof-conv.exe',
        'sqlite3.exe', 'libwinpthread-1.dll', 'libusb-1.0.dll',
        'mke2fs.exe', 'mke2fs.conf', 'make_f2fs.exe', 'make_f2fs_casefold.exe',
        'source.properties',
        'scrcpy.exe', 'scrcpy-server', 'scrcpy-noconsole.vbs', 'scrcpy.png',
        'SDL3.dll', 'avcodec-62.dll', 'avformat-62.dll', 'avutil-60.dll',
        'swresample-6.dll',
        'disconnected.png',
        'LICENSE.txt', 'NOTICE.txt', 'README.md',
        'open_a_terminal_here.bat',
    ]
    result = []
    for fname in runtime_files:
        fpath = os.path.join(base, fname)
        if os.path.isfile(fpath):
            # 所有文件打包到 dist/ 子目录（相对 sys.executable）
            result.append((fpath, 'dist'))
        else:
            # 同时尝试 platform-tools/platform-tools/ 子目录
            alt_path = os.path.join(base, 'platform-tools', 'platform-tools', fname)
            if os.path.isfile(alt_path):
                result.append((alt_path, 'dist'))
    # 额外检查 platform-tools 目录下的所有文件
    pt_dir = os.path.join(base, 'platform-tools', 'platform-tools')
    if os.path.isdir(pt_dir):
        for fname in os.listdir(pt_dir):
            fpath = os.path.join(pt_dir, fname)
            if os.path.isfile(fpath):
                already = any(p[0] == fpath for p in result)
                if not already:
                    result.append((fpath, 'dist'))
    print(f"[INFO] 收集到 {len(result)} 个运行时文件")
    return result


def collect_pyqt5_translations():
    """收集 PyQt5 中文翻译文件。"""
    try:
        import PyQt5.QtCore
        qt_dir = os.path.dirname(PyQt5.QtCore.__file__)
        translations_dir = os.path.join(qt_dir, 'translations')
        if not os.path.isdir(translations_dir):
            return []
        result = []
        for fname in os.listdir(translations_dir):
            if fname.endswith('.qm'):
                result.append((
                    os.path.join(translations_dir, fname),
                    'PyQt5/Qt5/translations'
                ))
        return result
    except Exception:
        return []


def collect_ui_assets():
    """收集 UI 资源（像素字体 TTF + SVG 图标）到 adbtools/ui/assets 下，
    与 theme.py 的 _asset_path() 冻结路径解析保持一致。"""
    base = os.path.abspath(SPECPATH)
    result = []
    for sub in ('fonts', 'icons'):
        src_dir = os.path.join(base, 'ui', 'assets', sub)
        if not os.path.isdir(src_dir):
            continue
        for fname in os.listdir(src_dir):
            fpath = os.path.join(src_dir, fname)
            if os.path.isfile(fpath):
                result.append((fpath, os.path.join('adbtools', 'ui', 'assets', sub)))
    print(f"[INFO] 收集到 {len(result)} 个 UI 资源文件（字体/图标）")
    return result


def collect_config_files():
    """收集 config/ 目录（commands.json 等用户自定义命令配置）。"""
    base = os.path.abspath(SPECPATH)
    cfg_dir = os.path.join(base, 'config')
    result = []
    if os.path.isdir(cfg_dir):
        for fname in os.listdir(cfg_dir):
            fpath = os.path.join(cfg_dir, fname)
            if os.path.isfile(fpath):
                result.append((fpath, os.path.join('adbtools', 'config')))
    print(f"[INFO] 收集到 {len(result)} 个配置文件")
    return result


# adbtools 包的父目录：入口脚本通过 sys.path 注入上一级来 import adbtools.*
# SPECPATH = d:/testpy/adbtools/adbtools → 父目录 d:/testpy/adbtools 才是 adbtools 包所在位置
_package_parent = os.path.dirname(os.path.abspath(SPECPATH))

a = Analysis(
    ['adb_gui_interactive.py'],
    pathex=[_package_parent],
    binaries=collect_runtime_files(),
    datas=collect_pyqt5_translations() + collect_ui_assets() + collect_config_files(),
    hiddenimports=[
        # PyQt5 相关
        'PyQt5.QtCore',
        'PyQt5.QtGui',
        'PyQt5.QtWidgets',
        'PyQt5.QtSvg',
        'PyQt5.QtNetwork',
        'PyQt5.QtXml',
        # adbtools 顶层与 core 子包
        'adbtools',
        'adbtools.core',
        'adbtools.core.adb_client',
        'adbtools.core.adb_runner',
        'adbtools.core.config',
        'adbtools.core.utils',
        'adbtools.core.skill_plugin',
        # adbtools core.skills 子包（多屏架构 + 技能卡片）
        'adbtools.core.skills',
        'adbtools.core.skills.builtin',
        # adbtools services 子包
        'adbtools.services',
        'adbtools.services.device_service',
        'adbtools.services.display_service',
        'adbtools.services.file_service',
        'adbtools.services.logcat_service',
        'adbtools.services.scrcpy_service',
        'adbtools.services.terminal_service',
        'adbtools.services.system_monitor_service',
        # adbtools ui 子包
        'adbtools.ui',
        'adbtools.ui.main_window',
        'adbtools.ui.theme',
        'adbtools.ui.panels',
        'adbtools.ui.panels.file_explorer',
        'adbtools.ui.panels.logcat_panel',
        'adbtools.ui.panels.scrcpy_control_panel',
        'adbtools.ui.panels.terminal_tab',
        'adbtools.ui.dialogs',
        'adbtools.ui.dialogs.create_path_dialog',
        'adbtools.ui.dialogs.dialog_styles',
        'adbtools.ui.dialogs.rename_dialog',
        'adbtools.ui.widgets',
        'adbtools.ui.widgets.command_manager_dialog',
        'adbtools.ui.widgets.console_edit',
        'adbtools.ui.widgets.file_tree_widget',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib',
        'numpy',
        'pandas',
        'PIL',
        'tkinter',
        'unittest',
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

# ================= OneDir 目录模式 =================
# EXE 只接收引导脚本（不含 binaries/datas），体积小、启动快；
# COLLECT 再把 exe + dll + qt 翻译 + adb/scrcpy 运行时一起收集到输出目录。
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,          # OneDir 关键：把 DLL 交给 COLLECT
    name='aT',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,                  # 无黑框（GUI 模式）
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

# 所有运行时文件（PyQt5 DLL/翻译、adb/scrcpy 二进制+DLL）收集到 ADBVisualTool 子目录
# 最终产物路径：dist/ADBVisualTool/ADBVisualTool.exe + 同级 dist/ 子目录放 adb.exe 等
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='aT',
)
