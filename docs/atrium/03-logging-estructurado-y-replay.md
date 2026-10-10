# 03 — Logging estructurado de sesiones y replay

**Prioridad: ALTA.** Barato de construir sobre la traza que EMVy ya captura, y
habilita tres flujos que hoy no existen: evidencia estructurada por sesión,
regresión (re-ejecutar una sesión contra una tarjeta), y análisis offline.

## En atrium

**`tmp/atrium/emv_logger.py` (61KB)** — capa "cero latencia" dentro del path de
intercept. Clasificación por INS (SELECT/GPO/READ RECORD/GENERATE AC…), parseo
BER-TLV inline con diccionario de tags, y **detección automática de sesión**: nueva
sesión en SELECT AID, cierre en GENERATE AC o timeout configurable.

Handlers de salida combinables (config en `emv_logger.yaml`):
- Consola a color (`ConsoleHandler`).
- **JSON por sesión** (`logs/sessions/session_<uuid>.json`).
- **hexlog estilo PC/SC** (`logs/apdu.hexlog`, reproductible).
- **SQLite WAL** con escritura async (`logs/emv.db`: tablas `sessions`, `apdus`,
  `tlv_nodes`).
- `WebSocketHandler` alimentando el Live Trace del dashboard.

Filtros por dirección y por par CLA+INS; **hooks Python externos**
(`hooks: pre_send/pre_response: "fichero.py::función"`) con acciones
passthrough/modify/drop/inject. `CryptogramDB`: captura de criptogramas (`9F26`…)
a `logs/cryptograms.jsonl`.

**`tmp/atrium/emv_logger_cli.py`** — modos: `live` (observador pasivo del socket
vpcd), `file` (re-parsear un hexlog offline), `replay` (reenviar comandos de una
sesión JSON a tarjeta física vía pyscard, `--send`), `stdin` (parejas C/R hex).

**`tmp/atrium/apdu_printer.py` + `descriptions/`** — formateador a color de APDUs
(CLA/P1/P2/Lc/Le, SW categorizadas) con descripciones ISO 7816 del proyecto
apdu-parser (`commands.txt` 146 líneas, `responses.txt` 242 líneas).

## En EMVy hoy

- `TraceEvent`/`on_event` (APDU con SW) y `on_wire` (líneas serie crudas del
  BomberCat) ya recorren toda la pila; la consola cruda es exportable a archivo y
  guardable en `<proyecto>/logs/` (`store.save_log`).
- Pero es salida **plana**: no hay identidad de sesión, no hay JSON estructurado por
  sesión, no hay re-parseo offline, no hay replay contra tarjeta, y los criptogramas
  no se extraen a colección.
- Las capturas (`<proyecto>/captures/*.json`) son snapshots de estado, no trazas de
  conversación.

## Propuesta para EMVy

Nuevo `emvy/core/sessionlog.py` (puro: formateo/parseo) + `emvy/session/recorder.py`
(efectos: escritura):

1. **Sesión estructurada**: el `Transceiver` ya es el punto de corte perfecto —
   grabar ahí produce sesión automáticamente para **todos** los backends
   (PC/SC, nfcpy, BomberCat). Detección de sesión copiada de atrium (SELECT AID →
   GENERATE AC / timeout). Salidas:
   - `<proyecto>/sessions/<uuid>.json` (pares comando/respuesta con TLV parseado),
   - `sessions.hexlog` (formato PC/SC, diffs amigables en git),
   - `cryptograms.jsonl` (todo tag de criptograma + contexto: ATC, importe si se
     conoce del PDOL).
2. **CLI `emvy log …`**:
   - `emvy log list` — sesiones del proyecto.
   - `emvy log show <id>` — visor con APDU printer (3).
   - `emvy log replay <id> [-r lector]` — re-enviar los comandos a una tarjeta
     física (regresión tras cambios de configuración; verificación de PoCs).
   - `emvy log convert <hexlog|session.json>` — entre formatos; importar un hexlog
     como captura navegable en el Explorador.
3. **APDU printer + descripciones ISO 7816** (`emvy/core/apduprint.py` +
   diccionarios traducidos de `descriptions/`): en la consola cruda y en el
   Explorador. Es la feature más barata de todos estos docs y mejora todo lo demás.
4. SQLite: **opcional/diferido**. El JSONL + JSON por sesión cubre el 90% del valor
   con cero esfuerzo de esquema; la base relacional solo se justifica si el
   reporteador lo pide.

**Esfuerzo estimado:** recorder + formatos ≈ 300 líneas; CLI ≈ 150; APDU printer ≈
200 con los diccionarios ya escritos. Tests: round-trip parse→format→parse, igual
que hace `cardfuzz` con sus plantillas.

**Por qué sí:** profesionaliza la evidencia (engagements), habilita replay/regresión
sin nuevo hardware, y el cryptograms.jsonl alimenta el análisis de replay que
`payments/cryptogram.py` ya empieza. Se combina natural con el doc 02: cada sesión
queda ligada al hash de tarjeta.
