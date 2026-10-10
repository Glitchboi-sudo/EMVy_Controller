"""Panel Explorador (GUI): captura una tarjeta, muestra su árbol TLV y permite
**copiar / asignar** el valor de un nodo a una variable, y **guardar** la
captura en un proyecto o archivo. Reutiliza `core.tlv`/`project.env`/`store`.
"""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMenu, QPushButton, QSplitter,
    QTableWidget, QTableWidgetItem, QTreeWidget, QTreeWidgetItem,
    QTreeWidgetItemIterator, QVBoxLayout, QWidget,
)

from ...core import tlv
from ...core.hexutil import ascii_printable, from_hex, to_hex
from ...project import env as envmod
from ...project import store

_DATA = Qt.UserRole


def _ascii_of(raw: bytes) -> str:
    if not raw:
        return ""
    s = ascii_printable(raw)
    printable = sum(ch != "." for ch in s)
    return s if printable >= max(1, len(s) * 0.6) else ""


def _hexdata(tag, hexstr, suggest=None) -> dict:
    try:
        ascii_ = _ascii_of(from_hex(hexstr))
    except ValueError:
        ascii_ = ""
    return {"tag": tag, "value": hexstr, "ascii": ascii_, "is_hex": True,
            "suggest": suggest or tag}


def _textdata(text, suggest) -> dict:
    return {"tag": None, "value": str(text), "ascii": str(text), "is_hex": False,
            "suggest": suggest}


def _tlv_item(t: tlv.TLV) -> QTreeWidgetItem:
    name = f"{t.tag}  {t.name}"
    is_leaf = not (t.constructed and t.children)
    raw = t.value if is_leaf else t.to_bytes()
    data = {"tag": t.tag, "value": to_hex(raw), "ascii": _ascii_of(raw),
            "is_hex": True, "suggest": t.tag}
    if not is_leaf:
        item = QTreeWidgetItem([name, ""])
        item.setData(0, _DATA, data)
        for child in t.children:
            item.addChild(_tlv_item(child))
        return item
    interp = t.interpret()
    hx = to_hex(t.value)
    val = hx or "(vacío)"
    if interp != hx and interp != "(vacío)":
        val = f"{hx} → {interp}"
    item = QTreeWidgetItem([name, val])
    item.setData(0, _DATA, data)
    return item


def _add_tlvs(parent: QTreeWidgetItem, blob_hex: str) -> None:
    try:
        for t in tlv.parse(from_hex(blob_hex)):
            parent.addChild(_tlv_item(t))
    except Exception:
        parent.addChild(QTreeWidgetItem(["(no TLV)", blob_hex]))


