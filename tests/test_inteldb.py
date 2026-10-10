"""Tests de la intel DB del proyecto (SQLite WAL en <proyecto>/intel.db)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import pytest  # noqa: E402

from fakecard import build_fake_card  # noqa: E402

from emvy.core import fingerprint  # noqa: E402
from emvy.project import store  # noqa: E402
from emvy.project.inteldb import IntelDB, intel_db_path  # noqa: E402
from emvy.session.capture import capture_card  # noqa: E402


@pytest.fixture
def xdg(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    return tmp_path


@pytest.fixture
def perfil():
    send, _ = build_fake_card()
    return fingerprint.profile_from_dump(capture_card(send, profile={}))


def test_db_creacion_lazy(xdg, perfil):
    p = store.create_project("lab")
    db_path = intel_db_path(p)
    assert not db_path.exists()          # no se crea al crear el proyecto
    with IntelDB(p) as db:
        assert db_path.exists()          # creación lazy al abrirla
        row = db.upsert_card(perfil)
    assert row.times_seen == 1
    assert row.hash == perfil.hash
    # WAL: se genera el fichero -wal en algún momento de la vida de la conexión
    with IntelDB(p) as db:
        assert db.list_cards()[0].hash == perfil.hash


def test_upsert_dos_veces(xdg, perfil):
    p = store.create_project("lab")
    with IntelDB(p) as db:
        db.upsert_card(perfil)
        row = db.upsert_card(perfil)
        assert row.times_seen == 2
        assert row.first_seen <= row.last_seen
        # el perfil persistido se reconstruye igual
        assert row.profile.hash == perfil.hash
        assert row.profile.aip == perfil.aip


def test_notas_preservadas(xdg, perfil):
    p = store.create_project("lab")
    with IntelDB(p) as db:
        db.upsert_card(perfil, note="tarjeta del lab A")
        row = db.upsert_card(perfil)          # sin nota: se preserva
        assert row.notes == "tarjeta del lab A"
        db.set_note(perfil.hash, "reescrita")
        assert db.get_card(perfil.hash).notes == "reescrita"
        # find_card por prefijo
        assert db.find_card(perfil.hash[:10]).hash == perfil.hash


def test_outcomes_crud_y_validacion(xdg, perfil):
    p = store.create_project("lab")
    with IntelDB(p) as db:
        db.upsert_card(perfil)
        oid = db.add_outcome(perfil.hash, "attack-1", "partial",
                             notes="casi", config={"a": 1})
        assert isinstance(oid, int)
        rows = db.outcomes_for(perfil.hash)
        assert len(rows) == 1
        assert rows[0].attack_id == "ATTACK-1"     # normalizado a mayúsculas
        assert rows[0].result == "partial"
        assert rows[0].config == {"a": 1}
        with pytest.raises(ValueError):
            db.add_outcome(perfil.hash, "NO-EXISTE", "success")
        with pytest.raises(ValueError):
            db.add_outcome(perfil.hash, "ATTACK-1", "quizás")


def test_recommend_for_integrado(xdg, perfil):
    p = store.create_project("lab")
    with IntelDB(p) as db:
        db.upsert_card(perfil)
        db.add_outcome(perfil.hash, "ATTACK-1", "partial")
        recs = db.recommend_for(perfil.hash)
        assert recs and recs[0].attack_id == "ATTACK-1"
        assert recs[0].tried is not None
        # hash desconocido → sin recomendaciones
        assert db.recommend_for("00" * 32) == []


def test_patterns_integrado(xdg, perfil):
    p = store.create_project("lab")
    with IntelDB(p) as db:
        db.upsert_card(perfil)
        assert db.patterns() == []                # sin outcomes no hay patrones
        db.add_outcome(perfil.hash, "ATTACK-7", "blocked")
        # una segunda tarjeta distinta (mismo perfil mutado en AIP)
        send, _ = build_fake_card()
        dump = capture_card(send, profile={})
        dump.applications[0]["aip"] = "7C00"
        dump.blobs = [b for b in dump.blobs if not b["source"].endswith(":FCI")]
        perfil2 = fingerprint.profile_from_dump(dump)
        assert perfil2.hash != perfil.hash
        db.upsert_card(perfil2)
        db.add_outcome(perfil2.hash, "ATTACK-7", "blocked")
        lines = db.patterns()
        assert any("ATTACK-7 → blocked" in l and "2 tarjetas" in l for l in lines)


def test_profile_json_es_dict_completo(xdg, perfil):
    p = store.create_project("lab")
    with IntelDB(p) as db:
        db.upsert_card(perfil)
    import sqlite3
    conn = sqlite3.connect(intel_db_path(p))
    raw = json.loads(conn.execute("SELECT profile_json FROM cards").fetchone()[0])
    conn.close()
    assert raw["hash"] == perfil.hash
    assert "aip" in raw and "pdol" in raw and "cvm_rules" in raw
