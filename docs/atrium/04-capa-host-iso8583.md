# 04 — Capa host ISO 8583 (adquirente ⇄ emisor)

**Prioridad: ALTA–MEDIA (incremental).** Aquí la distancia es menor — EMVy ya tiene
codec, traductor, switch y análisis de criptogramas — pero atrium aporta cuatro
piezas concretas que redondean la capa de pagos.

## En atrium

Paquete separado `tmp/atrium/host/` (sin pyscard, sin tarjeta), ~330 tests propios:

- **Codec genérico** (`host/iso8583/`): framing (MLI 2B bin / 4B ASCII / 2B BCD /
  4B bin, TPDU 5B), pack/unpack sin código de dialecto (ASCII/EBCDIC cp500, MTI
  ASCII/BCD, bitmap primario+secundario, LLVAR/LLLVAR/LLLLVAR BCD/ASCII),
  **dialectos como YAML** (`dialects/iso8583-1987.yaml`, `postilion.yaml`,
  `base24.yaml`, con `extends:`), **detección de dialecto rankeada** por score con
  verificaciones autoconsistentes, y `de55.py`: puente DE55⇄BER-TLV con **cross-check
  DE4 vs `9F02`, `5F2A`, `9F36`, `9F26`, `9F27`, `9F34`, `95`** (¿el campo 55 dice lo
  mismo que los DE planos?). Filosofía: "degrade, never crash".
- **Proxy pasivo / mutante** (`host/proxy.py` + `host/mutation.py`): byte-exact
  passthrough off-path; si no puede decodificar, degrada a relay opaco (nunca tumba
  el enlace). Mutaciones por `direction` + `on_mti` sobre DEs y tags DE55, mismos 6
  modos que la capa tarjeta; re-encode solo de mensajes tocados. Playbooks:
  `amount-mismatch`, `atc-replay`, `cryptogram-tamper`, `cvm-forgery`,
  `entry-mode-downgrade`, `response-tamper`.
- **Replay de corpus** (`host/replay.py`): modo **verbatim** (dedupe por STAN/RRN) y
  **`--freshen`** (reescribe DE7/DE11/DE12/DE13/DE37 con base aleatoria; DE55 intacto
  → pregunta de investigación: ¿el ARQC sigue ligado a la transacción?). Componible
  con playbooks y con `--imk` (re-firma).
- **Criptografía EMV** (`host/crypto/`): DES/3DES, derivación Book 2
  (IMK→UDK por PAN+PSN, UDK→SK por ATC), ARQC/ARPC, perfiles de criptograma en
  YAML, `verify` sobre capturas y `selftest` que declara qué valida y qué no.
  Maneo cuidadoso de la IMK (`--imk-file` → `$HOST_IMK` → `--imk`; nunca en logs).
- **Scoping** (`host/scoping.py`): allow-list `--allow` que **falla closed**,
  PAN-test awareness con BINs conocidos, `--abort-on-live-pan`, masking de DE2/track
  en captura.
- CLI: `python3 -m host.cli {proxy|mutate|replay|verify|detect|inspect|dialects|
  playbooks|profiles|selftest}`.

## En EMVy hoy

- `emvy/payments/iso8583.py`: codec build/parse + `emv_icc()` campo 55 +
  `translate()`/`describe_mti()` — el traductor CLI `emvy iso8583` ya es útil.
- `switch.py`: cliente TCP (0800 signon, 0200→0210 purchase, 0400 reversal) con
  evidencia en `<proyecto>/transactions/`.
- `cryptogram.py`: análisis de capturas — ATC duplicado/hueco, ARQC/UN reutilizado
  → indicios de replay.
- **No tiene**: dialectos YAML ni detección (todo va al esquema embebido), ni
  replay de capturas, ni verificación criptográfica ARQC, ni proxy pasivo, ni
  scoping de PAN.

## Propuesta para EMVy (incremental, en este orden)

1. **Dialectos YAML + detección** (`emvy/payments/dialects/*.yaml` con `extends:`,
   `emvy iso8583 --detect`): hoy traducir un dump de Postilion/BASE24 requiere
   adivinar. Detección por score = ~200 líneas sobre el codec existente. Copiar
   también el cross-check DE55 vs DEs planos (`de55.py`) — encaja con el espíritu de
   `analyze` (hallazgos combinados).
2. **Replay con freshen** (`emvy payments replay <captura> [--freshen]`):
   re-ejecutar transacciones capturadas contra el switch de laboratorio. Reutiliza
   `switch.py`; el dedupe por STAN/RRN evita falsos duplicados. Base para
   regresión de la capa de pagos.
3. **Verify ARQC en laboratorio** (`emvy payments verify --imk-file …`): derivación
   Book 2 + verificación de criptogramas capturados. Especialmente valioso junto al
   `cryptograms.jsonl` del [doc 03](03-logging-estructurado-y-replay.md): pasar de
   "indicios de replay" a "el ARQC no verifica contra esta IMK". Solo con claves de
   laboratorio; seguir el manejo de atrium (nunca loguear la IMK).
4. **Scoping/masking**: masking de PAN en `transactions/` y capturas exportadas
   (requisito típico de engagement). Barato y de alto valor profesional.
5. **Proxy pasivo host**: la pieza grande — queda ligada al relay (doc 05). No
   empezar por aquí.

**Esfuerzo estimado:** 1+2 ≈ 400–500 líneas; 3 ≈ 300 (pycryptodome ya es
dependencia `[gp]`); 4 ≈ 100. Todo en `payments/` sin tocar UI hasta el final.

**Por qué sí:** EMVy ya tiene el 60% de esta capa; son piezas que la convierten en
herramienta de pruebas de adquirente/switch seria. **Nota de confidencialidad:**
los dialectos de esquema (Visa/MC/Amex) atrium deliberadamente no los incluye — EMVy
tendría que construirlos igual que atrium: desde capturas propias.
