# 05 — Relay MITM, transportes y hardware

**Prioridad: MEDIA–ALTA** (vpcd) y **MEDIA** (proxy remoto, recorded). Este es el
terreno central de atrium y el hueco más grande de EMVy — pero también el que más
depende de hardware. La buena noticia: hay una vía que **no necesita hardware
nuevo**.

## En atrium

**Relay de contacto (el corazón del proyecto):**
- `virtual_card.py` — `VirtualCard` habla el protocolo de socket de **vpcd**
  (módulo kernel `vpcd`, puerto 35963) y se presenta al SO como **tarjeta virtual**.
- `relay_os.py` — `RelayOS` (subclase `SmartcardOS` de vsmartcard) reenvía cada
  APDU al lector PC/SC físico.
- `intercept_attack.py` — hub de despacho: logger → mutation engine → tarjeta →
  mutaciones de respuesta → logger. Ataques legacy por CLI: cambio de CVM,
  modificación por hex, brute-force de PIN (código viejo, ignorar).
- **SimTrace2** (`api/routes/simtrace.py`): descubre la placa Osmocom por sysfs,
  genera el comando para `simtrace2-remsim`, imprime regla udev. Lado **terminal**
  del relay contacto (la tarjeta real va en la placa entre el terminal y el PC).
- **Contactless** (`nfc/`): stack propio PN532/ACR122U (framing propio, pseudo-APDUs
  vendor, escape CCID), emulación de tarjeta con ISO-DEP propio (RATS/ATS, I/R/S
  blocks, chaining, **S(WTX)**), `--split-responses` (61xx + GET RESPONSE), relay
  completo con dos ACR122U, y herramientas: `measure-ats`, `transmit-limit`,
  `relay_loopback.py`, `bench_card_path.py`, prefetch. Nada probado "en el aire"
  (lo dicen explícitamente; sí contra chip fake).

**Transportes "dónde está la tarjeta"** (`transport/`):
- `source.py` — resolución unificada: local / remota / NFCGate / fichero.
- `recorded.py` — **tarjeta virtual a partir de captura** (hexlog, session JSON,
  JSONL `{cmd,resp}` o `>`/`<` plano): matching por capas (exacto → CLA/INS/P1/P2 →
  INS → 6D00), repeticiones servidas en orden; `--strict-replay`. Aviso honesto: no
  puede responder a un challenge que no ha visto.
- `prefetch.py` — precarga PPSE+AIDs antes de que llegue el terminal (74→32 ms).
- `remote.py` + `card_proxy.py` + `remote_relay_os.py` — la tarjeta puede estar en
  **otra máquina**: proxy TCP (7654) junto al lector físico, y `secure_link.py`:
  TLS self-signed con **pinning SHA-256 + token**, pairing estilo SSH: `atrium.py
  pair [--rotate]` genera identidad en `~/.atrium` y emite un *pairing string*
  `atrium1:eyJ...` (dirección + fingerprint + token en base64); token comparado en
  tiempo constante; `--rotate` revoca. Refuso de bindear sin `--secure` fuera de
  loopback.
- `nfcgate/` — teléfono Android (app NFCGate, sin root) sostiene la tarjeta como
  "lector"; protobuf ServerData/NFCData **codificado a mano** (sin dependencia).

## En EMVy hoy

- Relay/MITM real **diferido** (`TODO.md`): la librería PN7150 no expone hooks de
  emulación EMV genérica; la vía prevista es firmware NFCGate del vendor con **dos
  BomberCat o BomberCat + Android rooteado** — y solo hay un BomberCat.
- Existe: puente MQTT (`relay_command`), relay NFCGate vía vendor (`bombercat
  relay` config/run/stop/status) y **capture a pcap** (`bombercat capture`), pero
  no ejercitables sin segundo extremo.
- `core/intercept.py` (reglas MITM) no tiene tráfico vivo donde aplicarse.

## Propuesta para EMVy

**Fase 1 — MITM de contacto sin hardware nuevo (vpcd).** PC/SC reader + módulo
`vpcd` + `virtualsmartcard` (construir desde fuente, como documenta atrium). El SO
ve una tarjeta virtual; EMVy la sirve reenviando a la tarjeta real por el lector
PC/SC que ya soporta. Comandos:
- `emvy relay start|stop|status [--mutations combo] [--intercept reglas]` — con el
  motor del [doc 01](01-motor-mutaciones-y-playbooks.md) y las reglas de
  `core/intercept.py` **en el path por fin**, y el logger del
  [doc 03](03-logging-estructurado-y-replay.md) de serie.
- Requisito Linux; documentar setup (vpcd + vsmartcard desde fuente) en
  `docs/HARDWARE.md`.
- SimTrace2 queda como extensión opcional (hardware ~40 USD) para el lado terminal.

**Fase 2 — recorded + prefetch (dev/test, sin hardware).**
- `transport/recorded` como backend más en `readers/registry.py` ("tarjeta" =
  captura): hoy `fakecard.py` ya hace esto en tests; formalizarlo como backend
  abierto permite **demo y desarrollo de UI sin tarjeta**, y rejugar capturas de
  engagements.
- Prefetch: optimización, solo cuando el relay contactless exista.

**Fase 3 — proxy remoto con pairing** (`emvy relay serve` / `emvy relay connect
atrium1:eyJ…`-style): para engagements donde la tarjeta está en las oficinas y el
terminal/POS en el sitio del cliente. Copiar el modelo completo: TLS self-signed +
pinning SHA-256 + token en tiempo constante + `--rotate` + no bind sin `--secure`
fuera de loopback. Alineado con el modelo de proyectos: la identidad vive en el
proyecto.

**No portar:** el stack PN532/ACR122U propio (duplica nfcpy + BomberCat; revisitar
solo si se quiere emular contactless sin BomberCat — la ISO-DEP con S(WTX) es
admirable pero son semanas de trabajo); el protobuf NFCGate propio (ya hay vía
vendor); el brute-force de PIN legacy.

**Esfuerzo estimado:** Fase 1 ≈ 600–800 líneas (virtual card + relay + integración
con mutaciones/loggers existentes) + documentación de setup. Fase 2 ≈ 300.
Fase 3 ≈ 500 (la mitad es `secure_link`, que está bien acotado).

**Por qué sí:** desbloquea el ítem más antiguo del `TODO.md` por una vía que no
depende de conseguir un segundo BomberCat, y le da al motor de mutaciones y al
logger su terreno natural. El resultado es el flujo estrella de atrium ("pon la
tarjeta, `relay start`, pasa el terminal") dentro de la suite de EMVy.
