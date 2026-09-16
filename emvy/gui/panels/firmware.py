"""Panel BomberCat (GUI): compila y sube el firmware de `firmware/` con
arduino-cli (`integrations.arduino`). El flasheo por picotool sube el `.elf`
(no `.uf2`); ver CLAUDE.md §12.
"""
from __future__ import annotations

from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton,
    QVBoxLayout, QWidget,
)

from ...integrations import arduino as ard

_MONO = QFont("monospace"); _MONO.setStyleHint(QFont.Monospace)


class FirmwarePanel(QWidget):
    def __init__(self, win) -> None:
        super().__init__()
        self.win = win
        sub = QLabel("Compila y sube el firmware BomberCat de `firmware/` con arduino-cli. "
                     "Subir usa picotool (reset 1200-bps); requiere regla udev o sudo.")
        sub.setWordWrap(True); sub.setStyleSheet("color:#8b949e")

        self._sketch = QComboBox()
        self._port = QLineEdit(); self._port.setPlaceholderText("puerto (opcional, p.ej. /dev/ttyACM0)")
        self._port.setFixedWidth(220)
        comp = QPushButton("Compilar"); comp.clicked.connect(lambda: self._go(False))
        upl = QPushButton("Compilar y subir"); upl.clicked.connect(lambda: self._go(True))
        rel = QPushButton("Recargar"); rel.clicked.connect(self.reload)
        row = QHBoxLayout()
        row.addWidget(QLabel("Sketch")); row.addWidget(self._sketch, 1)
        row.addWidget(self._port); row.addWidget(comp); row.addWidget(upl); row.addWidget(rel)

        # permisos USB (reglas udev + grupos) — resuelve el fallo de picotool/serie
        perms = QPushButton("Configurar permisos USB")
        perms.clicked.connect(lambda: self.win.setup_usb_permissions())
        permrow = QHBoxLayout()
        permrow.addWidget(QLabel("Permisos:"))
        permrow.addWidget(perms); permrow.addStretch(1)

        self._log = QPlainTextEdit(readOnly=True); self._log.setFont(_MONO)
        lay = QVBoxLayout(self)
        lay.addWidget(sub); lay.addLayout(row); lay.addLayout(permrow); lay.addWidget(self._log, 1)
        self.reload()

    def reload(self) -> None:
        self._sketch.clear()
        if not ard.arduino_cli_available():
            self._log.appendPlainText("arduino-cli no disponible (instálalo para compilar/subir).")
        try:
            for p in ard.list_sketches():
                self._sketch.addItem(p.name, str(p))
        except Exception as e:  # noqa: BLE001
            self._log.appendPlainText(f"No se pudieron listar sketches: {e}")
        if self._sketch.count() == 0:
            self._sketch.addItem("(sin sketches en firmware/)", "")

    def _go(self, upload: bool) -> None:
        sketch = self._sketch.currentData()
        if not sketch:
            self.win.notify.emit("No hay sketch seleccionado.")
            return
        port = self._port.text().strip() or None
        self.win.compile_firmware(sketch, upload=upload, port=port)

    def log(self, text: str) -> None:
        self._log.appendPlainText(text)

    def log_result(self, res) -> None:
        rc = getattr(res, "returncode", "?")
        out = (getattr(res, "stdout", "") or "")[-2000:]
        err = (getattr(res, "stderr", "") or "")[-800:]
        self._log.appendPlainText(f"── returncode {rc} ──")
        if out:
            self._log.appendPlainText(out)
        if err:
            self._log.appendPlainText(err)
