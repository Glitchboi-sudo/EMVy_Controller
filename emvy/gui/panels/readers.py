"""Panel Lectores (GUI): descubre dispositivos de todos los backends y conecta."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QHeaderView, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ...readers import registry


class ReadersPanel(QWidget):
    def __init__(self, win) -> None:
        super().__init__()
        self.win = win
        self._devices = []

        sub = QLabel("Selecciona un lector y conecta."
                     "")
        sub.setWordWrap(True)
        sub.setProperty("hint", "true")

        self._backends = QLabel("")
        self._backends.setProperty("hint", "true")

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["#", "backend", "nombre", "capacidades"])
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.doubleClicked.connect(lambda *_: self._connect())

        refresh = QPushButton("Refrescar"); refresh.clicked.connect(self.reload)
        connect = QPushButton("Conectar"); connect.clicked.connect(self._connect)
        disc = QPushButton("Desconectar"); disc.clicked.connect(self.win.disconnect_reader)
        row = QHBoxLayout()
        row.addWidget(refresh); row.addWidget(connect); row.addWidget(disc)
        row.addStretch(1)

        lay = QVBoxLayout(self)
        lay.addWidget(sub)
        lay.addLayout(row)
        lay.addWidget(self._backends)
        lay.addWidget(self._table, 1)

        self.reload()

    def reload(self) -> None:
        backends = registry.available_backends()
        self._backends.setText("Backends:  " + "   ".join(
            f"{n}={'✓' if ok else '✗'}" for n, ok in backends.items()))
        self._devices = registry.list_all_devices()
        self._table.setRowCount(len(self._devices))
        for i, d in enumerate(self._devices):
            for col, val in enumerate((str(i), d.backend, d.name, d.caps_str)):
                self._table.setItem(i, col, QTableWidgetItem(val))
        if self._devices:
            self._table.selectRow(0)

    def _selected(self):
        row = self._table.currentRow()
        if 0 <= row < len(self._devices):
            return self._devices[row]
        return None

    def _connect(self) -> None:
        self.win.connect_reader(self._selected())
