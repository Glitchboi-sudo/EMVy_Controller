<p align="center">
  <pre>
███████╗███╗   ███╗██╗   ██╗██╗   ██╗
██╔════╝████╗ ████║██║   ██║╚██╗ ██╔╝
█████╗  ██╔████╔██║██║   ██║ ╚████╔╝ 
██╔══╝  ██║╚██╔╝██║╚██╗ ██╔╝  ╚██╔╝  
███████╗██║ ╚═╝ ██║ ╚████╔╝    ██║   
╚══════╝╚═╝     ╚═╝  ╚═══╝     ╚═╝    
        C  O  N  T  R  O  L  L  E  R
  </pre>
</p>

<p align="center">
  <strong>Desarrollado por Glitchboi</strong><br>
  Seguridad desde México para todos
</p>

<p align="center">
  <img src="https://img.shields.io/badge/estado-BETA-orange" alt="Estado" />
  <img src="https://img.shields.io/badge/license-GNU_AGPLv3-blue" alt="License" />
  <img src="https://img.shields.io/badge/python-3.10%2B-3776AB" alt="Python" />
  <img src="https://img.shields.io/badge/plataforma-Linux-333" alt="Plataforma" />
  <img src="https://img.shields.io/badge/tests-238%20passing-brightgreen" alt="Tests" />
</p>

<p align="center">
  <a href="README.md">English</a> ·
  <strong>Español</strong> ·
  <a href="README.pt.md">Português</a>
</p>

---

> **Software en beta.** EMVy Controller funciona y está probado (238 tests y hardware real), pero la
> API, la CLI y los formatos de datos aún pueden cambiar entre versiones. Espera aristas y reporta lo
> que encuentres.

> **Uso autorizado únicamente.** Es una suite para **pruebas de seguridad autorizadas** (pentest,
> laboratorio, CTF) con tarjetas **propias o de laboratorio**. Lee y explora; los valores de "terminal"
> son de laboratorio y **no generan transacciones válidas**. **No la uses contra tarjetas ajenas ni para
> fraude.** Consulta [`SECURITY.md`](SECURITY.md).

---

## ¿Qué es EMVy Controller?

EMVy Controller es una suite **funcional** de **pruebas de seguridad para tarjetas bancarias**. Controla
varios lectores — chip **EMV** vía PC/SC, **NFC/contactless**, **banda magnética** y **BomberCat** —,
organiza el trabajo en **proyectos**, gestiona **variables de entorno** (un perfil de terminal EMV más
variables libres) y ofrece una **TUI**, una **GUI** de escritorio y una **CLI**.

Descubre y explora todo lo accesible en una tarjeta de pago, y ayuda a **perfilar terminales/POS**:

- **Descubre** aplicaciones EMV (PSE/PPSE/AIDs), lee el FCI, ejecuta el GPO (AIP/AFL), lee registros y
  contadores (`GET DATA`), y decodifica pistas de **banda magnética**.
- **Analiza** la seguridad de la tarjeta: AIP/AUC, la lista **CVM**, **ODA** (SDA/DDA/CDA, claves
  débiles, verificación RSA del certificado del emisor) y genera hallazgos.
- **Escribe** en tarjetas de laboratorio y **fuzzea** terminales con pistas mutadas (magspoof),
  registros EMV mutados y **tags NDEF** malformados.
- **BomberCat**: lector EMV contactless, passthrough APDU, magspoof, **emulación** de tag NDEF y de una
  **tarjeta EMV** (para perfilar/fuzzear terminales), y flasheo de firmware.
- **PoCs**: framework con runner y plugins por proyecto, con plantillas ISO 8583 (sign-on / compra /
  reverso) para flujos de switch/adquirente.
- Busca **flags** automáticamente en cada byte devuelto (útil en CTF).

---

## Descarga (Linux)

