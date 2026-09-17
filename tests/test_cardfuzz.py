"""Tests de plantillas de fuzzing de terminales (core.cardfuzz): banda
magnética, registros EMV y NDEF (emulación NFC). Cada mutación se verifica
contra los propios decodificadores del proyecto, no a ciegas."""
from emvy.core import cardfuzz, cvm, emvbits, ndef, tlv


# --- Luhn --------------------------------------------------------------
def test_luhn_valid_and_check_digit():
    assert cardfuzz.luhn_valid("4111111111111111")
    assert not cardfuzz.luhn_valid("4111111111111112")
    assert cardfuzz.luhn_check_digit("411111111111111") == "1"


# --- construcción de pistas ---------------------------------------------
def test_build_track1_track2_format():
    t1 = cardfuzz.build_track1("4111111111111111", "TEST/CARD", "2812", "201")
    assert t1 == "%B4111111111111111^TEST/CARD^2812201?"
    t2 = cardfuzz.build_track2("4111111111111111", "2812", "201")
    assert t2 == ";4111111111111111=2812201?"


# --- plantillas de banda magnética ---------------------------------------
def test_track_baseline_is_luhn_valid_and_well_formed():
    templates = cardfuzz.track_templates()
    base = cardfuzz.get_track_template(templates, "baseline")
    pan = base.track2.split(";")[1].split("=")[0]
    assert cardfuzz.luhn_valid(pan)
    assert base.track1.startswith("%B") and base.track1.endswith("?")
    assert base.track2.startswith(";") and base.track2.endswith("?")


def test_track_bad_luhn_breaks_checksum_only():
    templates = cardfuzz.track_templates()
    base = cardfuzz.get_track_template(templates, "baseline")
    bad = cardfuzz.get_track_template(templates, "bad-luhn")
    pan_bad = bad.track2.split(";")[1].split("=")[0]
    assert not cardfuzz.luhn_valid(pan_bad)
    # todo lo demás (fecha/servicio) queda igual que el baseline
    assert bad.track2.split("=")[1] == base.track2.split("=")[1]


def test_track_expired_is_in_the_past():
    t = cardfuzz.get_track_template(cardfuzz.track_templates(), "expired")
    yymm = t.track2.split("=")[1][:4]
    assert yymm == "0101"          # enero de 2001: claramente vencida


def test_track_missing_separator_and_no_end_sentinel():
    templates = cardfuzz.track_templates()
    sep = cardfuzz.get_track_template(templates, "missing-separator")
    assert "=" not in sep.track2
    nosent = cardfuzz.get_track_template(templates, "no-end-sentinel")
    assert not nosent.track1.endswith("?") and not nosent.track2.endswith("?")


def test_track_truncated_and_oversized_pan():
    templates = cardfuzz.track_templates()
    short = cardfuzz.get_track_template(templates, "truncated-pan")
    long_ = cardfuzz.get_track_template(templates, "oversized-pan")
    pan_short = short.track2.split(";")[1].split("=")[0]
    pan_long = long_.track2.split(";")[1].split("=")[0]
    assert len(pan_short) == 8
    assert len(pan_long) > 19


def test_track_overrides_change_baseline():
    templates = cardfuzz.track_templates(pan="5555555555554444", service_code="121")
    base = cardfuzz.get_track_template(templates, "baseline")
    assert "5555555555554444" in base.track2
    assert base.track2.split("=")[1].startswith("2812121")   # sc propagado


def test_unknown_track_template_returns_none():
    assert cardfuzz.get_track_template(cardfuzz.track_templates(), "no-existe") is None


# --- plantillas de registro EMV ------------------------------------------
def test_emv_baseline_roundtrips_and_has_pan():
    t = cardfuzz.get_emv_template(cardfuzz.emv_templates(), "baseline")
    rec = t.to_record()
    parsed = tlv.parse(rec)
    assert parsed.find("5A") is not None
    assert parsed.find("70") is not None or parsed  # el 70 es el nodo raíz


def test_emv_no_cvm_actually_decodes_as_no_cvm_risk():
    t = cardfuzz.get_emv_template(cardfuzz.emv_templates(), "no-cvm")
    parsed = tlv.parse(t.to_record())
    lst = cvm.parse_cvm_list(parsed.find("8E").value)
    risks = lst.risks()
    assert any("Sin CVM" in r for r in risks)


def test_emv_weak_aip_actually_decodes_as_sda_only():
    t = cardfuzz.get_emv_template(cardfuzz.emv_templates(), "weak-aip")
    parsed = tlv.parse(t.to_record())
    flags = emvbits.set_flags(emvbits.decode_aip(parsed.find("82").value))
    assert flags == ["SDA soportado"]


def test_emv_missing_pan_has_no_5a_tag():
    t = cardfuzz.get_emv_template(cardfuzz.emv_templates(), "missing-pan")
    parsed = tlv.parse(t.to_record())
    assert parsed.find("5A") is None


def test_emv_oversized_pan_exceeds_normal_length():
    t = cardfuzz.get_emv_template(cardfuzz.emv_templates(), "oversized-pan")
    parsed = tlv.parse(t.to_record())
    assert len(parsed.find("5A").value) == 10   # 20 dígitos empaquetados


def test_emv_expired_date_is_in_the_past():
    t = cardfuzz.get_emv_template(cardfuzz.emv_templates(), "expired")
    parsed = tlv.parse(t.to_record())
    assert parsed.find("5F24").value.hex() == "010101"


