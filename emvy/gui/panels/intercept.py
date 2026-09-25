"""Panel Intercept (GUI): MITM de APDUs — reglas que reescriben tag/valor y
fuerzan status words. Al activarse, todo el tráfico de la sesión pasa por ellas
(`core.intercept.intercepting`, cableado en `MainWindow.active_send`).
"""
from __future__ import annotations

from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout,
    QWidget,
)

_MONO = QFont("monospace"); _MONO.setStyleHint(QFont.Monospace)

_EXAMPLE = (
    "# una regla por línea (scope cmd|resp; @INS filtra por instrucción):\n"
    "# resp set-tag 82 3900          # reescribe el AIP en las respuestas\n"
    "# resp set-sw 9000 @A8          # fuerza SW=9000 solo en GPO (INS A8)\n"
    "# cmd  set-tag 9F02 000000000100\n"
    "# resp replace 9F34031F0302 9F34035E0300\n"
)


class InterceptPanel(QWidget):
    def __init__(self, win) -> None:
        super().__init__()
        self.win = win
        sub = QLabel("Reglas MITM sobre los APDU de la sesión."
                     "")
        sub.setWordWrap(True); sub.setProperty("hint", "true")

        self._rules = QPlainTextEdit(); self._rules.setFont(_MONO)
        self._rules.setPlaceholderText(_EXAMPLE)
        self._rules.setMaximumHeight(140)

        apply_b = QPushButton("Aplicar reglas"); apply_b.clicked.connect(self._apply)
        self._active = QCheckBox("Interceptar activo"); self._active.toggled.connect(self._toggle)
        row = QHBoxLayout(); row.addWidget(apply_b); row.addWidget(self._active); row.addStretch(1)

        self._log = QPlainTextEdit(readOnly=True); self._log.setFont(_MONO)
        lay = QVBoxLayout(self)
        lay.addWidget(sub); lay.addWidget(self._rules); lay.addLayout(row); lay.addWidget(self._log, 1)

        win.intercept_event.connect(self._on_exchange)

    def _apply(self) -> None:
        rules, errors = self.win.apply_intercept(self._rules.toPlainText())
        self._log.appendPlainText(f"Reglas aplicadas: {len(rules)}")
        for e in errors:
            self._log.appendPlainText(f"  ! {e}")

    def _toggle(self, on: bool) -> None:
        if on and not self.win.intercept_rules:
            self._apply()
        self.win.intercept_active = on
        self._log.appendPlainText("Interceptor " + ("ACTIVO" if on else "inactivo"))

    def _on_exchange(self, ex) -> None:
        # ex: core.intercept.Exchange — muestra lo que la regla cambió
        try:
            for note in getattr(ex, "notes", []) or []:
                self._log.appendPlainText(f"  · {note}")
        except Exception:
            self._log.appendPlainText(f"  · {ex}")
