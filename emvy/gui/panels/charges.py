"""Panel Cobros (GUI): flujo de switch ISO 8583 (sign-on → compra → reverso).

Configurado por variables del proyecto (`SwitchConfig.from_vars`); la tarjeta
sale de la última captura. Evidencia en `<proyecto>/transactions/`.
"""
from __future__ import annotations

from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton,
    QVBoxLayout, QWidget,
)

_MONO = QFont("monospace"); _MONO.setStyleHint(QFont.Monospace)


class ChargesPanel(QWidget):
    def __init__(self, win) -> None:
        super().__init__()
        self.win = win
        sub = QLabel("Flujo de switch/adquirente ISO 8583. Config por variables del proyecto "
                     "(switch_host, switch_port, tpdu, terminal_id…). La tarjeta sale de la "
                     "última captura del Explorador.")
        sub.setWordWrap(True); sub.setProperty("hint", "true")

        self._amount = QLineEdit("500"); self._amount.setFixedWidth(100)
        self._dry = QCheckBox("dry-run"); self._dry.setChecked(True)
        self._signon = QCheckBox("sign-on antes"); self._signon.setChecked(True)
        row = QHBoxLayout()
        row.addWidget(QLabel("Monto (centavos)")); row.addWidget(self._amount)
        row.addWidget(self._dry); row.addWidget(self._signon); row.addStretch(1)

        b_so = QPushButton("Sign-on (0800)"); b_so.clicked.connect(lambda: self._go("signon"))
        b_pur = QPushButton("Cobrar (0200)"); b_pur.clicked.connect(lambda: self._go("purchase"))
        b_rev = QPushButton("Reverso (0400)"); b_rev.clicked.connect(lambda: self._go("reversal"))
        brow = QHBoxLayout()
        for b in (b_so, b_pur, b_rev):
            brow.addWidget(b)
        brow.addStretch(1)

        self._log = QPlainTextEdit(readOnly=True); self._log.setFont(_MONO)
        lay = QVBoxLayout(self)
        lay.addWidget(sub); lay.addLayout(row); lay.addLayout(brow); lay.addWidget(self._log, 1)

    def _amount_cents(self) -> int:
        try:
            return int(self._amount.text())
        except ValueError:
            return 0

    def _go(self, kind: str) -> None:
        self._log.appendPlainText(f"→ {kind}…")
        self.win.run_switch_flow(kind, amount=self._amount_cents(),
                                 dry_run=self._dry.isChecked(), sign_on=self._signon.isChecked())

    def log_flow(self, kind: str, res) -> None:
        self._log.appendPlainText(f"══ {kind} ══")
        try:
            self._log.appendPlainText(res.summary())
        except Exception:
            self._log.appendPlainText(str(res))
