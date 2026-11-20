"""
Toybox - a modular workspace of small tools (lenses, scripts, ...).

Run from the project folder:  python -m toybox
"""

import sys


def _check_dependencies() -> None:
    missing = []
    for module, package in (("PySide6", "PySide6"), ("pyqtgraph", "pyqtgraph"),
                            ("mss", "mss"), ("cv2", "opencv-python"),
                            ("numpy", "numpy"), ("pytesseract", "pytesseract")):
        try:
            __import__(module)
        except ImportError:
            missing.append(package)
    if missing:
        sys.exit("Missing packages. Install them with:\n  pip install " + " ".join(missing))


def main() -> int:
    _check_dependencies()
    from PySide6.QtWidgets import QApplication

    from .core.bridge import init_bridge
    from .core.executor import install_output_router
    from .ui.theme import apply_theme

    app = QApplication(sys.argv)
    app.setApplicationName("Toybox")
    app.setOrganizationName("Toybox")
    init_bridge()
    install_output_router()             # print() in scripts lands in their own console
    apply_theme(app)

    from . import panels  # noqa: F401  registers the built-in tools
    from .ui.main_window import MainWindow
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
