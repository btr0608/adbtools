"""
ADB Visual Tool - 像素/轻复古游戏风主题系统

设计原则：
- 长时间使用不眼酸：暖灰底、低对比、柔和强调色
- 像素/轻复古：硬边小圆角（2px）、清晰粗边框、硬阴影
- 功能图标一眼可识别：统一 SVG 像素图标
"""

import os

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont, QFontDatabase, QIcon, QPainter, QPixmap
from PyQt5.QtSvg import QSvgRenderer
from PyQt5.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget


# ===== 资源路径 =====
def _asset_path(*parts: str) -> str:
    """返回 ui/assets 下某个资源的绝对路径。

    兼容三种运行环境：
    - 源码运行：ui/theme.py 同级 assets
    - PyInstaller onedir/onefile：资源被收集到 _MEIPASS/adbtools/ui/assets
    """
    candidates = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets"),
    ]
    meipass = getattr(__import__("sys"), "_MEIPASS", None)
    if meipass:
        candidates.append(os.path.join(meipass, "adbtools", "ui", "assets"))
        candidates.append(os.path.join(meipass, "ui", "assets"))
    for base in candidates:
        full = os.path.join(base, *parts)
        if os.path.exists(full):
            return full
    return os.path.join(candidates[0], *parts)


# ===== 调色板（柔和暖调）=====
class Palette:
    BG = "#F5F1E8"              # 主背景：暖米色
    SURFACE = "#FAF8F2"         # 卡片/面板表面
    SURFACE_DARK = "#EFEBE0"    # 次级表面（输入框、工具栏）
    BORDER = "#D8D4C8"          # 边框
    BORDER_STRONG = "#A9A59A"   # 粗边框
    DIVIDER = "#E0DCD0"         # 分隔线

    TEXT = "#4A4A48"            # 主文字
    TEXT_DIM = "#7A7A78"        # 次要文字
    TEXT_LIGHT = "#A9A59A"      # 禁用/占位文字
    TEXT_DARK = "#5A4A32"       # 深棕文字（次要按钮文字、选中竖条）
    TEXT_BTN = "#3A2F1E"        # 更深棕（次要按钮文字：灰底上保证对比度）

    PRIMARY = "#8FA878"         # 主色：橄榄绿（主操作按钮）
    PRIMARY_DARK = "#6E8A5A"
    PRIMARY_HOVER = "#7D9868"
    PRIMARY_LIGHT = "#E8F0DF"

    SECONDARY = "#D6CFB8"       # 次色：米灰（次要按钮）
    SECONDARY_DARK = "#C9C1AA"
    SECONDARY_HOVER = "#CBC3A8"
    SECONDARY_LIGHT = "#EDE8D8"

    ACCENT = "#D4A373"          # 点缀：暖棕/琥珀
    ACCENT_DARK = "#B08352"
    ACCENT_HOVER = "#C29364"

    SUCCESS = "#8FB996"         # 成功：柔和绿（投屏连接等）
    SUCCESS_DARK = "#6E9676"
    SUCCESS_HOVER = "#7DA883"
    SUCCESS_LIGHT = "#E8F3EA"

    WARNING = "#E9C46A"         # 警告：柔和黄
    WARNING_HOVER = "#D8B55C"

    ERROR = "#C97B63"           # 危险：砖红（断开/停止/删除）
    ERROR_DARK = "#A75E48"
    ERROR_HOVER = "#B86A55"
    ERROR_LIGHT = "#F5E6DD"

    TERMINAL_BG = "#2D2C2A"
    TERMINAL_TEXT = "#D8D4C8"

    # 选中/高亮
    SELECT_BG = "#D8CFAE"       # 文件列表选中行（米黄加深一档）
    SELECT_STRIPE = "#5A4A32"   # 选中行左侧深棕竖条


# ===== 字体栈 =====
# 像素风策略：
# - Zpix（最像素）同时覆盖中文和拉丁像素字形 → 全局正文字体
# - Press Start 2P 仅用于纯拉丁装饰标题（无中文字形）
# - VT323 用于终端等大量拉丁/数字的等宽场景
# - 微软雅黑作为像素字体缺失时的中文安全回退
class Fonts:
    """QSS 字体栈。"""
    UI = (
        '"Zpix", "Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC", '
        '"Noto Sans CJK SC", sans-serif'
    )
    MONO = (
        '"VT323", "Zpix", "Consolas", "JetBrains Mono", "Fira Code", '
        '"Courier New", "Microsoft YaHei UI", monospace'
    )


# 全局界面字体候选（按优先级）：
# Zpix 是含完整常用中文的像素字体（已 bundled 到 ui/assets/fonts），
# 中文界面走像素风；其加载失败时降级为微软雅黑保证可读性。
_UI_FONT_CANDIDATES = (
    "Zpix",
    "Microsoft YaHei UI",
    "Microsoft YaHei",
    "PingFang SC",
    "Noto Sans CJK SC",
    "Noto Sans SC",
    "SimHei",            # 黑体兜底（不要回退到 JhengHei 繁体字体）
)
# 像素标题字体候选（Press Start 2P，仅拉丁字符）
_TITLE_FONT_CANDIDATES = (
    "Press Start 2P (SMBTLL Version)",
    "Press Start 2P",
)

