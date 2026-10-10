"""Logging estructurado de sesiones EMV: modelo, detección de sesión, hexlog,
extracción de criptogramas, plan de replay y conversión entre formatos.

Núcleo **puro**: sin IO, sin reloj global, sin estado compartido. Toda fuente
de no-determinismo (uuid, fecha/hora) se inyecta como parámetro opcional con
valor por defecto, así los tests son deterministas. La escritura a disco vive
en `emvy.session.recorder`.

Semántica portada de atrium (`emv_logger.py`):
  * nueva sesión en **SELECT AID** (CLA 0x00, INS 0xA4, P1 0x04);
  * cierre en **GENERATE AC** (INS 0xAE) o cuando el gap temporal supera el
    timeout configurable;
  * hexlog estilo PC/SC (una línea por APDU, `C`/`R`, prefijo de sesión).

El nivel de grabación es el `Transceiver` **lógico** (el que devuelve
`core.apdu.make_transceiver` ya resuelto de 61xx/6Cxx), así cada intercambio
grabado es 1 comando → 1 respuesta final, sin reintentos ni GET RESPONSE
encadenados. Esto es lo que hace que el hexlog sea reproductible 1:1.
"""
from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from . import tlv
from .apdu import APDU, INS_GENERATE_AC, INS_GET_PROCESSING_OPTIONS, INS_SELECT, Response
from .hexutil import from_hex, to_hex
from .intercept import to_apdu

# Tags criptográficos que se extraen a la colección de criptogramas.
CRYPTO_TAGS: dict[str, str] = {
    "9F26": "Application Cryptogram (AC)",
    "9F27": "Cryptogram Information Data (CID)",
    "9F36": "Application Transaction Counter (ATC)",
    "9F10": "Issuer Application Data (IAD)",
    "9F37": "Unpredictable Number (UN)",
}


# ---------------------------------------------------------------------------
# Modelo
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class LogExchange:
    """Un intercambio lógico comando → respuesta.

    `t_ms` es el gap temporal desde el intercambio anterior en milisegundos
    (así lo mide `session.recorder` con reloj de pared; el primer intercambio
    de la corriente trae su propia duración). `notes` anota mutaciones u
    observaciones del intercambio.
    """

    command: APDU
    response: Response
    t_ms: float = 0.0
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class LogSession:
    """Una sesión EMV detectada: intercambios contiguos de una 'conversación'
    con la tarjeta (SELECT AID … GENERATE AC)."""

    sid: str                 # uuid4 hex corto
    started: str             # ISO 8601
    closed: str | None       # ISO 8601 si la sesión se cerró (GEN AC / timeout)
    reader: str
    atr: str                 # hex (sin separadores) o ""
    exchanges: tuple[LogExchange, ...]


# --- serialización JSON ------------------------------------------------------
def _apdu_to_dict(a: APDU) -> dict:
    return {"cla": a.cla, "ins": a.ins, "p1": a.p1, "p2": a.p2,
            "data": to_hex(a.data), "le": a.le}


def _apdu_from_dict(d: dict) -> APDU:
    return APDU(int(d["cla"]), int(d["ins"]), int(d.get("p1", 0)),
                int(d.get("p2", 0)), from_hex(d.get("data", "")),
                d.get("le"))


def _resp_to_dict(r: Response) -> dict:
    return {"data": to_hex(r.data), "sw1": r.sw1, "sw2": r.sw2}


def _resp_from_dict(d: dict) -> Response:
    return Response(from_hex(d.get("data", "")), int(d["sw1"]), int(d["sw2"]))


def session_to_dict(session: LogSession) -> dict:
    return {
        "sid": session.sid,
        "started": session.started,
        "closed": session.closed,
        "reader": session.reader,
        "atr": session.atr,
        "exchanges": [
            {"command": _apdu_to_dict(e.command),
             "response": _resp_to_dict(e.response),
             "t_ms": e.t_ms, "notes": list(e.notes)}
            for e in session.exchanges
        ],
    }


def session_from_dict(d: dict) -> LogSession:
    return LogSession(
        sid=str(d["sid"]),
        started=str(d.get("started", "")),
        closed=d.get("closed"),
        reader=str(d.get("reader", "")),
        atr=str(d.get("atr", "")),
        exchanges=tuple(
            LogExchange(_apdu_from_dict(e["command"]),
                        _resp_from_dict(e["response"]),
                        float(e.get("t_ms", 0.0)),
                        tuple(e.get("notes", ())))
            for e in d.get("exchanges", [])
        ),
    )


def session_to_json(session: LogSession, indent: int = 2) -> str:
    return json.dumps(session_to_dict(session), indent=indent, ensure_ascii=False)


def session_from_json(text: str) -> LogSession:
    return session_from_dict(json.loads(text))


