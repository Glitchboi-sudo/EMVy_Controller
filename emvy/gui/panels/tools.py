"""Panel Herramientas (GUI): sub-pestañas Flags, ISO 8583 y Escritura.

Reutiliza `core.search`, `payments.iso8583`/`iso_host` y `core.cardwrite`
(igual que la TUI). La consola cruda del dock inferior es aparte (transporte).
"""
from __future__ import annotations

from html import escape

from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QFileDialog, QFormLayout, QGroupBox,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPlainTextEdit, QPushButton,
    QTabWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ...core import cardfuzz
from ...core.hexutil import from_hex, to_hex
from ...core.search import search_flags, search_regex
from ...payments import iso8583

_MONO = QFont("monospace"); _MONO.setStyleHint(QFont.Monospace)


def _log() -> QPlainTextEdit:
    w = QPlainTextEdit(readOnly=True); w.setFont(_MONO); w.setMaximumBlockCount(4000)
    return w


class ToolsPanel(QTabWidget):
    def __init__(self, win) -> None:
        super().__init__()
        self.win = win
        self.flags = _FlagsTool(win)
        self.iso = _IsoTool(win)
        self.write = _CardWriteTool(win)     # Escritura directa (APDU) + GlobalPlatform
        self.addTab(self.flags, "Flags")
        self.addTab(self.iso, "ISO 8583")
        self.addTab(self.write, "Escritura")

    # reexpuestos para MainWindow (resultados de workers)
    def log_write(self, op, resp) -> None:
        self.write.log_result(op, resp)
        self.setCurrentWidget(self.write)

    def iso_response(self, resp) -> None:
        self.iso.show_response(resp)

    def gp_log(self, lines) -> None:
        self.write.append_gp_lines(lines)
        self.setCurrentWidget(self.write)

    def gp_refresh(self) -> None:
        self.write.refresh_keysets()


class _FlagsTool(QWidget):
    def __init__(self, win) -> None:
        super().__init__()
        self.win = win
        from ..components import Card, SectionLabel, button, primary_button
        self._pat = QLineEdit(r"flag\{[^}]+\}"); self._pat.setPlaceholderText("patrón regex")
        search = primary_button("Buscar"); search.clicked.connect(self._search)
        default = button("Por defecto"); default.clicked.connect(self._default)
        row = QHBoxLayout(); row.setSpacing(8)
        row.addWidget(self._pat, 1); row.addWidget(search); row.addWidget(default)
        card = Card(margins="sm", spacing="xs")
        card.body.addWidget(SectionLabel("Coincidencias"))
        self._log = _log(); card.body.addWidget(self._log, 1)
        lay = QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(10)
        lay.addLayout(row); lay.addWidget(card, 1)

    def _dump(self):
        d = self.win.last_dump
        if d is None:
            self._log.appendPlainText("No hay captura. Ve a Explorador → Capturar primero.")
        return d

    def _search(self) -> None:
        d = self._dump()
        if d:
            self._render(search_regex(d.all_blobs(), self._pat.text() or r"flag\{[^}]+\}"))

    def _default(self) -> None:
        d = self._dump()
        if d:
            self._render(search_flags(d.all_blobs()))

    def _render(self, hits) -> None:
        if not hits:
            self._log.appendPlainText("Sin coincidencias.")
            return
        self._log.appendPlainText(f"══ {len(hits)} posible(s) flag(s) ══")
        for h in hits:
            self._log.appendPlainText(f"  {h.match}\n    en {h.source} ({h.where})\n    ctx: …{h.context}…")


