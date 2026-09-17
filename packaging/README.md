# Empaquetado — EMVy Controller (BETA)

Genera binarios **de la GUI** de EMVy Controller. La misma `EMVyController.spec`
(PyInstaller) sirve en Linux y Windows.

## Qué se incluye / qué NO

- **Sí:** La aplicación (GUI PySide6) + núcleo + lectores (PC/SC, BomberCat serie).
- **Sí:** **`firmware/`** (código de los sketches + el `.uf2` flasheable) — para
  compilar/flashear desde la pestaña BomberCat.
- **No:** **Proyectos y capturas**: viven en el directorio XDG del sistema
  (`~/.local/share/emvy`), nunca dentro del binario.
- **No:** **`engagements/`** (datos de cliente): excluidos por `.dockerignore`.
- **No:** `vendor/bombercat-tools`: opcional, usa su propio venv; no se empaqueta.

## Linux — AppImage (recomendado)

Requiere Docker. Construye en Ubuntu 22.04 (glibc antigua = portable):

```sh
packaging/build-appimage.sh
# → dist/EMVy_Controller-0.6.0-beta-x86_64.AppImage
chmod +x dist/*.AppImage
./dist/EMVy_Controller-0.6.0-beta-x86_64.AppImage
```

### Requisitos en el equipo destino (no se pueden empaquetar)

- **PC/SC (lectores de chip)**: el **daemon `pcscd` y el driver CCID son del
  sistema** — un AppImage/.exe **no** los puede incluir. Instálalos en el destino:
  - Arch: `sudo pacman -S ccid`  · Debian/Ubuntu: `sudo apt install pcscd libccid`
    · Fedora: `sudo dnf install pcsc-lite ccid`
  - **El socket `pcscd.socket` lo arranca la app sola** al abrir la GUI (mismo
    mecanismo que la CLI: `pcscd.ensure_started()`, vía `systemctl start` sin sudo
    en la mayoría de setups con polkit) y lo para al salir si fue ella quien lo
    activó. Si no tiene permiso, arráncalo a mano una vez:
    `sudo systemctl enable --now pcscd.socket`.
  - NFC (`nfcpy`) y banda (`evdev`) tienen sus propias deps del sistema; PC/SC y
    BomberCat (serie) funcionan sin ellas.
- **Flashear firmware**: `arduino-cli` (compilar/subir desde la pestaña BomberCat)
  debe estar en el destino (ver §12 del CLAUDE.md). El `.uf2` **incluido** en el
  binario se puede flashear a mano arrastrándolo a la unidad `RPI-RP2` (BOOTSEL),
  sin toolchain.

## Windows — .exe

**Opción A (fiable): en Windows** (o un runner `windows-latest` de CI):

```powershell
pip install pyinstaller ".[gui]" pyserial
pyinstaller --noconfirm --clean packaging/EMVyController.spec
# → dist/EMVyController/EMVyController.exe  (distribuir la carpeta, o comprimir en .zip)
```

**Opción B (best-effort, desde Linux con Docker + Wine):**

```sh
docker build -f packaging/Dockerfile.windows -t emvy-win .
docker run --rm -v "$PWD/dist:/out" emvy-win
# → dist/EMVyController/EMVyController.exe
```

PySide6 bajo Wine puede fallar; si es tu caso, usa la Opción A.

## Versión

`emvy/__init__.py` define `__version__` (0.6.0) y `__release__` ("BETA"), que se
muestran en el título de la ventana y en Inicio (GUI/TUI).