# ---------------------------------------------------------------------------
# Detección de sesión
# ---------------------------------------------------------------------------
def is_select_aid(a: APDU) -> bool:
    """SELECT por DF name (AID): CLA 0x00, INS 0xA4, P1 0x04 (ISO 7816-4)."""
    return a.cla == 0x00 and a.ins == INS_SELECT and a.p1 == 0x04


def split_sessions(
    events: list[LogExchange],
    *,
    timeout_s: float = 30.0,
    reader: str = "",
    atr: str = "",
    sid_factory: Callable[[], str] | None = None,
    now: Callable[[], str] | None = None,
) -> list[LogSession]:
    """Agrupa intercambios en sesiones EMV (semántica de atrium).

    * Empieza sesión nueva en **SELECT AID**.
    * Cierra la sesión al llegar un **GENERATE AC** (incluido en la sesión) o
      cuando el gap temporal entre intercambios supera `timeout_s`.

    El tiempo usa el `t_ms` de cada intercambio como **gap desde el anterior**
    (así lo genera `session.recorder`, con reloj de pared; igual que atrium
    compara `ts_ms` consecutivos). El primer intercambio de la corriente trae
    su propia duración. Así un silencio largo (tarjeta retirada, usuario
    cambiando de app) cierra sesión aunque los SELECT/GENERATE AC falten.

    `sid_factory`/`now` permiten inyectar determinismo en tests; por defecto
    generan uuid4 hex corto (8 chars) y timestamp ISO 8601 UTC.
    """
    sid_factory = sid_factory or (lambda: uuid.uuid4().hex[:8])
    now = now or (lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))

    sessions: list[LogSession] = []
    current: list[LogExchange] = []
    started = ""

    def close(closed_at: str | None) -> None:
        nonlocal current, started
        if not current:
            return
        sessions.append(LogSession(sid_factory(), started, closed_at,
                                   reader, atr, tuple(current)))
        current, started = [], ""

    for ex in events:
        if current and (is_select_aid(ex.command)
                        or ex.t_ms > timeout_s * 1000.0):
            close(now())   # SELECT AID de otra app o pausa larga: cierra
        if not current:
            started = now()
        current.append(ex)
        if ex.command.ins == INS_GENERATE_AC:
            close(now())   # GENERATE AC finaliza la transacción (incluido)
    close(None)            # sesión a medias (p.ej. tarjeta retirada): closed=None
    return sessions


# ---------------------------------------------------------------------------
# Hexlog estilo PC/SC (formato de atrium: una línea por APDU, C/R, [sid8])
# ---------------------------------------------------------------------------
def to_hexlog(session: LogSession) -> str:
    """Serializa una sesión a hexlog (líneas `>>`/`<<` con cabecera de sesión).

    Formato (compatible con `parse_hexlog` y con el de atrium):
        # session <sid8>  started=<ISO>  reader=<lector>  atr=<hex>
        00012  C  [<sid8>]  00 A4 04 00 0E 32 50 41 59 ...
        00103  R  [<sid8>]  6F 33 84 0E ... 90 00
        # end <sid8>  closed=<ISO>

    El primer campo es el tiempo **acumulado** en milisegundos (t_ms acumulado
    de los intercambios), suficiente para reconstruir gaps en el parseo.
    """
    sid8 = session.sid[:8]
    lines = [f"# session {sid8}  started={session.started}"
             + (f"  reader={session.reader}" if session.reader else "")
             + (f"  atr={session.atr}" if session.atr else "")]
    t_cum = 0.0
    for ex in session.exchanges:
        t_cum += max(ex.t_ms, 0.0)
        cmd = to_hex(ex.command.to_bytes(), sep=" ")
        resp = to_hex(ex.response.data + bytes([ex.response.sw1, ex.response.sw2]),
                      sep=" ")
        lines.append(f"{int(round(t_cum)):05d}  C  [{sid8}]  {cmd}")
        lines.append(f"{int(round(t_cum)):05d}  R  [{sid8}]  {resp}")
    lines.append(f"# end {sid8}" + (f"  closed={session.closed}" if session.closed else ""))
    return "\n".join(lines) + "\n"


_HEXLOG_LINE = re.compile(
    r"^\s*(\d+)\s+([CR])\s+\[([^\]]+)\]\s+((?:[0-9A-Fa-f]{2}\s*)+)\s*$")


