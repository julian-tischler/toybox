"""
preferences.py - The Preferences dialog (app-wide settings).
"""

from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QLabel,
                               QSpinBox, QVBoxLayout)


class PreferencesDialog(QDialog):
    def __init__(self, parent, prefs: dict):
        super().__init__(parent)
        self.setWindowTitle("Preferences")
        self.setMinimumWidth(360)
        lay = QVBoxLayout(self)

        form = QFormLayout()
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(10)
        self.hide = QCheckBox("Hide lenses while measuring")
        self.hide.setChecked(bool(prefs["hide_while_measuring"]))
        self.hide.setToolTip("Make lenses invisible during each capture so they are never "
                             "part of the pixels a script reads.")
        form.addRow(self.hide)
        self.settle = QSpinBox()
        self.settle.setRange(0, 1000)
        self.settle.setSingleStep(10)
        self.settle.setSuffix(" ms")
        self.settle.setValue(int(prefs["settle_ms"]))
        self.settle.setToolTip("Wait after hiding lenses, so the screen has repainted.")
        form.addRow("Settle delay", self.settle)
        self.interval = QSpinBox()
        self.interval.setRange(50, 3_600_000)
        self.interval.setSingleStep(100)
        self.interval.setSuffix(" ms")
        self.interval.setValue(int(prefs["interval_ms"]))
        form.addRow("Default run interval", self.interval)
        note = QLabel("The run interval applies to new Script panels; each panel can "
                      "change its own.")
        note.setProperty("muted", True)
        note.setWordWrap(True)
        form.addRow(note)
        lay.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def values(self) -> dict:
        return {"hide_while_measuring": self.hide.isChecked(),
                "settle_ms": self.settle.value(), "interval_ms": self.interval.value()}
