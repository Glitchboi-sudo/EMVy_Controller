"""Tests del adaptador de bombercat-tools (vendorizado).

Las partes offline (parseo/ubicación) siempre corren; las que ejecutan el
framework por subprocess se saltan si su venv no está listo (para no requerir
red ni bootstrap en CI)."""
import pytest

from emvy import config
from emvy.integrations import bombercat_tools as bt

_HAS_VENDOR = (config.bombercat_tools_dir() / "bombercat.py").exists()
pytestmark = pytest.mark.skipif(not _HAS_VENDOR, reason="bombercat-tools no vendorizado")


def test_locate():
    root = bt.locate()
    assert (root / "bombercat.py").exists()


def test_version():
    v = bt.version()
    assert v and v[0].isdigit()


def test_extract_json_from_noisy_output():
    text = (
        "╰─ banner rich ─╯\n"
        'ID  Port\n'
        '{"uid": "04A1B2C3", "protocol": "ISODEP"}\n'
        "ℹ hint line\n"
    )
    objs = bt._extract_json(text)
    assert objs == [{"uid": "04A1B2C3", "protocol": "ISODEP"}]


def test_extract_json_whole_document():
    assert bt._extract_json('{"a": 1}') == [{"a": 1}]


def test_extract_json_none():
    assert bt._extract_json("solo texto, sin json") == []


@pytest.mark.skipif(not bt.venv_ready() if _HAS_VENDOR else True,
                    reason="venv de bombercat-tools no está listo")
def test_run_capture_help():
    cp = bt.run_capture(["--help"], timeout=60)
    assert cp.returncode == 0
    assert "flash" in cp.stdout and "relay" in cp.stdout


# ---------------------------------------------------------------------------
# Parseo puro de tablas rich (status / relay) — sin hardware ni subprocess
# ---------------------------------------------------------------------------
_STATUS_TABLE = (
    "         BomberCat status          \n"
    "┏━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━┓\n"
    "│ name         │ NFCGate          │\n"
    "│ version      │ 0.9.7            │\n"
    "│ detected     │ yes              │\n"
    "│ capabilities │ relay, config,   │\n"
    "│              │ capture          │\n"
    "└──────────────┴──────────────────┘\n"
)


def test_parse_status():
    st = bt.parse_status(_STATUS_TABLE)
    assert st["name"] == "NFCGate"
    assert st["version"] == "0.9.7"
    assert st["detected"] == "yes"
    # 'capture' viene de la continuación de celda multilínea
    assert st["capabilities"] == ["relay", "config", "capture"]


def test_parse_status_empty_caps():
    text = "│ name │ DetectTags │\n│ capabilities │ — │\n"
    st = bt.parse_status(text)
    assert st["name"] == "DetectTags" and st["capabilities"] == []


def test_image_for_capability():
    assert bt.image_for_capability("mifare") == "MifareClassic"
    assert bt.image_for_capability("relay") == "NFCGate"
    with pytest.raises(bt.BombercatToolsError):
        bt.image_for_capability("nope")


def test_parse_relay_config_and_status():
    cfg = bt.parse_relay_config(
        "│ fw │ nfcgate │\n│ role │ reader │\n│ ssid │ lab │\n"
        "│ server │ 10.0.0.5 │\n│ port │ 5566 │\n│ session │ 3 │\n│ state │ idle │\n")
    assert cfg["role"] == "reader" and cfg["server"] == "10.0.0.5" and cfg["session"] == "3"
    stt = bt.parse_relay_status(
        "│ state │ relaying │\n│ link connected │ yes │\n"
        "│ peer present │ no │\n│ APDU pairs relayed │ 12 │\n")
    assert stt["state"] == "relaying" and stt["link_connected"] is True
    assert stt["peer_present"] is False and stt["relayed"] == "12"


# ---------------------------------------------------------------------------
# Construcción de argumentos (monkeypatch run_capture/run_json; sin subprocess)
# ---------------------------------------------------------------------------
def test_magspoof_card_add_omits_empty_tracks(monkeypatch):
    seen = {}
    monkeypatch.setattr(bt, "run_capture", lambda args, **kw: seen.setdefault("args", args))
    bt.magspoof_card_add("mycard", t1=None, t2="; 4111 ?", port="/dev/ttyACM0")
    assert seen["args"] == ["magspoof", "card", "add", "mycard",
                            "--t2", "; 4111 ?", "-p", "/dev/ttyACM0"]


def test_magspoof_card_list_jsonl_empty_ok(monkeypatch):
    class _CP:
        stdout = ""            # store vacío: salida sin JSON es válida (lista vacía)
    monkeypatch.setattr(bt, "run_capture", lambda args, **kw: _CP())
    assert bt.magspoof_card_list() == []


def test_mifare_restore_args(monkeypatch):
    seen = {}
    monkeypatch.setattr(bt, "run_capture", lambda args, **kw: seen.setdefault("args", args))
    bt.mifare_restore("/tmp/d.json", write_block0=True)
    assert seen["args"][:5] == ["tags", "mifare", "restore", "--dump", "/tmp/d.json"]
    assert "--yes" in seen["args"] and "--write-block0" in seen["args"]


def test_capture_run_times_out_and_stops(monkeypatch):
    import subprocess
    calls = {"stop": 0}

    def _raise_timeout(args, **kw):
        raise subprocess.TimeoutExpired(cmd=args, timeout=kw.get("timeout", 0))

    monkeypatch.setattr(bt, "run_capture", _raise_timeout)
    monkeypatch.setattr(bt, "capture_stop",
                        lambda **kw: calls.__setitem__("stop", calls["stop"] + 1))
    cp, timed_out = bt.capture_run("/tmp/x.pcap", duration=0.01)
    assert timed_out is True and calls["stop"] == 1
