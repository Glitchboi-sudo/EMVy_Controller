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
  <strong>Desenvolvido por Glitchboi</strong><br>
  Segurança do México para todos
</p>

<p align="center">
  <img src="https://img.shields.io/badge/status-BETA-orange" alt="Status" />
  <img src="https://img.shields.io/badge/license-GNU_AGPLv3-blue" alt="License" />
  <img src="https://img.shields.io/badge/python-3.10%2B-3776AB" alt="Python" />
  <img src="https://img.shields.io/badge/plataforma-Linux-333" alt="Plataforma" />
  <img src="https://img.shields.io/badge/tests-238%20passing-brightgreen" alt="Tests" />
</p>

<p align="center">
  <a href="README.md">English</a> ·
  <a href="README.es.md">Español</a> ·
  <strong>Português</strong>
</p>

---

> **Software em beta.** O EMVy Controller funciona e é testado (238 testes e hardware real), mas a API,
> a CLI e os formatos de dados ainda podem mudar entre versões. Espere arestas e relate o que encontrar.

> **Uso autorizado apenas.** É uma suíte para **testes de segurança autorizados** (pentest, laboratório,
> CTF) com cartões **próprios ou de laboratório**. Ela lê e explora; os valores de "terminal" são de
> laboratório e **não geram transações válidas**. **Não a use contra cartões de terceiros nem para
> fraude.** Consulte [`SECURITY.md`](SECURITY.md).

---

## O que é o EMVy Controller?

O EMVy Controller é uma suíte **funcional** para **testes de segurança de cartões bancários**. Ela
controla vários leitores — chip **EMV** via PC/SC, **NFC/contactless**, **tarja magnética** e
**BomberCat** —, organiza o trabalho em **projetos**, gerencia **variáveis de ambiente** (um perfil de
terminal EMV mais variáveis livres) e oferece uma **TUI**, uma **GUI** de desktop e uma **CLI**.

Ela descobre e explora tudo o que é acessível em um cartão de pagamento e ajuda a **perfilar
terminais/POS**:

- **Descobre** aplicações EMV (PSE/PPSE/AIDs), lê o FCI, executa o GPO (AIP/AFL), lê registros e
  contadores (`GET DATA`) e decodifica trilhas de **tarja magnética**.
- **Analisa** a segurança do cartão: AIP/AUC, a lista **CVM**, **ODA** (SDA/DDA/CDA, chaves fracas,
  verificação RSA do certificado do emissor) e gera achados.
- **Escreve** em cartões de laboratório e **fuzza** terminais com trilhas mutadas (magspoof), registros
  EMV mutados e **tags NDEF** malformados.
- **BomberCat**: leitor EMV contactless, passthrough APDU, magspoof, **emulação** de tag NDEF e de um
  **cartão EMV** (para perfilar/fuzzar terminais) e gravação de firmware.
- **PoCs**: framework com runner e plugins por projeto, com modelos ISO 8583 (sign-on / compra /
  estorno) para fluxos de switch/adquirente.
- Busca **flags** automaticamente em cada byte retornado (útil em CTF).

---

## Download (Linux)

