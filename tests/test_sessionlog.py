"""Tests del núcleo de logging estructurado de sesiones (sessionlog).

Cobertura: round-trip JSON y hexlog, detección de sesión (SELECT AID abre,
GENERATE AC cierra, timeout cierra), extracción de criptogramas, plan/ejecución
de replay contra la tarjeta falsa y conversión entre formatos.
"""
import json

from emvy.core import sessionlog as sl
from emvy.core.apdu import APDU, Response, get_data, get_processing_options, read_record, select
from emvy.core.hexutil import from_hex
from emvy.core import tlv
from emvy.session.recorder import replay_session

from fakecard import AID, build_fake_card

AID_BYTES = from_hex(AID)


def _flow_exchanges(send):
    """Flujo EMV corto contra la fakecard → lista de LogExchange."""
    cmds = [
        select(b"2PAY.SYS.DDF01"),                       # SELECT PPSE
        select(AID_BYTES),                               # SELECT AID → nueva sesión
        get_processing_options(from_hex("11223344000000000050")),
        read_record(1, 1),
        get_data(0x9F36),
        APDU(0x80, 0xAE, 0x00, 0x00, bytes(20), le=0),   # GENERATE AC (la fakecard da 6A82)
    ]
    out = []
    for i, cmd in enumerate(cmds):
        out.append(sl.LogExchange(cmd, send(cmd), t_ms=10.0 * (i + 1)))
    return out


def _split(events, **kw):
    sids = iter(f"sid{i:04d}" for i in range(100))
    nows = iter([f"2026-10-07T10:{i:02d}:00+00:00" for i in range(100)])
    kw.setdefault("sid_factory", lambda: next(sids))
    kw.setdefault("now", lambda: next(nows))
    return sl.split_sessions(events, **kw)


# --- detección de sesión -----------------------------------------------------
def test_split_sessions_select_aid_opens_and_generate_ac_closes():
    send, _ = build_fake_card()
    sessions = _split(_flow_exchanges(send))
    # PPSE solo (la tarjeta responde al PPSE) y luego el flujo AID…GENERATE AC
    assert len(sessions) == 2
    assert len(sessions[0].exchanges) == 1               # solo SELECT PPSE
    assert sessions[0].closed is not None
    assert len(sessions[1].exchanges) == 5
    assert sessions[1].exchanges[-1].command.ins == 0xAE  # GEN AC incluido
    assert sessions[1].closed is not None               # cerrada por GEN AC


def test_split_sessions_timeout_closes():
    send, _ = build_fake_card()
    events = _flow_exchanges(send)
    # gap > 30 s tras el SELECT AID → cierra la sesión anterior
    events[2] = sl.LogExchange(events[2].command, events[2].response, 120_000.0)
    sessions = _split(events)
    # [PPSE] [SELECT AID] [resto con GEN AC]
    assert len(sessions) == 3
    assert all(s.exchanges for s in sessions)


def test_split_sessions_trailing_is_open():
    send, _ = build_fake_card()
    events = _flow_exchanges(send)[:-1]                   # sin GENERATE AC final
    sessions = _split(events)
    assert sessions[-1].closed is None


# --- round-trips -------------------------------------------------------------
def test_session_json_roundtrip():
    send, _ = build_fake_card()
    s = _split(_flow_exchanges(send))[1]
    assert sl.session_from_json(sl.session_to_json(s)) == s


def test_hexlog_roundtrip():
    send, _ = build_fake_card()
    s = _split(_flow_exchanges(send))[1]
    text = sl.to_hexlog(s)
    assert f"# session {s.sid[:8]}" in text
    events = sl.parse_hexlog(text)
    assert len(events) == len(s.exchanges)
    for new, old in zip(events, s.exchanges):
        assert new.command.to_bytes() == old.command.to_bytes()
        assert new.response == old.response


def test_parse_hexlog_ignores_garbage_and_orphans():
    text = ("# comentario\n"
            "00010  R  [abcd1234]  90 00\n"                # R huérfana
            "línea basura\n"
            "00010  C  [abcd1234]  00 A4 04 00 07 A0 00 00 00 04 10 10 00\n"
            "00020  R  [abcd1234]  6A 82\n")
    events = sl.parse_hexlog(text)
    assert len(events) == 1
    assert events[0].command.ins == 0xA4
    assert events[0].response.sw == 0x6A82


# --- criptogramas ------------------------------------------------------------
def test_extract_cryptograms_from_get_data_and_genac():
    send, _ = build_fake_card()
    events = _flow_exchanges(send)
    # GENERATE AC con respuesta 77 real (9F26/9F27/9F36)
    ga = events[-1]
    ga_resp = tlv.encode([
        tlv.TLV("77", b"", [
            tlv.tlv("9F26", from_hex("1122334455667788")),
            tlv.tlv("9F27", b"\x80"),
            tlv.tlv("9F36", from_hex("0007")),
        ], constructed=True),
    ])
    events[-1] = sl.LogExchange(ga.command, Response(ga_resp, 0x90, 0x00), ga.t_ms)
    s = _split(events)[1]

    recs = sl.extract_cryptograms(s)
    by_tag = {r["tag"]: r for r in recs}
    assert by_tag["9F26"]["value"] == "1122334455667788"
    assert by_tag["9F36"]["value"] == "0007"              # también el del GET DATA
    assert by_tag["9F27"]["ins"] == "AE"                  # contexto: comando INS
    # importe best-effort del PDOL del GPO (9F02 = últimos 6 bytes del payload)
    assert "amount" in by_tag["9F26"]


# --- replay ------------------------------------------------------------------
def test_replay_plan_reenvia_todo_sin_get_response():
    send, _ = build_fake_card()
    s = _split(_flow_exchanges(send))[1]
    plan = sl.replay_plan(s)
    assert plan == [ex.command for ex in s.exchanges]
    assert all(c.ins != 0xC0 for c in plan)               # sin GET RESPONSE


def test_replay_session_contra_fakecard():
    send, _ = build_fake_card()
    s = _split(_flow_exchanges(send))[1]
    send2, _ = build_fake_card()
    seen = []
    new = replay_session(s, send2, on_exchange=seen.append)
    assert len(new) == len(s.exchanges) == len(seen)
    for old, replayed in zip(s.exchanges, new):
        assert replayed.command == old.command            # reenvía el comando original
        assert replayed.response.sw == old.response.sw    # la fakecard responde igual
        assert replayed.response.data == old.response.data


# --- conversión --------------------------------------------------------------
def test_convert_json_to_hexlog_and_back():
    send, _ = build_fake_card()
    s = _split(_flow_exchanges(send))[1]
    json_text = sl.session_to_json(s)
    hexlog_text = sl.convert(json_text, "session-json", "hexlog")
    assert "# session" in hexlog_text
    back = sl.convert(hexlog_text, "hexlog", "session-json")
    sessions = [sl.session_from_dict(d) for d in json.loads(back)]
    # una sesión-json → una sesión al re-detectar (SELECT AID … GENERATE AC)
    assert len(sessions) == 1
    assert sessions[0].exchanges == s.exchanges


def test_convert_lista_de_sesiones_a_hexlog():
    send, _ = build_fake_card()
    sessions = _split(_flow_exchanges(send))
    text = sl.convert(json.dumps([sl.session_to_dict(s) for s in sessions]),
                      "session-json", "hexlog")
    assert text.count("# session") == 2


def test_detect_format():
    assert sl.detect_format('{"sid": "x"}') == "session-json"
    assert sl.detect_format("  # session\n00010  C  [a]  00 A4") == "hexlog"
