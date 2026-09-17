"""Panel de Ajustes (GUI): preferencias globales — tema de color, idioma y
carpeta de datos. Persisten vía `emvy.settings` y se aplican en vivo (el tema
recolorea al instante; el idioma retraduce nav/pestañas y del todo al reiniciar).
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QVBoxLayout, QWidget,
)

from ... import config, i18n, palettes, settings as settingsmod


class SettingsPanel(QWidget):
    def __init__(self, win) -> None:
        super().__init__()
        self.win = win
        lay = QVBoxLayout(self)

        self._title = QLabel(); self._title.setStyleSheet("font-weight:700; font-size:16px;")
        self._sub = QLabel(); self._sub.setWordWrap(True); self._sub.setStyleSheet("color:#94A3B8;")
        lay.addWidget(self._title); lay.addWidget(self._sub)

        cur = settingsmod.load()
        self._theme = QComboBox()
        for name, label in palettes.names():
            self._theme.addItem(label, name)
        self._select_data(self._theme, cur.theme)
        self._theme.currentIndexChanged.connect(self._preview_theme)   # previsualiza en vivo

        self._lang = QComboBox()
        for code, label in i18n.LANGUAGES:
            self._lang.addItem(label, code)
        self._select_data(self._lang, cur.language)

        self._data = QLineEdit(cur.data_dir)
        browse = QPushButton(); browse.clicked.connect(self._browse)
        self._browse_btn = browse
        drow = QHBoxLayout(); drow.addWidget(self._data, 1); drow.addWidget(browse)
        drow_w = QWidget(); drow_w.setLayout(drow)

        self._form = QFormLayout()
        self._theme_lbl, self._lang_lbl, self._data_lbl = QLabel(), QLabel(), QLabel()
        self._form.addRow(self._theme_lbl, self._theme)
        self._form.addRow(self._lang_lbl, self._lang)
        self._form.addRow(self._data_lbl, drow_w)
        lay.addLayout(self._form)

        self._data_hint = QLabel(); self._data_hint.setWordWrap(True)
        self._data_hint.setStyleSheet("color:#94A3B8;")
        self._cur_data = QLabel(); self._cur_data.setStyleSheet("color:#94A3B8;")
        lay.addWidget(self._data_hint); lay.addWidget(self._cur_data)

        self._save = QPushButton(); self._save.setProperty("accent", True)
        self._save.clicked.connect(self._do_save)
        row = QHBoxLayout(); row.addStretch(1); row.addWidget(self._save)
        lay.addLayout(row); lay.addStretch(1)
        self.retranslate()

    @staticmethod
    def _select_data(combo: QComboBox, value: str) -> None:
        i = combo.findData(value)
        if i >= 0:
            combo.setCurrentIndex(i)

    def retranslate(self) -> None:
        self._title.setText(i18n.t("settings.title"))
        self._sub.setText(i18n.t("settings.subtitle"))
        self._theme_lbl.setText(i18n.t("settings.theme"))
        self._lang_lbl.setText(i18n.t("settings.language"))
        self._data_lbl.setText(i18n.t("settings.data_dir"))
        self._data.setPlaceholderText(str(config.data_home()))
        self._browse_btn.setText(i18n.t("common.browse"))
        self._data_hint.setText(i18n.t("settings.data_hint"))
        self._cur_data.setText(i18n.t("settings.current_data", path=config.data_home()))
        self._save.setText(i18n.t("common.save"))

    def reload(self) -> None:                 # llamado por refresh_all
        self._cur_data.setText(i18n.t("settings.current_data", path=config.data_home()))

    def _browse(self) -> None:
        d = QFileDialog.getExistingDirectory(self, i18n.t("settings.data_dir"),
                                             self._data.text() or str(config.data_home()))
        if d:
            self._data.setText(d)

    def _preview_theme(self) -> None:
        self.win.apply_theme_live(self._theme.currentData())

    def _do_save(self) -> None:
        s = settingsmod.Settings(theme=self._theme.currentData(),
                                 language=self._lang.currentData(),
                                 data_dir=self._data.text().strip())
        s = settingsmod.save(s)
        settingsmod.apply(s)
        self.win.apply_theme_live(s.theme)
        self.win.retranslate()
        self.win.refresh_all()
        self.win.notify.emit(i18n.t("settings.saved") + "  " + i18n.t("settings.lang_restart"))