class _IsoTool(QWidget):
    def __init__(self, win) -> None:
        super().__init__()
        self.win = win
        self._fields: dict[int, bytes] = {}
        self._built: bytes | None = None
        self._des: list[int] = []

        self._mti = QLineEdit("0200"); self._mti.setFixedWidth(64)
        self._de = QLineEdit(); self._de.setPlaceholderText("DE (nº)"); self._de.setFixedWidth(80)
        self._val = QLineEdit(); self._val.setPlaceholderText("valor (hex o texto)")
        self._hex = QCheckBox("hex"); self._hex.setChecked(True)
        setb = QPushButton("Set campo"); setb.clicked.connect(self._set)
        delb = QPushButton("Quitar sel."); delb.clicked.connect(self._del)
        row1 = QHBoxLayout()
        for x in (self._mti, self._de, self._val, self._hex, setb, delb):
            row1.addWidget(x)

        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels(["DE", "nombre", "valor (hex)"])
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)

        build = QPushButton("Construir"); build.clicked.connect(self._build)
        self._host = QLineEdit("127.0.0.1"); self._port = QLineEdit("0"); self._port.setFixedWidth(64)
        self._hdr = QComboBox()
        for label, val in (("hdr 2B", 2), ("sin hdr", 0), ("hdr 4B", 4)):
            self._hdr.addItem(label, val)
        send = QPushButton("Enviar"); send.clicked.connect(self._send)
        row2 = QHBoxLayout()
        row2.addWidget(build); row2.addWidget(self._host, 1)
        row2.addWidget(self._port); row2.addWidget(self._hdr); row2.addWidget(send)

        from ..components import Card, SectionLabel
        fields = Card(margins="sm", spacing="xs")
        fields.body.addWidget(SectionLabel("Campos del mensaje"))
        fields.body.addLayout(row1); fields.body.addWidget(self._table, 1)
        sendc = Card(margins="sm", spacing="xs")
        sendc.body.addWidget(SectionLabel("Enviar")); sendc.body.addLayout(row2)
        outc = Card(margins="sm", spacing="xs")
        outc.body.addWidget(SectionLabel("Salida"))
        self._log = _log(); outc.body.addWidget(self._log, 1)
        lay = QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(10)
        lay.addWidget(fields, 1); lay.addWidget(sendc); lay.addWidget(outc, 1)

    def _refresh(self) -> None:
        self._des = sorted(self._fields)
        self._table.setRowCount(len(self._des))
        for i, de in enumerate(self._des):
            spec = iso8583.DEFAULT_SPEC.get(de)
            for j, val in enumerate((str(de), spec.name if spec else "?", to_hex(self._fields[de]))):
                self._table.setItem(i, j, QTableWidgetItem(val))

    def _set(self) -> None:
        try:
            de = int(self._de.text())
            val = from_hex(self._val.text().strip()) if self._hex.isChecked() \
                else self._val.text().encode("latin-1")
        except ValueError:
            self.win.notify.emit("DE o valor inválido."); return
        self._fields[de] = val
        self._de.clear(); self._val.clear(); self._refresh()

    def _del(self) -> None:
        row = self._table.currentRow()
        if 0 <= row < len(self._des):
            self._fields.pop(self._des[row], None); self._refresh()

    def _build(self) -> None:
        try:
            msg = iso8583.build(self._mti.text().strip(), self._fields)
        except Exception as e:  # noqa: BLE001
            self.win.notify.emit(f"No se pudo construir: {e}"); return
        self._built = msg
        self._log.appendPlainText("Construido: " + to_hex(msg))
        self._log.appendPlainText(iso8583.translate(msg).text())

    def _send(self) -> None:
        if not self._built:
            self.win.notify.emit("Construye el mensaje primero."); return
        port = self._port.text().strip()
        if not port.isdigit() or int(port) == 0:
            self.win.notify.emit("Indica un puerto válido."); return
        self._log.appendPlainText(f"→ enviando a {self._host.text()}:{port}…")
        self.win.send_iso8583(self._host.text().strip(), int(port), self._built,
                              self._hdr.currentData())

    def show_response(self, resp: bytes) -> None:
        self._log.appendPlainText("Respuesta: " + (to_hex(resp) or "(vacía)"))
        if resp:
            try:
                self._log.appendPlainText(iso8583.translate(resp).text())
            except Exception as e:  # noqa: BLE001
                self._log.appendPlainText(f"no parseable como ISO 8583: {e}")


_OPS = [("UPDATE RECORD", "record"), ("UPDATE BINARY", "binary"),
        ("PUT DATA", "data"), ("APPEND RECORD", "append")]


_PRESETS = [
    ("Visa (prueba)", dict(pan="4111111111111111", expiry="2812", name="TEST/CARD", service_code="201")),
    ("Mastercard (prueba)", dict(pan="5555555555554444", expiry="2812", name="TEST/CARD", service_code="201")),
    ("Amex (prueba)", dict(pan="371449635398431", expiry="2812", name="TEST/CARD", service_code="201")),
    ("Personalizado…", None),
]