def parse_hexlog(text: str) -> list[LogExchange]:
    """Parsea un hexlog y devuelve los intercambios (C seguido de su R).

    El `t_ms` reconstruido es el **delta** entre tiempos acumulados consecutivos
    (el primer intercambio conserva su tiempo acumulado). Líneas `#` = cabeceras;
    las que no encajan se ignoran. Ver `to_hexlog` (round-trip garantizado).
    """
    exchanges: list[LogExchange] = []
    pending_cmd: tuple[float, APDU] | None = None
    t_prev = 0.0
    for line in text.splitlines():
        m = _HEXLOG_LINE.match(line)
        if not m:
            continue
        t_acc = float(m.group(1))
        raw = from_hex(m.group(4))
        if m.group(2) == "C":
            pending_cmd = (t_acc, to_apdu(raw))
            continue
        if pending_cmd is None:
            continue   # R huérfana: sin su C, se descarta
        t_cmd, cmd = pending_cmd
        pending_cmd = None
        data, sw1, sw2 = raw[:-2], raw[-2], raw[-1]
        t_ms = max(t_acc - t_prev, 0.0)
        t_prev = t_acc
        exchanges.append(LogExchange(cmd, Response(data, sw1, sw2), t_ms))
    return exchanges


# ---------------------------------------------------------------------------
# Criptogramas
# ---------------------------------------------------------------------------
def _amount_from_pdol(session: LogSession) -> str | None:
    """Importe (9F02) best-effort: localiza el PDOL (9F38) de las respuestas
    del SELECT, lo parte con `tlv.parse_dol` y mapea los valores crudos del
    GPO (template 83) a sus tags; devuelve el 9F02 si consta."""
    dol: list[tuple[str, int]] = []
    for ex in session.exchanges:
        if not ex.response.data:
            continue
        try:
            node = tlv.parse(ex.response.data).find("9F38")
        except Exception:
            node = None
        if node is not None and node.value:
            dol = tlv.parse_dol(node.value)
            break
    if not dol:
        return None
    for ex in session.exchanges:
        if ex.command.ins != INS_GET_PROCESSING_OPTIONS or not ex.command.data:
            continue
        data = ex.command.data
        try:  # el payload del GPO va envuelto en el template 83
            nodes = tlv.parse(data)
            if nodes and nodes[0].tag == "83":
                data = bytes(nodes[0].value)
        except Exception:
            pass
        off = 0
        for tag, ln in dol:
            if off + ln > len(data):
                break
            if tag == "9F02" and ln:
                return to_hex(data[off:off + ln]).lstrip("0") or "0"
            off += ln
    return None


def extract_cryptograms(session: LogSession) -> list[dict]:
    """Extrae los tags criptográficos (9F26 AC, 9F27 CID, 9F36 ATC, 9F10 IAD,
    9F37 UN) de las respuestas de la sesión, con contexto: índice de intercambio,
    INS del comando que los produjo y —best-effort vía PDOL— importe (9F02)."""
    amount = _amount_from_pdol(session)

    out: list[dict] = []
    for seq, ex in enumerate(session.exchanges):
        if not ex.response.data:
            continue
        try:
            nodes = tlv.parse(ex.response.data)
        except Exception:
            continue
        for tag, name in CRYPTO_TAGS.items():
            for node in nodes.find_all(tag):
                rec = {"sid": session.sid, "seq": seq, "tag": tag, "name": name,
                       "value": to_hex(node.value), "ins": f"{ex.command.ins:02X}"}
                if amount is not None:
                    rec["amount"] = amount
                out.append(rec)
    return out


# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------
def replay_plan(session: LogSession) -> list[APDU]:
    """Comandos a reenviar para reproducir la sesión contra una tarjeta.

    Se reenvía **todo** el comando tal cual se grabó: al vivir la grabación en
    el `Transceiver` lógico, aquí no hay GET RESPONSE (INS 0xC0) ni reintentos
    6Cxx que filtrar — 1 intercambio grabado = 1 comando lógico.
    """
    return [ex.command for ex in session.exchanges]


# ---------------------------------------------------------------------------
# Conversión entre formatos
# ---------------------------------------------------------------------------
def convert(text: str, from_fmt: str, to_fmt: str) -> str:
    """Convierte entre `hexlog` y `session-json` (offline, sin tarjeta).

    `session-json` acepta tanto un objeto de sesión como una lista de sesiones;
    en hexlog ambas se concatenan. hexlog → session-json produce la lista de
    sesiones detectadas con `split_sessions`.
    """
    if from_fmt == to_fmt:
        return text
    if from_fmt == "hexlog":
        events = parse_hexlog(text)
        sessions = split_sessions(events)
        return json.dumps([session_to_dict(s) for s in sessions],
                          indent=2, ensure_ascii=False)
    if from_fmt == "session-json":
        raw = json.loads(text)
        docs = raw if isinstance(raw, list) else [raw]
        return "".join(to_hexlog(session_from_dict(d)) for d in docs)
    raise ValueError(f"formato origen desconocido: {from_fmt!r} (usa hexlog|session-json)")


def detect_format(text: str) -> str:
    """Autodetección best-effort por el primer carácter significativo:
    `{`/`[` → session-json; en otro caso hexlog."""
    stripped = text.lstrip()
    if stripped.startswith(("{", "[")):
        return "session-json"
    return "hexlog"
