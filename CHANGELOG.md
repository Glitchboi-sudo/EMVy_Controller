# Changelog

Todas las versiones notables de EMVy Controller. El formato sigue, a grandes rasgos,
[Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/); el proyecto está en **BETA**, por lo que
la API y los formatos pueden cambiar entre versiones menores.

## [Unreleased]
### Añadido
- **`emvy bombercat probe-card`**: lee una tarjeta EMV real con el flujo de un terminal de
  pago (SELECT PPSE → SELECT AID → GPO con el PDOL **dinámico** anunciado por la tarjeta →
  READ RECORD del AFL) y vuelca las respuestas crudas (PPSE/FCI/GPO/registros). Es la
  herramienta de "ground truth" para ajustar la emulación: la estructura del GPO fast
  path qVSDC del firmware se derivó de una captura con este flujo. Solo lectura y sin
  persistencia; la salida puede contener el PAN real (no compartir tal cual). Opciones:
  `--amount` (centavos), `--country`/`--currency` (hex BCD) y `--wait`. Expuesto también
  como `bombercat.probe_card(...)`. Ojo al GPO: el `Lc` es `len(83 <len> <pdol>)` — un
  off-by-one hace que tarjetas reales respondan `6985`.
- **Emulación EMV completable (firmware + host)**: la decisión de criptograma de la
  tarjeta emulada es configurable vía nuevo campo `cid` en `EMUEMV` (5º campo, o
  `EMUEMV:RAM|<cid>`): `40`=TC el terminal aprueba **offline** y el cobro **completa**
  (default), `80`=ARQC el terminal intenta online (el cobro se cuelga), `00`=AAC
  declina. Expuesto en la GUI (selector **Decisión** en el carril de emulación EMV de
  Fuzzing), en la CLI (`emv-emulate --cid 40|80|00`) y en
  `bombercat.emv_emulate(cid=...)`. El GENERATE AC emulado ahora usa el CID
  configurado y el ATC vivo, y el log muestra la decisión (`da=TC/ARQC/AAC`).
- **Volcado pcap de la sesión** (`emvy/core/pcap.py`): `PcapTap` envuelve el `Transceiver`
  lógico y graba en streaming cada intercambio (comando + respuesta con SW1/SW2) en un
  .pcap classic con linktype ISO 14443 (DLT 264) que Wireshark/tshark disecan directo.
  - **GUI**: botón toggle **PCAP** en la barra superior; graba todo el tráfico APDU de la
    sesión (capturas, consola, escritura, ataques) hacia `artifacts/sniff-<ts>.pcap` del
    proyecto activo (o del data home si no hay proyecto). Las **emulaciones** NDEF/EMV
    (fuzzing de un terminal/POS) también se vuelcan: el intercambio lo hace el firmware
    del BomberCat y se reconstruye desde sus líneas `EMU:RX`/`EMU:TX` (APDU completo en hex).
  - **CLI**: flag global `-P/--pcap PATH` para cualquier operación (captura, fuzzing,
    escritura, …), con el mismo patrón de mínima invasión que `-R/--record`; en
    `fuzz ndef emit` y `bombercat card emv-emulate` graba el tráfico reconstruido de la
    emulación.

### Cambiado
- **Firmware EMVyBomberCat — emulación EMV mimética** (aprendizaje en hardware real con
  un POS MX): los FCIs del PPSE y del SELECT AID replican a una Visa real (label
  `50`/`9F12`, `5F2D`, `9F11`, `BF0C{9F5A, IIN}`) y el GPO es fast path qVSDC puro sin
  AFL (antes anunciaba un AFL y dependía del READ RECORD). Con un POS que exige online,
  `--cid 80` (ARQC) completa el flujo kernel-side y el cobro termina declinado por el
  emisor — el techo esperable con un criptograma sin clave del emisor.

### Arreglado
- **Puerto serie en exclusiva** (`TIOCEXCL`): abrir el mismo tty desde dos procesos
  ahora falla en el open en vez de compartirlo. Antes, dos procesos leyendo el mismo
  puerto se robaban bytes entre sí y la salida de ambos quedaba corrupta (interleaving
  silencioso, difícil de diagnosticar).
- Host: una sesión de emulación cuya placa quedó con una emulación huérfana ya no muere
  al recibir el `EMU:DONE reason=restart` de la sesión anterior (lo ignora y sigue con
  la nueva); y un reset del MCU a mitad de emulación (USB re-enumerado) reabre el
  puerto y relanza la emulación automáticamente (`# RECONNECT`).

## [0.5.0-beta] — 2026-09-13

Primera publicación pública (BETA).

### Añadido
- **Núcleo puro** (`emvy/core/`): parseo/encoding BER-TLV, APDU/`Transceiver`, tags EMV, AIDs, ATR,
  flujo EMV (discover/select/GPO/AFL/records/GET DATA), pistas de banda magnética, NDEF, y análisis
  de seguridad (AIP/AUC, CVM, ODA con verificación RSA del certificado del emisor).
- **Lectores** (`emvy/readers/`): backends PC/SC, NFC (nfcpy), banda magnética (evdev/pyserial) y
  **BomberCat** (serie), todos tras la abstracción `Transceiver`, con degradación elegante.
- **Proyectos y variables**: espacios de trabajo persistentes, perfil de terminal EMV, variables
  libres, alias amistosos y perfiles de terminal preconfigurados.
- **Interfaces**: **TUI** (Textual), **GUI** de escritorio (PySide6/Qt) con paridad de funciones, y
  **CLI** para scripting.
- **Escritura y fuzzing**: UPDATE RECORD/BINARY, PUT DATA, APPEND; plantillas de banda mutada
  (magspoof), registros EMV mutados y tags NDEF malformados para probar terminales/POS.
- **BomberCat**: lector EMV contactless, passthrough APDU, magspoof, **emulación de tag NDEF** y de
  **tarjeta EMV** (perfilado de terminales), escaneo a RAM, y flasheo de firmware (arduino-cli /
  bombercat-tools). Firmware unificado en `firmware/EMVyBomberCat/`.
- **Pagos** (`emvy/payments/`): modelo `EmvCard`, codec ISO 8583 (con campo 55 EMV y traductor
  legible), análisis de criptograma (replay ATC/ARQC) y cliente de switch/adquirente.
- **Framework de PoCs** (`emvy/poc/`): runner + plugins por proyecto + plantillas ISO 8583
  (sign-on / compra / reverso), con evidencia automática, dry-run y modo solo-lectura.
- **Empaquetado**: build de **AppImage** (Linux) y `.exe` (Windows) de la GUI vía PyInstaller.
- **Pruebas**: suite offline de 238 tests con tarjeta y serial simulados (sin hardware).

### Notas
- Publicado como **BETA**: la CLI, la API interna y los formatos de datos pueden cambiar.
- Solo se distribuyen binarios de **Linux** (AppImage) en las releases; Windows es best-effort desde
  el código.

[0.5.0-beta]: https://github.com/Glitchboi-sudo/EMVy_Controller/releases/tag/v0.5.0-beta
