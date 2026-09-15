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
  <strong>Built by Glitchboi</strong><br>
  Security from Mexico, for everyone
</p>

<p align="center">
  <img src="https://img.shields.io/badge/status-BETA-orange" alt="Status" />
  <img src="https://img.shields.io/badge/license-GNU_AGPLv3-blue" alt="License" />
  <img src="https://img.shields.io/badge/python-3.10%2B-3776AB" alt="Python" />
  <img src="https://img.shields.io/badge/platform-Linux-333" alt="Platform" />
  <img src="https://img.shields.io/badge/tests-238%20passing-brightgreen" alt="Tests" />
</p>

<p align="center">
  <strong>English</strong> ·
  <a href="README.es.md">Español</a> ·
  <a href="README.pt.md">Português</a>
</p>

---

> **Beta software.** EMVy Controller works and is tested (238 tests plus real hardware), but the API,
> the CLI and the data formats may still change between releases. Expect rough edges and please report
> anything you find.

> **Authorized use only.** This is a toolkit for **authorized security testing** (pentesting, lab work,
> CTF) with **your own or lab-issued cards**. It reads and explores; the "terminal" values are lab
> settings and **do not produce valid transactions**. **Do not use it against cards you do not own or
> for fraud.** See [`SECURITY.md`](SECURITY.md).

---

## What is EMVy Controller?

EMVy Controller is a **functional** toolkit for **payment-card security testing**. It drives several
readers — chip **EMV** over PC/SC, **NFC/contactless**, **magnetic stripe** and **BomberCat** — organizes
work into **projects**, manages **environment variables** (an EMV terminal profile plus free-form
variables), and ships a **TUI**, a desktop **GUI** and a **CLI**.

It discovers and explores everything reachable on a payment card, and helps **profile terminals/POS**:

- **Discover** EMV applications (PSE/PPSE/AIDs), read the FCI, run the GPO (AIP/AFL), read records and
  counters (`GET DATA`), and decode **magnetic-stripe** tracks.
- **Analyze** card security: AIP/AUC, the **CVM** list, **ODA** (SDA/DDA/CDA, weak keys, RSA
  verification of the issuer certificate) and surface findings.
- **Write** to lab cards and **fuzz** terminals with mutated tracks (magspoof), mutated EMV records and
  malformed **NDEF** tags.
- **BomberCat**: contactless EMV reader, APDU passthrough, magspoof, **emulation** of an NDEF tag and of
  an **EMV card** (to profile/fuzz terminals), and firmware flashing.
- **PoCs**: a runner-plus-plugins framework per project, with ISO 8583 templates (sign-on / purchase /
  reversal) for switch/acquirer flows.
- Automatically searches every returned byte for **flags** (handy in CTFs).

---

## Download (Linux)