# 像素正文字体候选（VT323，可读像素字体，仍只用于纯拉丁文本）
_PIXEL_ASCII_FONT_CANDIDATES = (
    "VT323",
)

_loaded_pixel_families: list = []
_loaded_fonts_ready = False


def _load_bundled_fonts():
    """加载本地 fonts 目录下的 TTF 字体，返回成功加载的 family 列表。"""
    loaded = []
    fonts_dir = _asset_path("fonts")
    if not os.path.isdir(fonts_dir):
        return loaded
    for fname in sorted(os.listdir(fonts_dir)):
        if not fname.lower().endswith(".ttf"):
            continue
        path = os.path.join(fonts_dir, fname)
        try:
            fid = QFontDatabase.addApplicationFont(path)
            if fid >= 0:
                loaded.extend(QFontDatabase.applicationFontFamilies(fid))
        except Exception:
            continue
    return loaded


def _ensure_fonts_loaded():
    global _loaded_fonts_ready, _loaded_pixel_families
    if not _loaded_fonts_ready:
        _loaded_pixel_families = _load_bundled_fonts()
        _loaded_fonts_ready = True


def _first_available_family(candidates) -> str:
    """返回系统/已加载字体中第一个可用的 family；都不可用时返回空串。"""
    _ensure_fonts_loaded()
    available = set(QFontDatabase().families()) | set(_loaded_pixel_families)
    for name in candidates:
        if name in available:
            return name
    return ""


def _make_pixel_font(family_name: str, point_size: int) -> QFont:
    """统一的像素字体工厂。

    PyQt5 StyleStrategy 枚举陷阱：
      PreferDefault      = 1  (低3位的首选策略)
      PreferBitmap       = 2
      PreferDevice       = 4
      NoAntialias        = 256  (高位附加标志)
      NoSubpixelAntialias= 2048
    必须同时设置"低位首选策略" + "高位附加标志"，低位为 0 时 Qt 会忽略高位。
    这里用 PreferBitmap（强制使用字体 bitmap 字形 / monochrome rasterize）
    配合 NoAntialias + NoSubpixelAntialias，彻底关闭灰度和 subpixel 渲染。
    """
    font = QFont(family_name, point_size)
    font.setStyleHint(QFont.Monospace)
    font.setStyleStrategy(
        QFont.PreferBitmap | QFont.NoAntialias | QFont.NoSubpixelAntialias
    )
    # 像素字体没有 bold 变体，Qt 合成 bold 会糊 → 关闭
    font.setBold(False)
    return font


def apply_app_font(app, family: str = None, point_size: int = 9) -> None:
    """设置 QApplication 全局字体。

    默认使用 Zpix（含中文的像素字体，9pt 对应其 12px 设计网格，
    像素边缘最锐利）；Zpix 不可用时回退微软雅黑保证中文可读。
    """
    _ensure_fonts_loaded()
    family_name = family or _first_available_family(_UI_FONT_CANDIDATES) or "SansSerif"
    if family_name in ("Zpix", "VT323", "Press Start 2P (SMBTLL Version)", "Press Start 2P"):
        app.setFont(_make_pixel_font(family_name, point_size))
        return
    # 非像素字体（回退到系统字体时）：保留默认策略
    font = QFont(family_name, point_size)
    font.setStyleHint(QFont.SansSerif)
    app.setFont(font)


def title_font(point_size: int = 9) -> QFont:
    """像素标题字体（Press Start 2P）。

    仅用于纯拉丁文本（如 "ADB VISUAL TOOL"、"SYSTEM HP"）；
    未加载成功时回退到 Zpix 像素字体。
    """
    name = _first_available_family(_TITLE_FONT_CANDIDATES)
    if name:
        return _make_pixel_font(name, point_size)
    return cjk_title_font(point_size)


def cjk_title_font(point_size: int = 10) -> QFont:
    """中文像素标题字体（Zpix）。

    用于含中文的标题（如"已连接设备"、"技能"），保持像素风；
    Zpix 不可用时回退雅黑粗体（系统字体才允许 bold）。
    """
    name = _first_available_family(("Zpix",))
    if name:
        # 像素字体不做 bold（没有 bold 变体），让字号本身表达"标题感"
        return _make_pixel_font(name, point_size)
    # 回退到系统字体时保留 bold（系统字体有粗体变体）
    font = QFont(_first_available_family(_UI_FONT_CANDIDATES) or "SansSerif", point_size)
    font.setBold(True)
    return font


def pixel_ascii_font(point_size: int = 10) -> QFont:
    """可读像素字体（VT323），用于纯拉丁文本标签。"""
    name = _first_available_family(_PIXEL_ASCII_FONT_CANDIDATES)
    if name:
        return _make_pixel_font(name, point_size)
    font = QFont(_first_available_family(_UI_FONT_CANDIDATES) or "SansSerif", point_size)
    return font


# 向后兼容别名：旧代码调用 pixel_font() 的地方均为纯拉丁标题
pixel_font = title_font


