"""Panel Fuzzing (GUI): tres carriles para probar terminales/lectores/POS.

  * **Banda magnética** → BomberCat magspoof.
  * **Registro EMV** → UPDATE RECORD en una tarjeta de prueba reescribible.
  * **NDEF** → emula un tag NFC Type 4; la fuente puede ser una **plantilla**
    malformada, una **tarjeta de prueba** o una **captura guardada** (sus datos
    presentados como NDEF — no es emulación EMV funcional, ver `core.ndef`).

Cada valor es editable antes de disparar.
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QTabWidget, QVBoxLayout, QWidget,
)

from ...core import cardfuzz
from ...core import track as tracklib
from ...core.hexutil import to_hex
from ...project import store
from ..icons import icon
from ..theme import ACCENT_FG


class FuzzPanel(QWidget):
    def __init__(self, win) -> None:
        super().__init__()
        self.win = win
        lay = QVBoxLayout(self)
        warn = QLabel("Aviso: genera datos de tarjeta/NFC fuera de norma para observar cómo "
                      "reacciona un lector real. Solo hardware propio o autorizado.")
        warn.setWordWrap(True); warn.setProperty("hint", "true")
        lay.addWidget(warn)
        # Sub-pestañas: una herramienta enfocada a la vez (menos ruido que apilar
        # los cuatro paneles). Los widgets/IDs no cambian.
        sub = QTabWidget()
        sub.addTab(self._card_editor(), "Editor de tarjeta")
        sub.addTab(self._ndef_lane(), "Emulación NFC/EMV")
        sub.addTab(self._emv_lane(), "Registro EMV")
        sub.addTab(self._track_lane(), "Banda magnética")
        lay.addWidget(sub, 1)
        self._gen_track(); self._gen_emv(); self._gen_ndef()

    # -- banda magnética ---------------------------------------------------
    def _track_lane(self) -> QGroupBox:
        box = QGroupBox("Banda magnética · magspoof (BomberCat)")
        self._track_tpl = QComboBox()
        for t in cardfuzz.track_templates():
            self._track_tpl.addItem(t.title, t.id)
        self._track_tpl.currentIndexChanged.connect(self._gen_track)
        gen = QPushButton("Generar"); gen.clicked.connect(self._gen_track)
        send = QPushButton("Enviar"); send.clicked.connect(self._send_track)
        self._track1 = QLineEdit(); self._track1.setPlaceholderText("track1 (editable)")
        self._track2 = QLineEdit(); self._track2.setPlaceholderText("track2 (editable)")
        self._track_desc = _desc()
        top = QHBoxLayout(); top.addWidget(self._track_tpl, 1); top.addWidget(gen); top.addWidget(send)
        v = QVBoxLayout(box); v.addLayout(top); v.addWidget(self._track_desc)
        v.addWidget(self._track1); v.addWidget(self._track2)
        return box

    def _gen_track(self) -> None:
        t = cardfuzz.get_track_template(cardfuzz.track_templates(),
                                        self._track_tpl.currentData())
        if not t:
            return
        self._track_desc.setText(t.description)
        self._track1.setText(t.track1 or ""); self._track2.setText(t.track2 or "")

    def _send_track(self) -> None:
        t1 = self._track1.text().strip() or None
        t2 = self._track2.text().strip() or None
        if not (t1 or t2):
            self.win.notify.emit("No hay track1/track2 que enviar.")
            return
        self.win.emit_magspoof(t1, t2)

    # -- registro EMV ------------------------------------------------------
    def _emv_lane(self) -> QGroupBox:
        box = QGroupBox("Registro EMV · escribir en tarjeta de prueba")
        self._emv_tpl = QComboBox()
        for t in cardfuzz.emv_templates():
            self._emv_tpl.addItem(t.title, t.id)
        self._emv_tpl.currentIndexChanged.connect(self._gen_emv)
        gen = QPushButton("Generar"); gen.clicked.connect(self._gen_emv)
        self._emv_hex = QLineEdit(); self._emv_hex.setPlaceholderText("registro en hex (editable)")
        self._emv_sfi = QLineEdit("1"); self._emv_sfi.setFixedWidth(56)
        self._emv_rec = QLineEdit("1"); self._emv_rec.setFixedWidth(56)
        write = QPushButton("Escribir"); write.clicked.connect(self._write_emv)
        self._emv_desc = _desc()
        top = QHBoxLayout(); top.addWidget(self._emv_tpl, 1); top.addWidget(gen)
        bottom = QHBoxLayout()
        bottom.addWidget(QLabel("SFI")); bottom.addWidget(self._emv_sfi)
        bottom.addWidget(QLabel("REC")); bottom.addWidget(self._emv_rec)
        bottom.addWidget(write); bottom.addStretch(1)
        v = QVBoxLayout(box); v.addLayout(top); v.addWidget(self._emv_desc)
        v.addWidget(self._emv_hex); v.addLayout(bottom)
        return box

    def _gen_emv(self) -> None:
        t = cardfuzz.get_emv_template(cardfuzz.emv_templates(), self._emv_tpl.currentData())
        if not t:
            return
        self._emv_desc.setText(t.description)
        self._emv_hex.setText(to_hex(t.to_record()))

    def _write_emv(self) -> None:
        from ...core.hexutil import from_hex
        try:
            data = from_hex(self._emv_hex.text().strip())
            sfi = int(self._emv_sfi.text()); rec = int(self._emv_rec.text())
        except ValueError:
            self.win.notify.emit("Hex/SFI/registro inválido.")
            return
        self.win.write_record(sfi, rec, data)

    # -- Emulación (NFC/NDEF o EMV, según la Fuente) -----------------------
    def _ndef_lane(self) -> QGroupBox:
        box = QGroupBox("Emular (BomberCat) · la Fuente decide NFC o EMV")
        # Cada fuente lleva su MODO: las NFC emulan un tag NDEF a un lector; la
        # EMV emula una tarjeta de pago a un terminal (perfilarlo). Un solo botón.
        self._ndef_src = QComboBox()
        self._ndef_src.addItem("NFC · plantilla NDEF (fuzz)", "template")
        self._ndef_src.addItem("NFC · tarjeta de prueba (NDEF)", "test")
        self._ndef_src.addItem("NFC · captura (NDEF)", "capture")
        self._ndef_src.addItem("EMV · tarjeta de pago (perfilar terminal)", "emv")
        self._ndef_src.currentIndexChanged.connect(self._ndef_src_changed)

        self._ndef_tpl = QComboBox()
        for t in cardfuzz.ndef_templates():
            self._ndef_tpl.addItem(t.title, t.id)
        self._ndef_tpl.currentIndexChanged.connect(self._gen_ndef)
        self._ndef_cap = QComboBox()
        self._ndef_cap.currentIndexChanged.connect(self._gen_ndef)
        self._ndef_cap.hide()

        self._ndef_gen = QPushButton("Generar"); self._ndef_gen.clicked.connect(self._gen_ndef)
        emit = QPushButton("Emular"); emit.clicked.connect(self._emit)
        emit.setProperty("accent", True)          # CTA principal del carril
        emit.setIcon(icon("play", color=ACCENT_FG))
        stop = QPushButton("Detener"); stop.clicked.connect(self._stop_ndef)
        stop.setIcon(icon("square"))
        reboot = QPushButton("Reboot"); reboot.clicked.connect(self._reboot)
        reboot.setIcon(icon("cpu"))
        self._ndef_hex = QLineEdit(); self._ndef_hex.setPlaceholderText("mensaje NDEF en hex (editable)")
        self._ndef_desc = _desc()

        # Fila de escaneo-a-RAM (solo visible en modo EMV): leer una tarjeta y
        # guardarla en memoria (app) o en la RAM del BomberCat para reemularla.
        scan_mem = QPushButton("Escanear→memoria"); scan_mem.clicked.connect(self._scan_mem)
        scan_ram = QPushButton("Escanear→RAM (BomberCat)"); scan_ram.clicked.connect(self._scan_ram)
        self._emv_scan = QWidget()
        sr = QHBoxLayout(self._emv_scan); sr.setContentsMargins(0, 0, 0, 0)
        sr.addWidget(QLabel("Escanear tarjeta:")); sr.addWidget(scan_mem)
        sr.addWidget(scan_ram); sr.addStretch(1)
        self._emv_scan.hide()

        top = QHBoxLayout()
        top.addWidget(QLabel("Fuente")); top.addWidget(self._ndef_src)
        top.addWidget(self._ndef_tpl, 1); top.addWidget(self._ndef_cap, 1)
        top.addWidget(self._ndef_gen); top.addWidget(emit)
        top.addWidget(stop); top.addWidget(reboot)
        hint = _desc()
        hint.setText("La consola cruda (dock inferior) muestra qué pide el lector. "
                     "NFC/NDEF: SELECT app/CC/NDEF y READ off/len. EMV (terminal de pago): "
                     "SELECT-PPSE/AID y el GPO con TTQ/monto/país/divisa/UN decodificados. "
                     "Escanea una tarjeta a memoria/RAM y elígela como fuente para reemularla. "
                     "Detener para la emulación; Reboot reinicia la placa.")
        v = QVBoxLayout(box); v.addLayout(top); v.addWidget(self._emv_scan)
        v.addWidget(self._ndef_desc); v.addWidget(self._ndef_hex); v.addWidget(hint)
        return box

    def _ndef_src_changed(self) -> None:
        src = self._ndef_src.currentData()
        is_emv = src == "emv"
        self._ndef_tpl.setVisible(src == "template")
        # el selector de captura se usa tanto para NDEF-captura como para EMV
        self._ndef_cap.setVisible(src in ("capture", "emv"))
        # En modo EMV no hay mensaje NDEF que generar/editar (se sirve la tarjeta).
        self._ndef_hex.setVisible(not is_emv)
        self._ndef_gen.setVisible(not is_emv)
        self._emv_scan.setVisible(is_emv)
        if is_emv:
            self._reload_captures(include_canned=True, include_ram=True)
            self._ndef_desc.setText("Emula una tarjeta de pago para que el TERMINAL avance y "
                                    "revele su config (TTQ/monto/país/divisa/UN). Elige la "
                                    "fuente: tarjeta de prueba fija, una captura guardada, la "
                                    "tarjeta escaneada en memoria de la app, o la guardada en "
                                    "la RAM del BomberCat (botones Escanear→…).")
            return
        if src == "capture":
            self._reload_captures()
        self._gen_ndef()

    def _reload_captures(self, include_canned: bool = False,
                         include_ram: bool = False) -> None:
        self._ndef_cap.blockSignals(True)
        self._ndef_cap.clear()
        if include_canned:
            self._ndef_cap.addItem("(tarjeta de prueba fija)", "")   # data "" = canned
        if include_ram:                                              # fuentes en RAM (EMV)
            self._ndef_cap.addItem("(tarjeta escaneada en memoria de la app)", "__mem__")
            self._ndef_cap.addItem("(tarjeta en RAM del BomberCat)", "__ram__")
        proj = store.active_project()
        if proj:
            for p in store.list_captures(proj):
                self._ndef_cap.addItem(p.stem, str(p))
        if self._ndef_cap.count() == 0:
            self._ndef_cap.addItem("(sin capturas en el proyecto)", "")
        self._ndef_cap.blockSignals(False)

    def _load_capture_card(self):
        """EmvCard de la captura seleccionada, o None (tarjeta de prueba fija)."""
        path = self._ndef_cap.currentData()
        if not path:
            return None
        from pathlib import Path
        from ...payments import EmvCard
        from ...session.model import CardDump
        return EmvCard.from_dump(CardDump.from_json(Path(path).read_text()))

    def _gen_ndef(self) -> None:
        src = self._ndef_src.currentData()
        if src == "emv":
            return                       # EMV no usa mensaje NDEF
        try:
            if src == "test":
                msg = cardfuzz.test_card_ndef()
                self._ndef_desc.setText("Datos de una tarjeta de prueba canónica como NDEF.")
            elif src == "capture":
                path = self._ndef_cap.currentData()
                if not path:
                    self._ndef_hex.setText(""); self._ndef_desc.setText(
                        "No hay capturas guardadas en el proyecto activo."); return
                from pathlib import Path
                from ...payments import EmvCard
                from ...session.model import CardDump
                dump = CardDump.from_json(Path(path).read_text())
                card = EmvCard.from_dump(dump)
                msg = cardfuzz.card_ndef_from_fields(
                    pan=card.pan_digits, expiry=card.expiry, track2=card.track2,
                    aid=card.aid, label=card.label)
                self._ndef_desc.setText(f"Datos de la captura «{self._ndef_cap.currentText()}» "
                                        "presentados como NDEF (no es emulación EMV).")
            else:
                t = cardfuzz.get_ndef_template(cardfuzz.ndef_templates(),
                                               self._ndef_tpl.currentData())
                if not t:
                    return
                msg = t.message
                self._ndef_desc.setText(t.description)
        except Exception as e:  # noqa: BLE001
            self.win.notify.emit(f"NDEF: {e}"); return
        self._ndef_hex.setText(to_hex(msg))

    def _emit(self) -> None:
        """Un solo botón: emula según el MODO de la Fuente (EMV o NFC/NDEF)."""
        if self._ndef_src.currentData() == "emv":
            sel = self._ndef_cap.currentData()
            if sel == "__ram__":                       # RAM del firmware (BomberCat)
                self.win.emit_emv(from_ram=True)
                return
            if sel == "__mem__":                       # RAM de la app
                if getattr(self.win, "_scanned_card", None) is None:
                    self.win.notify.emit("No hay tarjeta en memoria. Usa Escanear→memoria.")
                    return
                self.win.emit_emv(card=self.win._scanned_card)
                return
            try:
                card = self._load_capture_card()      # None = tarjeta de prueba fija
            except Exception as e:  # noqa: BLE001
                self.win.notify.emit(f"Captura EMV: {e}")
                return
            self.win.emit_emv(card)
            return
        from ...core.hexutil import from_hex
        hexval = self._ndef_hex.text().strip()
        try:
            from_hex(hexval)
        except ValueError:
            self.win.notify.emit("Mensaje NDEF hex inválido.")
            return
        self.win.emit_ndef(hexval)

    def _scan_mem(self) -> None:
        self.win.scan_to_memory()

    def _scan_ram(self) -> None:
        self.win.scan_to_bombercat_ram()

    def _stop_ndef(self) -> None:
        self.win.stop_ndef()

    def _reboot(self) -> None:
        self.win.reboot_bombercat()

    # -- Editor de tarjeta EMV (escanear → editar → emular) ----------------
    def _card_editor(self) -> QGroupBox:
        box = QGroupBox("Editor de tarjeta EMV · escanear, editar y emular")
        self._ed_disc = ""          # discrecional del track2 original (se preserva)

        # fila de carga: de dónde traer la tarjeta al editor
        self._ed_src = QComboBox()
        self._ed_src.addItem("Escanear→memoria (lector conectado)", "mem")
        self._ed_src.addItem("Escanear→RAM (BomberCat NFC)", "ram")
        self._ed_src.addItem("Captura guardada", "capture")
        self._ed_src.currentIndexChanged.connect(self._ed_src_changed)
        self._ed_cap = QComboBox(); self._ed_cap.hide()
        self._ed_cap.currentIndexChanged.connect(self._ed_load_capture)   # auto-carga al seleccionar
        load = QPushButton("Cargar / escanear"); load.clicked.connect(self._ed_load)
        top = QHBoxLayout()
        top.addWidget(QLabel("Cargar desde")); top.addWidget(self._ed_src)
        top.addWidget(self._ed_cap, 1); top.addWidget(load)

        # campos editables (amistoso): PAN, caducidad, código de servicio, AID,
        # titular, y el track2 (hex) que se puede regenerar desde los anteriores.
        self._ed_pan = QLineEdit(); self._ed_pan.setPlaceholderText("dígitos, p.ej. 4189143370041827")
        self._ed_exp = QLineEdit(); self._ed_exp.setPlaceholderText("YYMM, p.ej. 2909")
        self._ed_svc = QLineEdit(); self._ed_svc.setPlaceholderText("3 dígitos, p.ej. 201")
        self._ed_aid = QLineEdit(); self._ed_aid.setPlaceholderText("hex, p.ej. A0000000031010")
        self._ed_name = QLineEdit(); self._ed_name.setPlaceholderText("titular / etiqueta")
        self._ed_t2 = QLineEdit(); self._ed_t2.setPlaceholderText("Track2 (tag 57) hex")
        for w in (self._ed_pan, self._ed_exp, self._ed_svc):
            w.editingFinished.connect(self._ed_autotrack2)
        form = QFormLayout()
        form.addRow("PAN", self._ed_pan)
        form.addRow("Caducidad (YYMM)", self._ed_exp)
        form.addRow("Cód. servicio", self._ed_svc)
        form.addRow("AID", self._ed_aid)
        form.addRow("Titular", self._ed_name)
        form.addRow("Track2 (hex)", self._ed_t2)

        self._ed_auto = QCheckBox("Regenerar Track2 automáticamente al editar PAN/caducidad")
        self._ed_auto.setChecked(True)
        regen = QPushButton("Regenerar Track2"); regen.clicked.connect(self._ed_regen_track2)
        emit = QPushButton("Emular tarjeta editada"); emit.clicked.connect(self._ed_emit)
        emit.setProperty("accent", True)          # CTA principal del editor
        emit.setIcon(icon("play", color=ACCENT_FG))
        btns = QHBoxLayout(); btns.addWidget(self._ed_auto); btns.addStretch(1)
        btns.addWidget(regen); btns.addWidget(emit)

        hint = _desc()
        hint.setText("Escanea (memoria o RAM del BomberCat) o carga una captura; edita los campos y "
                     "pulsa «Emular tarjeta editada». El Track2 se regenera desde PAN/caducidad/servicio "
                     "(o edítalo a mano). Emula inyectando los datos editados al firmware (EMUEMV:).")
        v = QVBoxLayout(box); v.addLayout(top); v.addLayout(form); v.addLayout(btns); v.addWidget(hint)
        return box

    def _ed_src_changed(self) -> None:
        is_cap = self._ed_src.currentData() == "capture"
        self._ed_cap.setVisible(is_cap)
        if is_cap:
            self._ed_cap.blockSignals(True)      # no disparar la auto-carga al repoblar
            self._ed_cap.clear()
            proj = store.active_project()
            if proj:
                for p in store.list_captures(proj):
                    self._ed_cap.addItem(p.stem, str(p))
            if self._ed_cap.count() == 0:
                self._ed_cap.addItem("(sin capturas en el proyecto)", "")
            self._ed_cap.blockSignals(False)
            self._ed_load_capture()              # auto-carga la primera al elegir 'captura'

    def _ed_load_capture(self) -> None:
        """Carga la captura seleccionada al editor (auto: al cambiar la selección)."""
        path = self._ed_cap.currentData()
        if not path:
            return
        try:
            from pathlib import Path
            from ...payments import EmvCard
            from ...session.model import CardDump
            self._ed_populate(EmvCard.from_dump(CardDump.from_json(Path(path).read_text())))
        except Exception as e:  # noqa: BLE001
            self.win.notify.emit(f"Cargar captura: {e}")

    def _ed_load(self) -> None:
        # botón «Cargar / escanear»: para mem/ram lanza el escaneo (que rellena el
        # editor solo al terminar); para captura recarga la seleccionada.
        src = self._ed_src.currentData()
        if src == "mem":
            self.win.scan_to_memory()
        elif src == "ram":
            self.win.scan_to_bombercat_ram()
        else:
            self._ed_load_capture()

    def _ed_populate(self, card) -> None:
        """Vuelca un EmvCard al editor (se llama tras escanear o cargar)."""
        self._ed_pan.setText(card.pan_digits or "")
        self._ed_exp.setText((card.expiry or "")[:4])
        self._ed_aid.setText(card.aid or "")
        self._ed_name.setText(card.label or "")
        self._ed_t2.setText((card.track2 or "").upper())
        svc, disc = "", ""
        if card.track2:
            t2 = tracklib.parse_track2_emv(card.track2)
            if t2:
                svc = t2.service_code or ""
                disc = t2.discretionary or ""
        self._ed_svc.setText(svc)
        self._ed_disc = disc
        self.win.notify.emit(f"Editor cargado: PAN {card.pan_digits or '?'} AID {card.aid or '?'}.")

    def _ed_regen_track2(self) -> None:
        t2 = tracklib.build_track2_emv(self._ed_pan.text().strip(), self._ed_exp.text().strip(),
                                       self._ed_svc.text().strip(), self._ed_disc)
        self._ed_t2.setText(t2)

    def _ed_autotrack2(self) -> None:
        if self._ed_auto.isChecked():
            self._ed_regen_track2()

    def _ed_emit(self) -> None:
        from ...payments import EmvCard
        if self._ed_auto.isChecked():
            self._ed_regen_track2()
        pan = self._ed_pan.text().strip()
        if not pan and not self._ed_t2.text().strip():
            self.win.notify.emit("Nada que emular: escanea o edita el PAN/Track2 primero.")
            return
        card = EmvCard(pan=pan, expiry=self._ed_exp.text().strip(),
                       aid=self._ed_aid.text().strip(), label=self._ed_name.text().strip(),
                       track2=self._ed_t2.text().strip())
        self.win.emit_emv(card=card)


def _desc() -> QLabel:
    lbl = QLabel("")
    lbl.setWordWrap(True)
    lbl.setProperty("hint", "true")
    return lbl