Binaries are published on **[Releases](https://github.com/Glitchboi-sudo/EMVy_Controller/releases)**.

```bash
chmod +x EMVy_Controller-*-beta-x86_64.AppImage
./EMVy_Controller-*-beta-x86_64.AppImage
```

The **AppImage** bundles the full GUI, the core and the PC/SC and BomberCat (serial) readers, with no
Python install required. A few things must exist on the target system (they cannot be bundled):

| You need… | Install on the target |
|---|---|
| **Chip readers (PC/SC)** | Arch: `sudo pacman -S ccid` · Debian/Ubuntu: `sudo apt install pcscd libccid` · Fedora: `sudo dnf install pcsc-lite ccid` |
| **NFC** (`nfcpy`) / **stripe** (`evdev`) | backend-specific dependencies (optional) |
| **BomberCat firmware flashing** | `arduino-cli` (or drop the bundled `.uf2` onto the `RPI-RP2` drive) |

> The app starts the `pcscd.socket` on its own when it opens. If it lacks permission, run
> `sudo systemctl enable --now pcscd.socket`.

---

## Install from source

Requires **Python 3.10+** (tested up to 3.14). Recommended with [`uv`](https://docs.astral.sh/uv/):

```bash
git clone https://github.com/Glitchboi-sudo/EMVy_Controller.git
cd EMVy_Controller

uv venv .venv
uv pip install --python .venv -e '.[dev,tui]'   # + [gui] [nfc] [msr] [bombercat] as your hardware needs
```

System packages needed to build `pyscard` (the chip backend): `ccid`/`pcsc-lite` plus `swig` and a C
toolchain. Full, per-distro guidance lives in the
**[Wiki → Instalación](https://github.com/Glitchboi-sudo/EMVy_Controller/wiki/Instalación)**.

---

## Usage

```bash
./emvyctl.py tui       # TUI (recommended)   — or: emvy tui
./emvyctl.py gui       # desktop GUI (Qt)    — or: emvy gui

# CLI (scripting)
./emvyctl.py readers                 # list readers (all backends)
./emvyctl.py info                    # readable summary + flag search
./emvyctl.py discover                # EMV apps (PPSE/PSE/bruteforce)
./emvyctl.py dump --save cap1        # capture into the active project
./emvyctl.py analyze                 # EMV security analysis (AIP/AUC/CVM/ODA)
```

Reader selection: `-r <index|name|backend|id>`. The complete reference is in the
**[Wiki → Guía de uso](https://github.com/Glitchboi-sudo/EMVy_Controller/wiki/Guía-de-uso)**.

---

## Supported hardware

| Backend | Dependency | Covers | Notes |
|---|---|---|---|
| **pcsc** | pyscard | contact chip + PC/SC contactless | requires `pcscd` + `ccid` driver |
| **nfc** | nfcpy | NFC/ISO-DEP (contactless EMV, Type 4) | PN532/PN533, ACR122, RC-S380 |
| **msr** | evdev / pyserial | magnetic stripe (HID / serial) | parses the swipe with `core.track` |
| **bombercat** | pyserial | contactless EMV, passthrough, magspoof, emulation | Electronic Cats RP2040 |

**Graceful degradation**: if a dependency or the hardware is missing, that backend simply contributes no
devices — everything else keeps working.

---

## Documentation

The full documentation lives in the
**[project Wiki](https://github.com/Glitchboi-sudo/EMVy_Controller/wiki)**: installation, usage guide,
architecture, hardware and readers, BomberCat, terminal variables and profiles, security analysis, PoCs
and switch flows, and fuzzing. The repository also carries the
[`CHANGELOG.md`](CHANGELOG.md) and the contributor architecture notes in [`CLAUDE.md`](CLAUDE.md).

---

## Architecture

The guiding principle is **functional programming**: a **pure core** with no IO or global state, and
**effects at the edges** (readers, disk, terminal).

```
emvy/
├── core/       pure core: apdu, tlv, tags, aids, atr, emv, track, ndef, cvm, oda, analyze…
├── readers/    readers: pcsc · nfc · msr · bombercat (behind a Transceiver)
├── payments/   pure payment helpers: EmvCard, ISO 8583, cryptogram, switch
├── session/    card capture/dump (CardDump)
├── project/    projects + variables + profiles
├── poc/        PoC framework (runner + project plugins)
├── tui/        TUI (Textual)
├── gui/        desktop GUI (PySide6/Qt)
└── cli.py      CLI for scripting
```

The key abstraction is `Transceiver = Callable[[APDU|bytes], Response]`: **all** EMV logic receives a
`send` function rather than a stateful object. More in the
**[Wiki → Arquitectura](https://github.com/Glitchboi-sudo/EMVy_Controller/wiki/Arquitectura)**.

---

## Development & contributing

```bash
.venv/bin/python -m pytest tests/ -q     # offline suite (238 tests, no hardware)
```

`tests/fakecard.py` is a simulated card (a fake `Transceiver`) that exercises the whole EMV flow without
hardware. Pull requests are welcome; before starting, read [`CONTRIBUTING.md`](CONTRIBUTING.md) for the
code conventions (pure core, immutability, effects at the edges), how to run the tests and what must
**never** be committed (card data, captures, client data).

---

## Credits

Built by **[Glitchboi](https://github.com/Glitchboi-sudo)** — *Security from Mexico, for everyone*.

- Integrates the official **[bombercat-tools](https://github.com/ElectronicCats/bombercat-tools)**
  framework by [Electronic Cats](https://electroniccats.com/) (vendored under `vendor/`, with its own
  license).
- Built on `pyscard`, `nfcpy`, `Textual`, `PySide6` and the wider Python ecosystem.

---

## License

Copyright © 2026 **glitchboi**. Distributed under the **[GNU Affero General Public License v3.0 or
later](LICENSE)** (AGPL-3.0-or-later).

Third-party code vendored under `vendor/` keeps its **own license** (see
`vendor/bombercat-tools/LICENSE`) and is **not** covered by this project's AGPL.