# ===== 图标辅助类 =====
class IconHelper:
    """加载 ui/assets/icons/*.svg 并通过 QSvgRenderer 渲染成 QIcon/QPixmap。"""

    _cache = {}

    @classmethod
    def path(cls, name: str) -> str:
        return _asset_path("icons", f"{name}.svg")

    @classmethod
    def pixmap(cls, name: str, size: int = 16, color: str = None) -> QPixmap:
        cache_key = (name, size, color)
        if cache_key in cls._cache:
            return cls._cache[cache_key]

        path = cls.path(name)
        if not os.path.exists(path):
            pm = QPixmap(size, size)
            pm.fill(Qt.transparent)
            cls._cache[cache_key] = pm
            return pm

        # 如果指定了颜色，把 SVG 里的 currentColor 替换为指定色
        svg_bytes = None
        if color:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    svg_text = f.read().replace("currentColor", color)
                svg_bytes = svg_text.encode("utf-8")
            except Exception:
                svg_bytes = None

        renderer = QSvgRenderer(svg_bytes) if svg_bytes else QSvgRenderer(path)
        pm = QPixmap(size, size)
        pm.fill(Qt.transparent)
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.Antialiasing, False)
        renderer.render(painter)
        painter.end()
        cls._cache[cache_key] = pm
        return pm

    @classmethod
    def icon(cls, name: str, size: int = 16) -> QIcon:
        """返回 QIcon；可配合 QSS 的 icon-size 使用。"""
        pm = cls.pixmap(name, size)
        return QIcon(pm)


# ===== 语义化图标字典 =====
class Icons:
    """统一图标名称；UI 代码应通过 IconHelper.icon/name 使用。"""
    DEVICE = "device"
    REFRESH = "refresh"
    WIRELESS = "wireless"
    CONNECT = "connect"
    TERMINAL = "terminal"
    NEW_TERMINAL = "plus"
    SCREEN_MIRROR = "screen"
    LOGCAT = "logcat"
    FILE = "file"
    FOLDER = "folder"
    UPLOAD = "upload"
    DOWNLOAD = "download"
    RENAME = "edit"
    DELETE = "trash"
    SEARCH = "search"
    SETTINGS = "gear"
    PLAY = "play"
    STOP = "stop"
    RECORD = "bolt"
    ROOT = "play"
    SHELL = "play"
    REMOUNT = "play"
    DEVICES = "device"
    HOME = "folder"
    UP = "up"
    HELP = "gear"
    SAVE = "check"
    ADD = "plus"
    EDIT = "edit"
    MOVE_UP = "up"
    MOVE_DOWN = "download"
    CLOSE = "close"
    CHECK = "check"
    WARNING = "bolt"
    LOCK = "bolt"
    BOLT = "bolt"
    WINDOW_MIN = "window-min"
    WINDOW_MAX = "window-max"
    WINDOW_RESTORE = "window-restore"
    TOOLBOX_PLUS = "toolbox-plus"
    TOOLBOX_MINUS = "toolbox-minus"
    CAMERA = "camera"
    APP_BOX = "app-box"


# ===== 像素按钮工厂 =====
def _pixel_button_qss(
    bg: str,
    hover: str,
    text: str = Palette.TEXT_DARK,
    border: str = None,
    radius: str = "2px",
    padding: str = "0px 12px",
    icon_size: str = "16px"
) -> str:
    border_color = border or bg
    # Qt QSS border 是 content-box（边框画在 min-height 外面），
    # 所以 min-height 设 26px + 3px×2 border = 32px 总高
    return (
        f"QPushButton {{\n"
        f"  background-color: {bg};\n"
        f"  color: {text};\n"
        f"  border: 3px solid {border_color};\n"
        f"  border-radius: {radius};\n"
        f"  padding: {padding};\n"
        f"  min-height: 26px;\n"
        f"  max-height: 26px;\n"
        f"  icon-size: {icon_size};\n"
        f"  outline: none;\n"
        f"}}\n"
        f"QPushButton:hover {{\n"
        f"  background-color: {hover};\n"
        f"}}\n"
        f"QPushButton:pressed {{\n"
        f"  background-color: {hover};\n"
        f"}}\n"
        f"QPushButton:disabled {{\n"
        f"  background-color: {Palette.SURFACE_DARK};\n"
        f"  color: {Palette.TEXT_LIGHT};\n"
        f"  border-color: {Palette.BORDER};\n"
        f"}}"
    )


def _ghost_button_qss(
    text: str = Palette.TEXT_BTN,
    border: str = Palette.BORDER_STRONG,
    hover_bg: str = Palette.SURFACE_DARK,
    padding: str = "0px 12px",
    icon_size: str = "16px"
) -> str:
    # 同 _pixel_button_qss：min-height 26px + 3px×2 border = 32px 总高
    return (
        f"QPushButton {{\n"
        f"  background-color: transparent;\n"
        f"  color: {text};\n"
        f"  border: 3px solid {border};\n"
        f"  border-radius: 2px;\n"
        f"  padding: {padding};\n"
        f"  min-height: 26px;\n"
        f"  max-height: 26px;\n"
        f"  icon-size: {icon_size};\n"
        f"  outline: none;\n"
        f"}}\n"
        f"QPushButton:hover {{\n"
        f"  background-color: {hover_bg};\n"
        f"}}\n"
        f"QPushButton:pressed {{\n"
        f"  background-color: {hover_bg};\n"
        f"}}\n"
        f"QPushButton:disabled {{\n"
        f"  color: {Palette.TEXT_LIGHT};\n"
        f"  border-color: {Palette.BORDER};\n"
        f"}}"
    )


