"""Plantillas y mutaciones para **probar terminales/lectores/POS reales**, no
tarjetas: bandas magnéticas (Track1/Track2, para `bombercat magspoof`) y
registros EMV (para escribir en una tarjeta de prueba reescribible, vía
`core.cardwrite`). Todo puro — genera texto/bytes; el disparo real (magspoof o
escritura) lo hace el llamador (CLI/TUI) sobre un lector/BomberCat conectado.

La idea: variar campos de forma deliberada (PAN inválido, fecha vencida, CVM
forzando "sin verificación", AIP débil, campos truncados/sobredimensionados…)
para observar cómo reacciona un terminal real — rechazo local, fallback,
aceptación silenciosa — sin necesitar una tarjeta real ni emulación de tarjeta.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import ndef as ndefmod
from . import tlv
from . import track as tracklib
from .hexutil import from_hex, to_hex

# ---------------------------------------------------------------------------
# Banda magnética: construcción + plantillas
# ---------------------------------------------------------------------------
def luhn_check_digit(digits: str) -> str:
    """Dígito verificador Luhn para `digits` (sin el propio dígito)."""
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch) * (2 if i % 2 == 0 else 1)
        total += d - 9 if d > 9 else d
    return str((10 - total % 10) % 10)


def luhn_valid(pan: str) -> bool:
    return pan.isdigit() and luhn_check_digit(pan[:-1]) == pan[-1]


def build_track1(pan: str, name: str, expiry: str, service_code: str,
                 discretionary: str = "") -> str:
    """`%B<PAN>^<NOMBRE>^<YYMM><SC><DISC>?` (formato B, ISO/IEC 7813)."""
    return f"%B{pan}^{name}^{expiry}{service_code}{discretionary}?"


def build_track2(pan: str, expiry: str, service_code: str,
                 discretionary: str = "") -> str:
    """`;<PAN>=<YYMM><SC><DISC>?`."""
    return f";{pan}={expiry}{service_code}{discretionary}?"


@dataclass(frozen=True)
class TrackTemplate:
    id: str
    title: str
    description: str
    track1: str | None
    track2: str | None


def _track_fields(pan="4111111111111111", name="TEST/CARD", expiry="2812",
                  service_code="201", discretionary="000000"):
    return dict(pan=pan, name=name, expiry=expiry,
               service_code=service_code, discretionary=discretionary)


def track_templates(pan="4111111111111111", name="TEST/CARD", expiry="2812",
                    service_code="201", discretionary="000000"
                    ) -> tuple[TrackTemplate, ...]:
    """Plantilla base + mutaciones, parametrizables desde un PAN/fecha propios."""
    f = _track_fields(pan, name, expiry, service_code, discretionary)

    def t1(**over):
        d = {**f, **over}
        return build_track1(d["pan"], d["name"], d["expiry"], d["service_code"],
                            d["discretionary"])

    def t2(**over):
        d = {**f, **over}
        return build_track2(d["pan"], d["expiry"], d["service_code"],
                            d["discretionary"])

    bad_pan = pan[:-1] + ("0" if luhn_check_digit(pan[:-1]) != "0" else "1")
    return (
        TrackTemplate("baseline", "Pista válida (referencia)",
                      "Track1+Track2 bien formadas, para comparar contra las mutaciones.",
                      t1(), t2()),
        TrackTemplate("bad-luhn", "PAN con Luhn inválido",
                      "Dígito verificador incorrecto — ¿el terminal lo valida "
                      "localmente o lo manda igual al host?",
                      t1(pan=bad_pan), t2(pan=bad_pan)),
        TrackTemplate("expired", "Tarjeta vencida",
                      "Fecha de expiración en el pasado (2001-01) — ¿rechazo "
                      "local o pasa a autorización online?",
                      t1(expiry="0101"), t2(expiry="0101")),
        TrackTemplate("service-code-chip-required", "Código de servicio: exige chip",
                      "Service code 2xx (chip obligatorio) presentado por swipe — "
                      "¿el terminal fuerza inserción o hace fallback silencioso?",
                      t1(service_code="220"), t2(service_code="220")),
        TrackTemplate("truncated-pan", "PAN truncado",
                      "PAN cortado a 8 dígitos (por debajo del mínimo ISO/IEC 7812).",
                      t1(pan=pan[:8]), t2(pan=pan[:8])),
        TrackTemplate("oversized-pan", "PAN sobredimensionado",
                      "PAN de 22 dígitos (por encima del máximo de 19) — fuzz de "
                      "límites del parser del terminal.",
                      t1(pan=pan + "123456"), t2(pan=pan + "123456")),
        TrackTemplate("missing-separator", "Sin separador PAN/datos",
                      "Falta el '=' entre PAN y fecha/servicio — pista mal formada.",
                      f"%B{pan}{expiry}{service_code}{discretionary}?",
                      f";{pan}{expiry}{service_code}{discretionary}?"),
        TrackTemplate("no-end-sentinel", "Sin centinela final",
                      "Falta el '?' de cierre.",
                      t1()[:-1], t2()[:-1]),
        TrackTemplate("non-numeric-pan", "PAN no numérico",
                      "Letras dentro del PAN — ¿el terminal lo rechaza al leer o "
                      "lo reenvía tal cual?",
                      t1(pan="41111111ABCD1111"), t2(pan="41111111ABCD1111")),
        TrackTemplate("oversized-discretionary", "Campo discrecional excesivo",
                      "Datos discrecionales muy largos (60 dígitos) — fuzz de "
                      "buffer del lector.",
                      t1(discretionary="9" * 60), t2(discretionary="9" * 60)),
    )


def get_track_template(templates: tuple[TrackTemplate, ...], template_id: str
                       ) -> TrackTemplate | None:
    return next((t for t in templates if t.id == template_id), None)


# ---------------------------------------------------------------------------
# Registros EMV: construcción + plantillas (para escribir en tarjeta de prueba)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class EmvTemplate:
    id: str
    title: str
    description: str
    tlvs: tuple[tuple[str, bytes], ...]     # (tag, valor) en orden

    def to_record(self) -> bytes:
        """Codifica como un registro EMV (template '70', igual que la mayoría
        de tarjetas reales) listo para UPDATE RECORD."""
        return tlv.encode_tlv(tlv.TLV(
            "70", b"", [tlv.tlv(t, v) for t, v in self.tlvs], constructed=True))


def emv_templates(pan="4111111111111111", name="TEST/CARD", expiry="281231"
                  ) -> tuple[EmvTemplate, ...]:
    """Plantilla base + mutaciones de un registro EMV típico (5A/57/5F24/5F20)."""
    track2_hex = _track2_bcd(pan, expiry)
    base = (
        ("5A", from_hex(pan if len(pan) % 2 == 0 else pan + "F")),
        ("57", from_hex(track2_hex)),
        ("5F24", from_hex(expiry[2:] if len(expiry) == 6 else expiry)),
        ("5F20", name.encode("latin-1")),
        ("82", from_hex("2000")),                 # AIP: DDA soportado (referencia)
        ("8E", from_hex("00000000" "00000000" "4103" "1E03")),  # CVM: PIN online, luego firma
    )

    def replace(tag: str, value: bytes, tlvs=base):
        return tuple((t, value) if t == tag else (t, v) for t, v in tlvs)

    return (
        EmvTemplate("baseline", "Registro EMV válido (referencia)",
                    "PAN/expiry/nombre/AIP/CVM bien formados.", base),
        EmvTemplate("no-cvm", "CVM: sin verificación de titular",
                    "Fuerza 'Sin CVM requerido' (0x1F, siempre) — ¿el terminal "
                    "acepta la transacción sin pedir PIN/firma?",
                    replace("8E", from_hex("00000000" "00000000" "1F00"))),
        EmvTemplate("weak-aip", "AIP: solo SDA (sin DDA/CDA)",
                    "Autenticación offline débil/clonable — ¿el terminal la "
                    "acepta igual o exige online?",
                    replace("82", from_hex("4000"))),
        EmvTemplate("oversized-pan", "PAN sobredimensionado (5A)",
                    "10 bytes en el PAN (20 dígitos) — fuzz de límites de "
                    "parseo del terminal.",
                    replace("5A", from_hex("11" * 10))),
        EmvTemplate("missing-pan", "Sin PAN (5A ausente)",
                    "Registro sin el tag obligatorio 5A — ¿el terminal detecta "
                    "el campo faltante o falla de forma insegura?",
                    tuple((t, v) for t, v in base if t != "5A")),
        EmvTemplate("bad-track2", "Track2 equivalente roto (57)",
                    "Separador ausente en el tag 57 — ¿el terminal usa 5A/5F24 "
                    "igual, o falla el parseo completo del registro?",
                    replace("57", from_hex(pan + expiry))),
        EmvTemplate("expired", "Tarjeta vencida (5F24)",
                    "Fecha de expiración en el pasado (2001-01-01).",
                    replace("5F24", from_hex("010101"))),
    )


def _track2_bcd(pan: str, expiry: str) -> str:
    yymm = expiry[2:] if len(expiry) == 6 else expiry
    body = f"{pan}D{yymm}201"
    return body if len(body) % 2 == 0 else body + "F"


# Valores por defecto de un registro EMV de prueba (tarjeta de laboratorio).
TEST_RECORD = dict(pan="4111111111111111", name="TEST/CARD",
                   expiry="2812", service_code="201")


def _norm_expiry(expiry: str) -> tuple[str, str]:
    """Normaliza una caducidad a `(YYMM, YYMMDD)`.

    Acepta `YYMM` (4 díg., se asume día 31) o `YYMMDD` (6 díg.). Devuelve el
    par que usan, respectivamente, el Track2 (tag 57) y el tag 5F24.
    """
    digits = "".join(ch for ch in expiry if ch.isdigit())
    if len(digits) >= 6:
        yymmdd = digits[:6]
        return yymmdd[:4], yymmdd
    yymm = (digits + "0000")[:4]
    return yymm, yymm + "31"


def personalize_record(pan: str = "4111111111111111", name: str = "TEST/CARD",
                       expiry: str = "2812", service_code: str = "201") -> bytes:
    """Construye un registro EMV `70` **personalizado** listo para UPDATE RECORD.

    A partir de campos amistosos (PAN, titular, caducidad `YYMM`/`YYMMDD`, código
    de servicio) arma los tags 5A/57/5F24/5F20 + un AIP/CVM de referencia. El
    Track2 (57) se regenera con `core.track.build_track2_emv` (inverso de
    `parse_track2_emv`), de modo que PAN/caducidad/servicio quedan coherentes en
    5A, 57 y 5F24. Puro: no toca la tarjeta; el llamador lo escribe con
    `core.cardwrite.update_record`.
    """
    pan = "".join(ch for ch in pan if ch.isdigit()) or TEST_RECORD["pan"]
    service_code = ("".join(ch for ch in service_code if ch.isdigit()) or "201")[:3]
    yymm, yymmdd = _norm_expiry(expiry)
    track2 = tracklib.build_track2_emv(pan, yymm, service_code)
    pan_bcd = pan if len(pan) % 2 == 0 else pan + "F"
    tlvs = (
        ("5A", from_hex(pan_bcd)),
        ("57", from_hex(track2)),
        ("5F24", from_hex(yymmdd)),
        ("5F20", (name or TEST_RECORD["name"]).encode("latin-1")),
        ("82", from_hex("2000")),                             # AIP: DDA soportado
        ("8E", from_hex("00000000" "00000000" "4103" "1E03")),  # CVM: PIN online→firma
    )
    return tlv.encode_tlv(tlv.TLV(
        "70", b"", [tlv.tlv(t, v) for t, v in tlvs], constructed=True))


def get_emv_template(templates: tuple[EmvTemplate, ...], template_id: str
                     ) -> EmvTemplate | None:
    return next((t for t in templates if t.id == template_id), None)


# ---------------------------------------------------------------------------
# NDEF: mensaje base + mutaciones (para emular un tag NFC vía BomberCat)
# ---------------------------------------------------------------------------
# Equivalente NFC de magspoof: en vez de una banda mutada, se emula un **tag
# NFC Forum Type 4** cuyo mensaje NDEF está deliberadamente fuera de norma, para
# ver cómo lo parsea un lector/POS/teléfono (rechazo, cuelgue, aceptación). El
# firmware sirve estos bytes como el fichero NDEF; el llamador los dispara con
# `bombercat.ndef_emulate`. Emulación EMV completa NO es posible con este
# firmware (la librería PN7150 solo emula Type 4/NDEF), de ahí el foco en NDEF.
@dataclass(frozen=True)
class NdefTemplate:
    id: str
    title: str
    description: str
    message: bytes                       # bytes crudos del mensaje NDEF

    def to_hex(self) -> str:
        return to_hex(self.message)


def ndef_templates(url: str = "https://emvy.test/def-con",
                   text: str = "EMVy fuzz") -> tuple[NdefTemplate, ...]:
    """Mensaje NDEF válido (referencia) + mutaciones malformadas."""
    base = ndefmod.uri_record(url)                       # 1 registro URI válido

    # Registro URI con longitud de payload declarada enorme (0xFF) pero datos
    # cortos: prueba de overread/validación del parser del lector.
    oversized = bytes([0xD1, 0x01, 0xFF]) + b"U" + ndefmod.uri_payload(url)

    # type_length dice 0xFF pero no hay tipo/payload tras la cabecera.
    bad_type_len = bytes([0xD1, 0xFF, 0x03]) + b"U\x00ab"

    return (
        NdefTemplate("baseline", "NDEF válido (referencia)",
                     f"Un registro URI bien formado ({url}); para comparar "
                     "contra las mutaciones.", base),
        NdefTemplate("oversized-record", "Longitud de payload enorme",
                     "SR con payload_len=0xFF pero datos cortos — ¿el lector "
                     "sobre-lee el buffer o valida la longitud?", oversized),
        NdefTemplate("bad-type-length", "type_length inválido",
                     "Cabecera con type_length=0xFF sin tipo real detrás.",
                     bad_type_len),
        NdefTemplate("truncated", "Mensaje truncado",
                     "El mensaje base cortado a la mitad — registro incompleto.",
                     base[:max(1, len(base) // 2)]),
        NdefTemplate("invalid-tnf", "TNF reservado (0x07)",
                     "Type Name Format = 0x07 (reservado/ inválido por spec).",
                     ndefmod.build_record(0x07, b"U", ndefmod.uri_payload(url))),
        NdefTemplate("no-me-flag", "Sin flag ME (fin de mensaje)",
                     "Registro sin Message-End — el lector puede seguir leyendo "
                     "más allá del mensaje.",
                     ndefmod.uri_record(url, me=False)),
        NdefTemplate("huge-uri", "URI gigante",
                     "URI válida pero de ~1 KB — prueba de límites de buffer.",
                     ndefmod.uri_record(url + "/" + "A" * 1024)),
        NdefTemplate("long-format-mismatch", "Longitud de 4 bytes desalineada",
                     "Registro en formato largo (no-SR) con longitud declarada "
                     "mayor que el payload real.",
                     bytes([0xC1, 0x01]) + (999).to_bytes(4, "big") + b"U"
                     + ndefmod.uri_payload(url)),
        NdefTemplate("empty", "Mensaje NDEF vacío",
                     "Cero bytes — ¿el lector lo trata como tag vacío o falla?",
                     b""),
        NdefTemplate("multi-record", "Muchos registros",
                     "16 registros de texto encadenados — estrés del parser.",
                     _multi_text(text)),
    )


def _multi_text(text: str, n: int = 16) -> bytes:
    """`n` registros de texto: MB en el primero, ME en el último."""
    out = bytearray()
    for i in range(n):
        out += ndefmod.text_record(f"{text} {i}", mb=(i == 0), me=(i == n - 1))
    return bytes(out)


def get_ndef_template(templates: tuple[NdefTemplate, ...], template_id: str
                      ) -> NdefTemplate | None:
    return next((t for t in templates if t.id == template_id), None)


# Tarjeta de prueba canónica (para "emular una tarjeta" por NFC sin captura).
TEST_CARD = dict(pan="4111111111111111", expiry="2812",
                 aid="A0000000031010", label="TEST VISA")


def test_card_ndef() -> bytes:
    """Mensaje NDEF con los datos de una tarjeta de prueba canónica."""
    return ndefmod.card_record(**TEST_CARD)


def card_ndef_from_fields(pan="", expiry="", track2="", aid="", label="") -> bytes:
    """NDEF a partir de campos de una tarjeta (p.ej. de `EmvCard.from_dump`)."""
    return ndefmod.card_record(pan=pan, expiry=expiry, track2=track2,
                               aid=aid, label=label)
