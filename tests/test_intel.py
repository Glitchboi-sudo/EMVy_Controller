"""Tests puros del recomendador y los patrones cross-card (core.intel)."""
from emvy.core import intel
from emvy.core.fingerprint import CardProfile


def _profile(**kw) -> CardProfile:
    """Perfil mínimo parametrizable (defaults: tarjeta 'rica' en superficie)."""
    base = dict(
        aid="A0000000041010", aids=("A0000000041010",), scheme="Mastercard",
        label="LAB", aip="3980",
        aip_flags=("SDA soportado", "DDA soportado", "Verificación de titular (CVM) soportada",
                   "CDA soportado"),
        afl=((1, 1, 2, 0),),
        pdol=(("9F02", 6), ("9F66", 4)),
        cdol1=(("9F02", 6), ("5F2A", 2)),
        cdol2=(),
        cvm_rules=(("Sin CVM requerido", "Siempre", False),
                   ("PIN en claro verificado por el ICC (offline)", "Siempre", True)),
        crypto={"ca_index": "05", "issuer_key_bits": 2048,
                "sda_ready": True, "dda_ready": True, "methods": ["SDA", "DDA", "CDA"]},
        service_code="201",
        tag_inventory=("82", "8C", "8E", "90", "94", "9F0E", "9F36", "9F38", "9F46"),
        app_count=1,
    )
    base.update(kw)
    return CardProfile(**base)


# -- catálogo -----------------------------------------------------------------
def test_catalogo_ids_unicos_y_completos():
    ids = [a["id"] for a in intel.KNOWN_ATTACKS]
    assert ids == [f"ATTACK-{i}" for i in range(1, 12)]
    assert len(ids) == len(set(ids))
    for a in intel.KNOWN_ATTACKS:
        assert a["title"] and a["description"] and a["reason"]
        assert callable(a["conditions"])
        assert set(a) >= {"id", "title", "description", "conditions", "reason"}


def test_catalogo_referencias_combo_validas():
    from emvy.core.playbooks import get_playbook
    for a in intel.KNOWN_ATTACKS:
        if a.get("combo"):
            assert get_playbook(a["combo"]) is not None, a["id"]


# -- recomendador --------------------------------------------------------------
def test_recommend_partial_primero():
    p = _profile()
    outcomes = [intel.AttackOutcome("ATTACK-9", "partial")]
    recs = intel.recommend(p, outcomes)
    assert recs[0].attack_id == "ATTACK-9"
    assert recs[0].tried is not None and recs[0].tried.result == "partial"
    assert "parcial" in recs[0].reason


def test_recommend_condiciones_del_perfil():
    # perfil con PDOL 9F02/9F66 + DDA/CDA + CVM + CDOL → esos ataques casan
    recs = intel.recommend(_profile(), [], limit=11)
    ids = [r.attack_id for r in recs]
    assert "ATTACK-1" in ids and "ATTACK-2" in ids
    assert "ATTACK-3" in ids and "ATTACK-4" in ids and "ATTACK-8" in ids
    # los 6 primeros son los que casan con el perfil (antes que el relleno)
    assert [r.attack_id for r in intel.recommend(_profile(), [])] == \
        ["ATTACK-1", "ATTACK-2", "ATTACK-3", "ATTACK-4", "ATTACK-5"]
    # razón del match (no el relleno canónico)
    by_id = {r.attack_id: r for r in recs}
    assert "PDOL" in by_id["ATTACK-1"].reason
    # perfil vacío: ninguno casa por condiciones → solo relleno canónico
    vacio = _profile(aip_flags=(), afl=(), pdol=(), cdol1=(), cdol2=(),
                     cvm_rules=(), service_code="", tag_inventory=(),
                     crypto={"sda_ready": False, "dda_ready": False})
    recs_vacio = intel.recommend(vacio, [])
    assert all(r.reason == "sin probar aún" for r in recs_vacio)


def test_recommend_requires_relay_anotado():
    recs = intel.recommend(_profile(), [], limit=11)
    by_id = {r.attack_id: r for r in recs}
    assert by_id["ATTACK-11"].requires_relay is True
    assert by_id["ATTACK-1"].requires_relay is False


def test_recommend_limit():
    assert len(intel.recommend(_profile(), [], limit=3)) == 3
    assert len(intel.recommend(_profile(), [])) == 5


def test_recommend_no_repite_cerrados():
    # success y failed no se recomiendan; partial sí (reintento)
    outcomes = [intel.AttackOutcome("ATTACK-1", "success"),
                intel.AttackOutcome("ATTACK-2", "failed"),
                intel.AttackOutcome("ATTACK-3", "partial")]
    ids = [r.attack_id for r in intel.recommend(_profile(), outcomes, limit=11)]
    assert "ATTACK-1" not in ids and "ATTACK-2" not in ids
    assert ids[0] == "ATTACK-3"


def test_recommend_combo_prerequisitos():
    # ATTACK-1 con éxito → se sugiere una pieza restante de COMBO-C (ATTACK-6 u 8)
    outcomes = [intel.AttackOutcome("ATTACK-1", "success")]
    recs = intel.recommend(_profile(), outcomes)
    by_id = {r.attack_id: r for r in recs}
    assert "ATTACK-6" in by_id or "ATTACK-8" in by_id
    elegido = by_id.get("ATTACK-6") or by_id.get("ATTACK-8")
    assert "COMBO-C" in elegido.reason


# -- patrones cross-card --------------------------------------------------------
def test_cross_card_patterns():
    rows = [
        {"attack_id": "ATTACK-7", "result": "blocked", "hash": "aa"},
        {"attack_id": "ATTACK-7", "result": "blocked", "hash": "aa"},
        {"attack_id": "ATTACK-7", "result": "blocked", "hash": "bb"},
        {"attack_id": "ATTACK-1", "result": "success", "hash": "aa"},
        {"attack_id": "ATTACK-1", "result": "success", "hash": "bb"},
        {"attack_id": "ATTACK-2", "result": "failed", "hash": "aa"},  # 1 sola tarjeta
    ]
    lines = intel.cross_card_patterns(rows)
    assert any("ATTACK-7 → blocked" in l and "2 tarjetas" in l for l in lines)
    assert any("ATTACK-1 → success" in l for l in lines)
    assert not any("ATTACK-2" in l for l in lines)
    # orden: más tarjetas primero
    assert lines[0].startswith("ATTACK-7")


def test_cross_card_patterns_vacio():
    assert intel.cross_card_patterns([]) == []
    assert intel.cross_card_patterns([{"attack_id": "A", "result": "x", "hash": "h"}]) == []