def _input_qss() -> str:
    return (
        f"QLineEdit, QComboBox, QSpinBox {{\n"
        f"  background-color: {Palette.SURFACE};\n"
        f"  color: {Palette.TEXT};\n"
        f"  border: 3px solid {Palette.BORDER_STRONG};\n"
        f"  border-radius: 2px;\n"
        f"  padding: 0px 8px;\n"
        f"  min-height: 26px;\n"
        f"  max-height: 26px;\n"
        f"  selection-background-color: {Palette.SECONDARY};\n"
        f"}}\n"
        f"QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{\n"
        f"  border-color: {Palette.PRIMARY};\n"
        f"}}\n"
        f"QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled {{\n"
        f"  background-color: {Palette.SURFACE_DARK};\n"
        f"  color: {Palette.TEXT_LIGHT};\n"
        f"}}\n"
        # SpinBox 上下小箭头按钮：控制高度避免撑高 SpinBox
        f"QSpinBox::up-button, QSpinBox::down-button {{\n"
        f"  width: 18px;\n"
        f"  height: 13px;\n"
        f"  border: none;\n"
        f"  background-color: {Palette.SURFACE_DARK};\n"
        f"}}\n"
        f"QSpinBox::up-button:hover, QSpinBox::down-button:hover {{\n"
        f"  background-color: {Palette.BORDER};\n"
        f"}}"
    )


def _combo_popup_qss() -> str:
    return (
        f"QComboBox::drop-down {{\n"
        f"  border: none;\n"
        f"  width: 24px;\n"
        f"}}\n"
        f"QComboBox::down-arrow {{\n"
        f"  image: none;\n"
        f"  border-left: 5px solid transparent;\n"
        f"  border-right: 5px solid transparent;\n"
        f"  border-top: 6px solid {Palette.TEXT_DIM};\n"
        f"  width: 0;\n"
        f"  height: 0;\n"
        f"}}\n"
        f"QComboBox QAbstractItemView {{\n"
        f"  background-color: {Palette.SURFACE};\n"
        f"  color: {Palette.TEXT};\n"
        f"  border: 3px solid {Palette.BORDER_STRONG};\n"
        f"  selection-background-color: {Palette.PRIMARY_LIGHT};\n"
        f"  selection-color: {Palette.TEXT};\n"
        f"}}"
    )


def _tree_qss() -> str:
    return (
        f"QTreeWidget {{\n"
        f"  background-color: transparent;\n"
        f"  color: {Palette.TEXT};\n"
        f"  border: none;\n"
        f"  font-family: {Fonts.UI};\n"
        f"  font-size: 9pt;\n"
        f"  outline: none;\n"
        f"}}\n"
        f"QTreeWidget::item {{\n"
        f"  padding: 4px 6px;\n"
        f"  border-bottom: 1px solid {Palette.DIVIDER};\n"
        f"}}\n"
        f"QTreeWidget::item:selected {{\n"
        f"  background-color: {Palette.SELECT_BG};\n"
        f"  color: {Palette.TEXT_DARK};\n"
        f"  border-left: 3px solid {Palette.SELECT_STRIPE};\n"
        f"}}\n"
        f"QTreeWidget::item:hover:!selected {{\n"
        f"  background-color: {Palette.SURFACE_DARK};\n"
        f"}}\n"
        f"QHeaderView {{\n"
        f"  background-color: transparent;\n"
        f"  border: none;\n"
        f"}}\n"
        f"QHeaderView::section {{\n"
        f"  background-color: {Palette.SURFACE_DARK};\n"
        f"  color: {Palette.TEXT_DIM};\n"
        f"  padding: 6px 8px;\n"
        f"  border: none;\n"
        f"  border-right: 1px solid {Palette.BORDER};\n"
        f"  border-bottom: 3px solid {Palette.BORDER_STRONG};\n"
        f"  font-weight: 700;\n"
        f"}}"
    )


def _progress_qss() -> str:
    return (
        f"QProgressBar {{\n"
        f"  background-color: {Palette.SURFACE_DARK};\n"
        f"  border: 2px solid {Palette.BORDER_STRONG};\n"
        f"  border-radius: 2px;\n"
        f"  text-align: center;\n"
        f"  color: {Palette.TEXT};\n"
        f"  font-size: 8pt;\n"
        f"}}\n"
        f"QProgressBar::chunk {{\n"
        f"  background-color: {Palette.PRIMARY};\n"
        f"  border-radius: 1px;\n"
        f"}}"
    )


