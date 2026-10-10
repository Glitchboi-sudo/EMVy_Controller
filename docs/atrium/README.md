# Comparativa ATRIUM → EMVyController

Análisis del proyecto **ATRIUM (Payment Security Workbench)** — checkout local en
[`tmp/atrium/`](../../tmp/atrium/) (upstream: `github.com/salmg/atrium`) — con las
features que tiene y **EMVy Controller no**, y una propuesta de cuáles vale la pena
portar y cómo integrarlas en la arquitectura de EMVy.

## Los dos proyectos en una frase

- **ATRIUM**: workbench de investigación EMV cuyo corazón es el **relay MITM**
  terminal⇄tarjeta (vpcd + SimTrace2 + ACR122U) con mutaciones en vuelo, logging
  estructurado, capa host ISO 8583 completa, fingerprint/intel cross-session,
  agente LLM y dashboard web. Dos capas: tarjeta⇄terminal (APDU) y
  adquirente⇄host (ISO 8583).
- **EMVy Controller**: suite **multi-lector** (PC/SC, NFC/nfcpy, banda magnética,
  BomberCat) organizada en proyectos/engagements, orientada a probar **terminales**
  (magspoof, emulación de tarjeta EMV/NDEF, fuzzing de terminal, switch ISO 8583),
  con escritura/GlobalPlatform, framework de PoCs y UI rica (CLI/TUI/GUI).

Son **complementarios**: atrium muta la tarjeta para atacar el terminal por el lado
del relay; EMVy ya ataca el terminal por el lado de la emulación y la banda. Casi
todo lo que aporta atrium encaja en huecos que el propio `TODO.md` de EMVy reconoce.

## Matriz de features

| # | Feature (atrium) | EMVy hoy | ¿Portar? | Prioridad | Doc |
|---|---|---|---|---|---|
| 1 | Motor de mutaciones en vuelo (PDOL/AFL/CDOL/TLV/inyecciones) + playbooks COMBO-A…E | `core/cardfuzz` muta plantillas **hacia** terminales; `core/intercept` reglas sin relay en vivo; TODO pide más mutaciones | ✅ Sí — encaja perfecto con `emv-emulate` y futuro relay | **Alta** | [01](01-motor-mutaciones-y-playbooks.md) |
| 2 | Fingerprint normalizado (SHA-256) + intel DB cross-session con recomendador | `dump`/`analyze` sin identidad estable ni histórico | ✅ Sí — alimenta reportes y engagements | **Alta** | [02](02-fingerprinting-e-intel.md) |
| 3 | Logging de sesiones estructurado (JSON/hexlog/SQLite/cryptograms) + replay + APDU printer | `on_event` + consola cruda guardable en `<proyecto>/logs/` (plano) | ✅ Sí | **Alta** | [03](03-logging-estructurado-y-replay.md) |
| 4 | Capa host ISO 8583: dialectos YAML, detección, proxy, replay freshen, verify ARQC, scoping | `payments/`: codec + traductor + switch (signon/purchase/reversal) + análisis de replay | ✅ Sí, incremental | **Alta–Media** | [04](04-capa-host-iso8583.md) |
| 5 | Relay MITM contacto con **vpcd** (sin hardware extra) + SimTrace2 | Relay diferido: falta 2º extremo (NFCGate) y solo hay 1 BomberCat | ✅ Sí — desbloquea MITM ya | **Media–Alta** | [05](05-relay-mitm-y-hardware.md) |
| 6 | Proxy remoto de tarjeta con pairing TLS (pinning + token + rotate) | Puente MQTT solo (comando serie) | ✅ Sí, para engagements distribuidos | Media | [05](05-relay-mitm-y-hardware.md) |
| 7 | Transporte "recorded" (captura como tarjeta virtual) + prefetch | Inyección `EMUEMV:` en BomberCat (parcial) | ✅ Sí — muy útil para tests y demos | Media | [05](05-relay-mitm-y-hardware.md) |
| 8 | Agente LLM (provider-agnostic, 11 tools, catálogo de ataques) | Nada (el análogo natural es el framework de PoCs) | 🟡 Opcional | Media–Baja | [06](06-agente-llm-y-dashboard.md) |
| 9 | Dashboard web FastAPI + SPA (live trace, editor de mutaciones, chat agente) | TUI + GUI PySide6 ya cubren | ❌ No portar; reutilizar ideas sueltas | Baja | [06](06-agente-llm-y-dashboard.md) |
| 10 | Stack contactless propio PN532/ACR122U + ISO-DEP propio con S(WTX) | nfcpy + firmware BomberCat (capacidad equivalente ya) | ❌ No priorizar (esfuerzo alto, duplicado) | Baja | [05](05-relay-mitm-y-hardware.md) |
| 11 | NFCGate como transporte integrado (protobuf propio) | Ya integrado vía vendor `bombercat-tools` | ❌ No | — | [05](05-relay-mitm-y-hardware.md) |
| 12 | Modelo de seguridad del plano de control (token, anti DNS-rebinding, tests AST) | N/A (sin API web) | 🟡 Solo si se expone API algún día | Baja | [06](06-agente-llm-y-dashboard.md) |

## Qué **no** tiene sentido portar

- **Dashboard web**: EMVy ya tiene TUI (Textual) y GUI (PySide6) con paridad de
  pestañas. Un tercer front es deuda, no feature. Se salvan las ideas: live trace
  (ya existe como consola en vivo), editor YAML de mutaciones (sí entraría en la
  pestaña Fuzzing/Intercept).
- **Stack PN532/ACR122U propio** (`nfc/`, ~54KB + `doc/contactless-timing.md` de
  1592 líneas): duplica nfcpy y el firmware BomberCat. Solo se justificaría si se
  quisiera emular tarjeta contactless **sin** BomberCat (hardware de 20 USD); la
  ISO-DEP propia con S(WTX) es la pieza técnicamente más admirable de atrium, pero
  la relación esfuerzo/valor es mala para EMVy hoy.
- **Dialectos ISO 8583 de esquemas (Visa/MC/Amex)**: atrium tampoco los incluye
  (confidenciales por diseño). No es portarlo, es reconstruirlos por cuenta propia.
- **Ataques legacy**: el brute-force de PIN viejo de `intercept_attack.py` ya no es
  el camino principal ni en atrium; ignorarlo.

## Cómo leer estos documentos

Cada doc sigue la misma estructura: **En atrium** (qué es y dónde vive) →
**En EMVy hoy** (la brecha exacta) → **Propuesta** (módulos/comandos/UI concretos,
alineados con la arquitectura "núcleo puro, efectos en los bordes" de EMVy) →
**Prioridad y esfuerzo**.

1. [Motor de mutaciones y playbooks COMBO](01-motor-mutaciones-y-playbooks.md)
2. [Fingerprinting e inteligencia cross-session](02-fingerprinting-e-intel.md)
3. [Logging estructurado y replay](03-logging-estructurado-y-replay.md)
4. [Capa host ISO 8583](04-capa-host-iso8583.md)
5. [Relay MITM y hardware](05-relay-mitm-y-hardware.md)
6. [Agente LLM y dashboard web](06-agente-llm-y-dashboard.md)

> Orden sugerido de implementación: **1 → 3 → 2 → 4 → 5 → (6 opcional)**.
> Las tres primeras se potencian entre sí (mutar → registrar → recordar qué funcionó)
> y dejan hueco listo para el relay cuando haya segundo extremo.
