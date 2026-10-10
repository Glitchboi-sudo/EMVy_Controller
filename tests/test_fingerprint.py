"""Tests del fingerprinting normalizado (núcleo puro, offline).

Cubre la estabilidad del hash (mismo dump → mismo hash; volátiles excluidos),
la sensibilidad a cambios estructurales (AIP), la serialización y el perfil
completo sobre la tarjeta simulada (`fakecard`)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from fakecard import AID, build_fake_card  # noqa: E402

from emvy.core import fingerprint  # noqa: E402
from emvy.session.capture import capture_card  # noqa: E402
from emvy.session.model import CardDump  # noqa: E402


def _dump_con_cvm(aip="2000", atc="0031", pin_retry="03"):
    """Dump mínimo con CVM List; el AIP viene del campo `aip` de la app (el tag
    82 no viaja embebido en los registros, como en las capturas reales)."""
    rec = "700E" + "8E0C" + "00000000000000001F000103" + "9F3602" + atc
    return CardDump(applications=[{
        "aid": AID, "scheme": "Mastercard", "source": "ppse", "label": "LAB",
        "aip": aip, "afl": "08010100",
        "records": [{"sfi": 1, "record": 1, "hex": rec}],
        "get_data": {"9F36": atc, "9F17": pin_retry},
    }], blobs=[])


def _perfil(dump):
    p = fingerprint.profile_from_dump(dump)
    assert p is not None
    return p


# -- estabilidad y sensibilidad del hash -------------------------------------
def test_mismo_dump_mismo_hash():
    p1 = _perfil(_dump_con_cvm())
    p2 = _perfil(_dump_con_cvm())
    assert p1.hash == p2.hash


def test_datos_volatiles_no_cambian_el_hash():
    d1 = _dump_con_cvm(atc="0031", pin_retry="03")
    d2 = _dump_con_cvm(atc="00FF", pin_retry="01")
    assert _perfil(d1).hash == _perfil(d2).hash
    # los volátiles sí se exponen como informativos
    assert _perfil(d2).atc and _perfil(d2).pin_retry


def test_cambio_aip_cambia_el_hash():
    p1 = _perfil(_dump_con_cvm(aip="2000"))
    p2 = _perfil(_dump_con_cvm(aip="7C00"))
    assert p1.hash != p2.hash


def test_hash_es_sha256_hex_determinista():
    p = _perfil(_dump_con_cvm())
    assert len(p.hash) == 64
    assert all(ch in "0123456789abcdef" for ch in p.hash)
    assert p.hash == fingerprint.fingerprint_hash(p)


# -- serialización ------------------------------------------------------------
def test_dict_roundtrip():
    p = _perfil(_dump_con_cvm())
    d = fingerprint.profile_to_dict(p)
    p2 = fingerprint.profile_from_dict(d)
    assert p2 == p
    assert p2.hash == p.hash
    # sin hash en el dict también se recalcula igual
    d.pop("hash")
    assert fingerprint.profile_from_dict(d).hash == p.hash


def test_summary_lines_no_vacio():
    lines = fingerprint.summary_lines(_perfil(_dump_con_cvm()))
    assert lines and any("Hash" in l for l in lines)
    assert any("CVM" in l for l in lines)


# -- perfil completo sobre la tarjeta simulada --------------------------------
def test_perfil_fake_card_completo():
    send, _state = build_fake_card()
    dump = capture_card(send, profile={})
    p = fingerprint.profile_from_dump(dump)
    assert p is not None
    assert p.aid == AID
    assert p.aip == "1980"                       # AIP del GPO (tag 80) del fake
    assert any("CDA" in f for f in p.aip_flags)
    assert ("9F37", 4) in p.pdol and ("9F02", 6) in p.pdol
    assert p.afl and p.afl[0][0] == 1            # SFI 1 en el AFL
    assert p.service_code == "201"               # desde el Track 2
    assert p.atc                                 # GET DATA 9F36
    assert len(p.tag_inventory) >= 5
    assert "9F36" not in p.tag_inventory         # volátil excluido
    assert "9F37" not in p.tag_inventory
    assert p.app_count == 1
    assert p.hash == fingerprint.profile_from_dump(dump).hash


def test_perfil_dump_sin_apps_devuelve_none():
    assert fingerprint.profile_from_dump(CardDump()) is None
