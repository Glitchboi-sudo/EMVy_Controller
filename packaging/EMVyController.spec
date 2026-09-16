# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec para EMVy Controller (GUI). Sirve para AppImage (Linux) y
.exe (Windows) — la misma spec en cada plataforma.

Incluye `firmware/` como datos (para compilar/flashear desde la app). NO incluye
`engagements/` (datos de cliente) ni proyectos/capturas (viven en XDG del sistema).
"""
import os
import sys

from PyInstaller.utils.hooks import collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))   # raíz del repo
ENTRY = os.path.join(SPECPATH, "emvy_gui.py")

# Firmware + assets de marca en el bundle (config.repo_root() → _MEIPASS al congelar).
datas = [
    (os.path.join(ROOT, "firmware"), "firmware"),
    (os.path.join(ROOT, "emvy", "gui", "assets"), "emvy/gui/assets"),
]

# pyscard (smartcard) y pyserial cargan submódulos por nombre → declararlos.
hiddenimports = collect_submodules("smartcard") + [
    "serial", "serial.tools.list_ports",
]

a = Analysis(
    [ENTRY],
    pathex=[ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    excludes=["tkinter", "pytest", "textual"],  # TUI/tests no van en la GUI
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="EMVyController",
    console=False,          # app de ventana (sin consola)
    icon=os.path.join(SPECPATH, "emvy.ico") if os.path.exists(
        os.path.join(SPECPATH, "emvy.ico")) else None,
)
coll = COLLECT(
    exe, a.binaries, a.datas,
    strip=False, upx=False,
    name="EMVyController",
)