def _scrollbar_qss() -> str:
    return (
        f"QScrollBar:vertical {{\n"
        f"  background-color: {Palette.SURFACE_DARK};\n"
        f"  width: 12px;\n"
        f"  border-radius: 2px;\n"
        f"}}\n"
        f"QScrollBar::handle:vertical {{\n"
        f"  background-color: {Palette.BORDER};\n"
        f"  min-height: 24px;\n"
        f"  border-radius: 2px;\n"
        f"  margin: 2px;\n"
        f"}}\n"
        f"QScrollBar::handle:vertical:hover {{\n"
        f"  background-color: {Palette.TEXT_DIM};\n"
        f"}}\n"
        f"QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{\n"
        f"  height: 0;\n"
        f"}}\n"
        f"QScrollBar:horizontal {{\n"
        f"  background-color: {Palette.SURFACE_DARK};\n"
        f"  height: 12px;\n"
        f"  border-radius: 2px;\n"
        f"}}\n"
        f"QScrollBar::handle:horizontal {{\n"
        f"  background-color: {Palette.BORDER};\n"
        f"  min-width: 24px;\n"
        f"  border-radius: 2px;\n"
        f"  margin: 2px;\n"
        f"}}\n"
        f"QScrollBar::handle:horizontal:hover {{\n"
        f"  background-color: {Palette.TEXT_DIM};\n"
        f"}}\n"
        f"QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{\n"
        f"  width: 0;\n"
        f"}}"
    )


def _menu_qss() -> str:
    return (
        f"QMenu {{\n"
        f"  background-color: {Palette.SURFACE};\n"
        f"  color: {Palette.TEXT};\n"
        f"  border: 3px solid {Palette.BORDER_STRONG};\n"
        f"  border-radius: 2px;\n"
        f"  padding: 4px;\n"
        f"}}\n"
        f"QMenu::item {{\n"
        f"  padding: 5px 18px;\n"
        f"  border-radius: 2px;\n"
        f"}}\n"
        f"QMenu::item:selected {{\n"
        f"  background-color: {Palette.PRIMARY_LIGHT};\n"
        f"  color: {Palette.TEXT};\n"
        f"}}\n"
        f"QMenu::separator {{\n"
        f"  height: 1px;\n"
        f"  background-color: {Palette.DIVIDER};\n"
        f"  margin: 4px 8px;\n"
        f"}}"
    )


def _checkbox_qss() -> str:
    check_icon = IconHelper.path("check").replace("\\", "/")
    return (
        f"QCheckBox {{\n"
        f"  color: {Palette.TEXT};\n"
        f"  font-family: {Fonts.UI};\n"
        f"  font-size: 9pt;\n"
        f"  spacing: 6px;\n"
        f"  min-height: 20px;\n"
        f"}}\n"
        f"QCheckBox::indicator {{\n"
        f"  width: 14px;\n"
        f"  height: 14px;\n"
        f"  border: 2px solid {Palette.TEXT_DARK};\n"
        f"  border-radius: 0px;\n"
        f"  background: transparent;\n"
        f"}}\n"
        f"QCheckBox::indicator:checked {{\n"
        f"  background: {Palette.PRIMARY};\n"
        f"  border: 2px solid {Palette.PRIMARY_DARK};\n"
        f"  image: url(\"{check_icon}\");\n"
        f"}}\n"
        f"QCheckBox::indicator:hover {{\n"
        f"  border-color: {Palette.PRIMARY};\n"
        f"}}"
    )


def _spinbox_qss() -> str:
    return (
        f"QSpinBox {{\n"
        f"  background-color: {Palette.SURFACE};\n"
        f"  color: {Palette.TEXT};\n"
        f"  border: 3px solid {Palette.BORDER_STRONG};\n"
        f"  border-radius: 2px;\n"
        f"  padding: 4px;\n"
        f"  font-family: {Fonts.UI};\n"
        f"  font-size: 9pt;\n"
        f"}}\n"
        f"QSpinBox::up-button, QSpinBox::down-button {{\n"
        f"  background-color: {Palette.SURFACE_DARK};\n"
        f"  border: 2px solid {Palette.BORDER};\n"
        f"  width: 18px;\n"
        f"}}\n"
        f"QSpinBox::up-button:hover, QSpinBox::down-button:hover {{\n"
        f"  background-color: {Palette.PRIMARY_LIGHT};\n"
        f"}}"
    )


# ===== 按钮样式工厂 =====
# 三色规则（与 Palette 对齐）：
#   primary  = 橄榄绿底(#8FA878) + 深棕字  → 主操作（连接、启动投屏、开始）
#   secondary= 米灰底(#D6CFB8)   + 深棕字  → 次要（shell、Root权限、管理命令）
#   success  = 柔绿底(#8FB996)   + 深棕字  → 成功状态
#   danger   = 砖红底(#C97B63)   + 白字    → 危险（断开、停止、强制结束）
class Buttons:
    @staticmethod
    def primary(text: str = None, padding: str = "0px 12px", icon_size: str = "16px") -> str:
        return _pixel_button_qss(
            Palette.PRIMARY, Palette.PRIMARY_HOVER,
            text=Palette.TEXT_DARK,
            border=Palette.PRIMARY_DARK,
            padding=padding, icon_size=icon_size,
        )

    @staticmethod
    def secondary(text: str = None, padding: str = "0px 12px", icon_size: str = "16px") -> str:
        return _pixel_button_qss(
            Palette.SECONDARY, Palette.SECONDARY_HOVER,
            text=Palette.TEXT_BTN,
            border=Palette.BORDER_STRONG,
            padding=padding, icon_size=icon_size,
        )

    @staticmethod
    def success(text: str = None, padding: str = "0px 12px", icon_size: str = "16px") -> str:
        return _pixel_button_qss(
            Palette.SUCCESS, Palette.SUCCESS_HOVER,
            text=Palette.TEXT_DARK,
            border=Palette.SUCCESS_DARK,
            padding=padding, icon_size=icon_size,
        )

    @staticmethod
    def danger(text: str = None, padding: str = "0px 12px", icon_size: str = "16px") -> str:
        return _pixel_button_qss(
            Palette.ERROR, Palette.ERROR_HOVER,
            text="white",
            border=Palette.ERROR_DARK,
            padding=padding, icon_size=icon_size,
        )

    @staticmethod
    def ghost(text: str = None, padding: str = "0px 12px", icon_size: str = "16px") -> str:
        return _ghost_button_qss(padding=padding, icon_size=icon_size)

    @staticmethod
    def danger_ghost(padding: str = "0px 12px", icon_size: str = "16px") -> str:
        return (
            _ghost_button_qss(
                text=Palette.ERROR_DARK,
                border=Palette.ERROR,
                hover_bg=Palette.ERROR,
                padding=padding,
                icon_size=icon_size
            ) + f"""
            QPushButton:hover {{
              color: white;
            }}"""
        )

    @staticmethod
    def icon_button(padding: str = "4px 8px", icon_size: str = "16px") -> str:
        return _ghost_button_qss(
            text=Palette.TEXT, border=Palette.BORDER,
            hover_bg=Palette.SURFACE_DARK, padding=padding, icon_size=icon_size
        )


