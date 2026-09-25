"""Panel Variables (GUI): perfil de terminal EMV + variables libres del proyecto."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ...project import env as envmod
from ...project import profiles as profilesmod
from ...project import store


class VariablesPanel(QWidget):
    def __init__(self, win) -> None:
        super().__init__()
        self.win = win
        self._rows: list[str] = []

        self._hint = QLabel(""); self._hint.setProperty("hint", "true")

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["tag", "nombre", "valor", "tipo"])
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)

        self._name = QLineEdit(); self._name.setPlaceholderText("nombre / alias / tag (p.ej. amount, 9F02)")
        self._value = QLineEdit(); self._value.setPlaceholderText("valor (texto para an/ans, hex para el resto)")
        self._user = QCheckBox("variable libre (no terminal)")
        form = QHBoxLayout(); form.addWidget(self._name); form.addWidget(self._value)

        setb = QPushButton("Guardar"); setb.clicked.connect(self._set)
        delb = QPushButton("Borrar selección"); delb.clicked.connect(self._del)
        rel = QPushButton("Recargar"); rel.clicked.connect(self.reload)
        actions = QHBoxLayout()
        actions.addWidget(self._user); actions.addWidget(setb)
        actions.addWidget(delb); actions.addWidget(rel); actions.addStretch(1)

        self._profile = QComboBox()
        self._profile.addItem("perfil de terminal preconfigurado…", None)
        for p in profilesmod.list_profiles():
            self._profile.addItem(p.title, p.id)
        self._profile.currentIndexChanged.connect(self._profile_changed)
        apply_b = QPushButton("Aplicar perfil"); apply_b.clicked.connect(self._apply_profile)
        self._profile_desc = QLabel(""); self._profile_desc.setProperty("hint", "true")
        prow = QHBoxLayout(); prow.addWidget(self._profile, 1); prow.addWidget(apply_b)

        lay = QVBoxLayout(self)
        lay.addWidget(self._hint)
        lay.addWidget(self._table, 1)
        lay.addLayout(form); lay.addLayout(actions)
        lay.addLayout(prow); lay.addWidget(self._profile_desc)
        self.reload()

    def reload(self) -> None:
        proj = store.active_project()
        if not proj:
            self._hint.setText("No hay proyecto activo. Créalo/actívalo en la pestaña Proyectos.")
            self._table.setRowCount(0); self._rows = []
            return
        self._hint.setText(f"Proyecto activo: {proj.name}")
        variables = store.load_project_variables(proj)
        vs = sorted(variables, key=lambda x: (x.kind != "terminal", x.tag or "", x.name))
        self._rows = [v.name for v in vs]
        self._table.setRowCount(len(vs))
        for i, v in enumerate(vs):
            for j, val in enumerate((v.tag or "", v.name, v.value, v.kind)):
                self._table.setItem(i, j, QTableWidgetItem(val))

    def _selected(self):
        row = self._table.currentRow()
        return self._rows[row] if 0 <= row < len(self._rows) else None

    def _set(self) -> None:
        proj = store.active_project()
        if not proj:
            self.win.notify.emit("No hay proyecto activo.")
            return
        name = self._name.text().strip()
        if not name:
            self.win.notify.emit("Indica un nombre de variable.")
            return
        kind = "user" if self._user.isChecked() else None
        try:
            variables = envmod.set_var(store.load_project_variables(proj), name,
                                       self._value.text(), kind=kind)
        except Exception as e:  # noqa: BLE001
            self.win.notify.emit(str(e))
            return
        store.save_project_variables(proj, variables)
        self._name.clear(); self._value.clear()
        self.reload()
        self.win.notify.emit(f"Variable {name!r} guardada.")

    def _del(self) -> None:
        proj = store.active_project(); name = self._selected()
        if not (proj and name):
            self.win.notify.emit("Selecciona una variable.")
            return
        variables = envmod.del_var(store.load_project_variables(proj), name)
        store.save_project_variables(proj, variables)
        self.reload()
        self.win.notify.emit(f"Variable {name!r} borrada.")

    def _profile_changed(self) -> None:
        pid = self._profile.currentData()
        p = profilesmod.get(pid) if pid else None
        self._profile_desc.setText(p.description if p else "")

    def _apply_profile(self) -> None:
        proj = store.active_project()
        if not proj:
            self.win.notify.emit("No hay proyecto activo.")
            return
        pid = self._profile.currentData()
        if not pid:
            self.win.notify.emit("Elige un perfil de la lista.")
            return
        variables = profilesmod.apply_profile(store.load_project_variables(proj), pid)
        store.save_project_variables(proj, variables)
        self.reload()
        self.win.notify.emit(f"Perfil {pid!r} aplicado.")
