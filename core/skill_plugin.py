"""SkillPlugin — 技能插件基类 + SkillRegistry 扫描注册。

架构思路：
- PluginContext: 把主窗口持有的共享资源打包传给插件，插件之间隔离。
- SkillPlugin: 每个技能是一个独立类，继承基类，声明 metadata（name, category, supported_devices）。
- SkillRegistry: 自动扫描所有 SkillPlugin 子类，按设备类型过滤，构建 UI 卡片。

新增 BSP 功能的路径：
  1. 新增一个文件（如 core/skills/thermal_monitor.py）
  2. class ThermalMonitorPlugin(SkillPlugin): ...
  3. Registry._scan() 会自动发现它，无需改主框架。
"""

import abc
import inspect
from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional, Type

from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QWidget


# ──────────────────── 设备类型常量 ────────────────────

DEVICE_EMULATOR = "emulator"       # 模拟器
DEVICE_REAL = "real_device"        # 真机
DEVICE_ANY = "any"                 # 都支持


# ──────────────────── PluginContext ────────────────────

@dataclass
class PluginContext:
    """所有插件共享的依赖注入容器。

    插件通过 ctx.adb_runner / ctx.get_serial_cb 等访问共享资源，
    不直接 import AdbTool 主窗口。
    """

    # ADB 层
    adb_client: Any = None          # AdbClient
    adb_runner: Any = None          # AdbRunner（高层 facade）

    # 服务层
    logcat_service: Any = None      # LogcatService
    scrcpy_service: Any = None      # ScrcpyService
    terminal_service: Any = None    # TerminalService
    file_service: Any = None        # FileService
    system_monitor: Any = None      # SystemMonitorService
    display_service: Any = None     # DisplayService（多屏枚举 + 别名管理）

    # 回调（无参或返回当前值）
    get_serial_cb: Optional[Callable[[], Optional[str]]] = None
    get_current_device_info_cb: Optional[Callable[[], Any]] = None   # 返回 DeviceInfo

    # 宿主 UI 钩子
    main_window: Optional[QWidget] = None   # 尽量避免用；但某些功能必须
    on_terminal_msg: Optional[Callable[[str, str], None]] = None  # (msg, color)

    # 设备类型缓存（Registry 在设备切换时刷新）
    is_emulator: bool = False
    thermal_available: bool = False


# ──────────────────── SkillPlugin 基类 ────────────────────

class SkillPlugin(abc.ABC):
    """技能插件抽象基类。

    子类必须声明：
      - name: str              卡片显示文本
      - icon_name: str         theme.Icons.xxx 里的 key（如 "screen-mirror"）
      - category: str          "应用层" / "BSP" / "通用" — 用于后续分类展示
      - supported_devices: list  ["emulator", "real_device"] 或 ["any"]

    可选实现：
      - on_activate(): 卡片点击时回调
      - get_panel():   返回 QWidget，会放入右侧 StackedWidget
      - on_device_changed(is_emulator): 设备切换时通知

    子类实例化时会自动拿到 context。
    """

    # 元数据（子类必须覆盖）
    name: str = ""
    icon_name: str = ""
    category: str = "通用"
    supported_devices: List[str] = ["any"]

    def __init__(self, context: PluginContext):
        self.ctx = context

    # ── 可选扩展点 ──

    def on_activate(self):
        """用户点击卡片时调用。默认空实现。"""
        pass

    def get_panel(self) -> Optional[QWidget]:
        """返回右侧面板 QWidget。返回 None 表示这是「点击即执行」型插件（如安装 APK）。"""
        return None

    def on_device_changed(self, is_emulator: bool, thermal_available: bool):
        """设备类型变化时回调（可选覆盖）。"""
        pass

    # ── 工具方法 ──

    def is_supported_on(self, is_emulator: bool) -> bool:
        """检查当前设备类型是否在支持列表中。"""
        if "any" in self.supported_devices:
            return True
        dev_type = DEVICE_EMULATOR if is_emulator else DEVICE_REAL
        return dev_type in self.supported_devices


# ──────────────────── SkillRegistry ────────────────────

