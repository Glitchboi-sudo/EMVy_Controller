"""Panel Proyectos (GUI): crear, activar y borrar espacios de trabajo."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ...project import store


class ProjectsPanel(QWidget):
    def __init__(self, win) -> None:
        super().__init__()
        self.win = win
        self._rows: list[tuple[str, object]] = []

        sub = QLabel("Espacios de trabajo (XDG o engagements en ruta).")
        sub.setProperty("hint", "true")

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["", "nombre", "creado", "descripción"])
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)

        self._name = QLineEdit(); self._name.setPlaceholderText("nombre del proyecto")
        self._desc = QLineEdit(); self._desc.setPlaceholderText("descripción (opcional)")
        self._path = QLineEdit(); self._path.setPlaceholderText(
            "ruta (opcional; vacío = ~/.local/share/emvy/projects)")
        eng = QPushButton("engagements/"); eng.clicked.connect(self._fill_eng)

        form1 = QHBoxLayout(); form1.addWidget(self._name); form1.addWidget(self._desc)
        form2 = QHBoxLayout(); form2.addWidget(self._path, 1); form2.addWidget(eng)

        new = QPushButton("Crear + activar"); new.clicked.connect(self._new)
        use = QPushButton("Activar selección"); use.clicked.connect(self._use)
        dele = QPushButton("Eliminar selección"); dele.clicked.connect(self._del)
        actions = QHBoxLayout()
        actions.addWidget(new); actions.addWidget(use); actions.addWidget(dele); actions.addStretch(1)

        lay = QVBoxLayout(self)
        lay.addWidget(sub)
        lay.addWidget(self._table, 1)
        lay.addLayout(form1); lay.addLayout(form2); lay.addLayout(actions)
        self.reload()

    def reload(self) -> None:
        active = store.active_project()
        active_rp = active.path.resolve() if active else None
        self._rows = []
        rows = []
        for p in store.list_projects():
            mark = "●" if active_rp and p.path.resolve() == active_rp else ""
            rows.append((mark, p.name, p.created, p.description)); self._rows.append((p.name, None))
        for p in store.list_path_projects():
            mark = "●" if active_rp and p.path.resolve() == active_rp else ""
            desc = f"{p.description}  ·  {p.path}" if p.description else str(p.path)
            rows.append((mark, p.name, "engagement", desc)); self._rows.append((p.name, p.path))
        self._table.setRowCount(len(rows))
        for i, cols in enumerate(rows):
            for j, val in enumerate(cols):
                self._table.setItem(i, j, QTableWidgetItem(str(val)))

    def _selected(self):
        row = self._table.currentRow()
        return self._rows[row] if 0 <= row < len(self._rows) else None

    def _fill_eng(self) -> None:
        from ... import config
        name = self._name.text().strip() or "cliente"
        self._path.setText(str(config.engagements_dirs()[0] / name))

    def _new(self) -> None:
        name = self._name.text().strip(); desc = self._desc.text().strip()
        path = self._path.text().strip()
        if not name and not path:
            self.win.notify.emit("Indica un nombre (o una ruta).")
            return
        try:
            if path:
                p = store.create_project_at(path, name=name or None, description=desc)
                store.set_active_path(p.path)
            else:
                store.create_project(name, description=desc)
                store.set_active(name)
        except Exception as e:  # noqa: BLE001
            self.win.notify.emit(str(e))
            return
        self._name.clear(); self._desc.clear(); self._path.clear()
        self.win.refresh_all()
        self.win.notify.emit(f"Proyecto activo: {store.active_label()}")

    def _use(self) -> None:
        sel = self._selected()
        if not sel:
            self.win.notify.emit("Selecciona un proyecto.")
            return
        name, path = sel
        store.set_active_path(path) if path is not None else store.set_active(name)
        self.win.refresh_all()
        self.win.notify.emit(f"Proyecto activo: {store.active_label()}")

    def _del(self) -> None:
        sel = self._selected()
        if not sel:
            self.win.notify.emit("Selecciona un proyecto.")
            return
        name, path = sel
        if path is not None:
            self.win.notify.emit("Los engagements en ruta no se borran desde aquí.")
            return
        try:
            store.delete_project(name)
        except Exception as e:  # noqa: BLE001
            self.win.notify.emit(str(e))
            return
        self.win.refresh_all()
        self.win.notify.emit(f"Proyecto {name!r} eliminado.")
