"""Preferencias globales del programa (tema, idioma, carpeta de datos).

Persisten en `<config_home>/settings.json` (siempre en XDG, no se redirige). El
directorio de **datos** sí es redirigible por el usuario: `apply()` lo empuja a
`config.set_data_home()` y el idioma a `i18n.set_language()`, de modo que un
único `apply(load())` al arrancar configura toda la app.

Puro salvo la IO de disco (load/save), aislada aquí.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from . import config, i18n, palettes


@dataclass
class Settings:
    theme: str = palettes.DEFAULT       # nombre de paleta (palettes.PALETTES)
    language: str = "es"                 # es | en | pt
    data_dir: str = ""                   # override de la carpeta de datos ("" = por defecto)

    def normalized(self) -> "Settings":
        """Devuelve una copia saneada (tema/idioma válidos)."""
        theme = self.theme if self.theme in palettes.PALETTES else palettes.DEFAULT
        lang = self.language if self.language in {c for c, _ in i18n.LANGUAGES} else "es"
        return Settings(theme=theme, language=lang, data_dir=(self.data_dir or "").strip())


def settings_file():
    return config.config_home() / "settings.json"


def load() -> Settings:
    """Carga los ajustes (o los de por defecto si no hay/está corrupto)."""
    path = settings_file()
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return Settings()
    known = {f for f in Settings.__dataclass_fields__}
    return Settings(**{k: v for k, v in data.items() if k in known}).normalized()


def save(s: Settings) -> Settings:
    """Guarda los ajustes (saneados) y los devuelve."""
    s = s.normalized()
    config.ensure_dir(config.config_home())
    settings_file().write_text(json.dumps(asdict(s), indent=2, ensure_ascii=False))
    return s


def apply(s: Settings) -> Settings:
    """Aplica los ajustes al proceso: carpeta de datos + idioma (efecto global).
    El tema lo aplica cada front-end (necesita su `app`)."""
    s = s.normalized()
    config.set_data_home(s.data_dir or None)
    i18n.set_language(s.language)
    return s