# ===== 应用级全局 QSS =====
def app_stylesheet() -> str:
    """返回应设置在 QApplication 上的全局样式表。"""
    return (
        f"""
        /* 根窗口铺主背景；普通容器 QWidget 默认透明，避免卡片内层层涂色 */
        QMainWindow, QDialog {{
          background-color: {Palette.BG};
        }}

        QWidget {{
          color: {Palette.TEXT};
          font-size: 10pt;
          outline: none;
        }}

        QMainWindow::separator {{
          background-color: {Palette.BORDER};
          width: 2px;
          height: 2px;
        }}

        QStatusBar {{
          background-color: {Palette.SURFACE_DARK};
          color: {Palette.TEXT_DIM};
          border-top: 3px solid {Palette.BORDER_STRONG};
          padding: 4px 8px;
          font-size: 8pt;
        }}

        QStatusBar::item {{
          border: none;
        }}

        QLabel {{
          color: {Palette.TEXT};
          font-size: 10pt;
          background: transparent;
        }}

        QToolTip, QFrame#QTipLabel {{
          background-color: #3a3525;
          color: #ebe5d0;
          border: 1px solid #5a4a32;
          padding: 4px 8px;
          border-radius: 0;
          font-family: "Zpix";
          font-size: 12px;
        }}

        QToolTip QLabel {{
          background: transparent;
          color: #ebe5d0;
          border: none;
        }}

        /* ===== 像素卡片（属性选择器，只作用于卡片自身，不级联到子控件）===== */
        QWidget[pixelCard="card"] {{
          background-color: {Palette.SURFACE};
          border: 3px solid {Palette.BORDER_STRONG};
          border-radius: 2px;
        }}

        QWidget[pixelCard="titlebar"] {{
          background-color: {Palette.SURFACE_DARK};
          border: 3px solid {Palette.BORDER_STRONG};
          border-radius: 2px;
        }}

        QGroupBox {{
          border: 3px solid {Palette.BORDER_STRONG};
          border-radius: 2px;
          margin-top: 10px;
          padding-top: 10px;
          font-weight: 700;
        }}

        QGroupBox::title {{
          subcontrol-origin: margin;
          left: 8px;
          padding: 0 4px;
          color: {Palette.TEXT_DIM};
        }}

        QToolButton {{
          background-color: {Palette.SURFACE};
          color: {Palette.TEXT};
          border: 3px solid {Palette.BORDER_STRONG};
          border-radius: 2px;
          padding: 4px 8px;
          icon-size: 16px;
          font-family: {Fonts.UI};
          font-size: 9pt;
          font-weight: 700;
        }}

        QToolButton:hover {{
          background-color: {Palette.SURFACE_DARK};
        }}

        QToolButton::menu-indicator {{
          image: none;
          border-left: 4px solid transparent;
          border-right: 4px solid transparent;
          border-top: 5px solid {Palette.TEXT_DIM};
          width: 0;
          height: 0;
          subcontrol-origin: padding;
          subcontrol-position: right center;
          padding-right: 4px;
        }}

        QSplitter::handle {{
          background-color: {Palette.BORDER};
        }}

        QSplitter::handle:horizontal {{
          width: 4px;
        }}

        QSplitter::handle:vertical {{
          height: 4px;
        }}

        QMessageBox {{
          background-color: {Palette.SURFACE};
        }}

        QDialog {{
          background-color: {Palette.BG};
        }}

        /* ===== 终端标签页：像素卡片风 ===== */
        QTabWidget::pane {{
          background-color: {Palette.SURFACE};
          border: 3px solid {Palette.BORDER_STRONG};
          border-radius: 2px;
          top: -3px;
        }}

        QTabBar {{
          background: transparent;
        }}

        QTabBar::tab {{
          background-color: {Palette.SURFACE_DARK};
          color: {Palette.TEXT_DIM};
          border: 3px solid {Palette.BORDER_STRONG};
          border-bottom: none;
          border-top-left-radius: 2px;
          border-top-right-radius: 2px;
          padding: 6px 14px;
          margin-right: 6px;
          font-family: {Fonts.UI};
          font-size: 9pt;
          font-weight: 700;
        }}

        QTabBar::tab:selected {{
          background-color: {Palette.SURFACE};
          color: {Palette.PRIMARY_DARK};
        }}

        QTabBar::tab:hover:!selected {{
          background-color: {Palette.BORDER};
          color: {Palette.TEXT};
        }}

        QTabBar::close-button {{
          subcontrol-position: right;
          padding: 2px;
          border-radius: 2px;
        }}

        QTabBar::close-button:hover {{
          background-color: {Palette.ERROR_LIGHT};
        }}

        QPushButton {{
          background-color: {Palette.SURFACE};
          color: {Palette.TEXT_BTN};
          border: 3px solid {Palette.BORDER_STRONG};
          border-radius: 2px;
          padding: 6px 12px;
          icon-size: 16px;
          font-family: {Fonts.UI};
          font-size: 9pt;
          font-weight: 700;
        }}

        QPushButton:hover {{
          background-color: {Palette.SURFACE_DARK};
        }}

        QPushButton:pressed {{
          background-color: {Palette.SURFACE_DARK};
        }}

        QPushButton:disabled {{
          background-color: {Palette.SURFACE_DARK};
          color: {Palette.TEXT_LIGHT};
          border-color: {Palette.BORDER};
        }}

        {_input_qss()}
        {_combo_popup_qss()}
        {_tree_qss()}
        {_progress_qss()}
        {_scrollbar_qss()}
        {_menu_qss()}
        {_checkbox_qss()}
        {_spinbox_qss()}
        """
    )


