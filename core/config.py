import os
import json
from typing import List, Dict

# 优先使用项目目录下的 config 文件夹，fallback 到用户主目录
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CONFIG_DIR = os.path.join(_PROJECT_ROOT, "config")
if os.path.isdir(_CONFIG_DIR) and os.access(_CONFIG_DIR, os.W_OK):
    CONFIG_FILE = os.path.join(_CONFIG_DIR, "commands.json")
else:
    CONFIG_FILE = os.path.join(os.path.expanduser("~"), ".adb_visual_cmds.json")

DEFAULT_COMMANDS = [
    {"name": "Root权限", "cmd": "root"},
    {"name": "进入终端", "cmd": "shell"},
    {"name": "重新挂载系统", "cmd": "remount"},
    {"name": "查看设备", "cmd": "devices"},
]


def load_commands() -> List[Dict[str, str]]:
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