class ExplorerPanel(QWidget):
    def __init__(self, win) -> None:
        super().__init__()
        self.win = win
        self._sel: dict | None = None
        self._profile = None          # CardProfile de la última captura mostrada

        from ..components import Card, SectionCard, SectionLabel, button, primary_button
        self._SectionCard, self._button, self._primary = SectionCard, button, primary_button

        cap = primary_button("Capturar"); cap.clicked.connect(lambda: self.win.capture("auto"))
        raw = button("Dump crudo"); raw.clicked.connect(self._dump_raw)
        raw.setToolTip("Se adapta al lector (NFC en BomberCat)")
        ana = button("Analizar"); ana.clicked.connect(self._analyze)
        clr = button("Limpiar", variant="ghost"); clr.clicked.connect(self._clear)
        bar = QHBoxLayout(); bar.setSpacing(8)
        bar.addWidget(cap); bar.addWidget(raw); bar.addWidget(ana)
        bar.addStretch(1); bar.addWidget(clr)

        tree_card = Card(margins="sm", spacing="xs")
        tree_card.body.addWidget(SectionLabel("Árbol TLV"))
        self._tree = QTreeWidget()
        self._tree.setColumnCount(2)
        self._tree.setHeaderLabels(["campo", "valor"])
        self._tree.setColumnWidth(0, 320)
        self._tree.setAlternatingRowColors(True)
        self._tree.setRootIsDecorated(True)
        self._tree.currentItemChanged.connect(self._on_item)
        self._tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._context_menu)
        tree_card.body.addWidget(self._tree, 1)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(tree_card)
        splitter.addWidget(self._inspector())
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 1)
        splitter.setHandleWidth(8)

        lay = QVBoxLayout(self); lay.setSpacing(10); lay.setContentsMargins(2, 2, 2, 2)
        lay.addLayout(bar)
        lay.addWidget(splitter, 1)
        self.reload()

    def _inspector(self) -> QWidget:
        SectionCard, button, primary_button = self._SectionCard, self._button, self._primary
        w = QWidget()
        v = QVBoxLayout(w); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(10)

        ident = SectionCard("Identidad de tarjeta", margins="md", spacing="sm")
        self._identity = QLabel("Sin captura.")
        self._identity.setWordWrap(True); self._identity.setProperty("role", "mono")
        self._identity.setTextInteractionFlags(Qt.TextSelectableByMouse)
        ident.body.addWidget(self._identity)
        v.addWidget(ident)

        nodo = SectionCard("Nodo seleccionado", margins="md", spacing="sm")
        self._detail = QLabel("Selecciona un nodo del árbol.")
        self._detail.setWordWrap(True); self._detail.setProperty("role", "mono")
        self._detail.setTextInteractionFlags(Qt.TextSelectableByMouse)
        nodo.body.addWidget(self._detail)
        cprow = QHBoxLayout(); cprow.setSpacing(6)
        chex = button("Copiar hex"); chex.clicked.connect(lambda: self._copy("value"))
        casc = button("Copiar ASCII"); casc.clicked.connect(lambda: self._copy("ascii"))
        ctv = button("tag=val"); ctv.clicked.connect(self._copy_tagval)
        for b in (chex, casc, ctv):
            cprow.addWidget(b)
        cprow.addStretch(1)
        nodo.body.addLayout(cprow)
        v.addWidget(nodo)

        asig = SectionCard("Asignar a variable", margins="md", spacing="sm")
        self._varname = QLineEdit(); self._varname.setPlaceholderText(
            "tag/alias/nombre · vacío = sugerido")
        asig.body.addWidget(self._varname)
        crow = QHBoxLayout(); crow.setSpacing(8)
        self._var_user = QCheckBox("libre"); self._var_ascii = QCheckBox("ASCII")
        assign = primary_button("Asignar"); assign.clicked.connect(self._assign)
        crow.addWidget(self._var_user); crow.addWidget(self._var_ascii)
        crow.addStretch(1); crow.addWidget(assign)
        asig.body.addLayout(crow)
        v.addWidget(asig)

        guardar = SectionCard("Guardar captura", margins="md", spacing="sm")
        self._dest = QComboBox()
        self._savename = QLineEdit(); self._savename.setPlaceholderText(
            "nombre (o ruta .json si destino=archivo)")
        save = primary_button("Guardar"); save.clicked.connect(self._save)
        guardar.body.addWidget(self._dest); guardar.body.addWidget(self._savename)
        srow = QHBoxLayout(); srow.addStretch(1); srow.addWidget(save)
        guardar.body.addLayout(srow)
        v.addWidget(guardar)

        intel = SectionCard("Intel", margins="md", spacing="sm")
        self._intel_table = QTableWidget(0, 4)
        self._intel_table.setHorizontalHeaderLabels(["hash", "esquema", "veces", "última"])
        self._intel_table.horizontalHeader().setStretchLastSection(True)
        self._intel_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._intel_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        intel.body.addWidget(self._intel_table)
        irec = button("Recomendaciones"); irec.clicked.connect(self._intel_recs)
        irow = QHBoxLayout(); irow.addStretch(1); irow.addWidget(irec)
        intel.body.addLayout(irow)
        v.addWidget(intel)
        v.addStretch(1)
        return w

    # -- destinos de guardado ----------------------------------------------
    def reload(self) -> None:
        self._dest.clear()
        self._dest.addItem("→ proyecto activo", "active")
        for p in store.list_projects():
            self._dest.addItem(f"→ proyecto: {p.name}", f"proj:{p.name}")
        for p in store.list_path_projects():
            self._dest.addItem(f"→ ruta: {p.name}", f"path:{p.path}")
        self._dest.addItem("→ archivo (el campo es la ruta)", "file")
        self._reload_intel_table()

    # -- intel: identidad + tabla del proyecto --------------------------------
    def _reload_intel_table(self) -> None:
        """Tarjetas conocidas del proyecto en la tabla INTEL (defensivo)."""
        self._intel_table.setRowCount(0)
        proj = store.active_project()
        if not proj:
            return
        try:
            from ...project.inteldb import IntelDB
            with IntelDB(proj) as db:
                rows = db.list_cards()
        except Exception:
            return
        self._intel_table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            vals = (r.hash[:12], r.profile.scheme or "?",
                    str(r.times_seen),
                    datetime.fromtimestamp(r.last_seen).strftime("%Y-%m-%d"))
            for j, val in enumerate(vals):
                item = QTableWidgetItem(val)
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self._intel_table.setItem(i, j, item)

    def _update_identity(self, dump) -> None:
        """Fingerprint de la captura: hash + veces vista (intel DB del proyecto)."""
        from ...core import fingerprint
        try:
            profile = fingerprint.profile_from_dump(dump)
        except Exception:
            profile = None
        self._profile = profile
        if profile is None:
            self._identity.setText("Captura sin datos de aplicación: sin identidad.")
            return
        proj = store.active_project()
        if not proj:
            self._identity.setText(f"{profile.hash[:16]}…\n"
                                   "Sin proyecto activo: no se consulta la intel DB.")
            return
        try:
            from ...project.inteldb import IntelDB
            with IntelDB(proj) as db:
                row = db.upsert_card(profile)
        except Exception:
            self._identity.setText(f"{profile.hash[:16]}…\n"
                                   "No se pudo consultar la intel DB.")
            return
        veces = "vez" if row.times_seen == 1 else "veces"
        self._identity.setText(
            f"{profile.hash[:16]}…  {profile.scheme or '?'}\n"
            f"Vista {row.times_seen} {veces} en el proyecto · "
            f"última {datetime.fromtimestamp(row.last_seen):%Y-%m-%d %H:%M}"
            + (f"\nNota: {row.notes}" if row.notes else ""))
        self._reload_intel_table()

    def _intel_recs(self) -> None:
        """Diálogo con el top-5 de recomendaciones para el hash mostrado."""
        profile = getattr(self, "_profile", None)
        if profile is None:
            self.win.notify.emit("Captura una tarjeta primero (la identidad da el hash).")
            return
        proj = store.active_project()
        if not proj:
            self.win.notify.emit("Sin proyecto activo: no hay intel DB que consultar.")
            return
        try:
            from ...project.inteldb import IntelDB
            with IntelDB(proj) as db:
                recs = db.recommend_for(profile.hash)
        except Exception as e:  # noqa: BLE001
            self.win.notify.emit(f"No se pudieron calcular recomendaciones: {e}")
            return
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Recomendaciones — {profile.hash[:16]}…")
        lay = QVBoxLayout(dlg)
        text = QLabel()
        text.setWordWrap(True); text.setTextInteractionFlags(Qt.TextSelectableByMouse)
        if not recs:
            text.setText("Sin datos de inteligencia para esta tarjeta.")
        lines = []
        for i, r in enumerate(recs, 1):
            notas = []
            if r.requires_relay:
                notas.append("requiere relay NFC — EMVy aún no lo integra")
            if r.combo:
                notas.append(r.combo)
            tried = f" (previo: {r.tried.result})" if r.tried else ""
            lines.append(f"{i}. {r.attack_id} — {r.title}{tried}\n"
                         f"    {r.reason}" + (f"\n    ⚠ {' · '.join(notas)}" if notas else ""))
        text.setText("\n\n".join(lines))
        lay.addWidget(text)
        btns = QDialogButtonBox(QDialogButtonBox.Close)
        btns.rejected.connect(dlg.reject); btns.accepted.connect(dlg.accept)
        lay.addWidget(btns)
        dlg.exec()

    # -- acciones ----------------------------------------------------------
    def _dump_raw(self) -> None:
        backend = getattr(self.win.reader_device, "backend", None)
        self.win.capture(mode="nfc") if backend == "bombercat" else self.win.capture(raw=True)

    def _clear(self) -> None:
        self._tree.clear(); self._sel = None
        self._detail.setText("Árbol limpio.")
        self._identity.setText("Sin captura.")
        self._profile = None

    def _on_item(self, cur, _prev) -> None:
        data = cur.data(0, _DATA) if cur else None
        self._sel = data if isinstance(data, dict) else None
        if not self._sel:
            self._detail.setText("nodo sin valor asignable")
            return
        tag = self._sel.get("tag") or "—"
        val = self._sel["value"]
        val = val if len(val) <= 96 else val[:96] + "…"
        lines = [f"tag: {tag}", f"valor: {val}"]
        if self._sel.get("ascii"):
            lines.append(f'ascii: "{self._sel["ascii"]}"')
        if self._sel.get("suggest"):
            lines.append(f"→ sugerido: {self._sel['suggest']}")
        self._detail.setText("\n".join(lines))

    # -- menú contextual ---------------------------------------------------
    def _set_all_expanded(self, expanded: bool) -> None:
        it = QTreeWidgetItemIterator(self._tree)
        while it.value():
            it.value().setExpanded(expanded)
            it += 1

    def _context_menu(self, pos) -> None:
        item = self._tree.itemAt(pos)
        if item is not None:
            self._tree.setCurrentItem(item)
        sel = self._sel
        menu = QMenu(self)
        menu.addAction("Expandir todo", lambda: self._set_all_expanded(True))
        menu.addAction("Contraer todo", lambda: self._set_all_expanded(False))
        menu.addSeparator()
        if item is not None:
            campo = item.text(0)
            menu.addAction("Copiar campo", lambda: self._copy_text(campo))
        act_hex = menu.addAction("Copiar hex", lambda: self._copy("value"))
        act_ascii = menu.addAction("Copiar ASCII", lambda: self._copy("ascii"))
        act_tv = menu.addAction("Copiar tag=valor", self._copy_tagval)
        act_hex.setEnabled(bool(sel and sel.get("value")))
        act_ascii.setEnabled(bool(sel and sel.get("ascii")))
        act_tv.setEnabled(bool(sel and sel.get("value")))
        if sel and sel.get("suggest"):
            menu.addSeparator()
            menu.addAction(f"Asignar a variable “{sel['suggest']}”",
                           lambda: self._assign(name=sel["suggest"]))
        menu.addSeparator()
        menu.addAction("Limpiar árbol", self._clear)
        menu.exec(self._tree.viewport().mapToGlobal(pos))

    def _copy_text(self, text: str) -> None:
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(text)
        self.win.notify.emit(f"Copiado: {text[:48]}")

    def _copy(self, key: str) -> None:
        if not self._sel:
            self.win.notify.emit("Selecciona un nodo con valor.")
            return
        text = self._sel.get(key) or ""
        if not text:
            self.win.notify.emit("Sin valor para copiar.")
            return
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(text)
        self.win.notify.emit(f"Copiado: {text[:48]}")

    def _copy_tagval(self) -> None:
        if not self._sel:
            self.win.notify.emit("Selecciona un nodo con valor.")
            return
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(f"{self._sel.get('tag') or '?'}={self._sel['value']}")
        self.win.notify.emit("Copiado tag=valor.")

    def _assign(self, name: str | None = None) -> None:
        if not self._sel:
            self.win.notify.emit("Selecciona un nodo con valor.")
            return
        proj = store.active_project()
        if not proj:
            self.win.notify.emit("No hay proyecto activo.")
            return
        from_field = name is None
        if from_field:
            name = self._varname.text().strip() or self._sel.get("suggest") or ""
        if not name:
            self.win.notify.emit("Indica un nombre de variable.")
            return
        force_user = self._var_user.isChecked()
        if self._var_ascii.isChecked() and self._sel.get("ascii"):
            value, is_hex = self._sel["ascii"], False
        else:
            value, is_hex = self._sel["value"], self._sel.get("is_hex", True)
        tag = None if force_user else envmod.resolve_tag(name)
        try:
            if tag is not None and is_hex:
                value_str = envmod.decode_value(tag, from_hex(value))
            elif tag is not None and not is_hex and not envmod.is_text_tag(tag):
                tag, value_str = None, value
            else:
                value_str = value
            kind = "terminal" if tag is not None else "user"
            variables = envmod.set_var(store.load_project_variables(proj), name, value_str, kind=kind)
            store.save_project_variables(proj, variables)
        except Exception as e:  # noqa: BLE001
            self.win.notify.emit(f"No se pudo asignar: {e}")
            return
        if from_field:
            self._varname.clear()
        self.win.refresh_all()
        self.win.notify.emit(f"{name} = {value_str}  → guardado ({kind}).")

    def _resolve_project(self, dest: str):
        if dest == "active":
            return store.active_project()
        if dest.startswith("proj:"):
            return store.open_project(dest[5:])
        if dest.startswith("path:"):
            return store.open_project_path(dest[5:])
        return None

    def _save(self) -> None:
        dump = self.win.last_dump
        if dump is None:
            self.win.notify.emit("No hay captura que guardar (captura primero).")
            return
        dest = self._dest.currentData()
        name = self._savename.text().strip()
        ts = f"captura-{datetime.now():%Y%m%d-%H%M%S}"
        try:
            if dest == "file":
                from pathlib import Path
                if not name:
                    self.win.notify.emit("Indica la ruta del archivo .json.")
                    return
                path = Path(name).expanduser()
                if path.is_dir() or path.suffix == "":
                    path = path / f"{ts}.json"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(dump.to_json())
                where = str(path)
            else:
                proj = self._resolve_project(dest)
                if not proj:
                    self.win.notify.emit("Sin proyecto destino.")
                    return
                saved = store.save_capture(proj, name or ts, dump.to_json())
                where = f"{proj.name}/{saved.name}"
        except Exception as e:  # noqa: BLE001
            self.win.notify.emit(f"No se pudo guardar: {e}")
            return
        self._savename.clear()
        self.win.refresh_all()
        self.win.notify.emit(f"Captura guardada → {where}")

    def _analyze(self) -> None:
        from ...core import analyze
        from ...session.model import tlvs_from_dump
        dump = self.win.last_dump
        if dump is None:
            self.win.notify.emit("No hay captura para analizar.")
            return
        _app, tlvs = tlvs_from_dump(dump)
        if not tlvs:
            self.win.notify.emit("La captura no tiene datos de aplicación.")
            return
        a = analyze.assess(tlvs)
        root = QTreeWidgetItem(["ANÁLISIS DE SEGURIDAD", ""])
        caps = QTreeWidgetItem(["Capacidades / CVM / ODA", ""])
        for line in a.summary().splitlines():
            caps.addChild(QTreeWidgetItem([line, ""]))
        root.addChild(caps)
        if a.findings:
            fnode = QTreeWidgetItem([f"Hallazgos ({len(a.findings)})", ""])
            for f in a.findings:
                fnode.addChild(QTreeWidgetItem([f"! {f}", ""]))
            root.addChild(fnode)
        self._tree.addTopLevelItem(root)
        root.setExpanded(True)
        self.win.notify.emit(f"Análisis: {len(a.findings)} hallazgo(s).")

    # -- poblar el árbol (lo llama MainWindow tras capturar) ---------------
    def show_dump(self, dump) -> None:
        self._update_identity(dump)
        self._tree.clear()
        blobs = {b["source"]: b["hex"] for b in dump.blobs}
        for app in dump.applications:
            aid = app["aid"]
            meta = " · ".join(x for x in (app.get("label", ""), app.get("source", "")) if x)
            top = QTreeWidgetItem([f"{aid}  {app['scheme']}", meta])
            top.setData(0, _DATA, _hexdata("4F", aid))
            ch = app.get("cardholder") or {}
            if ch:
                info = QTreeWidgetItem(["Titular", ""])
                for k, val in ch.items():
                    it = QTreeWidgetItem([k, str(val)]); it.setData(0, _DATA, _textdata(val, k))
                    info.addChild(it)
                top.addChild(info)
            if app.get("aip"):
                it = QTreeWidgetItem(["AIP", app["aip"]]); it.setData(0, _DATA, _hexdata("82", app["aip"]))
                top.addChild(it)
            if app.get("afl"):
                it = QTreeWidgetItem(["AFL", app["afl"]]); it.setData(0, _DATA, _hexdata("94", app["afl"]))
                top.addChild(it)
            for line in app.get("ndef_records") or []:
                it = QTreeWidgetItem(["NDEF", line]); it.setData(0, _DATA, _textdata(line, "ndef"))
                top.addChild(it)
            fci = blobs.get(f"{aid}:FCI")
            if fci:
                fnode = QTreeWidgetItem(["FCI", ""]); _add_tlvs(fnode, fci); top.addChild(fnode)
            for rec in app.get("records", []):
                rnode = QTreeWidgetItem([f"SFI {rec['sfi']} · REC {rec['record']}", ""])
                _add_tlvs(rnode, rec["hex"]); top.addChild(rnode)
            gd = app.get("get_data") or {}
            if gd:
                gnode = QTreeWidgetItem([f"GET DATA ({len(gd)})", ""])
                for tg, hx in gd.items():
                    it = QTreeWidgetItem([tg, hx]); it.setData(0, _DATA, _hexdata(tg, hx))
                    gnode.addChild(it)
                top.addChild(gnode)
            self._tree.addTopLevelItem(top)
            top.setExpanded(True)