# ===== 组件级便捷样式 =====
def titlebar_button_style(danger: bool = False) -> str:
    """无边框窗口标题栏右侧的窗口控制按钮（最小化/最大化/关闭）。

    紧凑方块、2px 像素边框；图标 16px 与 SVG viewBox 整数对齐（避免 subpixel）。
    """
    border = Palette.ERROR if danger else Palette.BORDER_STRONG
    hover_bg = Palette.ERROR if danger else Palette.SURFACE
    return (
        f"QPushButton {{\n"
        f"  background-color: transparent;\n"
        f"  border: 2px solid {border};\n"
        f"  border-radius: 2px;\n"
        f"  padding: 0px;\n"
        f"  icon-size: 16px;\n"
        f"  outline: none;\n"
        f"}}\n"
        f"QPushButton:hover {{\n"
        f"  background-color: {hover_bg};\n"
        f"  border-color: {border};\n"
        f"}}\n"
        f"QPushButton:pressed {{\n"
        f"  background-color: {hover_bg};\n"
        f"}}"
    )


def cmd_chip_style() -> str:
    """命令栏小药片按钮。"""
    return (
        f"QPushButton {{\n"
        f"  background-color: {Palette.SECONDARY_LIGHT};\n"
        f"  color: {Palette.TEXT_BTN};\n"
        f"  border: 2px solid {Palette.SECONDARY};\n"
        f"  border-radius: 2px;\n"
        f"  padding: 4px 10px;\n"
        f"  icon-size: 14px;\n"
        f"  font-size: 8pt;\n"
        f"  font-weight: 700;\n"
        f"}}\n"
        f"QPushButton:hover {{\n"
        f"  background-color: {Palette.SECONDARY};\n"
        f"  color: {Palette.TEXT_BTN};\n"
        f"}}\n"
        f"QPushButton:pressed {{\n"
        f"  background-color: {Palette.SECONDARY_HOVER};\n"
        f"  color: {Palette.TEXT_BTN};\n"
        f"}}"
    )


def terminal_style() -> str:
    """终端编辑区 CRT 样式。

    不包含 font-family / font-size —— 字体由 QTextEdit.setFont 精确控制，
    确保 styleStrategy（PreferBitmap+NoAntialias）不会被 QSS 创建的 QFont 覆盖。
    """
    return (
        f"QTextEdit {{\n"
        f"  background-color: {Palette.TERMINAL_BG};\n"
        f"  color: {Palette.TERMINAL_TEXT};\n"
        f"  border: 4px solid {Palette.BORDER_STRONG};\n"
        f"  border-radius: 2px;\n"
        f"  padding: 8px;\n"
        f"  selection-background-color: {Palette.SECONDARY};\n"
        f"}}"
    )


def log_view_style() -> str:
    """Logcat 日志视图样式。同样不在 QSS 里写 font-*，由 setFont 控制。"""
    return (
        f"QPlainTextEdit {{\n"
        f"  background-color: {Palette.TERMINAL_BG};\n"
        f"  color: {Palette.TERMINAL_TEXT};\n"
        f"  border: 3px solid {Palette.BORDER_STRONG};\n"
        f"  border-radius: 2px;\n"
        f"  padding: 6px;\n"
        f"  selection-background-color: {Palette.SECONDARY};\n"
        f"}}"
    )


