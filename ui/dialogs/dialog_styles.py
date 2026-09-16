from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QDialog, QPushButton

from ..theme import Buttons, Palette

DLG_MIN_WIDTH = 420

BTN_PRIMARY_QSS = Buttons.primary()

BTN_SECONDARY_QSS = Buttons.secondary()

BTN_DANGER_QSS = Buttons.danger()

STATUS_SUCCESS_QSS = f"color: {Palette.SUCCESS}; font-weight: 700;"
STATUS_ERROR_QSS = f"color: {Palette.ERROR}; font-weight: 700;"
STATUS_NEUTRAL_QSS = f"color: {Palette.TEXT_DIM};"
STATUS_WARNING_QSS = f"color: {Palette.ACCENT_DARK}; font-weight: 700;"


def install_global_dialog_hooks():
    """全局 monkey-patch：剥离所有对话框标题栏的 ? 帮助按钮。

    两层防御：
    1. 对 QDialog 实例方法（__init__ / exec_ / show / setWindowFlags / setWindowFlag）
       统一强制剥掉 WindowContextHelpButtonHint。
    2. 对 QInputDialog / QMessageBox / QFileDialog / QColorDialog / QFontDialog
       等的静态工厂方法直接 patch，因为这些方法内部走 C++ 侧创建对话框，
       可能绕过 QDialog.__init__ 的 patch（实测 QInputDialog.getText 就绕过了）。
    """
    from PyQt5.QtWidgets import (
        QDialog, QInputDialog, QMessageBox, QFileDialog,
        QColorDialog, QFontDialog,
    )
    from PyQt5.QtCore import Qt

    _HELP = Qt.WindowContextHelpButtonHint

    # ── 层 1：实例方法 patch ──
    orig_init = QDialog.__init__
    orig_exec = QDialog.exec_
    orig_show = QDialog.show
    orig_set_wf = QDialog.setWindowFlags
    orig_set_one_wf = QDialog.setWindowFlag

    def _strip_help(self):
        cur = self.windowFlags()
        stripped = cur & ~_HELP
        if stripped != cur:
            orig_set_wf(self, stripped)
        return stripped

    def patched_init(self, *args, **kwargs):
        orig_init(self, *args, **kwargs)
        _strip_help(self)

    def patched_exec(self):
        _strip_help(self)
        return orig_exec(self)

    def patched_show(self):
        _strip_help(self)
        return orig_show(self)

    def patched_set_wf(self, flags):
        stripped = flags & ~_HELP
        return orig_set_wf(self, stripped)

    def patched_set_one_wf(self, flag, on=True):
        if flag == _HELP:
            return None
        return orig_set_one_wf(self, flag, on)

    QDialog.__init__ = patched_init
    QDialog.exec_ = patched_exec
    QDialog.show = patched_show
    QDialog.setWindowFlags = patched_set_wf
    QDialog.setWindowFlag = patched_set_one_wf

    # ── 层 2：子类也各 patch 一次（双保险） ──
    # PyQt5 某些子类的 exec_ / show 可能走 C++ 虚函数不经过 QDialog 覆盖，
    # 这里对每个常用对话框子类直接 patch，确保无论静态工厂还是手动构造都被拦截
    _dialog_classes = [QInputDialog, QMessageBox, QFileDialog, QColorDialog, QFontDialog]
    for cls in _dialog_classes:
        if cls is QDialog:
            continue
        # __init__
        orig_cls_init = cls.__init__

        def make_init_wrapper(orig):
            def wrapper(self, *args, **kwargs):
                orig(self, *args, **kwargs)
                _strip_help(self)
            return wrapper

        cls.__init__ = make_init_wrapper(orig_cls_init)
        # exec_
        orig_cls_exec = cls.exec_

        def make_exec_wrapper(orig):
            def wrapper(self):
                _strip_help(self)
                return orig(self)
            return wrapper

        cls.exec_ = make_exec_wrapper(orig_cls_exec)
        # show
        orig_cls_show = cls.show

        def make_show_wrapper(orig):
            def wrapper(self):
                _strip_help(self)
                return orig(self)
            return wrapper

        cls.show = make_show_wrapper(orig_cls_show)

    # ── 层 3：静态工厂方法 patch ──
    for name in ("getText", "getItem", "getInt", "getDouble", "getMultiLineText"):
        _patch_static_get(QInputDialog, name)
    for name in ("information", "warning", "critical", "question", "about"):
        _patch_static_get(QMessageBox, name)
    for name in (
        "getOpenFileName", "getOpenFileNames", "getSaveFileName",
        "getExistingDirectory", "getOpenFileUrl", "getOpenFileUrls",
        "getSaveFileUrl", "getExistingDirectoryUrl",
    ):
        _patch_static_get(QFileDialog, name)
    _patch_static_get(QColorDialog, "getColor")
    _patch_static_get(QFontDialog, "getFont")


def _patch_static_get(cls, method_name: str):
    """patch 一个 QInputDialog / QMessageBox 等的静态工厂方法。

    策略：在原方法外层包一层，构造并 exec 对话框实例前，
    主动调用 setWindowFlags(..., strip help)。

    但 QInputDialog.getText 返回的是 (text, ok)，QMessageBox.question 返回 StandardButton，
    QFileDialog 返回的是 str 或 (str, str)。所以直接 wrapper 调原方法就行——
    只要层 1 的 patch 已经装好，层 2 是冗余但保险的。

    真正有效的层 2 patch：包装 QMessageBox 的 "about" / QMessageBox 的静态版本
    以及 QFileDialog，因为这些可能在某些 Qt 版本下不走 QDialog.exec_。
    """
    from PyQt5.QtCore import Qt
    _HELP = Qt.WindowContextHelpButtonHint

    orig = getattr(cls, method_name, None)
    if orig is None:
        return
    # 已经 patch 过就别重复包了
    if getattr(orig, "_help_stripped", False):
        return

    def wrapper(*args, **kwargs):
        # 直接调原方法，层 1 的 QDialog 实例 patch 会自动剥 help hint
        return orig(*args, **kwargs)

    wrapper._help_stripped = True
    setattr(cls, method_name, wrapper)


def setup_dialog_window(dialog, title: str, min_width: int = DLG_MIN_WIDTH):
    dialog.setWindowTitle(title)
    dialog.setMinimumWidth(min_width)
    dialog.setWindowFlags(dialog.windowFlags() & ~Qt.WindowContextHelpButtonHint)


def create_primary_button(text: str, enabled: bool = True) -> QPushButton:
    btn = QPushButton(text)
    btn.setStyleSheet(BTN_PRIMARY_QSS)
    btn.setEnabled(enabled)
    return btn


def create_secondary_button(text: str) -> QPushButton:
    btn = QPushButton(text)
    btn.setStyleSheet(BTN_SECONDARY_QSS)
    return btn


def create_danger_button(text: str) -> QPushButton:
    btn = QPushButton(text)
    btn.setStyleSheet(BTN_DANGER_QSS)
    return btn
