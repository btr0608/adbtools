import os
import sys
import traceback

# Allow running this script directly: the project root (this file's dir)
# is the `adbtools` package, so its parent must be on sys.path.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt5.QtWidgets import QApplication, QMessageBox

from adbtools.core.adb_client import AdbClient
from adbtools.ui.dialogs.dialog_styles import install_global_dialog_hooks
from adbtools.ui.main_window import AdbTool
from adbtools.ui.theme import app_stylesheet, apply_app_font


def global_exception_handler(exc_type, exc_value, exc_traceback):
    err_msg = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    print("未捕获的异常:\n", err_msg)
    QMessageBox.critical(
        None, "程序发生异常",
        f"抱歉，程序遇到错误被拦截：\n\n{err_msg}\n这不会导致程序退出。"
    )


def main():
    sys.excepthook = global_exception_handler
    app = QApplication(sys.argv)
    install_global_dialog_hooks()  # 全局剥离对话框的 ? 帮助按钮
    app.setStyle("Fusion")
    apply_app_font(app)
    app.setStyleSheet(app_stylesheet())

    adb_client = AdbClient(serial_getter=lambda: None)
    window = AdbTool(adb_client)
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