# ===== 像素卡片 / 区块标题组件 =====
def apply_card(widget: QWidget, kind: str = "card") -> None:
    """把控件标记为像素卡片。

    卡片样式由全局样式表中的属性选择器 QWidget[pixelCard=...] 提供，
    只作用于控件自身，不会级联到子控件（旧版 QWidget{} 选择器会把
    3px 边框泄漏给卡片内每个容器/标签，导致层层套框）。

    kind:
      - "card"     普通卡片（SURFACE 底）
      - "titlebar" 顶部标题栏（SURFACE_DARK 底）

    注意：QWidget 的自定义子类（如 FileExplorer）默认不会绘制样式表
    背景/边框（QStyleSheetStyle 只对内置控件自动启用），必须显式设置
    WA_StyledBackground，否则卡片边框会整块缺失。
    """
    widget.setProperty("pixelCard", kind)
    widget.setAttribute(Qt.WA_StyledBackground, True)


def _dashed_separator() -> QFrame:
    """原型图同款：标题下方的横向虚线分隔。"""
    line = QFrame()
    line.setFixedHeight(3)
    line.setStyleSheet(
        f"QFrame {{ border: none; border-bottom: 2px dashed {Palette.BORDER}; "
        f"background: transparent; }}"
    )
    return line


def make_section_header(title: str, icon_name: str = None, icon_size: int = 16) -> QWidget:
    """生成区块标题：像素图标 + Zpix 粗体标题 + 右侧铺满的虚线分隔。

    与原型图 panel-header 一致（图标 + 标题 + 3px dashed 分隔线），
    所有面板统一使用，保证字号/颜色/间距完全一致。
    """
    container = QWidget()
    container.setStyleSheet("background: transparent;")
    outer = QVBoxLayout(container)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.setSpacing(6)

    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(8)

    if icon_name:
        icon = QLabel()
        icon.setPixmap(IconHelper.pixmap(icon_name, icon_size, Palette.PRIMARY_DARK))
        icon.setStyleSheet("border: none; background: transparent;")
        row.addWidget(icon, 0, Qt.AlignVCenter)

    label = QLabel(title)
    label.setFont(cjk_title_font(10))
    label.setStyleSheet(
        f"color: {Palette.PRIMARY_DARK}; background: transparent; padding: 0;"
    )
    row.addWidget(label, 0, Qt.AlignVCenter)
    row.addStretch()

    outer.addLayout(row)
    outer.addWidget(_dashed_separator())
    return container


def field_label_style() -> str:
    """表单字段标签样式（如"分辨率"/"标签过滤"）：次要色、粗体、透明底。"""
    return (
        f"QLabel {{\n"
        f"  color: {Palette.TEXT_DIM};\n"
        f"  font-weight: 700;\n"
        f"  background: transparent;\n"
        f"}}"
    )


# ===== 状态常量（供外部引用）=====
class Status:
    SUCCESS = Palette.SUCCESS
    ERROR = Palette.ERROR
    WARNING = Palette.WARNING
    INFO = Palette.SECONDARY
    NEUTRAL = Palette.TEXT_DIM


def status_badge_style(color: str) -> str:
    """状态徽章标签（运行中/未启动等）。"""
    return (
        f"QLabel {{\n"
        f"  color: {color};\n"
        f"  font-weight: bold;\n"
        f"  font-size: 8pt;\n"
        f"  padding: 2px 8px;\n"
        f"  border-radius: 2px;\n"
        f"  background-color: {color}22;\n"
        f"  border: 2px solid {color};\n"
        f"}}"
    )


def avatar_style(bg: str = Palette.PRIMARY_LIGHT, border: str = Palette.PRIMARY_DARK) -> str:
    return (
        f"QFrame {{\n"
        f"  background-color: {bg};\n"
        f"  border: 3px solid {border};\n"
        f"  border-radius: 2px;\n"
        f"}}"
    )


def stat_pill_style(color: str = Palette.PRIMARY, bg: str = Palette.PRIMARY_LIGHT) -> str:
    return (
        f"QLabel {{\n"
        f"  color: {color};\n"
        f"  background-color: {bg};\n"
        f"  border: 2px solid {color};\n"
        f"  border-radius: 2px;\n"
        f"  padding: 1px 6px;\n"
        f"  font-size: 8pt;\n"
        f"  font-weight: 700;\n"
        f"}}"
    )


def skill_item_style(active: bool = False) -> str:
    return (
        f"QToolButton {{\n"
        f"  background-color: {Palette.SURFACE if not active else Palette.PRIMARY_LIGHT};\n"
        f"  color: {Palette.TEXT_BTN if not active else Palette.PRIMARY_DARK};\n"
        f"  border: 3px solid {Palette.BORDER if not active else Palette.PRIMARY};\n"
        f"  border-radius: 2px;\n"
        f"  padding: 10px 8px;\n"
        f"  icon-size: 28px;\n"
        f"  font-size: 8pt;\n"
        f"  font-weight: 700;\n"
        f"}}\n"
        f"QToolButton:hover {{\n"
        f"  border-color: {Palette.PRIMARY};\n"
        f"  background-color: {Palette.PRIMARY_LIGHT};\n"
        f"}}\n"
        f"QToolButton:pressed {{\n"
        f"  background-color: {Palette.PRIMARY_LIGHT};\n"
        f"}}"
    )
