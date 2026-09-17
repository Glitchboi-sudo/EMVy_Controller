"""Pantalla de Ajustes (TUI): preferencias globales — tema de color, idioma y
carpeta de datos. Persisten vía `emvy.settings`; el tema se aplica en vivo, el
idioma del todo al reiniciar (los textos ya construidos no se retraducen).
"""
from __future__ import annotations

from textual import on
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Input, Label, Select

from ... import config, i18n, palettes
from ... import settings as settingsmod


class SettingsScreen(Vertical):
    def compose(self):
        cur = settingsmod.load()
        yield Label(i18n.t("settings.title"), classes="title")
        yield Label(i18n.t("settings.subtitle"), classes="subtitle")

        yield Label(i18n.t("settings.theme"), classes="section")
        yield Select([(label, name) for name, label in palettes.names()],
                     value=cur.theme, allow_blank=False, id="set_theme")

        yield Label(i18n.t("settings.language"), classes="section")
        yield Select([(label, code) for code, label in i18n.LANGUAGES],
                     value=cur.language, allow_blank=False, id="set_lang")

        yield Label(i18n.t("settings.data_dir"), classes="section")
        yield Input(value=cur.data_dir, placeholder=str(config.data_home()), id="set_data")
        yield Label(i18n.t("settings.data_hint"), classes="hint")
        yield Label(i18n.t("settings.current_data", path=config.data_home()),
                    id="set_curdata", classes="hint")

        with Horizontal(classes="actions"):
            yield Button(i18n.t("common.save"), id="set_save", variant="primary")

    @on(Select.Changed, "#set_theme")
    def _preview_theme(self, ev: Select.Changed):
        if isinstance(ev.value, str):
            self.app.theme = ev.value          # previsualiza el tema en vivo

    @on(Button.Pressed, "#set_save")
    def _save(self):
        s = settingsmod.Settings(
            theme=str(self.query_one("#set_theme", Select).value),
            language=str(self.query_one("#set_lang", Select).value),
            data_dir=self.query_one("#set_data", Input).value.strip())
        s = settingsmod.save(s)
        settingsmod.apply(s)
        self.app.theme = s.theme               # tema en vivo
        self.query_one("#set_curdata", Label).update(
            i18n.t("settings.current_data", path=config.data_home()))
        try:
            self.app.refresh_ui()              # la carpeta de datos pudo cambiar
        except Exception:
            pass
        self.app.notify(i18n.t("settings.saved") + " " + i18n.t("settings.lang_restart"))
