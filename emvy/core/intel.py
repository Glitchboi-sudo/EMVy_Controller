"""Inteligencia cross-session (núcleo puro): catálogo de ataques conocidos,
recomendador y patrones cross-card.

Traducción/adaptación de `tmp/atrium/card_intel.py` al estilo funcional de EMVy:
todo es puro (sin DB ni estado global). La persistencia vive en
`project.inteldb.IntelDB`, que carga el perfil + los outcomes y delega aquí.

El catálogo `KNOWN_ATTACKS` documenta ATTACK-1…11 con sus condiciones de
disparo sobre el perfil. Los ataques que requieren relay NFC (que EMVy aún no
integra) se marcan con `requires_relay`; el recomendador los incluye anotándolo.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .fingerprint import CardProfile

# Resultados válidos de un outcome (mismo vocabulario que atrium).
RESULTS: tuple[str, ...] = ("success", "partial", "failed", "blocked", "error")


@dataclass(frozen=True)
class AttackOutcome:
    """Resultado de probar un ataque contra una tarjeta (fila de `attacks`)."""
    attack_id: str
    result: str          # success | partial | failed | blocked | error
    notes: str = ""


@dataclass(frozen=True)
class Recommendation:
    """Sugerencia del recomendador, con la razón y el outcome previo si lo hay."""
    attack_id: str
    title: str
    reason: str
    tried: AttackOutcome | None = None
    requires_relay: bool = False
    combo: str | None = None


# ---------------------------------------------------------------------------
# Catálogo de ataques conocidos (ATTACK-1…11, traducido de atrium)
# ---------------------------------------------------------------------------
# Cada entrada:
#   id           — identificador estable (ATTACK-n)
#   title        — nombre corto
#   description  — vector del ataque (qué hace)
#   conditions   — callable(profile) -> bool: qué perfil lo hace aplicable
#   reason       — texto que explica por qué casa con el perfil
#   combo        — COMBO de core.playbooks que lo implementa (si existe)
#   requires_relay — True si necesita relay NFC (EMVy aún no lo integra)
# ---------------------------------------------------------------------------

KNOWN_ATTACKS: tuple[dict, ...] = (
    {
        "id": "ATTACK-1",
        "title": "Importe + bypass de CVM",
        "description": ("Mutar el importe del PDOL (9F02) a 1 céntimo para activar "
                        "la regla de umbral 'Sin CVM requerido' del CVM List y "
                        "saltar la verificación de titular."),
        "conditions": lambda p: "9F02" in {t for t, _ in p.pdol},
        "reason": "el PDOL pide el importe (9F02): se puede forzar el umbral No-CVM",
        "combo": "COMBO-A",
        "requires_relay": False,
    },
    {
        "id": "ATTACK-2",
        "title": "Manipulación del TTQ",
        "description": ("Reescribir el TTQ (9F66) que pide el PDOL para anunciar un "
                        "terminal online-only sin PIN offline y forzar un "
                        "criptograma ARQC en vez de un TC offline."),
        "conditions": lambda p: "9F66" in {t for t, _ in p.pdol},
        "reason": "el PDOL pide el TTQ (9F66): se controlan las capacidades anunciadas",
        "combo": "COMBO-A",
        "requires_relay": False,
    },
    {
        "id": "ATTACK-3",
        "title": "Degradación CDA/DDA",
        "description": ("Mutar el AIP (tag 82, XOR 0x2100) para limpiar los bits "
                        "DDA/CDA: el terminal queda degradado a SDA-only y no puede "
                        "verificar la tarjeta offline."),
        "conditions": lambda p: any("DDA" in f or "CDA" in f for f in p.aip_flags),
        "reason": "el AIP declara DDA/CDA: degradando el AIP se anula la autenticación offline",
        "combo": "COMBO-B",
        "requires_relay": False,
    },
    {
        "id": "ATTACK-4",
        "title": "Forzar No-CVM",
        "description": ("Sustituir el CVM List (8E) por una lista con 'Sin CVM "
                        "requerido' primero para que el terminal omita cualquier "
                        "verificación de titular."),
        "conditions": lambda p: bool(p.cvm_rules),
        "reason": "la tarjeta expone CVM List: se puede forzar No-CVM",
        "combo": "COMBO-A",
        "requires_relay": False,
    },
    {
        "id": "ATTACK-5",
        "title": "Recolección silenciosa",
        "description": ("Inyectar GET DATA de ATC (9F36), Last Online ATC (9F13) y "
                        "reintentos PIN (9F17) en los huecos del flujo para leer "
                        "el estado de la tarjeta sin alterar la transacción."),
        "conditions": lambda p: bool(p.pin_retry) or "9F36" in p.tag_inventory,
        "reason": "hay contador de reintentos PIN / ATC observable vía GET DATA",
        "combo": "COMBO-E",
        "requires_relay": False,
    },
    {
        "id": "ATTACK-6",
        "title": "Deshabilitar IAC-Denial",
        "description": ("Poner a cero el Issuer Action Code – Denial (9F0E) para "
                        "que la tarjeta nunca decline offline y acepte transacciones "
                        "que deberían fallar."),
        "conditions": lambda p: "9F0E" in p.tag_inventory,
        "reason": "el IAC-Denial (9F0E) está presente: ponerlo a cero evita declives offline",
        "combo": "COMBO-C",
        "requires_relay": False,
    },
    {
        "id": "ATTACK-7",
        "title": "Manipulación del AFL",
        "description": ("Mutar el AFL (tag 94): skip_signed (contador de auth "
                        "offline a 0, nada firmado) o truncate a 1 entrada para "
                        "que el terminal no lea los registros de CVM/risk data."),
        "conditions": lambda p: bool(p.afl),
        "reason": "hay AFL que mutar: el terminal se puede desviar de los registros firmados",
        "combo": "COMBO-B",
        "requires_relay": False,
    },
    {
        "id": "ATTACK-8",
        "title": "Desincronización CDOL1/CDOL2",
        "description": ("Quitar campos del CDOL1 (p.ej. el importe 9F02) para que "
                        "el criptograma deje de quedar ligado al importe mostrado, "
                        "o borrar CDOL2 (8D) para suprimir el segundo GENERATE AC."),
        "conditions": lambda p: bool(p.cdol1 or p.cdol2),
        "reason": "la tarjeta define CDOL: se puede desligar el criptograma del importe",
        "combo": "COMBO-D",
        "requires_relay": False,
    },
    {
        "id": "ATTACK-9",
        "title": "Manipulación de ATC / Last Online ATC",
        "description": ("Congelar ATC (9F36) y Last Online ATC (9F13) en valores "
                        "fijos vía mutación de GET DATA para investigar "
                        "replay/pre-play contra el emisor."),
        "conditions": lambda p: "9F36" in p.tag_inventory or bool(p.atc),
        "reason": "el ATC es legible vía GET DATA: se puede congelar para pruebas de replay",
        "combo": "COMBO-E",
        "requires_relay": False,
    },
    {
        "id": "ATTACK-10",
        "title": "Emparejamiento divisa + país",
        "description": ("Mutar la divisa (5F2A) y el país del terminal (9F1A) del "
                        "PDOL para desincronizarlos del importe y forzar rutas de "
                        "procesamiento inesperadas."),
        "conditions": lambda p: bool(p.service_code),
        "reason": "hay service code (política de la tarjeta): divisa/país mal emparejados alteran el procesamiento",
        "combo": None,
        "requires_relay": False,
    },
    {
        "id": "ATTACK-11",
        "title": "Supresión / inyección de issuer scripts",
        "description": ("Intervenir los issuer scripts post-GENERATE AC: suprimir "
                        "bloques de script (p.ej. PUT de PIN) o inyectar comandos "
                        "con el canal emisor→tarjeta."),
        "conditions": lambda p: bool(p.cdol1),
        "reason": "hay CDOL1 (transacción online con scripts del emisor): se pueden suprimir/inyectar scripts",
        "combo": "COMBO-D",
        "requires_relay": True,
    },
)

# Prerrequisitos de COMBOs (de core.playbooks): cuando los prerequisitos
# tuvieron éxito, se sugiere el resto de piezas del COMBO aún no probadas.
COMBO_PREREQS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    # COMBO -> (prerequisitos, piezas restantes del COMBO a recomendar)
    "COMBO-C": (("ATTACK-1",), ("ATTACK-6", "ATTACK-8")),
    "COMBO-B": (("ATTACK-3", "ATTACK-7"), ()),
}

_ATTACKS_BY_ID = {a["id"]: a for a in KNOWN_ATTACKS}


def get_attack(attack_id: str) -> dict | None:
    """Ataque del catálogo por id (None si no existe)."""
    return _ATTACKS_BY_ID.get((attack_id or "").upper())


def attack_ids() -> tuple[str, ...]:
    """Ids conocidos, en orden canónico."""
    return tuple(a["id"] for a in KNOWN_ATTACKS)


# ---------------------------------------------------------------------------
# Recomendador (orden de atrium: parciales → casan con perfil → prerrequisitos
# de combos → orden canónico)
# ---------------------------------------------------------------------------
def recommend(profile: CardProfile,
              outcomes: Iterable[AttackOutcome],
              attacks: tuple[dict, ...] = KNOWN_ATTACKS,
              limit: int = 5) -> list[Recommendation]:
    """Top-N ataques recomendados para una tarjeta, dados sus outcomes previos.

    Orden (mismo criterio que `_recommend` de atrium):
      1. ataques con resultado 'partial' → reintentar primero;
      2. no probados que casan con las condiciones del perfil;
      3. COMBOs cuyos prerrequisitos se cumplieron;
      4. relleno en orden canónico (los no probados).
    """
    outcomes = list(outcomes)
    by_id: dict[str, AttackOutcome] = {}
    for o in outcomes:
        by_id.setdefault(o.attack_id.upper(), o)
    succeeded = {o.attack_id.upper() for o in outcomes if o.result == "success"}
    partial = [o.attack_id.upper() for o in outcomes if o.result == "partial"]
    closed = {o.attack_id.upper() for o in outcomes if o.result in ("success", "failed")}

    catalog = {a["id"]: a for a in attacks}
    candidates: list[list] = []   # [prioridad, id, razón] (mutables para upgrades)

    def add(priority: int, aid_: str, reason: str) -> None:
        a = catalog.get(aid_)
        if a is None or aid_ in closed:
            return
        for c in candidates:
            if c[1] == aid_:
                if priority < c[0]:     # una vía con más prioridad: se actualiza
                    c[0], c[2] = priority, reason
                return
        candidates.append([priority, aid_, reason])

    # 1) parciales primero: mostraron efecto, conviene insistir
    for aid_ in partial:
        add(0, aid_, "resultado parcial previo: conviene reintentar/refinar")

    # 2) no probados que casan con el perfil
    for a in attacks:
        if a["id"] in by_id:
            continue
        try:
            match = a["conditions"](profile)
        except Exception:
            match = False
        if match:
            add(10, a["id"], a["reason"])

    # 3) prerrequisitos de COMBOs cumplidos → piezas restantes del COMBO
    for combo, (prereqs, piezas) in COMBO_PREREQS.items():
        if set(prereqs) <= succeeded:
            for pieza in piezas:
                add(5, pieza,
                    f"pieza del {combo}: su prerequisito ({', '.join(prereqs)}) "
                    "tuvo éxito")

    # 4) relleno canónico con los no probados
    for a in attacks:
        add(30, a["id"], "sin probar aún")

    out: list[Recommendation] = []
    # orden estable: por prioridad; a igual prioridad, orden de inserción
    # (que sigue el orden canónico del catálogo)
    for _, aid_, reason in sorted(candidates, key=lambda c: c[0])[:limit]:
        a = catalog[aid_]
        out.append(Recommendation(
            attack_id=aid_,
            title=a["title"],
            reason=reason,
            tried=by_id.get(aid_),
            requires_relay=bool(a.get("requires_relay")),
            combo=a.get("combo"),
        ))
    return out


# ---------------------------------------------------------------------------
# Patrones cross-card (adaptado de `get_cross_card_patterns` de atrium)
# ---------------------------------------------------------------------------
def cross_card_patterns(rows: list[dict]) -> list[str]:
    """Patrones de status words / resultados repetidos entre tarjetas.

    `rows` son outcomes APDU de la forma
    `{attack_id|label, result|sw, hash}`. Devuelve líneas legibles con los
    patrones que se repiten en 2+ tarjetas (ordenados por nº de tarjetas).
    """
    by_key: dict[tuple[str, str], set[str]] = {}
    counts: dict[tuple[str, str], int] = {}
    for r in rows:
        key = (str(r.get("attack_id") or r.get("label") or "?"),
               str(r.get("result") or r.get("sw") or "?"))
        h = str(r.get("hash") or "")
        by_key.setdefault(key, set()).add(h)
        counts[key] = counts.get(key, 0) + 1

    lines: list[str] = []
    for (attack, res), hashes in sorted(by_key.items(),
                                        key=lambda kv: (-len(kv[1]), -counts[kv[0]])):
        if len(hashes) < 2:
            continue
        lines.append(f"{attack} → {res}: en {len(hashes)} tarjetas "
                     f"({counts[(attack, res)]} veces)")
    return lines
