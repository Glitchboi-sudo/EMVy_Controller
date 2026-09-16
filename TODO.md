# TODO — EMVyController

> Nota: lo ya implementado se documenta en `CLAUDE.md` (wiki), no aquí. Este
> archivo es solo la lista de trabajo pendiente.

## Salida cruda de APDU durante la emulación NDEF (diferido)

La consola cruda (GUI dock / consola del Explorador en la TUI) ya muestra TX/RX
completo para todas las operaciones de **lector** (captura, dump, APDU manual,
escritura), vía `on_event`/`on_wire`. Falta lo mismo **durante la emulación
NDEF**: ver los APDU que el lector externo manda al tag emulado y lo que el tag
responde. Requiere reescribir el bucle de card-mode del firmware: la librería lo
resuelve en `ProcessCardMode()` (usa miembros privados `rxBuffer`/`getMessage`/
`writeData`), así que habría que rehacerlo en el sketch con los públicos
`CardModeReceive()`/`CardModeSend()` + `T4T_NDEF_EMU_Next()`, imprimiendo cada
`EMU:RX <hex>` / `EMU:TX <hex>`, y manejando activación/desactivación como hace
`ProcessCardMode`. Riesgo: podría romper la emulación (probada y funcionando) y
sólo se valida el lado de lectura con un teléfono/lector NFC a mano.

## GUI (PySide6) — siguientes iteraciones

Paridad de pestañas con la TUI hecha (`emvy gui`: Inicio, Proyectos, Variables,
Lectores, Explorador con inspector guardar/copiar/asignar, Herramientas
—Flags/ISO/Escritura—, Cobros, PoC, Intercept, BomberCat, Fuzzing con fuentes
NDEF, consola cruda). Pendiente: el **IDE/editor de PoCs** (crear/editar
`pocs/*.py` desde la GUI; hoy solo lista y ejecuta), gestión de fuentes de
firmware alternas en el panel BomberCat (hoy solo compila/sube los sketches de
`firmware/`), y un tema oscuro consistente / QSS propio.

## Relay / MITM con hardware real (diferido — limitación técnica)

Un MITM real terminal↔tarjeta necesita que un dispositivo **emule una tarjeta**
hacia el POS. Investigado y descartado por ahora:

- La librería `Electronic_Cats_PN7150` solo expone `setEmulationMode()` +
  `handleCardEmulation()` → `ProcessCardMode()` → `T4T_NDEF_EMU_Next()`, un
  estado fijo de emulación **NDEF** (Type 4 Tag), sin hook genérico para
  responder APDUs EMV arbitrarios. Reprogramar ese estado a mano (o la capa NCI
  del sketch) es cirugía de firmware de alto riesgo, no validable sin POS físico
  a mano y con fuertes restricciones de timing RF.
- La vía madura y ya probada por el fabricante es el firmware oficial
  **NFCGate** (vendorizado en `vendor/bombercat-tools/modules/nfcgate/` +
  comandos `bombercat relay config/run/stop/status/monitor` y
  `bombercat capture` para tap de APDUs en vivo a pcap/Wireshark). Funciona con
  **dos BomberCat** (uno `reader`, uno `card`, vía `nfcgate-server` TCP) o con
  **un BomberCat + un teléfono Android rooteado** corriendo la app NFCGate
  (ver `docs/android-nfcgate-rooting-guide.*.md`).
- El usuario solo tiene **un** BomberCat por ahora → no se puede ejercitar el
  flujo de dos extremos hoy. Retomar cuando haya un segundo extremo (otro
  BomberCat o el teléfono rooteado): integrar `bombercat relay`/`capture` desde
  EMVy (CLI/TUI) y, si el tap de `capture` lo permite, aplicar reglas de
  `core.intercept` sobre el flujo relevado en vivo.

## NFC multi-protocolo (overhaul completo — diferido)