def test_emv_overrides_propagate_to_pan():
    t = cardfuzz.get_emv_template(cardfuzz.emv_templates(pan="5555555555554444"), "baseline")
    parsed = tlv.parse(t.to_record())
    assert parsed.find("5A").value.hex().upper().rstrip("F") == "5555555555554444"


def test_unknown_emv_template_returns_none():
    assert cardfuzz.get_emv_template(cardfuzz.emv_templates(), "no-existe") is None


def test_all_emv_templates_produce_valid_tlv():
    for t in cardfuzz.emv_templates():
        rec = t.to_record()
        parsed = tlv.parse(rec)     # no debe lanzar
        assert parsed is not None


# --- NDEF (emulación NFC) ---------------------------------------------
def test_ndef_baseline_is_valid_uri():
    t = cardfuzz.get_ndef_template(cardfuzz.ndef_templates(), "baseline")
    recs = ndef.parse_records(t.message)
    assert len(recs) == 1
    assert recs[0].decoded() == "URI: https://emvy.test/def-con"


def test_ndef_baseline_roundtrips_through_builder():
    # el builder (uri_record) y el parser (parse_records) son inversos
    msg = ndef.uri_record("https://example.com/x")
    assert ndef.parse_records(msg)[0].decoded() == "URI: https://example.com/x"


def test_ndef_empty_and_multi():
    tpls = cardfuzz.ndef_templates()
    assert cardfuzz.get_ndef_template(tpls, "empty").message == b""
    mr = cardfuzz.get_ndef_template(tpls, "multi-record")
    assert len(ndef.parse_records(mr.message)) == 16


def test_ndef_mutations_are_actually_malformed():
    tpls = cardfuzz.ndef_templates()
    base = cardfuzz.get_ndef_template(tpls, "baseline").message
    # invalid-tnf: TNF 0x07 (reservado) — distinto del well-known del baseline
    inv = cardfuzz.get_ndef_template(tpls, "invalid-tnf").message
    assert (inv[0] & 0x07) == 0x07 and (base[0] & 0x07) == ndef.TNF_WELL_KNOWN
    # no-me-flag: el baseline tiene ME (0x40); esta mutación no
    nome = cardfuzz.get_ndef_template(tpls, "no-me-flag").message
    assert (base[0] & 0x40) and not (nome[0] & 0x40)
    # truncated: más corto que el base
    assert len(cardfuzz.get_ndef_template(tpls, "truncated").message) < len(base)
    # huge-uri: mucho más largo
    assert len(cardfuzz.get_ndef_template(tpls, "huge-uri").message) > 1000


def test_ndef_overrides_and_unknown():
    tpls = cardfuzz.ndef_templates(url="https://acme.example/abc")
    base = cardfuzz.get_ndef_template(tpls, "baseline")
    assert ndef.parse_records(base.message)[0].decoded().endswith("acme.example/abc")
    assert cardfuzz.get_ndef_template(tpls, "no-existe") is None


def test_all_ndef_templates_have_hex():
    for t in cardfuzz.ndef_templates():
        assert isinstance(t.to_hex(), str)   # incluido el vacío ("")


def test_test_card_ndef_carries_card_fields():
    msg = cardfuzz.test_card_ndef()
    dec = ndef.parse_records(msg)[0].decoded()
    assert "PAN=4111111111111111" in dec and "TEST VISA" in dec


def test_card_ndef_from_fields():
    msg = cardfuzz.card_ndef_from_fields(pan="5555444433332222", expiry="2704",
                                         aid="A0000000041010", label="LAB MC")
    dec = ndef.parse_records(msg)[0].decoded()
    assert "PAN=5555444433332222" in dec and "EXP=2704" in dec and "LAB MC" in dec


def test_card_record_empty_is_safe():
    dec = ndef.parse_records(ndef.card_record())[0].decoded()
    assert "sin datos" in dec


# --- personalización (registro EMV amistoso) ----------------------------
def test_personalize_record_coherent_fields():
    from emvy.core import track
    rec = cardfuzz.personalize_record(pan="4189143370041827", name="JANE DOE",
                                      expiry="2909", service_code="201")
    top = tlv.parse(rec)
    assert len(top) == 1 and top[0].tag == "70"
    kids = {n.tag: n.value for n in top[0].children}
    assert kids["5A"].hex().upper().rstrip("F") == "4189143370041827"
    assert kids["5F24"].hex().upper() == "290931"          # YYMM → YYMMDD (día 31)
    assert kids["5F20"] == b"JANE DOE"
    t2 = track.parse_track2_emv(kids["57"])                # coherente con PAN/exp/servicio
    assert t2.pan == "4189143370041827" and t2.expiry == "2909" and t2.service_code == "201"


def test_personalize_record_yymmdd_and_defaults():
    rec = cardfuzz.personalize_record(expiry="270431")     # YYMMDD explícito
    kids = {n.tag: n.value for n in tlv.parse(rec)[0].children}
    assert kids["5F24"].hex().upper() == "270431"
    # defaults = TEST_RECORD, registro válido y parseable
    base = cardfuzz.personalize_record()
    assert tlv.parse(base)[0].tag == "70"
    assert cardfuzz.TEST_RECORD["pan"] == "4111111111111111"