class SkillRegistry:
    """自动扫描 SkillPlugin 子类并管理注册。

    用法（在 main_window 中）：
        registry = SkillRegistry(context)
        registry.scan()               # 扫描所有已导入模块中的 SkillPlugin 子类
        registry.set_device(is_emulator, thermal_available)
        plugins = registry.visible_plugins()  # 按设备类型过滤后的插件列表
        registry.build_skill_cards(grid_layout, stacked_widget)  # 构建 UI
    """

    def __init__(self, context: PluginContext):
        self.ctx = context
        self._plugins: List[SkillPlugin] = []
        self._plugin_classes: List[Type[SkillPlugin]] = []

    # ── 扫描 ──

    def scan(self):
        """扫描所有 SkillPlugin 子类。

        优先用 pkgutil.iter_modules 扫描 core/skills/ 包目录（自动发现未来新增插件）；
        兜底遍历 sys.modules 中已导入模块。

        匹配条件：
          - issubclass(cls, SkillPlugin)
          - cls 不是 SkillPlugin 本身
          - cls.name 非空
        """
        import sys

        candidates = set()

        # 1. pkgutil 扫描 skills 包目录
        try:
            import pkgutil
            import importlib
            skills_pkg = __import__(self.__class__.__module__.rsplit('.', 1)[0] + '.skills', fromlist=[''])
            if hasattr(skills_pkg, '__path__'):
                for _, modname, _ in pkgutil.iter_modules(skills_pkg.__path__):
                    try:
                        mod = importlib.import_module(f"{skills_pkg.__name__}.{modname}")
                        for _, obj in inspect.getmembers(mod, inspect.isclass):
                            if (
                                issubclass(obj, SkillPlugin)
                                and obj is not SkillPlugin
                                and getattr(obj, "name", "")
                            ):
                                candidates.add(obj)
                    except Exception:
                        continue
        except Exception:
            pass

        # 2. 兜底：sys.modules 已导入模块
        for module in list(sys.modules.values()):
            if module is None:
                continue
            try:
                for _, obj in inspect.getmembers(module, inspect.isclass):
                    if (
                        issubclass(obj, SkillPlugin)
                        and obj is not SkillPlugin
                        and getattr(obj, "name", "")
                    ):
                        candidates.add(obj)
            except Exception:
                continue

        self._plugin_classes = list(candidates)
        self._instantiate_all()

    def _instantiate_all(self):
        """为所有扫描到的类创建实例，并按 order 属性排序。"""
        self._plugin_classes.sort(key=lambda cls: getattr(cls, 'order', 999))
        self._plugins = [cls(self.ctx) for cls in self._plugin_classes]

    # ── 设备感知 ──

    def set_device(self, is_emulator: bool, thermal_available: bool):
        """设备类型变化时调用。更新 context 并通知所有插件。"""
        self.ctx.is_emulator = is_emulator
        self.ctx.thermal_available = thermal_available
        for p in self._plugins:
            p.on_device_changed(is_emulator, thermal_available)

    def visible_plugins(self) -> List[SkillPlugin]:
        """按当前设备类型过滤后的插件列表。"""
        return [p for p in self._plugins if p.is_supported_on(self.ctx.is_emulator)]

    # ── UI 构建 ──

    def build_skill_cards(self, grid_layout, stacked_widget, main_window_ref):
        """把 visible 插件渲染成 QToolButton 卡片 + QStackedWidget 面板。

        维护独立的 plugin_idx 和 panel_idx：
          - plugin_idx: 按钮在 grid 中的位置（用来高亮）
          - panel_idx: 右侧面板在 stacked_widget 中的位置（只有 get_panel()!=None 时才递增）
        点击即执行型插件（get_panel=None）不会引起 panel_idx 偏移。

        返回：(button_list, panel_list)
        """
        from PyQt5.QtCore import Qt
        from PyQt5.QtWidgets import QToolButton

        from ..ui.theme import IconHelper, Icons, skill_item_style

        visible = self.visible_plugins()
        buttons: List[QToolButton] = []
        panels: List[QWidget] = []

        panel_idx = 0  # 独立于 plugin_idx

        for plugin_idx, plugin in enumerate(visible):
            # 解析 icon
            icon_enum = getattr(Icons, plugin.icon_name.upper(), None) if plugin.icon_name else None
            icon_size = 32 if ("APK" in plugin.name or "安装" in plugin.name or "卸载" in plugin.name) else 28

            btn = QToolButton()
            btn.setText(plugin.name)
            if icon_enum is not None:
                btn.setIcon(IconHelper.icon(icon_enum, icon_size))
            btn.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            btn.setStyleSheet(skill_item_style(active=(plugin_idx == 0)))
            btn.setMinimumHeight(72)
            btn.setToolTip(f"[{plugin.category}] {plugin.name}")

            panel = plugin.get_panel()
            has_panel = panel is not None

            # 点击事件
            def _make_click(plg=plugin, pi=plugin_idx, has_p=has_panel, si=panel_idx):
                def _on_click():
                    plg.on_activate()
                    if has_p:
                        stacked_widget.setCurrentIndex(si)
                        main_window_ref._highlight_skill(pi)
                    else:
                        # 无面板型插件：保持第一个插件高亮
                        main_window_ref._highlight_skill(0)
                return _on_click
            btn.clicked.connect(_make_click())

            buttons.append(btn)
            grid_layout.addWidget(btn)

            # 面板（只有 get_panel()!=None 时才占 stacked_widget 索引）
            panels.append(panel)
            if has_panel:
                stacked_widget.addWidget(panel)
                panel_idx += 1

        return buttons, panels
