import os
import sys
import json
import shutil
from typing import List, Dict

# ── 应用标识（版本号从这里统一管理） ──
APP_NAME = "aT"
APP_VERSION = "1.0.0"


def _app_config_dir() -> str:
    """用户配置目录：%APPDATA%/aT（Windows），随用户资料走，与程序目录解耦。

    配置放用户目录的原因：打包分发时同事替换整个程序文件夹不会丢命令；
    程序目录在 Program Files 等位置时也可能没有写权限。
    """
    appdata = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(appdata, APP_NAME)


# 用户配置文件（唯一写入位置）
CONFIG_FILE = os.path.join(_app_config_dir(), "commands.json")


def _legacy_config_candidates() -> List[str]:
    """旧版本可能存放 commands.json 的位置，按优先级排列（用于一次性迁移）。"""
    candidates = []
    # 1) 开发环境 / 旧打包版：程序目录下的 config/commands.json
    #    frozen 时 __file__ 位于 _internal/adbtools/core/，_PROJECT_ROOT 即 _internal/
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidates.append(os.path.join(project_root, "config", "commands.json"))
    # 2) 更早版本的用户主目录散文件
    candidates.append(os.path.join(os.path.expanduser("~"), ".adb_visual_cmds.json"))
    return candidates


def _migrate_legacy_config():
    """首次运行时把旧位置的命令配置迁移到用户目录（仅在目标不存在时执行）。"""
    if os.path.exists(CONFIG_FILE):
        return
    for legacy in _legacy_config_candidates():
        try:
            if os.path.isfile(legacy):
                os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
                shutil.copyfile(legacy, CONFIG_FILE)
                return
        except OSError:
            continue


DEFAULT_COMMANDS = [
    {"name": "Root权限", "cmd": "root"},
    {"name": "进入终端", "cmd": "shell"},
    {"name": "重新挂载系统", "cmd": "remount"},
    {"name": "查看设备", "cmd": "devices"},
]


def load_commands() -> List[Dict[str, str]]:
    _migrate_legacy_config()
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return list(DEFAULT_COMMANDS)


def save_commands(commands: List[Dict[str, str]]) -> bool:
    try:
        # 确保目标目录存在
        target_dir = os.path.dirname(CONFIG_FILE)
        if target_dir and not os.path.isdir(target_dir):
            os.makedirs(target_dir, exist_ok=True)
        # 用临时文件 + replace 的方式原子写入，避免杀毒软件/同步工具锁定
        tmp = CONFIG_FILE + ".tmp"
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(commands, f, ensure_ascii=False, indent=4)
        os.replace(tmp, CONFIG_FILE)
        return True
    except OSError:
        return False
