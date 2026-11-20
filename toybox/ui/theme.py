"""
theme.py - Colours and the dark Qt theme (Fusion style + palette + stylesheet).
"""

import os

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

BG = "#1f2024"          # window background
EDITOR_BG = "#17181b"   # editor + console
FIELD = "#2a2c31"       # entries, lists
PANEL_HEADER = "#25272c"
BTN = "#2f3238"
BTN_HOVER = "#3a3e46"
BTN_PRESSED = "#454a54"
BORDER = "#3a3d44"
FG = "#d7dae0"
MUTED = "#8b919c"
ACCENT = "#4c8dff"
ACCENT_HOVER = "#6aa1ff"
ACCENT_PRESSED = "#3b78e0"
SELECTION = "#2f4b7c"
ERROR_FG = "#ff6b6b"
INFO_FG = "#7aa2f7"
DIVIDER = BORDER          # divider line colour
DIVIDER_HOVER = "#5a5f6a" # divider under the mouse: a little lighter, not the accent

UI_FONT = ("Segoe UI", 9)

STYLESHEET = f"""
QWidget {{ color: {FG}; }}
QMainWindow, QDialog {{ background: {BG}; }}
QMenuBar {{ background: {BG}; padding: 2px 4px; }}
QMenuBar::item {{ padding: 4px 10px; border-radius: 4px; background: transparent; }}
QMenuBar::item:selected {{ background: {BTN_HOVER}; }}
QMenu {{ background: {FIELD}; border: 1px solid {BORDER}; padding: 4px; }}
QMenu::item {{ padding: 5px 24px 5px 14px; border-radius: 3px; }}
QMenu::item:selected {{ background: {SELECTION}; }}
QMenu::item:disabled {{ color: {MUTED}; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 4px 6px; }}

QPushButton {{ background: {BTN}; border: 1px solid {BORDER}; border-radius: 4px;
              padding: 5px 14px; }}
QPushButton:hover {{ background: {BTN_HOVER}; }}
QPushButton:pressed {{ background: {BTN_PRESSED}; }}
QPushButton:disabled {{ color: {MUTED}; background: {BG}; }}
QPushButton[accent="true"] {{ background: {ACCENT}; border-color: {ACCENT}; color: white; }}
QPushButton[accent="true"]:hover {{ background: {ACCENT_HOVER}; }}
QPushButton[accent="true"]:pressed {{ background: {ACCENT_PRESSED}; }}
QPushButton[accent="true"]:disabled {{ background: {BG}; border-color: {BORDER}; color: {MUTED}; }}

QToolButton {{ background: transparent; border: none; border-radius: 4px; padding: 3px; }}
QToolButton:hover {{ background: {BTN_HOVER}; }}
QToolButton:pressed {{ background: {BTN_PRESSED}; }}
QToolButton::menu-indicator {{ image: none; }}

QLineEdit, QSpinBox {{ background: {FIELD}; border: 1px solid {BORDER}; border-radius: 3px;
                       padding: 3px 5px; selection-background-color: {SELECTION}; }}
QLineEdit:focus, QSpinBox:focus {{ border-color: {ACCENT}; }}
QLineEdit[invalid="true"] {{ border-color: {ERROR_FG}; }}
QSpinBox {{ padding-right: 18px; }}
QSpinBox::up-button, QSpinBox::down-button {{ subcontrol-origin: border; width: 16px;
    background: {BTN}; border-left: 1px solid {BORDER}; }}
QSpinBox::up-button {{ subcontrol-position: top right; border-top-right-radius: 3px; }}
QSpinBox::down-button {{ subcontrol-position: bottom right; border-bottom-right-radius: 3px; }}
QSpinBox::up-button:hover, QSpinBox::down-button:hover {{ background: {BTN_HOVER}; }}
QSpinBox::up-arrow {{ image: url(@ICONS@/spin-up.svg); width: 8px; height: 5px; }}
QSpinBox::down-arrow {{ image: url(@ICONS@/spin-down.svg); width: 8px; height: 5px; }}
QToolButton#panelMenu {{ font-size: 14px; font-weight: bold; padding: 0 6px; }}

QPlainTextEdit {{ background: {EDITOR_BG}; border: 1px solid {BORDER};
                  selection-background-color: {SELECTION}; selection-color: white; }}
QPlainTextEdit:focus {{ border-color: {ACCENT}; }}

QCheckBox {{ spacing: 6px; }}
QLabel[muted="true"] {{ color: {MUTED}; }}
QLabel[header="true"] {{ color: {MUTED}; font-weight: bold; font-size: 8pt; }}

QScrollBar:vertical {{ background: {EDITOR_BG}; width: 11px; margin: 0; }}
QScrollBar:horizontal {{ background: {EDITOR_BG}; height: 11px; margin: 0; }}
QScrollBar::handle {{ background: {BTN}; border-radius: 4px; min-height: 24px; min-width: 24px;
                      margin: 2px; }}
QScrollBar::handle:hover {{ background: {BTN_HOVER}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

QToolTip {{ background: {FIELD}; color: {FG}; border: 1px solid {BORDER}; padding: 3px 6px; }}

/* Workspace */
PanelFrame {{ background: {BG}; border: 1px solid {BORDER}; border-radius: 4px; }}
PanelFrame[dragSource="true"] {{ border-color: {ACCENT}; }}
QWidget#panelHeader {{ background: {PANEL_HEADER}; border-top-left-radius: 4px;
                       border-top-right-radius: 4px; }}
QLabel#panelKind {{ color: {MUTED}; font-weight: bold; font-size: 8pt; }}
QLabel#panelName {{ color: {FG}; }}
"""


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    app.setFont(QFont(*UI_FONT))
    pal = QPalette()
    for role, color in (
            (QPalette.Window, BG), (QPalette.WindowText, FG), (QPalette.Base, FIELD),
            (QPalette.AlternateBase, BG), (QPalette.Text, FG), (QPalette.Button, BTN),
            (QPalette.ButtonText, FG), (QPalette.Highlight, SELECTION),
            (QPalette.HighlightedText, "#ffffff"), (QPalette.ToolTipBase, FIELD),
            (QPalette.ToolTipText, FG), (QPalette.PlaceholderText, MUTED),
            (QPalette.Link, ACCENT)):
        pal.setColor(role, QColor(color))
    pal.setColor(QPalette.Disabled, QPalette.Text, QColor(MUTED))
    pal.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(MUTED))
    app.setPalette(pal)
    icons = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "assets", "icons").replace("\\", "/")
    app.setStyleSheet(STYLESHEET.replace("@ICONS@", icons))
