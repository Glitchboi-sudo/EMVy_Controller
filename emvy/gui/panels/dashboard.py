"""Panel Inicio (GUI): **centro de operaciones**. De un vistazo: estado del
proyecto/lector/tarjeta, el siguiente paso como acción directa, capturas y
proyectos recientes (abribles con doble clic) y accesos rápidos. Refleja el
estado de sesión de MainWindow y el proyecto activo.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QPushButton, QVBoxLayout, QWidget,
)

from ... import __release__, __version__
from ...project import store
from ..brand import brand_pixmap
from ..icons import icon
from ..theme import ACCENT, ACCENT_FG, MUTED, TEXT


class DashboardPanel(QWidget):
    def __init__(self, win) -> None:
        super().__init__()
        self.win = win
        self._next_action = None

        # -- encabezado con la marca (mark + wordmark + versión) -----------
        mark = QLabel(); mark.setPixmap(brand_pixmap("logo", 46, ACCENT))
        mark.setFixedSize(mark.pixmap().size())
        wm = QLabel(); wm.setPixmap(brand_pixmap("wordmark", 30, TEXT))
        wm.setFixedSize(wm.pixmap().size())
        ctrl = QLabel("Controller"); ctrl.setStyleSheet(f"color:{MUTED}; font-size:20px; font-weight:600;")
        wmrow = QHBoxLayout(); wmrow.setSpacing(8); wmrow.setContentsMargins(0, 0, 0, 0)
        wmrow.addWidget(wm); wmrow.addWidget(ctrl, 0, Qt.AlignBottom)
        ver = QLabel(f"v{__version__} · {__release__} · EMV security testing & card exploration")
        ver.setStyleSheet(f"color:{MUTED}; font-size:12px;")
        text_col = QVBoxLayout(); text_col.setSpacing(2)
        text_col.addLayout(wmrow); text_col.addWidget(ver)
        head = QHBoxLayout(); head.setSpacing(14)
        head.addWidget(mark, 0, Qt.AlignVCenter); head.addLayout(text_col); head.addStretch(1)

        # -- fila de tarjetas de estado ------------------------------------
        self._proj_box, self._proj_v, self._proj_c = self._stat("Proyecto activo")
        self._rdr_box, self._rdr_v, self._rdr_c = self._stat("Lector")
        self._card_box, self._card_v, self._card_c = self._stat("Tarjeta · captura")
        cards = QHBoxLayout(); cards.setSpacing(12)
        for b in (self._proj_box, self._rdr_box, self._card_box):
            cards.addWidget(b, 1)

        # -- siguiente paso (acción directa) -------------------------------
        step_box = QGroupBox("Siguiente paso")
        sv = QHBoxLayout(step_box)
        self._next_lbl = QLabel(""); self._next_lbl.setWordWrap(True)
        self._next_lbl.setStyleSheet(f"color:{TEXT};")
        self._next_btn = QPushButton("Continuar"); self._next_btn.setProperty("accent", True)
        self._next_btn.setIcon(icon("play", color=ACCENT_FG))
        self._next_btn.setMinimumWidth(160)
        self._next_btn.clicked.connect(lambda: self._next_action and self._next_action())
        sv.addWidget(self._next_lbl, 1); sv.addWidget(self._next_btn)

        # -- listas: capturas del proyecto | proyectos ---------------------
        cap_box = QGroupBox("Capturas del proyecto  ·  doble clic para abrir")
        self._caps = QListWidget()
        self._caps.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._caps.itemDoubleClicked.connect(self._open_capture)
        cv = QVBoxLayout(cap_box); cv.addWidget(self._caps)

        prj_box = QGroupBox("Proyectos  ·  doble clic para activar")
        self._projs = QListWidget()
        self._projs.itemDoubleClicked.connect(self._activate_recent)
        pv = QVBoxLayout(prj_box); pv.addWidget(self._projs)

        lists = QHBoxLayout(); lists.setSpacing(12)
        lists.addWidget(cap_box, 1); lists.addWidget(prj_box, 1)

        # -- accesos rápidos ------------------------------------------------
        qa = QHBoxLayout()
        qa.addWidget(QLabel("Accesos rápidos:"))
        for text, ic, fn in (("Lectores", "plug", lambda: self._go("Lectores")),
                             ("Capturar", "search", self._capture_now),
                             ("Emular / Editor", "zap", lambda: self._go("Fuzzing")),
                             ("Cobros", "credit-card", lambda: self._go("Cobros")),
                             ("PoC", "flask", lambda: self._go("PoC"))):
            b = QPushButton(text); b.setIcon(icon(ic)); b.clicked.connect(fn); qa.addWidget(b)
        qa.addStretch(1)

        lay = QVBoxLayout(self); lay.setSpacing(12)
        lay.addLayout(head)
        lay.addLayout(cards)
        lay.addWidget(step_box)
        lay.addLayout(lists, 1)
        lay.addLayout(qa)
        self.reload()

    # -- helpers de UI ------------------------------------------------------
    def _stat(self, title: str):
        box = QGroupBox(title)
        v = QVBoxLayout(box); v.setSpacing(2)
        value = QLabel("—"); value.setStyleSheet(f"font-size:16px; font-weight:600; color:{TEXT};")
        caption = QLabel(""); caption.setStyleSheet(f"color:{MUTED}; font-size:12px;")
        v.addWidget(value); v.addWidget(caption)
        return box, value, caption

    # -- refresco -----------------------------------------------------------
    def reload(self) -> None:
        proj = store.active_project()
        if proj:
            nvar = len(store.load_project_variables(proj))
            caps = store.list_captures(proj)
            self._proj_v.setText(proj.name)
            self._proj_c.setText(f"{nvar} variables · {len(caps)} capturas")
        else:
            self._proj_v.setText("Sin proyecto")
            self._proj_c.setText("crea/activa uno en Proyectos")
            caps = []

        rdr = self.win.reader_device.name if self.win.reader_device else None
        self._rdr_v.setText(rdr or "Desconectado")
        self._rdr_c.setText(f"{self.win.reader_device.backend}" if rdr else "pulsa Lectores")

        dump = self.win.last_dump
        self._card_v.setText(self.win.card_atr[:22] + "…" if (self.win.card_atr and
                             len(self.win.card_atr) > 23) else (self.win.card_atr or
                             ("Sin tarjeta" if rdr else "Sin lector")))
        self._card_c.setText(f"captura: {len(dump.applications)} app · {len(dump.blobs)} blobs"
                             if dump else "sin captura")

        # siguiente paso + acción
        if not proj:
            self._set_next("Crea o selecciona un proyecto para empezar.",
                           "Ir a Proyectos", lambda: self._go("Proyectos"))
        elif not rdr:
            self._set_next("Conecta un lector (PC/SC, NFC o BomberCat).",
                           "Conectar lector", lambda: self._go("Lectores"))
        elif dump is None:
            self._set_next("Captura una tarjeta para inspeccionar su árbol TLV.",
                           "Capturar tarjeta", self._capture_now)
        else:
            self._set_next("Tarjeta capturada. Explórala, emúlala o busca flags.",
                           "Ir a Fuzzing", lambda: self._go("Fuzzing"))

        # capturas del proyecto (recientes primero)
        self._caps.clear()
        for p in sorted(caps, key=lambda x: x.stat().st_mtime, reverse=True):
            it = QListWidgetItem(p.stem)
            it.setData(Qt.UserRole, str(p))
            self._caps.addItem(it)
        if not caps:
            self._caps.addItem(QListWidgetItem("(sin capturas — captura una tarjeta)"))

        # proyectos
        self._projs.clear()
        projs = store.list_projects()
        try:
            projs = projs + [p for p in store.list_path_projects() if p not in projs]
        except Exception:
            pass
        for p in projs:
            it = QListWidgetItem(p.name)
            it.setData(Qt.UserRole, (p.name, getattr(p, "path", None)))
            self._projs.addItem(it)

    def _set_next(self, text: str, btn: str, action) -> None:
        self._next_lbl.setText(text)
        self._next_btn.setText(btn)
        self._next_action = action

    # -- acciones -----------------------------------------------------------
    def _open_capture(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.UserRole)
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
        self.win.notify.emit(f"Captura abierta en el Explorador: {item.text()}")

    def _activate_recent(self, item: QListWidgetItem) -> None:
        data = item.data(Qt.UserRole)
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