`--mode nfc` ya cubre tags **NFC Forum Type 4** (NDEF sobre ISO 7816, vía
`core.rawscan.read_type4_ndef`) porque hablan APDU igual que EMV. Queda fuera,
por requerir cambios de firmware+host más grandes (y más pruebas de hardware
tras la sesión de debugging del passthrough EMV):

- **Type 2 Tag** (NTAG21x/Mifare Ultralight): no hablan APDU, sino comandos
  crudos ISO 14443-3 (`30 <página>` para READ). Requiere: (a) relajar `WAIT`
  en `EMVyBomberCat.ino` para aceptar cualquier protocolo detectado (hoy exige
  `getProtocol()==ISODEP`), reportando `READY:<protocolo>:<tech>:<uid>`; (b)
  confirmar que `nfc.readerTagCmd()` transporta tramas crudas igual que APDUs
  (no solo ISO-DEP); (c) en `core/`, leer páginas y buscar el TLV NDEF (T=0x03)
  con `core.ndef.find_ndef_tlv` (ya reutilizable).
- **Mifare Classic**: sondas de seguridad con llaves por defecto
  (`FFFFFFFFFFFF`, `A0A1A2A3A4A5`, etc.) y dump de sectores legibles — hallazgo
  de seguridad en sí mismo (llave débil/por defecto).
- Host: `emvy/readers/bombercat.py` asume que toda respuesta trae 2 bytes de
  SW al final (semántica APDU); una trama T2T cruda no los tiene — necesita un
  modo de transceive distinto, no reutilizar `Transceiver` tal cual.

## Generador de reportes

Compilar capturas + análisis de seguridad (AIP/CVM/ODA) + PoC runs +
transacciones de Cobros en un informe Markdown/HTML profesional con evidencia.
Ya hay una captura real (BomberCat genuino) para usar de ejemplo.

## Otros pendientes menores

- Exponer exportar/importar proyecto (`store.export_project`/`import_project`)
  también en la TUI (pestaña Proyectos) — hoy solo CLI.
- Mover la documentación extensa del dashboard a una pantalla Help/Wiki propia,
  para que Inicio se mantenga corto (Fase 5 del rediseño original).
- Ampliar `core.cardfuzz` con más mutaciones si surgen casos de prueba nuevos
  contra terminales reales (p.ej. variantes de TTQ, PDOL con longitudes
  inválidas, respuestas GPO fuera de rango).

## GlobalPlatform — escritura/gestión de JavaCards (implementado)

Secure Channel GP (SCP02/SCP03) + gestión de contenido (LOAD/INSTALL/DELETE,
STORE DATA) en JavaCards, **nativo** en Python (extra `[gp]` → pycryptodome).

Claves de la J3R150 cargadas en el proyecto activo (`gp keyset add`; keysets en
`<proyecto>/keysets.json`). Módulos en `emvy/core/gp/`: `keyset`, `crypto`
(SCP02/03: derivación, criptogramas, KDF, retail-MAC, ICV — validado con AES-CMAC
RFC 4493), `apdu` (comandos GP), `scp` (canal sobre Transceiver + wrap C-MAC/
C-ENC, autodetección de protocolo), `cap` (parseo de CAP → Load File Data Block),
`content` (authenticate/get_status/delete/install_cap). CLI `emvy gp keyset …` y
`emvy gp auth|status|install|delete|store-data`. GUI/TUI: pestaña **Herramientas →
Escritura** (secciones "Escritura directa (APDU)" + "GlobalPlatform"). Tests:
`tests/test_gp.py` + `tests/fakegpcard.py` (handshake SCP02/03 end-to-end).

**Pendiente**: validación end-to-end contra la **J3R150 real** (el canal lo
valida la tarjeta: auth con las claves reales → GET STATUS → instalar un CAP de
prueba). Posibles ajustes tras hardware: SCP02 "i"-param (ICV encryption), nivel
de seguridad requerido por la tarjeta, orden/again de componentes CAP exóticos.