Os binários são publicados em **[Releases](https://github.com/Glitchboi-sudo/EMVy_Controller/releases)**.

```bash
chmod +x EMVy_Controller-*-beta-x86_64.AppImage
./EMVy_Controller-*-beta-x86_64.AppImage
```

O **AppImage** traz a GUI completa, o núcleo e os leitores PC/SC e BomberCat (serial), sem instalar
Python. Algumas coisas precisam existir no sistema de destino (não podem ser empacotadas):

| Você precisa de… | Instale no destino |
|---|---|
| **Leitores de chip (PC/SC)** | Arch: `sudo pacman -S ccid` · Debian/Ubuntu: `sudo apt install pcscd libccid` · Fedora: `sudo dnf install pcsc-lite ccid` |
| **NFC** (`nfcpy`) / **tarja** (`evdev`) | dependências próprias do backend (opcionais) |
| **Gravar firmware** do BomberCat | `arduino-cli` (ou arraste o `.uf2` incluído para a unidade `RPI-RP2`) |

> O app **inicia sozinho** o socket `pcscd.socket` ao abrir. Se não tiver permissão:
> `sudo systemctl enable --now pcscd.socket`.

---

## Instalação a partir do código-fonte

Requer **Python 3.10+** (testado até 3.14). Recomendado com [`uv`](https://docs.astral.sh/uv/):

```bash
git clone https://github.com/Glitchboi-sudo/EMVy_Controller.git
cd EMVy_Controller

uv venv .venv
uv pip install --python .venv -e '.[dev,tui]'   # + [gui] [nfc] [msr] [bombercat] conforme seu hardware
```

Pacotes de sistema para compilar o `pyscard` (backend de chip): `ccid`/`pcsc-lite` mais `swig` e um
toolchain C. O guia completo por distribuição está na
**[Wiki → Instalação](https://github.com/Glitchboi-sudo/EMVy_Controller/wiki/Instalación)**.

---

## Uso

```bash
./emvyctl.py tui       # TUI (recomendada)   — ou: emvy tui
./emvyctl.py gui       # GUI de desktop (Qt) — ou: emvy gui

# CLI (scripting)
./emvyctl.py readers                 # lista leitores (todos os backends)
./emvyctl.py info                    # resumo legível + busca de flags
./emvyctl.py discover                # apps EMV (PPSE/PSE/bruteforce)
./emvyctl.py dump --save cap1        # captura no projeto ativo
./emvyctl.py analyze                 # análise de segurança EMV (AIP/AUC/CVM/ODA)
```

Seleção de leitor: `-r <índice|nome|backend|id>`. A referência completa está na
**[Wiki → Guia de uso](https://github.com/Glitchboi-sudo/EMVy_Controller/wiki/Guía-de-uso)**.

---

## Hardware suportado

| Backend | Dependência | Cobre | Notas |
|---|---|---|---|
| **pcsc** | pyscard | chip de contato + contactless PC/SC | requer `pcscd` + driver `ccid` |
| **nfc** | nfcpy | NFC/ISO-DEP (EMV contactless, Type 4) | PN532/PN533, ACR122, RC-S380 |
| **msr** | evdev / pyserial | tarja magnética (HID / serial) | analisa o swipe com `core.track` |
| **bombercat** | pyserial | EMV contactless, passthrough, magspoof, emulação | Electronic Cats RP2040 |

**Degradação elegante**: se faltar uma dependência ou o hardware, aquele backend simplesmente não
fornece dispositivos — o restante continua funcionando.

---

## Documentação

A documentação completa vive na
**[Wiki do projeto](https://github.com/Glitchboi-sudo/EMVy_Controller/wiki)**: instalação, guia de uso,
arquitetura, hardware e leitores, BomberCat, variáveis e perfis de terminal, análise de segurança, PoCs
e fluxos de switch, e fuzzing. O repositório também inclui o
[`CHANGELOG.md`](CHANGELOG.md) e as notas de arquitetura para contribuir em [`CLAUDE.md`](CLAUDE.md).

---

## Arquitetura

Princípio norteador: **programação funcional** — um **núcleo puro** sem IO nem estado global, e os
**efeitos nas bordas** (leitores, disco, terminal).

```
emvy/
├── core/       núcleo puro: apdu, tlv, tags, aids, atr, emv, track, ndef, cvm, oda, analyze…
├── readers/    leitores: pcsc · nfc · msr · bombercat (atrás de um Transceiver)
├── payments/   helpers de pagamento puros: EmvCard, ISO 8583, cryptogram, switch
├── session/    captura/dump de cartão (CardDump)
├── project/    projetos + variáveis + perfis
├── poc/        framework de PoCs (runner + plugins do projeto)
├── tui/        interface TUI (Textual)
├── gui/        interface GUI de desktop (PySide6/Qt)
└── cli.py      CLI para scripting
```

A abstração-chave é `Transceiver = Callable[[APDU|bytes], Response]`: **toda** a lógica EMV recebe uma
função `send`, não um objeto com estado. Mais na
**[Wiki → Arquitetura](https://github.com/Glitchboi-sudo/EMVy_Controller/wiki/Arquitectura)**.

---

## Desenvolvimento e contribuição

```bash
.venv/bin/python -m pytest tests/ -q     # suíte offline (238 testes, sem hardware)
```

`tests/fakecard.py` é um cartão simulado (um `Transceiver` falso) que exercita todo o fluxo EMV sem
hardware. PRs são bem-vindos; antes de começar, leia [`CONTRIBUTING.md`](CONTRIBUTING.md): as convenções
de código (núcleo puro, imutabilidade, efeitos nas bordas), como rodar os testes e o que **nunca**
enviar (dados de cartão, capturas, dados de cliente).

---

## Créditos

Desenvolvido por **[Glitchboi](https://github.com/Glitchboi-sudo)** — *Segurança do México para todos*.

- Integra o framework oficial **[bombercat-tools](https://github.com/ElectronicCats/bombercat-tools)**
  da [Electronic Cats](https://electroniccats.com/) (vendorizado em `vendor/`, com sua própria licença).
- Construído sobre `pyscard`, `nfcpy`, `Textual`, `PySide6` e o ecossistema Python.

---

## Licença

Copyright © 2026 **glitchboi**. Distribuído sob a **[GNU Affero General Public License v3.0 ou
posterior](LICENSE)** (AGPL-3.0-or-later).

O código de terceiros vendorizado em `vendor/` mantém sua **própria licença** (ver
`vendor/bombercat-tools/LICENSE`) e **não** está coberto pela AGPL deste projeto.