Los binarios se publican en **[Releases](https://github.com/Glitchboi-sudo/EMVy_Controller/releases)**.

```bash
chmod +x EMVy_Controller-*-beta-x86_64.AppImage
./EMVy_Controller-*-beta-x86_64.AppImage
```

El **AppImage** trae la GUI completa, el núcleo y los lectores PC/SC y BomberCat (serie), sin instalar
Python. Unas pocas cosas deben existir en el sistema destino (no se pueden empaquetar):

| Necesitas… | Instala en el destino |
|---|---|
| **Lectores de chip (PC/SC)** | Arch: `sudo pacman -S ccid` · Debian/Ubuntu: `sudo apt install pcscd libccid` · Fedora: `sudo dnf install pcsc-lite ccid` |
| **NFC** (`nfcpy`) / **banda** (`evdev`) | dependencias propias del backend (opcionales) |
| **Flashear firmware** BomberCat | `arduino-cli` (o arrastrar el `.uf2` incluido a la unidad `RPI-RP2`) |

> La app **arranca sola** el socket `pcscd.socket` al abrir. Si no tiene permiso:
> `sudo systemctl enable --now pcscd.socket`.

---

## Instalación desde fuente

Requiere **Python 3.10+** (probado hasta 3.14). Recomendado con [`uv`](https://docs.astral.sh/uv/):

```bash
git clone https://github.com/Glitchboi-sudo/EMVy_Controller.git
cd EMVy_Controller

uv venv .venv
uv pip install --python .venv -e '.[dev,tui]'   # + [gui] [nfc] [msr] [bombercat] según tu hardware
```

Paquetes del sistema para compilar `pyscard` (backend de chip): `ccid`/`pcsc-lite` más `swig` y un
toolchain de C. La guía completa por distro está en la
**[Wiki → Instalación](https://github.com/Glitchboi-sudo/EMVy_Controller/wiki/Instalación)**.

---

## Uso

```bash
./emvyctl.py tui       # TUI (recomendada)   — o: emvy tui
./emvyctl.py gui       # GUI de escritorio (Qt) — o: emvy gui

# CLI (scripting)
./emvyctl.py readers                 # lista lectores (todos los backends)
./emvyctl.py info                    # resumen legible + búsqueda de flags
./emvyctl.py discover                # apps EMV (PPSE/PSE/bruteforce)
./emvyctl.py dump --save cap1        # captura en el proyecto activo
./emvyctl.py analyze                 # análisis de seguridad EMV (AIP/AUC/CVM/ODA)
```

Selección de lector: `-r <índice|nombre|backend|id>`. La referencia completa está en la
**[Wiki → Guía de uso](https://github.com/Glitchboi-sudo/EMVy_Controller/wiki/Guía-de-uso)**.

---

## Hardware soportado

| Backend | Dependencia | Cubre | Notas |
|---|---|---|---|
| **pcsc** | pyscard | chip de contacto + contactless PC/SC | requiere `pcscd` + driver `ccid` |
| **nfc** | nfcpy | NFC/ISO-DEP (EMV contactless, Type 4) | PN532/PN533, ACR122, RC-S380 |
| **msr** | evdev / pyserial | banda magnética (HID / serie) | parsea el swipe con `core.track` |
| **bombercat** | pyserial | EMV contactless, passthrough, magspoof, emulación | Electronic Cats RP2040 |

**Degradación elegante**: si falta una dependencia o el hardware, ese backend simplemente no aporta
dispositivos — el resto sigue funcionando.

---

## Documentación

La documentación completa vive en la
**[Wiki del proyecto](https://github.com/Glitchboi-sudo/EMVy_Controller/wiki)**: instalación, guía de
uso, arquitectura, hardware y lectores, BomberCat, variables y perfiles de terminal, análisis de
seguridad, PoCs y flujos de switch, y fuzzing. El repositorio también incluye el
[`CHANGELOG.md`](CHANGELOG.md) y las notas de arquitectura para contribuir en [`CLAUDE.md`](CLAUDE.md).

---

## Arquitectura

Principio rector: **programación funcional** — un **núcleo puro** sin IO ni estado global, y los
**efectos en los bordes** (lectores, disco, terminal).

```
emvy/
├── core/       núcleo puro: apdu, tlv, tags, aids, atr, emv, track, ndef, cvm, oda, analyze…
├── readers/    lectores: pcsc · nfc · msr · bombercat (tras un Transceiver)
├── payments/   helpers de pago puros: EmvCard, ISO 8583, cryptogram, switch
├── session/    captura/volcado de tarjeta (CardDump)
├── project/    proyectos + variables + perfiles
├── poc/        framework de PoCs (runner + plugins del proyecto)
├── tui/        interfaz TUI (Textual)
├── gui/        interfaz GUI de escritorio (PySide6/Qt)
└── cli.py      CLI para scripting
```

La abstracción clave es `Transceiver = Callable[[APDU|bytes], Response]`: **toda** la lógica EMV recibe
una función `send`, no un objeto con estado. Más en la
**[Wiki → Arquitectura](https://github.com/Glitchboi-sudo/EMVy_Controller/wiki/Arquitectura)**.

---

## Desarrollo y contribución

```bash
.venv/bin/python -m pytest tests/ -q     # suite offline (238 tests, sin hardware)
```

`tests/fakecard.py` es una tarjeta simulada (un `Transceiver` falso) que ejercita todo el flujo EMV sin
hardware. Los PRs son bienvenidos; antes de empezar, lee [`CONTRIBUTING.md`](CONTRIBUTING.md): las
convenciones de código (núcleo puro, inmutabilidad, efectos en los bordes), cómo correr los tests y qué
**nunca** subir (datos de tarjeta, capturas, datos de cliente).

---

## Créditos

Desarrollado por **[Glitchboi](https://github.com/Glitchboi-sudo)** — *Seguridad desde México para
todos*.

- Integra el framework oficial **[bombercat-tools](https://github.com/ElectronicCats/bombercat-tools)**
  de [Electronic Cats](https://electroniccats.com/) (vendorizado en `vendor/`, con su propia licencia).
- Construido sobre `pyscard`, `nfcpy`, `Textual`, `PySide6` y el ecosistema Python.

---

## Licencia

Copyright © 2026 **glitchboi**. Distribuido bajo la **[GNU Affero General Public License v3.0 o
posterior](LICENSE)** (AGPL-3.0-or-later).

El código de terceros vendorizado en `vendor/` conserva su **propia licencia** (ver
`vendor/bombercat-tools/LICENSE`) y **no** está cubierto por la AGPL de este proyecto.
