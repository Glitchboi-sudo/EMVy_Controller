"""Panel Inicio (GUI): panel de operaciones **sobrio y denso** de un console de
pentest bancario. Sin texto de ayuda obvio: estado del entorno en tarjetas KPI,
una sugerencia de acción compacta, y capturas/proyectos en tablas. Compuesto con
el kit (`gui.components`); reutiliza la lógica de datos (`store.*`).
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QHeaderView, QLabel, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from ... import __release__, __version__
from ...project import store
from ...readers import registry
from ..components import Card, Chip, EmptyState, SectionLabel, StatCard, button


class DashboardPanel(QWidget):
    def __init__(self, win) -> None:
        super().__init__()
        self.win = win
        self._next_action = None

        # -- fila de KPIs de estado ----------------------------------------
        self._proj_card = StatCard("Proyecto", icon_name="folder", badge="accent")
        self._rdr_card = StatCard("Lector", icon_name="plug", badge="neutral")
        self._card_card = StatCard("Tarjeta", icon_name="credit-card", badge="neutral")
        self._env_card = StatCard("Backends", icon_name="cpu", badge="neutral")
        cards = QHBoxLayout(); cards.setSpacing(10)
        for c in (self._proj_card, self._rdr_card, self._card_card, self._env_card):
            cards.addWidget(c, 1)

        # -- sugerencia de acción (una línea, discreta) --------------------
        strip = Card(variant="hero", margins="sm", spacing="xs")
        srow = QHBoxLayout(); srow.setSpacing(10)
        srow.addWidget(SectionLabel("Siguiente"), 0, Qt.AlignVCenter)
        self._next_lbl = QLabel(""); self._next_lbl.setProperty("role", "body")
        srow.addWidget(self._next_lbl, 1, Qt.AlignVCenter)
        self._next_btn = button("Continuar", variant="primary")
        self._next_btn.clicked.connect(lambda: self._next_action and self._next_action())
        srow.addWidget(self._next_btn, 0, Qt.AlignVCenter)
        strip.body.addLayout(srow)

        # -- tablas: capturas | proyectos ----------------------------------
        cap_card = Card()
        cap_card.body.addWidget(self._table_head("Capturas", "abrir: doble clic"))
        self._caps = self._make_table(["Captura", "Actualizado"])
        self._caps.itemDoubleClicked.connect(self._open_capture)
        self._caps_empty = EmptyState("Sin capturas", icon_name="inbox")
        cap_card.body.addWidget(self._caps, 1)
        cap_card.body.addWidget(self._caps_empty, 1)

        prj_card = Card()
        prj_card.body.addWidget(self._table_head("Proyectos", "activar: doble clic"))
        self._projs = self._make_table(["Proyecto", "Tipo"])
        self._projs.itemDoubleClicked.connect(self._activate_recent)
        prj_card.body.addWidget(self._projs, 1)

        lists = QHBoxLayout(); lists.setSpacing(10)
        lists.addWidget(cap_card, 1); lists.addWidget(prj_card, 1)

        # -- pie: uso autorizado (una línea) -------------------------------
        foot = QHBoxLayout(); foot.setSpacing(8)
        foot.addWidget(Chip("USO AUTORIZADO", "warn"), 0, Qt.AlignVCenter)
        ftxt = QLabel("Laboratorio · tarjetas propias/de test · sin transacciones válidas")
        ftxt.setProperty("role", "caption")
        foot.addWidget(ftxt, 1, Qt.AlignVCenter)
        fver = QLabel(f"v{__version__} · {__release__}"); fver.setProperty("role", "caption")
        foot.addWidget(fver, 0, Qt.AlignVCenter)

        lay = QVBoxLayout(self); lay.setSpacing(10); lay.setContentsMargins(2, 2, 2, 2)
        lay.addLayout(cards)
        lay.addWidget(strip)
        lay.addLayout(lists, 1)
        lay.addLayout(foot)
        self.reload()

    # -- helpers de UI ------------------------------------------------------
    @staticmethod
    def _table_head(title: str, hint: str) -> QWidget:
        w = QWidget(); row = QHBoxLayout(w); row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(SectionLabel(title)); row.addStretch(1)
        row.addWidget(Chip(hint, "neutral"))
        return w

    @staticmethod
    def _make_table(cols: list[str]) -> QTableWidget:
        t = QTableWidget(0, len(cols))
        t.setHorizontalHeaderLabels(cols)
        t.verticalHeader().setVisible(False)
        t.setSelectionBehavior(QAbstractItemView.SelectRows)
        t.setSelectionMode(QAbstractItemView.SingleSelection)
        t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        t.setShowGrid(False)
        t.horizontalHeader().setStretchLastSection(True)
        t.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        return t

    # -- refresco -----------------------------------------------------------
    def reload(self) -> None:
        proj = store.active_project()
        if proj:
            nvar = len(store.load_project_variables(proj))
            caps = store.list_captures(proj)
            self._proj_card.set_value(proj.name)
            self._proj_card.set_caption(f"{nvar} vars · {len(caps)} capt.")
            self._proj_card.set_status("Activo", "on")
        else:
            self._proj_card.set_value("—")
            self._proj_card.set_caption("ninguno activo")
            self._proj_card.set_status("", "off")
            caps = []

        rdr = self.win.reader_device.name if self.win.reader_device else None
        self._rdr_card.set_value(rdr or "—")
        self._rdr_card.set_caption(self.win.reader_device.backend if rdr else "desconectado")
        self._rdr_card.set_status("Online" if rdr else "", "on" if rdr else "off")

        dump = self.win.last_dump
        atr = self.win.card_atr
        self._card_card.set_value("Presente" if atr else "—")
        self._card_card.set_caption(
            f"{len(dump.applications)} app · {len(dump.blobs)} blobs" if dump else "sin captura")
        self._card_card.set_status("Capturada" if dump else "", "on" if dump else "off")

        # backends disponibles (dato de entorno, denso)
        try:
            b = registry.available_backends()
            up = [n for n, ok in b.items() if ok]
            self._env_card.set_value(f"{len(up)}/{len(b)}")
            self._env_card.set_caption(" ".join(up) if up else "ninguno")
        except Exception:
            self._env_card.set_value("—"); self._env_card.set_caption("")

        # sugerencia de acción (terse)
        if not proj:
            self._set_next("sin proyecto activo", "Proyectos", lambda: self._go("Proyectos"))
        elif not rdr:
            self._set_next("lector desconectado", "Conectar", lambda: self._go("Lectores"))
        elif dump is None:
            self._set_next("sin captura en sesión", "Capturar", self._capture_now)
        else:
            self._set_next("captura lista", "Explorar", lambda: self._go("Explorador"))

        # capturas (recientes primero)
        self._caps.setRowCount(0)
        for p in sorted(caps, key=lambda x: x.stat().st_mtime, reverse=True):
            when = datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            self._add_row(self._caps, [p.stem, when], data=str(p))
        has_caps = bool(caps)
        self._caps.setVisible(has_caps)
        self._caps_empty.setVisible(not has_caps)

        # proyectos
        self._projs.setRowCount(0)
        xdg = store.list_projects()
        xdg_names = {p.name for p in xdg}
        rows = [(p, "XDG") for p in xdg]
        try:
            rows += [(p, "engagement") for p in store.list_path_projects()
                     if p.name not in xdg_names]
        except Exception:
            pass
        for p, kind in rows:
            self._add_row(self._projs, [p.name, kind], data=(p.name, getattr(p, "path", None)))

    @staticmethod
    def _add_row(t: QTableWidget, values: list[str], *, data) -> None:
        r = t.rowCount(); t.insertRow(r)
        for c, v in enumerate(values):
            it = QTableWidgetItem(v)
            if c == 0:
                it.setData(Qt.UserRole, data)
            t.setItem(r, c, it)

    def _set_next(self, text: str, btn: str, action) -> None:
        self._next_lbl.setText(text)
        self._next_btn.setText(btn)
        self._next_action = action

    # -- acciones -----------------------------------------------------------
    def _open_capture(self, item: QTableWidgetItem) -> None:
        path = self._caps.item(item.row(), 0).data(Qt.UserRole)
        if not path:
            return
        try:
            from ...session.model import CardDump
            dump = CardDump.from_json(Path(path).read_text())
        except Exception as e:  # noqa: BLE001
            self.win.notify.emit(f"Abrir captura: {e}"); return
        self.win.last_dump = dump
        self.win.explorer_panel.show_dump(dump)
        self._go("Explorador")
        self.win.notify.emit(f"Captura abierta: {Path(path).stem}")

    def _activate_recent(self, item: QTableWidgetItem) -> None:
        data = self._projs.item(item.row(), 0).data(Qt.UserRole)
        if not data:
            return
        name, path = data
        try:
            store.set_active(name)
        except Exception:
            if path is not None:
                store.set_active_path(path)
        self.win.refresh_all()
        self.win.notify.emit(f"Proyecto activo: {name}")

    def _go(self, tab_name: str) -> None:
        tabs = self.win.tabs
        for i in range(tabs.count()):
            if tabs.tabText(i) == tab_name:
                tabs.setCurrentIndex(i); return

    def _capture_now(self) -> None:
        self._go("Explorador")
        self.win.capture("auto")
