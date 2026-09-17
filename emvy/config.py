"""Rutas base de la aplicación (XDG) y ajustes globales.

Un único lugar donde se resuelven los directorios de datos/config, para que
`project.store` y la TUI no dupliquen lógica de rutas.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "emvy"


def _xdg(env: str, default: Path) -> Path:
    val = os.environ.get(env)
    return Path(val) if val else default


# Override en runtime del directorio de datos (lo fija `settings.apply()` desde
# la preferencia del usuario). Tiene prioridad sobre XDG; `EMVY_DATA_HOME` (env)
# sirve para lo mismo sin tocar los ajustes. Ambos apuntan a la carpeta de datos
# **completa** (la que contiene `projects/`), no a la base XDG.
_DATA_OVERRIDE: Path | None = None


def set_data_home(path: "str | Path | None") -> None:
    """Fija (o limpia con None) el directorio de datos usado por toda la app."""
    global _DATA_OVERRIDE
    _DATA_OVERRIDE = Path(path).expanduser() if path else None


def data_home() -> Path:
    """Directorio de datos (proyectos, capturas).

    Prioridad: override de ajustes > `EMVY_DATA_HOME` (env) > `XDG_DATA_HOME`/emvy.
    """
    if _DATA_OVERRIDE is not None:
        return _DATA_OVERRIDE
    env = os.environ.get("EMVY_DATA_HOME")
    if env:
        return Path(env).expanduser()
    base = _xdg("XDG_DATA_HOME", Path.home() / ".local" / "share")
    return base / APP_NAME


def config_home() -> Path:
    """Directorio de configuración. Respeta XDG_CONFIG_HOME."""
    base = _xdg("XDG_CONFIG_HOME", Path.home() / ".config")
    return base / APP_NAME


def projects_dir() -> Path:
    """Directorio raíz de proyectos: <data_home>/projects."""
    return data_home() / "projects"


def state_file() -> Path:
    """Archivo de estado ligero (p.ej. proyecto activo)."""
    return config_home() / "state.json"


def repo_root() -> Path:
    """Raíz del repositorio EMVyController (padre del paquete `emvy`).

    Empaquetado (PyInstaller/AppImage): apunta a la carpeta de datos del bundle
    (`sys._MEIPASS`), donde va incluido `firmware/`. Así el compilado/flasheo de
    firmware y demás recursos funcionan en el binario distribuido."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parent.parent


def engagements_dirs() -> list[Path]:
    """Raíces donde buscar **proyectos en ruta** (engagements): carpetas con su
    propio `project.json`, fuera del árbol XDG.

    Por defecto `<repo>/engagements` y `./engagements` (relativo al cwd, para
    cuando se trabaja dentro de un checkout). Ampliable con la variable de
    entorno `EMVY_ENGAGEMENTS` (rutas separadas por `os.pathsep`).
    """
    roots = [repo_root() / "engagements", Path.cwd() / "engagements"]
    env = os.environ.get("EMVY_ENGAGEMENTS")
    if env:
        roots += [Path(p).expanduser() for p in env.split(os.pathsep) if p]
    # dedup preservando orden
    seen: set[Path] = set()
    out: list[Path] = []
    for r in roots:
        rp = r.resolve()
        if rp not in seen:
            seen.add(rp)
            out.append(r)
    return out


def bombercat_tools_dir() -> Path:
    """Ubicación de bombercat-tools (vendorizado). Override: EMVY_BOMBERCAT_TOOLS."""
    env = os.environ.get("EMVY_BOMBERCAT_TOOLS")
    return Path(env) if env else repo_root() / "vendor" / "bombercat-tools"


def ensure_dir(path: Path) -> Path:
    """Crea `path` (y padres) si no existe y la devuelve."""
    path.mkdir(parents=True, exist_ok=True)
    return path