class _CardWriteTool(QWidget):
    """Escritura en tarjeta, con una UX guiada por intención:

    * **Personalizar** — el camino amistoso: elige un preset o rellena
      PAN/caducidad/titular, mira la vista previa del registro EMV, y escríbelo
      en un clic. La escritura es *inteligente*: si la tarjeta exige canal seguro
      abre GlobalPlatform sola con el keyset elegido.
    * **Avanzado** — escritura directa por APDU (UPDATE RECORD/BINARY, PUT DATA,
      APPEND) e **inicializar/gestionar** la tarjeta por GlobalPlatform (auth,
      GET STATUS, instalar CAP, instanciar applet, DELETE, restaurar a virgen).

    Arriba, una barra de **canal seguro** (keyset) compartida por todo; abajo, un
    log común."""

    def __init__(self, win) -> None:
        super().__init__()
        self.win = win
        lay = QVBoxLayout(self)
        lay.setSpacing(8)

        title = QLabel("Escritura en tarjeta"); title.setProperty("section", True)
        title.setProperty("role", "h2")
        lay.addWidget(title)

        # -- barra de canal seguro (compartida por Personalizar + Avanzado) --
        self._keyset = QComboBox()
        self._enc = QCheckBox("C-ENC")
        refresh = QPushButton("Recargar"); refresh.clicked.connect(self.refresh_keysets)
        bar = QHBoxLayout()
        lk = QLabel("Canal seguro · keyset:")
        bar.addWidget(lk); bar.addWidget(self._keyset, 1); bar.addWidget(self._enc); bar.addWidget(refresh)
        self._sec_hint = QLabel()
        self._sec_hint.setProperty("hint", "true")
        self._keyset.currentTextChanged.connect(self._update_sec_hint)
        lay.addLayout(bar); lay.addWidget(self._sec_hint)

        # -- pestañas por intención -----------------------------------------
        self._tabs = QTabWidget()
        self._tabs.addTab(self._page_personalize(), "Personalizar")
        self._tabs.addTab(self._page_advanced(), "Avanzado")
        lay.addWidget(self._tabs, 1)

        # -- log compartido -------------------------------------------------
        self._log = _log(); self._log.setMaximumHeight(150)
        lay.addWidget(QLabel("Registro:"))
        lay.addWidget(self._log)
        self.refresh_keysets()
        self._apply_preset()          # arranca con el preset por defecto (Visa)
        self._update_preview()

    # -- páginas ------------------------------------------------------------
    def _page_personalize(self) -> QWidget:
        w = QWidget(); v = QVBoxLayout(w)
        sub = QLabel("Preset o campos → registro EMV en SFI 1 · registro 1."
                     "")
        sub.setWordWrap(True); sub.setProperty("hint", "true")
        v.addWidget(sub)

        self._preset = QComboBox()
        for label, _data in _PRESETS:
            self._preset.addItem(label)
        self._preset.currentIndexChanged.connect(self._apply_preset)

        self._p_pan = QLineEdit(); self._p_pan.setPlaceholderText("16 dígitos, p.ej. 4111111111111111")
        self._p_exp = QLineEdit(); self._p_exp.setPlaceholderText("YYMM, p.ej. 2812")
        self._p_name = QLineEdit(); self._p_name.setPlaceholderText("p.ej. TEST/CARD")
        self._p_svc = QLineEdit(); self._p_svc.setPlaceholderText("3 dígitos, p.ej. 201")
        for e in (self._p_pan, self._p_exp, self._p_name, self._p_svc):
            e.textChanged.connect(self._update_preview)
        form = QFormLayout()
        form.addRow("Preset", self._preset)
        form.addRow("PAN", self._p_pan)
        form.addRow("Caducidad (YYMM)", self._p_exp)
        form.addRow("Titular", self._p_name)
        form.addRow("Cód. servicio", self._p_svc)
        v.addLayout(form)

        # vista previa (resumen + hex del registro)
        prev = QGroupBox("Vista previa del registro EMV")
        pv = QVBoxLayout(prev)
        self._prev_sum = QLabel(); self._prev_sum.setWordWrap(True)
        self._prev_hex = QLineEdit(readOnly=True); self._prev_hex.setFont(_MONO)
        pv.addWidget(self._prev_sum); pv.addWidget(self._prev_hex)
        v.addWidget(prev)

        sample = QPushButton("Datos de prueba"); sample.clicked.connect(self._fill_sample)
        copyb = QPushButton("Copiar hex"); copyb.clicked.connect(self._copy_hex)
        adv = QPushButton("Editar en Avanzado →"); adv.clicked.connect(self._generate)
        perso = QPushButton("  Escribir en la tarjeta  "); perso.setProperty("accent", True)
        perso.clicked.connect(self._personalize_write)
        btns = QHBoxLayout()
        btns.addWidget(sample); btns.addWidget(copyb); btns.addWidget(adv)
        btns.addStretch(1); btns.addWidget(perso)
        v.addLayout(btns); v.addStretch(1)
        return w

    def _page_advanced(self) -> QWidget:
        w = QWidget(); v = QVBoxLayout(w)

        # grupo A: escritura directa (APDU)
        direct = QGroupBox("Escritura directa (APDU)")
        dv = QVBoxLayout(direct)
        warn = QLabel("Aviso: modifica la tarjeta (puede ser irreversible). Solo tarjetas "
                      "propias/de laboratorio. Si la tarjeta pide canal seguro, se "
                      "autentica sola con el keyset de arriba.")
        warn.setWordWrap(True); warn.setProperty("hint", "true")
        self._op = QComboBox()
        for label, val in _OPS:
            self._op.addItem(label, val)
        self._op.currentIndexChanged.connect(self._sync_fields)
        self._op_lbl = QLabel("Operación")
        self._sfi_lbl = QLabel("SFI"); self._sfi = QLineEdit(); self._sfi.setFixedWidth(90)
        self._num_lbl = QLabel("Registro"); self._num = QLineEdit(); self._num.setFixedWidth(120)
        self._tag_lbl = QLabel("Tag"); self._tag = QLineEdit(); self._tag.setFixedWidth(120)
        row1 = QHBoxLayout()
        for x in (self._op_lbl, self._op, self._sfi_lbl, self._sfi,
                  self._num_lbl, self._num, self._tag_lbl, self._tag):
            row1.addWidget(x)
        row1.addStretch(1)
        self._data = QLineEdit(); self._data.setPlaceholderText("datos en hex")
        write = QPushButton("Escribir"); write.setProperty("accent", True)
        write.clicked.connect(self._write)
        row2 = QHBoxLayout(); row2.addWidget(self._data, 1); row2.addWidget(write)
        dv.addWidget(warn); dv.addLayout(row1); dv.addLayout(row2)
        v.addWidget(direct)
        self._sync_fields()

        # grupo B: GlobalPlatform · inicializar/gestionar
        gp = QGroupBox("GlobalPlatform · inicializar/gestionar la tarjeta")
        gpl = QVBoxLayout(gp)
        gph = QLabel("Prepara una tarjeta EMV para poder escribir: instala un CAP EMV "
                     "abierto, o instancia un applet ya cargado (GET STATUS lista los "
                     "módulos). Luego personaliza en la pestaña «Personalizar».")
        gph.setWordWrap(True); gph.setProperty("hint", "true")
        auth = QPushButton("Probar autenticación"); auth.clicked.connect(lambda: self._gp("auth"))
        status = QPushButton("Ver contenido (GET STATUS)"); status.clicked.connect(lambda: self._gp("status"))
        install = QPushButton("Instalar CAP EMV…"); install.clicked.connect(self._install)
        arow = QHBoxLayout()
        for b in (auth, status, install):
            arow.addWidget(b)
        arow.addStretch(1)
        self._inst_pkg = QLineEdit(); self._inst_pkg.setPlaceholderText("paquete (hex)")
        self._inst_mod = QLineEdit(); self._inst_mod.setPlaceholderText("módulo (hex)")
        self._inst_aid = QLineEdit(); self._inst_aid.setPlaceholderText("instancia/AID a crear (hex)")
        instantiate = QPushButton("Instanciar applet cargado"); instantiate.clicked.connect(self._instantiate)
        irow = QHBoxLayout()
        for x in (self._inst_pkg, self._inst_mod, self._inst_aid, instantiate):
            irow.addWidget(x)
        self._aid = QLineEdit(); self._aid.setPlaceholderText("AID en hex (para DELETE)")
        delete = QPushButton("DELETE"); delete.clicked.connect(self._delete)
        virgin = QPushButton("Restaurar (virgen)"); virgin.clicked.connect(self._wipe)
        drow = QHBoxLayout(); drow.addWidget(self._aid, 1); drow.addWidget(delete); drow.addWidget(virgin)
        gpl.addWidget(gph); gpl.addLayout(arow); gpl.addLayout(irow); gpl.addLayout(drow)
        v.addWidget(gp); v.addStretch(1)
        return w

    # -- vista previa / presets --------------------------------------------
    def _apply_preset(self) -> None:
        data = _PRESETS[self._preset.currentIndex()][1]
        if data is None:                       # "Personalizado…" → no tocar campos
            return
        self._p_pan.setText(data["pan"]); self._p_exp.setText(data["expiry"])
        self._p_name.setText(data["name"]); self._p_svc.setText(data["service_code"])

    def _update_preview(self) -> None:
        rec = self._build_record()
        self._prev_hex.setText(to_hex(rec))
        self._prev_sum.setText(self._decode_summary(rec))

    def _decode_summary(self, rec: bytes) -> str:
        from ...core import tlv
        try:
            kids = {n.tag: n.value for n in tlv.parse(rec)[0].children}
        except Exception:  # noqa: BLE001
            return ""
        pan = to_hex(kids.get("5A", b"")).rstrip("Ff")
        exp = to_hex(kids.get("5F24", b""))
        t2 = to_hex(kids.get("57", b""))
        name = kids.get("5F20", b"").decode("latin-1", "replace")
        return (f"PAN <b>{pan}</b> · Cad <b>{exp[:2]}/{exp[2:4]}</b> · "
                f"Titular <b>{name}</b><br>Track2 (57): <code>{t2}</code>")

    def _copy_hex(self) -> None:
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(self._prev_hex.text())
        self.win.notify.emit("Registro copiado al portapapeles.")

    def _update_sec_hint(self) -> None:
        ks = self._keyset.currentText().strip()
        if ks:
            self._sec_hint.setText(f"Se autentica sola con «{ks}» solo si la tarjeta lo exige.")
        else:
            self._sec_hint.setText("Sin keyset: si la tarjeta pide canal seguro, la escritura "
                                   "se detendrá (añade uno con 'gp keyset add').")

    def _write_params(self, base: dict) -> dict:
        """Añade el keyset/C-ENC seleccionados a los params de escritura (para la
        escalada automática a canal seguro en `MainWindow.write_op`)."""
        ks = self._keyset.currentText().strip()
        if ks:
            base = {**base, "keyset": ks, "enc": self._enc.isChecked()}
        return base

    # -- personalización rápida --------------------------------------------
    def _fill_sample(self) -> None:
        d = cardfuzz.TEST_RECORD
        self._p_pan.setText(d["pan"]); self._p_exp.setText(d["expiry"])
        self._p_name.setText(d["name"]); self._p_svc.setText(d["service_code"])

    def _build_record(self) -> bytes:
        return cardfuzz.personalize_record(
            pan=self._p_pan.text().strip() or cardfuzz.TEST_RECORD["pan"],
            name=self._p_name.text().strip() or cardfuzz.TEST_RECORD["name"],
            expiry=self._p_exp.text().strip() or cardfuzz.TEST_RECORD["expiry"],
            service_code=self._p_svc.text().strip() or cardfuzz.TEST_RECORD["service_code"])

    def _generate(self) -> None:
        """Lleva el registro generado a la escritura directa (SFI 1 · reg 1) y
        cambia a la pestaña Avanzado para revisarlo/editarlo antes de escribir."""
        rec = self._build_record()
        self._op.setCurrentIndex(0)          # UPDATE RECORD
        self._sfi.setText("1"); self._num.setText("1")
        self._data.setText(to_hex(rec))
        self._tabs.setCurrentIndex(1)        # → Avanzado
        self._log.appendPlainText("Registro llevado a Avanzado (revisa y pulsa «Escribir»): "
                                  + to_hex(rec))

    def _personalize_write(self) -> None:
        rec = self._build_record()
        self._log.appendPlainText("→ personalizar SFI 1 · reg 1: " + to_hex(rec))
        self.win.write_op("record", self._write_params({"sfi": 1, "record": 1, "data": rec}))

    def _write_test(self) -> None:
        """Quick action: escribe el registro EMV de prueba de referencia en un clic."""
        rec = cardfuzz.personalize_record()
        self._log.appendPlainText("→ datos de prueba SFI 1 · reg 1: " + to_hex(rec))
        self.win.write_op("record", self._write_params({"sfi": 1, "record": 1, "data": rec}))

    # -- escritura directa --------------------------------------------------
    def _sync_fields(self) -> None:
        """Muestra solo los campos que el op seleccionado necesita, con la
        etiqueta/placeholder correctos (record/append: SFI+registro; binary:
        offset+SFI; data: tag)."""
        op = self._op.currentData()
        show = {"sfi": op in ("record", "binary", "append"),
                "num": op in ("record", "binary"),
                "tag": op == "data"}
        self._sfi_lbl.setVisible(show["sfi"]); self._sfi.setVisible(show["sfi"])
        self._num_lbl.setVisible(show["num"]); self._num.setVisible(show["num"])
        self._tag_lbl.setVisible(show["tag"]); self._tag.setVisible(show["tag"])
        self._sfi_lbl.setText("SFI (opcional)" if op == "binary" else "SFI")
        self._num_lbl.setText("Offset" if op == "binary" else "Registro")
        self._sfi.setPlaceholderText("1")
        self._num.setPlaceholderText("0" if op == "binary" else "1")
        self._tag.setPlaceholderText("9F36")

    def _write(self) -> None:
        op = self._op.currentData()
        try:
            data = from_hex(self._data.text().strip())
        except ValueError:
            self.win.notify.emit("Datos hex inválidos."); return
        params = {"data": data}
        try:
            if op == "record":
                params["sfi"] = int(self._sfi.text()); params["record"] = int(self._num.text())
            elif op == "binary":
                params["offset"] = int(self._num.text() or "0")
                sfi = self._sfi.text().strip(); params["sfi"] = int(sfi) if sfi else None
            elif op == "data":
                params["tag"] = int(self._tag.text().strip(), 16)
            elif op == "append":
                params["sfi"] = int(self._sfi.text())
        except ValueError:
            self.win.notify.emit("SFI/registro/offset/tag inválido."); return
        self._log.appendPlainText(f"→ {op} {to_hex(data)}…")
        self.win.write_op(op, self._write_params(params))

    def log_result(self, op: str, resp) -> None:
        from ...core import cardwrite
        ok = resp.sw == 0x9000
        mark = "✓" if ok else "✗"
        self._log.appendPlainText(f"{mark} {op.upper()}  SW {resp.sw_hex}  {cardwrite.write_status(resp.sw)}")
        if resp.data:
            self._log.appendPlainText("   data: " + to_hex(resp.data))
        hint = cardwrite.write_hint(resp.sw)
        if hint:
            self._log.appendPlainText("   ℹ " + hint)

    # -- GlobalPlatform -----------------------------------------------------
    def refresh_keysets(self) -> None:
        from ...project import store
        self._keyset.clear()
        proj = store.active_project()
        names = [k.name for k in store.load_keysets(proj)] if proj else []
        self._keyset.addItems(names)
        self._update_sec_hint()

    def _selected(self):
        name = self._keyset.currentText().strip()
        if not name:
            self.win.notify.emit("No hay keyset seleccionado (añade con 'gp keyset add')."); return None
        return name

    def _gp(self, action: str, **kw) -> None:
        name = self._selected()
        if name:
            self.win.gp_op(action, name, enc=self._enc.isChecked(), **kw)

    def _install(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Elegir CAP EMV", "", "CAP (*.cap);;Todos (*)")
        if path:
            self._gp("install", cap=path)

    def _instantiate(self) -> None:
        pkg = self._inst_pkg.text().strip(); mod = self._inst_mod.text().strip()
        inst = self._inst_aid.text().strip()
        if not (pkg and mod and inst):
            self.win.notify.emit("Indica paquete, módulo e instancia (hex). "
                                 "Usa GET STATUS para ver los módulos.")
            return
        self._gp("instantiate", package=pkg, module=mod, instance=inst)

    def _delete(self) -> None:
        aid = self._aid.text().strip()
        if not aid:
            self.win.notify.emit("Indica un AID (hex) para DELETE."); return
        self._gp("delete", aid=aid)

    def _wipe(self) -> None:
        """Restaura la tarjeta a 'virgen': borra las instancias creadas (conserva
        ISD/SD y los paquetes de fábrica)."""
        self._gp("wipe")

    def append_gp_lines(self, lines) -> None:
        for line in lines:
            self._log.appendPlainText(line)
