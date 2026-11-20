"""
main.py - Application entry point.

Run:  python main.py
"""

import sys


def _enable_dpi_awareness() -> None:
    """On Windows, make Tk and mss agree on physical pixels (must run before Tk starts)."""
    if not sys.platform.startswith("win"):
        return
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


def _check_dependencies() -> None:
    missing = []
    for module, package in (("mss", "mss"), ("cv2", "opencv-python"),
                            ("numpy", "numpy"), ("pytesseract", "pytesseract")):
        try:
            __import__(module)
        except ImportError:
            missing.append(package)
    if missing:
        sys.exit("Missing packages. Install them with:\n  pip install " + " ".join(missing))


def main() -> None:
    _enable_dpi_awareness()
    _check_dependencies()
    from gui_ide import AppMainWindow  # imported late so DPI awareness is set first
    AppMainWindow().mainloop()


if __name__ == "__main__":
    main()
    
