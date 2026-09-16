"""Adaptador de `bombercat-tools` (Electronic Cats), vendorizado en
`vendor/bombercat-tools/`. EMVy lo maneja por **subprocess** contra su propio
venv aislado — así el framework conserva sus dependencias con pines propios y no
contamina el venv de EMVy.

Expone:
  * `locate()` / `ensure_venv()` — ubicación y bootstrap perezoso del venv.
  * `run_passthrough(args)` — ejecuta heredando la terminal (para `flash`,
    `device list`, `relay`, o passthrough libre): salida rica/interactiva.
  * `run_json(args)` — captura stdout y extrae el/los objeto(s) JSON (para
    `tags/readers --json`).
  * helpers: `version()`, `devices()`, `fw_list()`, `flash()`, `tags_read()`,
    `readers_read()`.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from .. import config


class BombercatToolsError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Ubicación / venv
# ---------------------------------------------------------------------------
def locate() -> Path:
    """Ruta del checkout de bombercat-tools; error claro si falta."""
    root = config.bombercat_tools_dir()
    if not (root / "bombercat.py").exists():
        raise BombercatToolsError(
            f"No encuentro bombercat-tools en {root}.\n"
            "Vendorízalo (o define EMVY_BOMBERCAT_TOOLS) y corre 'emvy bombercat setup'."
        )
    return root


def _venv_python(root: Path) -> Path:
    sub = "Scripts" if os.name == "nt" else "bin"
    exe = "python.exe" if os.name == "nt" else "python"
    return root / ".venv" / sub / exe


def venv_ready(root: Path | None = None) -> bool:
    root = root or locate()
    py = _venv_python(root)
    if not py.exists():
        return False
    # 'serial' es la primera dependencia que importa bombercat.py
    r = subprocess.run([str(py), "-c", "import serial, click, rich"],
                       capture_output=True)
    return r.returncode == 0


def ensure_venv(root: Path | None = None, *, log=None) -> Path:
    """Crea el venv del framework e instala sus deps la primera vez. Idempotente."""
    root = root or locate()
    py = _venv_python(root)
    if venv_ready(root):
        return py

    def say(m):
        (log or (lambda _: None))(m)

    req = root / "requirements.txt"
    if shutil.which("uv"):
        say("Creando venv de bombercat-tools con uv…")
        subprocess.run(["uv", "venv", str(root / ".venv")], check=True)
        subprocess.run(["uv", "pip", "install", "--python", str(py), "-r", str(req)],
                       check=True)
    else:
        say("Creando venv de bombercat-tools con venv+pip…")
        subprocess.run([sys.executable, "-m", "venv", str(root / ".venv")], check=True)
        subprocess.run([str(py), "-m", "pip", "install", "-q", "-U", "pip"], check=True)
        subprocess.run([str(py), "-m", "pip", "install", "-q", "-r", str(req)], check=True)

    if not venv_ready(root):
        raise BombercatToolsError(
            "El venv de bombercat-tools quedó incompleto tras instalar deps.")
    return py


# ---------------------------------------------------------------------------
# Ejecución
# ---------------------------------------------------------------------------
def _base_cmd(root: Path) -> list[str]:
    return [str(ensure_venv(root)), "bombercat.py"]


def _env() -> dict:
    e = dict(os.environ)
    e.setdefault("NO_COLOR", "1")
    e.setdefault("TERM", "dumb")
    # bombercat-tools >= v1.3.0 enruta `tags`/`readers` por un orquestador de
    # auto-flash cuya política es ASK en TTY / NEVER en pipe. Como EMVy invoca por
    # subprocess capturando stdout, un ASK dejaría un prompt de confirmación
    # invisible bloqueado en stdin. Fijamos NEVER para que falle limpio (mismatch
    # de firmware) en vez de colgarse; el usuario flashea explícito desde el panel.
    # Las versiones antiguas (la vendorizada, v1.1.0.0) ignoran la variable.
    e.setdefault("BOMBERCAT_AUTO_FLASH", "never")
    return e


def run_passthrough(args: list[str], *, log=None) -> int:
    """Ejecuta el framework heredando stdin/stdout/stderr (interactivo/rico)."""
    root = locate()
    ensure_venv(root, log=log)
    cmd = _base_cmd(root) + list(args)
    return subprocess.run(cmd, cwd=str(root), env=_env()).returncode


def run_capture(args: list[str], *, timeout: float | None = 120) -> subprocess.CompletedProcess:
    root = locate()
    ensure_venv(root)
    cmd = _base_cmd(root) + list(args)
    return subprocess.run(cmd, cwd=str(root), env=_env(),
                          capture_output=True, text=True, timeout=timeout)


def run_json(args: list[str], *, timeout: float | None = 120):
    """Ejecuta y extrae JSON de stdout (para comandos con `--json`)."""
    cp = run_capture(args, timeout=timeout)
    objs = _extract_json(cp.stdout)
    if not objs:
        raise BombercatToolsError(
            f"El comando no devolvió JSON (rc={cp.returncode}).\n"
            f"stderr: {cp.stderr.strip()[:400]}")
    return objs if len(objs) > 1 else objs[0]


def _extract_json(text: str):
    """Recupera objetos JSON de una salida que puede traer banner/tablas rich."""
    out = []
    # intento 1: el texto entero
    try:
        return [json.loads(text)]
    except Exception:
        pass
    # intento 2: por líneas que parezcan JSON (una por línea, caso --json)
    for line in text.splitlines():
        s = line.strip()
        if s and s[0] in "{[":
            try:
                out.append(json.loads(s))
            except Exception:
                continue
    return out


# ---------------------------------------------------------------------------
# Helpers de alto nivel
# ---------------------------------------------------------------------------
def version() -> str:
    try:
        return (locate() / "VERSION").read_text().strip()
    except Exception:
        return "?"


def devices() -> int:
    return run_passthrough(["device", "list"])


def status(port: str | None = None) -> int:
    return run_passthrough(["status"] + (["-p", port] if port else []))


def fw_list() -> int:
    return run_passthrough(["flash", "--list"])


def flash(name: str, *, port: str | None = None, device_id: int | None = None,
          yes: bool = False, log=None) -> int:
    args = ["flash", name]
    if port:
        args += ["-p", port]
    if device_id is not None:
        args += ["-d", str(device_id)]
    if yes:
        args += ["-y"]
    return run_passthrough(args, log=log)


# --- variantes que CAPTURAN la salida (para la TUI; no heredan stdout) -----
def parse_fw_names(text: str) -> list[str]:
    """Extrae los nombres de firmware de la tabla rich de `flash --list`."""
    names: list[str] = []
    for line in text.splitlines():
        s = line.strip()
        if not s.startswith("│"):                 # solo filas de tabla ligera
            continue
        cells = [c.strip() for c in s.strip("│").split("│")]
        if len(cells) < 2:
            continue
        name = cells[0]
        if name and name != "Firmware" and all(ch.isalnum() or ch in "._-" for ch in name):
            names.append(name)
    return names


def fw_list_names(timeout: float = 90) -> list[str]:
    """Nombres de firmware disponibles (captura y parsea `flash --list`)."""
    cp = run_capture(["flash", "--list"], timeout=timeout)
    return parse_fw_names(cp.stdout)


def flash_capture(name: str, *, port: str | None = None, device_id: int | None = None,
                  timeout: float = 300):
    """Flashea `name` capturando la salida (para mostrarla en la TUI). Siempre
    con `-y` (no interactivo). Devuelve el CompletedProcess."""
    args = ["flash", name, "-y"]
    if port:
        args += ["-p", port]
    if device_id is not None:
        args += ["-d", str(device_id)]
    return run_capture(args, timeout=timeout)


def devices_text(timeout: float = 30) -> str:
    return run_capture(["device", "list"], timeout=timeout).stdout


def status_text(port: str | None = None, timeout: float = 30) -> str:
    return run_capture(["status"] + (["-p", port] if port else []), timeout=timeout).stdout


def tags_read(timeout: int = 20):
    return run_json(["tags", "read", "--json", "-t", str(timeout)])


def readers_read(timeout: int = 20):
    return run_json(["readers", "read", "--json", "-t", str(timeout)])
