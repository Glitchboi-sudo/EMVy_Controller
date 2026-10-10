"""Tests del recorder: middleware de grabación, persistencia en el proyecto
(sessions/*.json, sessions.hexlog, cryptograms.jsonl) y modo sin proyecto."""
import json

import pytest

from emvy.core import sessionlog as sl
from emvy.core.apdu import get_data, get_processing_options, read_record, select
from emvy.core.hexutil import from_hex
from emvy.project import store
from emvy.session.recorder import (SessionRecorder, list_sessions, load_session,
                                   replay_session)

from fakecard import AID, build_fake_card


@pytest.fixture
def xdg(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    return tmp_path


def _run_flow(send):
    cmds = [
        select(b"2PAY.SYS.DDF01"),
        select(from_hex(AID)),
        get_processing_options(from_hex("11223344000000000050")),
        read_record(1, 1),
        get_data(0x9F36),
    ]
    return [send(c) for c in cmds]


def test_wrap_graba_intercambios_y_mantiene_respuesta():
    send, state = build_fake_card()
    rec = SessionRecorder(None, reader="fake")
    wrapped = rec.wrap(send)
    resp = wrapped(select(from_hex(AID)))
    assert resp.sw == 0x9000                       # la respuesta se delega intacta
    assert len(rec.exchanges()) == 1
    ex = rec.exchanges()[0]
    assert ex.command.ins == 0xA4 and ex.response.sw == 0x9000
    assert rec.exchanges()[0].t_ms >= 0.0


def test_save_all_con_proyecto_escribe_los_tres_ficheros(xdg):
    proj = store.create_project("lab")
    rec = SessionRecorder(proj, reader="fake")
    rec.set_atr(from_hex("3B8F8001805A0A010203"))
    _run_flow(rec.wrap(build_fake_card()[0]))

    paths = rec.save_all()
    assert paths
    sdir = proj.path / "sessions"
    assert (sdir / "sessions.hexlog").exists()
    assert (sdir / "cryptograms.jsonl").exists()   # el GET DATA 9F36 da un criptograma

    sessions_files = list_sessions(proj)
    assert len(sessions_files) == 2                # PPSE + flujo AID
    s = max((load_session(p) for p in sessions_files), key=lambda x: len(x.exchanges))
    assert s.reader == "fake" and s.atr == "3B8F8001805A0A010203"
    assert len(s.exchanges) == 4

    # el hexlog acumulado contiene ambas sesiones
    hexlog = (sdir / "sessions.hexlog").read_text()
    assert hexlog.count("# session") == 2

    # cryptograms.jsonl: líneas JSON con tag y contexto
    lines = [json.loads(l) for l in
             (sdir / "cryptograms.jsonl").read_text().splitlines()]
    assert any(r["tag"] == "9F36" and r["ins"] == "CA" for r in lines)

    # save_all es idempotente: no duplica en una segunda llamada
    assert rec.save_all() == []
    assert len(list_sessions(proj)) == 2


def test_sin_proyecto_no_escribe_y_expone_pending(xdg, tmp_path):
    rec = SessionRecorder(None, reader="fake")
    _run_flow(rec.wrap(build_fake_card()[0]))
    assert rec.save_all() == []
    assert len(rec.pending) == 2                   # datos conservados en memoria
    assert rec.pending[0].reader == "fake"
    assert not (tmp_path / "data").exists() or not list(
        (tmp_path / "data").rglob("sessions.hexlog"))


def test_list_sessions_mas_reciente_primero(xdg):
    proj = store.create_project("lab")
    rec = SessionRecorder(proj)
    _run_flow(rec.wrap(build_fake_card()[0]))
    rec.save_all()
    paths = list_sessions(proj)
    assert len(paths) == 2
    mtimes = [p.stat().st_mtime for p in paths]
    assert mtimes == sorted(mtimes, reverse=True)


def test_replay_session_recoge_nuevas_respuestas():
    send, _ = build_fake_card()
    rec = SessionRecorder(None)
    _run_flow(rec.wrap(send))
    s = rec.sessions()[-1]
    new = replay_session(s, build_fake_card()[0])
    assert len(new) == len(s.exchanges)
    assert all(n.response.sw == o.response.sw for n, o in zip(new, s.exchanges))
