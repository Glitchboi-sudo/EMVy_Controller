"""Fingerprinting normalizado de tarjeta EMV (núcleo puro).

Construye un `CardProfile` estable a partir de los TLVs de una aplicación (o de
un `session.CardDump`) y calcula un **hash SHA-256** que identifica la tarjeta
entre sesiones, aunque cambien los datos volátiles (ATC, UN, fechas de
transacción…). Traducción/adaptación al estilo funcional de EMVy del perfil de
`tmp/atrium/card_fingerprint.py`, empaquetando lo que `dump`/`analyze` ya
extraen en lugar de re-hacer el escaneo.

Qué entra en el hash (identidad estable):
  AIDs ordenados, esquema/etiquetas, flags del AIP, AFL, PDOL/CDOL1/CDOL2,
  reglas CVM resumidas, capacidades cripto (índice de CA, tamaños de clave,
  readiness SDA/DDA), service code del Track 2 e inventario de tags.

Qué se EXCLUYE del hash (volátil o de sesión):
  • `9F36` ATC, `9F13` Last Online ATC — contadores que cambian cada uso.
  • `9F37` UN (Unpredictable Number) — aleatorio por transacción.
  • `9A` fecha, `9F21` hora y `9C` tipo de transacción — datos de terminal.
  • Valores de Track 2 / PAN / titular — sensibles y reasignables por el emisor
    (y en laboratorio/CTF se reescriben con frecuencia); el service code (que
    sí configura la política de la tarjeta) sí participa.
  • `9F6E` Form Factor Indicator (Visa) — puede variar según el canal (contacto
    vs contactless); se expone en `crypto` pero no rompe la identidad.
  • Los valores de GET DATA (`atc`, `pin_retry`) — informativos, no de identidad.

Elección de AID con varias apps en un dump: el perfil se calcula sobre **una**
aplicación (la de `aid` si se indica, si no la primera del dump, como hace
`tlvs_from_dump`); los AIDs de las demás aplicaciones del dump se listan en
`aids` para que formen parte de la identidad. Así el hash reconoce la tarjeta
independientemente del AID por el que se entró.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from . import cvm as cvmmod
from . import emv, emvbits, oda, tlv, track
from .hexutil import to_hex

# Tags volátiles excluidos del inventario que alimenta el hash.
# Se documentan aquí (y en el docstring del módulo) porque definen la estabilidad
# de la identidad entre sesiones.
_TAGS_VOLATILES = frozenset({"9F36", "9F13", "9F17", "9F37", "9A", "9F21", "9C",
                             "9F6E", "57", "5A", "5F20", "5F24", "5F34",
                             "9F26", "9F10", "9F27"})


@dataclass(frozen=True)
class CardProfile:
    """Perfil normalizado de una tarjeta (aplicación principal + contexto).

    Todos los campos son serializables de forma determinista: tuplas ordenadas
    y dicts con claves simples. `to_canonical()` produce el JSON estable sobre
    el que se calcula `hash`."""

    aid: str                              # AID de la app analizada
    aids: tuple[str, ...]                 # todos los AIDs del dump (ordenados)
    scheme: str                           # esquema de pago (Visa, Mastercard…)
    label: str                            # etiqueta de la app (o "")
    aip: str                              # hex del AIP (tag 82) o ""
    aip_flags: tuple[str, ...]            # nombres de flags activos (decode_aip)
    afl: tuple[tuple[int, int, int, int], ...]  # (sfi, primero, último, offline)
    pdol: tuple[tuple[str, int], ...]     # (tag, longitud)
    cdol1: tuple[tuple[str, int], ...]
    cdol2: tuple[tuple[str, int], ...]
    cvm_rules: tuple[tuple[str, str, bool], ...]  # (método, condición, sigue_si_falla)
    crypto: dict[str, Any]                # ca_index, issuer_key_bits, sda_ready…
    service_code: str                     # desde Track 2 (o "")
    tag_inventory: tuple[str, ...]        # tags vistos (volátiles excluidos), ordenados
    app_count: int                        # nº de apps del dump
    atc: str = ""                         # 9F36 vía GET DATA (informativo; no entra al hash)
    pin_retry: str = ""                   # 9F17 vía GET DATA (informativo)
    hash: str = field(init=False, default="")  # SHA-256 de to_canonical()

    def __post_init__(self):
        object.__setattr__(self, "hash", fingerprint_hash(self))

    # -- serialización ------------------------------------------------------
    def to_canonical(self) -> str:
        """JSON estable (claves ordenadas, sin espacios) — base del hash.

        Excluye lo volátil documentado en el módulo: `atc` y `pin_retry`
        (contadores GET DATA que cambian entre sesiones) ya no intervienen."""
        d = self.to_dict(include_hash=False)
        d.pop("atc", None)
        d.pop("pin_retry", None)
        return json.dumps(d, sort_keys=True, separators=(",", ":"))

    def to_dict(self, include_hash: bool = True) -> dict:
        out = {
            "aid": self.aid,
            "aids": list(self.aids),
            "scheme": self.scheme,
            "label": self.label,
            "aip": self.aip,
            "aip_flags": list(self.aip_flags),
            "afl": [list(e) for e in self.afl],
            "pdol": [list(e) for e in self.pdol],
            "cdol1": [list(e) for e in self.cdol1],
            "cdol2": [list(e) for e in self.cdol2],
            "cvm_rules": [list(r) for r in self.cvm_rules],
            "crypto": dict(self.crypto),
            "service_code": self.service_code,
            "tag_inventory": list(self.tag_inventory),
            "app_count": self.app_count,
            "atc": self.atc,
            "pin_retry": self.pin_retry,
        }
        if include_hash:
            out["hash"] = self.hash
        return out


def fingerprint_hash(profile: CardProfile) -> str:
    """SHA-256 hex del perfil canónico = identidad estable de la tarjeta."""
    return hashlib.sha256(profile.to_canonical().encode("utf-8")).hexdigest()


def profile_to_dict(profile: CardProfile) -> dict:
    """Serializa incluyendo el hash (para persistir en la intel DB)."""
    return profile.to_dict(include_hash=True)


def profile_from_dict(d: dict) -> CardProfile:
    """Inverso de `profile_to_dict`. Tolera dicts sin `hash` (se recalcula)."""
    return CardProfile(
        aid=str(d.get("aid", "")),
        aids=tuple(d.get("aids") or ()),
        scheme=str(d.get("scheme", "")),
        label=str(d.get("label", "")),
        aip=str(d.get("aip", "")),
        aip_flags=tuple(d.get("aip_flags") or ()),
        afl=tuple(tuple(e) for e in d.get("afl") or ()),
        pdol=tuple(tuple(e) for e in d.get("pdol") or ()),
        cdol1=tuple(tuple(e) for e in d.get("cdol1") or ()),
        cdol2=tuple(tuple(e) for e in d.get("cdol2") or ()),
        cvm_rules=tuple(tuple(r) for r in d.get("cvm_rules") or ()),
        crypto=dict(d.get("crypto") or {}),
        service_code=str(d.get("service_code", "")),
        tag_inventory=tuple(d.get("tag_inventory") or ()),
        app_count=int(d.get("app_count", 0)),
        atc=str(d.get("atc", "")),
        pin_retry=str(d.get("pin_retry", "")),
    )


def _collect_tags(tlvs: tlv.TLVList) -> list[str]:
    """Inventario plano de tags (DFS), con los volátiles excluidos."""
    seen: set[str] = set()

    def walk(nodes) -> None:
        for t in nodes:
            seen.add(t.tag)
            if t.children:
                walk(t.children)

    walk(tlvs)
    seen -= _TAGS_VOLATILES
    return sorted(seen)


def profile_from_tlvs(tlvs: tlv.TLVList, *, aid: str = "", label: str = "") -> CardProfile:
    """Perfil normalizado desde los TLVs de una aplicación (puro, offline)."""
    aip_t = tlvs.find("82")
    aip = to_hex(aip_t.value) if aip_t else ""
    aip_flags = tuple(emvbits.set_flags(emvbits.decode_aip(
        bytes.fromhex(aip) if aip else b"")))

    afl_t = tlvs.find("94")
    afl = tuple(emv.parse_afl(afl_t.value)) if afl_t else ()

    pdol_t = tlvs.find("9F38")
    pdol = tuple(tlv.parse_dol(pdol_t.value)) if pdol_t and pdol_t.value else ()
    cdol1_t = tlvs.find("8C")
    cdol1 = tuple(tlv.parse_dol(cdol1_t.value)) if cdol1_t and cdol1_t.value else ()
    cdol2_t = tlvs.find("8D")
    cdol2 = tuple(tlv.parse_dol(cdol2_t.value)) if cdol2_t and cdol2_t.value else ()

    cvm_rules: list[tuple[str, str, bool]] = []
    cvm_t = tlvs.find("8E")
    if cvm_t and cvm_t.value:
        cl = cvmmod.parse_cvm_list(cvm_t.value)
        if cl:
            cvm_rules = [(r.code_name, r.condition_name, r.apply_next_if_fails)
                         for r in cl.rules]

    rep = oda.oda_report(tlvs)
    crypto = {
        "ca_index": rep.ca_index,
        "issuer_key_bits": rep.issuer_key_bits,
        "sda_ready": rep.sda_ready,
        "dda_ready": rep.dda_ready,
        "methods": rep.methods_supported,
    }
    t9f08 = tlvs.find("9F08")
    if t9f08:
        crypto["app_version"] = to_hex(t9f08.value)

    service_code = ""
    t57 = tlvs.find("57")
    if t57 and t57.value:
        t2 = track.parse_track2_emv(t57.value)
        if t2:
            service_code = t2.service_code

    atc = tlvs.find("9F36")
    pin_retry = tlvs.find("9F17")

    return CardProfile(
        aid=aid.upper(),
        aids=(aid.upper(),) if aid else (),
        scheme="",
        label=label,
        aip=aip,
        aip_flags=aip_flags,
        afl=afl,
        pdol=pdol,
        cdol1=cdol1,
        cdol2=cdol2,
        cvm_rules=tuple(cvm_rules),
        crypto=crypto,
        service_code=service_code,
        tag_inventory=tuple(_collect_tags(tlvs)),
        app_count=1,
        atc=to_hex(atc.value) if atc else "",
        pin_retry=to_hex(pin_retry.value) if pin_retry else "",
    )


def profile_from_dump(dump, aid: str | None = None) -> CardProfile | None:
    """Perfil desde un `CardDump` (puro, offline).

    Si `aid` es None usa la primera aplicación (mismo criterio que
    `session.model.tlvs_from_dump`); el hash engloba los AIDs de todas las apps
    del dump (ordenados) para que la identidad no dependa del AID de entrada.
    Devuelve None si el dump no tiene datos de aplicación.
    """
    from ..session.model import tlvs_from_dump

    app, tlvs = tlvs_from_dump(dump, aid)
    if not tlvs:
        return None
    profile = profile_from_tlvs(tlvs, aid=app.get("aid", ""),
                                label=app.get("label", "") or "")
    # El AFL puede no aparecer como TLV (los dumps guardan el hex crudo del GPO):
    # se rellena desde el campo `afl` de la app cuando el tag 94 no viajó en los datos.
    if not profile.afl and app.get("afl"):
        from .hexutil import from_hex
        try:
            profile = _replace(profile, afl=tuple(emv.parse_afl(from_hex(app["afl"]))))
        except ValueError:
            pass
    profile = _replace(profile,
                       aids=tuple(sorted(a["aid"].upper()
                                         for a in dump.applications if a.get("aid"))),
                       scheme=app.get("scheme", "") or "",
                       app_count=len(dump.applications))
    return profile


def _replace(profile: CardProfile, **changes) -> CardProfile:
    """`dataclasses.replace` sin importar replace: reconstruye recalculando hash."""
    d = profile.to_dict(include_hash=False)
    d.update(changes)
    return profile_from_dict(d)


def summary_lines(profile: CardProfile) -> list[str]:
    """Resumen legible del perfil (lo usan CLI y UI)."""
    lines = [
        f"AID          : {profile.aid}  {profile.label}".rstrip(),
        f"Esquema      : {profile.scheme or '—'}",
        f"Hash         : {profile.hash}",
        f"AIP          : {profile.aip or '—'}  →  {', '.join(profile.aip_flags) or 'sin flags'}",
    ]
    if profile.afl:
        afl_str = "  ".join(f"SFI{e[0]}[{e[1]}-{e[2]}]" + (f"*{e[3]}" if e[3] else "")
                            for e in profile.afl)
        lines.append(f"AFL          : {afl_str}")
    if profile.pdol:
        lines.append("PDOL         : " + "  ".join(f"{t}({n}B)" for t, n in profile.pdol))
    for nombre, dol in (("CDOL1", profile.cdol1), ("CDOL2", profile.cdol2)):
        if dol:
            lines.append(f"{nombre:<13}: " + "  ".join(f"{t}({n}B)" for t, n in dol))
    if profile.cvm_rules:
        lines.append("CVM          :")
        for i, (metodo, condicion, sigue) in enumerate(profile.cvm_rules, 1):
            cont = " (sigue si falla)" if sigue else ""
            lines.append(f"  {i}. {metodo}{cont} — {condicion}")
    c = profile.crypto
    lines.append("Cripto       : "
                 + "  ".join(f"{k}={'✓' if c.get(k) else '✗'}"
                             for k in ("sda_ready", "dda_ready")))
    if c.get("ca_index"):
        lines.append(f"Índice CA    : {c['ca_index']}")
    if c.get("issuer_key_bits"):
        lines.append(f"Clave emisor : ~{c['issuer_key_bits']} bits (por cert ICC)")
    if c.get("app_version"):
        lines.append(f"Versión app  : {c['app_version']}")
    if profile.service_code:
        lines.append(f"Service code : {profile.service_code} (Track 2)")
    if profile.pin_retry:
        lines.append(f"Reintentos PIN (9F17): {profile.pin_retry}")
    if profile.atc:
        lines.append(f"ATC actual (9F36): {profile.atc}")
    lines.append(f"Apps en dump : {profile.app_count}   Tags: {len(profile.tag_inventory)}")
    return lines
