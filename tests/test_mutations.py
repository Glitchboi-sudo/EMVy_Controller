"""Tests del motor de mutaciones EMV (core.mutations) y los playbooks COMBO
(core.playbooks). Cada familia se valida con los decodificadores reales del
proyecto (`emv.parse_afl`, `tlv.parse_dol`, `tlv.parse`), no a ciegas."""
from emvy.core import mutations as mut
from emvy.core import playbooks
from emvy.core import tlv
from emvy.core.apdu import APDU, Response
from emvy.core.emv import parse_afl
from emvy.core.hexutil import from_hex, to_hex
from emvy.session.model import CardDump


def _cfg(d: dict) -> mut.MutationConfig:
    return mut.MutationConfig.from_dict(d)


# ---------------------------------------------------------------------------
# Config: from_dict / to_dict
# ---------------------------------------------------------------------------
def test_config_roundtrip():
    d = {
        "enabled": True,
        "pdol": [{"tag": "9F02", "value": "000000000001", "comment": "1 céntimo"}],
        "afl": [{"mode": "skip_signed"}],
        "dol": [{"target_tag": "8C", "mode": "remove_field", "field_tag": "9F02"}],
        "response": [{"tag": "82", "mode": "xor", "value": "2100", "on_ins": ["A8"]}],
        "injections": [{"trigger_ins": "AE", "when": "after_response",
                        "apdu": "80CA9F3600"}],
        "pdol_dol": [["9F02", 6], ["5F2A", 2]],
    }
    cfg = _cfg(d)
    cfg2 = _cfg(cfg.to_dict())
    assert cfg == cfg2
    assert cfg.pdol[0].value == from_hex("000000000001")
    assert cfg.response[0].on_ins == ("A8",)


def test_config_from_dict_accepts_atrium_key_names():
    cfg = _cfg({"pdol_mutations": [{"tag": "9F02", "value": "000000000001"}],
                "afl_mutations": [{"mode": "truncate", "truncate_to": 1}],
                "dol_mutations": [{"target_tag": "8C", "mode": "remove_field",
                                   "field_tag": "9F34"}],
                "response_mutations": [{"tag": "82", "mode": "replace", "value": "5800"}],
                "injected_commands": [{"trigger_ins": "A4", "when": "before_command",
                                       "apdu": "80CA9F4F00"}]})
    assert len(cfg.pdol) == 1 and len(cfg.afl) == 1 and len(cfg.dol) == 1
    assert len(cfg.response) == 1 and len(cfg.injections) == 1


def test_config_rejects_bad_modes():
    import pytest
    with pytest.raises(ValueError):
        _cfg({"afl": [{"mode": "bogus"}]})
    with pytest.raises(ValueError):
        _cfg({"response": [{"tag": "82", "mode": "bogus"}]})
    with pytest.raises(ValueError):
        _cfg({"injections": [{"trigger_ins": "A4", "when": "nunca",
                              "apdu": "80CA9F4F00"}]})


# ---------------------------------------------------------------------------
# Familia 1: PDOL (comando GPO)
# ---------------------------------------------------------------------------
def _gpo_apdu() -> APDU:
    # PDOL: 9F02 (6), 5F2A (2) → datos dentro del template 83
    data = tlv.encode([tlv.tlv("83", from_hex("0000000010000978"))])
    return APDU(0x80, 0xA8, 0x00, 0x00, data, le=0x00)


def test_pdol_mutation_rewrites_amount_and_currency():
    cfg = _cfg({"pdol": [{"tag": "9F02", "value": "000000000001"},
                         {"tag": "5F2A", "value": "0978"}]})
    pdol = [("9F02", 6), ("5F2A", 2)]
    out, notes = mut.apply_command(_gpo_apdu(), cfg, pdol=pdol)
    assert out != _gpo_apdu()
    t83 = tlv.parse(out.data).find("83")
    assert t83.value == from_hex("0000000000010978")
    assert any("PDOL 9F02" in n for n in notes)


def test_pdol_mutation_uses_config_pdol_dol_fallback():
    cfg = _cfg({"pdol": [{"tag": "9F02", "value": "000000000001"}],
                "pdol_dol": [["9F02", 6], ["5F2A", 2]]})
    out, notes = mut.apply_command(_gpo_apdu(), cfg)  # sin layout explícito
    assert tlv.parse(out.data).find("83").value[:6] == from_hex("000000000001")
    assert notes


def test_pdol_skips_disabled_and_unknown_tags():
    cfg = _cfg({"pdol": [{"tag": "9F02", "value": "000000000001", "enabled": False},
                         {"tag": "9F1A", "value": "0276"}]})  # 9F1A no está en el PDOL
    out, notes = mut.apply_command(_gpo_apdu(), cfg, pdol=[("9F02", 6), ("5F2A", 2)])
    assert out == _gpo_apdu() and not notes


def test_pdol_ignores_non_gpo_commands():
    cfg = _cfg({"pdol": [{"tag": "9F02", "value": "000000000001"}]})
    apdu = APDU(0x00, 0xB2, 0x01, 0x0C, b"", le=0x00)
    out, notes = mut.apply_command(apdu, cfg, pdol=[("9F02", 6)])
    assert out is apdu and not notes


# ---------------------------------------------------------------------------
# Familia 2: AFL (tag 94)
# ---------------------------------------------------------------------------
AFL_BYTES = from_hex("0801010010010200")  # SFI1 r1; SFI2 r1-2


def _afl_config(spec: dict) -> mut.MutationConfig:
    return _cfg({"afl": [spec]})


def test_afl_skip_signed_zeroes_offline_counters():
    out, notes = mut.mutate_afl(AFL_BYTES, _afl_config({"mode": "skip_signed"}).afl)
    entries = parse_afl(out)  # validado con el decoder real
    assert [e[3] for e in entries] == [0, 0]
    assert [e[0] for e in entries] == [1, 2]  # SFI intactos
    assert notes and "skip_signed" in notes[0]


def test_afl_truncate_keeps_first_n():
    out, _ = mut.mutate_afl(AFL_BYTES, _afl_config({"mode": "truncate", "truncate_to": 1}).afl)
    assert parse_afl(out) == [(1, 1, 1, 0)]


def test_afl_remove_sfi():
    out, _ = mut.mutate_afl(AFL_BYTES, _afl_config({"mode": "remove_sfi", "target_sfi": 2}).afl)
    assert parse_afl(out) == [(1, 1, 1, 0)]


def test_afl_extend_appends_entries():
    out, _ = mut.mutate_afl(AFL_BYTES,
                            _afl_config({"mode": "extend",
                                         "extra_entries": [{"sfi": 3, "first": 1,
                                                            "last": 1, "offline": 0}]}).afl)
    assert parse_afl(out) == [(1, 1, 1, 0), (2, 1, 2, 0), (3, 1, 1, 0)]


def test_afl_roundtrip_is_byte_exact():
    out, _ = mut.mutate_afl(AFL_BYTES, _afl_config({"mode": "skip_signed"}).afl)
    rebuilt = bytes(b for e in parse_afl(out) for b in (e[0] << 3, e[1], e[2], e[3]))
    assert rebuilt == out


def test_apply_response_mutates_afl_tag_in_gpo_response():
    gpo = tlv.encode([_tmpl("77", [
        tlv.tlv("82", from_hex("2000")),
        tlv.tlv("94", AFL_BYTES)])])
    resp = Response(gpo, 0x90, 0x00)
    cfg = _cfg({"afl": [{"mode": "truncate", "truncate_to": 1}]})
    out, notes = mut.apply_response(resp, 0xA8, cfg)
    assert parse_afl(tlv.parse(out.data).find("94").value) == [(1, 1, 1, 0)]
    assert any("AFL truncate" in n for n in notes)


# ---------------------------------------------------------------------------
# Familia 3: DOL (CDOL1 8C / CDOL2 8D)
# ---------------------------------------------------------------------------
CDOL1 = from_hex("9F02069F030695055F2A029A039C019F37049F3403")  # incluye 9F02 y 9F34


def test_dol_remove_field_drops_amount():
    cfg = _cfg({"dol": [{"target_tag": "8C", "mode": "remove_field", "field_tag": "9F02"}]})
    out, notes = mut.mutate_dol(CDOL1, cfg.dol)
    entries = tlv.parse_dol(out)  # decoder real
    assert "9F02" not in [t for t, _ in entries]
    assert ("9F34", 3) in entries  # el resto se conserva
    assert notes and "remove_field 9F02" in notes[0]


def test_dol_truncate_keeps_first_n_fields():
    cfg = _cfg({"dol": [{"target_tag": "8C", "mode": "truncate", "truncate_to": 2}]})
    out, _ = mut.mutate_dol(CDOL1, cfg.dol)
    assert tlv.parse_dol(out) == [("9F02", 6), ("9F03", 6)]


def test_dol_remove_cvm_results():
    cfg = _cfg({"dol": [{"target_tag": "8C", "mode": "remove_field", "field_tag": "9F34"}]})
    out, _ = mut.mutate_dol(CDOL1, cfg.dol)
    assert "9F34" not in [t for t, _ in tlv.parse_dol(out)]


def test_apply_response_mutates_cdol_in_record():
    rec = tlv.encode([_tmpl("70", [
        tlv.tlv("8C", CDOL1), tlv.tlv("8D", from_hex("9F0206"))])])
    cfg = _cfg({"dol": [{"target_tag": "8C", "mode": "remove_field", "field_tag": "9F02"}]})
    out, notes = mut.apply_response(Response(rec, 0x90, 0x00), 0xB2, cfg)
    cdol = tlv.parse(out.data).find("8C")
    assert "9F02" not in [t for t, _ in tlv.parse_dol(cdol.value)]
    # el 8D (CDOL2) queda intacto: la regla apuntaba solo a 8C
    assert tlv.parse(out.data).find("8D").value == from_hex("9F0206")
    assert any("DOL 8C" in n for n in notes)


# ---------------------------------------------------------------------------
# Familia 4: TLV de respuesta (todos los modos + on_ins)
# ---------------------------------------------------------------------------
def _tmpl(tag: str, children) -> tlv.TLV:
    return tlv.TLV(tag, b"", list(children), True)


def _resp_with(tags) -> Response:
    return Response(tlv.encode(tags), 0x90, 0x00)


def test_resp_replace():
    cfg = _cfg({"response": [{"tag": "82", "mode": "replace", "value": "5800"}]})
    out, notes = mut.apply_response(_resp_with([tlv.tlv("82", from_hex("2000"))]), None, cfg)
    assert tlv.parse(out.data).find("82").value == from_hex("5800")
    assert notes[0].startswith("resp TLV replace 82")


def test_resp_delete_removes_tag():
    cfg = _cfg({"response": [{"tag": "8D", "mode": "delete"}]})
    out, _ = mut.apply_response(
        _resp_with([tlv.tlv("8C", CDOL1), tlv.tlv("8D", from_hex("9F0206"))]), None, cfg)
    assert tlv.parse(out.data).find("8D") is None
    assert tlv.parse(out.data).find("8C") is not None


def test_resp_prepend_append():
    cfg = _cfg({"response": [{"tag": "9F36", "mode": "prepend", "value": "FF"},
                             {"tag": "9F36", "mode": "append", "value": "EE"}]})
    out, _ = mut.apply_response(_resp_with([tlv.tlv("9F36", from_hex("0031"))]), None, cfg)
    assert tlv.parse(out.data).find("9F36").value == from_hex("FF0031EE")


def test_resp_splice_keeps_length():
    cfg = _cfg({"response": [{"tag": "57", "mode": "splice", "value": "99",
                              "offset": 2}]})
    out, _ = mut.apply_response(_resp_with([tlv.tlv("57", from_hex("12345678"))]), None, cfg)
    assert tlv.parse(out.data).find("57").value == from_hex("12349978")


def test_resp_splice_past_end_raises():
    import pytest
    cfg = _cfg({"response": [{"tag": "57", "mode": "splice", "value": "AABB",
                              "offset": 3}]})
    with pytest.raises(ValueError):
        mut.apply_response(_resp_with([tlv.tlv("57", from_hex("1234"))]), None, cfg)


def test_resp_xor_mask():
    cfg = _cfg({"response": [{"tag": "82", "mode": "xor", "value": "2100"}]})
    out, _ = mut.apply_response(_resp_with([tlv.tlv("82", from_hex("3900"))]), None, cfg)
    assert tlv.parse(out.data).find("82").value == from_hex("1800")


def test_resp_flip_bit_msb_first():
    cfg = _cfg({"response": [{"tag": "82", "mode": "flip_bit", "bit_position": 0}]})
    out, _ = mut.apply_response(_resp_with([tlv.tlv("82", from_hex("2000"))]), None, cfg)
    assert tlv.parse(out.data).find("82").value == from_hex("A000")


def test_resp_on_ins_filter():
    cfg = _cfg({"response": [{"tag": "82", "mode": "replace", "value": "5800",
                              "on_ins": ["A8"]}]})
    data = _resp_with([tlv.tlv("82", from_hex("2000"))])
    on_a8, _ = mut.apply_response(data, 0xA8, cfg)
    on_b2, notes = mut.apply_response(data, 0xB2, cfg)
    assert tlv.parse(on_a8.data).find("82").value == from_hex("5800")
    assert on_b2 is data and not notes  # B2 no pasa el filtro


def test_resp_recurses_into_constructed_templates():
    cfg = _cfg({"response": [{"tag": "9F36", "mode": "replace", "value": "0001"}]})
    inner = _tmpl("70", [tlv.tlv("9F36", from_hex("0031"))])
    out, _ = mut.apply_response(_resp_with([inner]), 0xB2, cfg)
    assert tlv.parse(out.data).find("9F36").value == from_hex("0001")


# ---------------------------------------------------------------------------
# Familia 5 + middleware: inyecciones y mutating()
# ---------------------------------------------------------------------------
def _fake_card(send_log: list):
    """Transceiver fake que simula una tarjeta mínima: SELECT devuelve FCI con
    PDOL, GPO devuelve AIP+AFL (formato 1), READ RECORD devuelve un registro
    con CDOL1 y CVM list, GET DATA devuelve un contador."""
    fci = tlv.encode([
        _tmpl("6F", [
            tlv.tlv("84", from_hex("A0000000031010")),
            _tmpl("A5", [
                tlv.tlv("9F38", from_hex("9F02065F2A02")),  # PDOL: importe+divisa
            ]),
        ])])
    gpo = Response(tlv.encode([_tmpl("77", [
        tlv.tlv("82", from_hex("2000")), tlv.tlv("94", AFL_BYTES)])]),
        0x90, 0x00)  # formato 2: AIP + AFL en template 77
    record = Response(tlv.encode([
        _tmpl("70", [tlv.tlv("8C", CDOL1),
                     tlv.tlv("8E", from_hex("00000000000000001F00"))])]), 0x90, 0x00)

    def send(apdu):
        a = mut.to_apdu(apdu)
        send_log.append(a)
        if a.ins == 0xA4:
            return Response(fci, 0x90, 0x00)
        if a.ins == 0xA8:
            return gpo
        if a.ins == 0xB2:
            return record
        if a.ins == 0xCA:
            return Response(from_hex("0003"), 0x90, 0x00)
        return Response(b"", 0x6D, 0x00)

    return send


def test_injections_fire_but_never_forward_response():
    sent = []
    cfg = _cfg({"injections": [
        {"trigger_ins": "A8", "when": "after_response", "apdu": "80CA9F1700"},
        {"trigger_ins": "A4", "when": "before_command", "apdu": "80CA9F4F00"},
    ]})
    events = []
    send = mut.mutating(_fake_card(sent), cfg, on_event=events.append)
    # dos SELECT: la inyección before_command solo debe disparar una vez
    send(APDU(0x00, 0xA4, 0x04, 0x00, from_hex("A0000000031010")))
    resp = send(APDU(0x00, 0xA4, 0x04, 0x00, from_hex("A0000000031010")))
    # la respuesta al terminal es la del SELECT (FCI), nunca la de la inyección
    assert tlv.parse(resp.data).find("9F38") is not None
    # el GET DATA inyectado llegó a la tarjeta (solo una vez: repeat=False)
    ca = [a for a in sent if a.ins == 0xCA]
    assert len(ca) == 1 and ca[0].p1 == 0x9F and ca[0].p2 == 0x4F
    notes = [n for ev in events for n in ev.notes]
    assert any("9000" in n for n in notes)  # la respuesta se registró
    # tras el GPO: la inyección 9F17 dispara y su respuesta NO se reenvía
    gpo = APDU(0x80, 0xA8, 0x00, 0x00,
               tlv.encode([tlv.tlv("83", from_hex("0000000010000978"))]), le=0x00)
    gpo_resp = send(gpo)
    assert tlv.parse(gpo_resp.data).find("94") is not None  # respuesta GPO, no la inyección
    assert any(a.ins == 0xCA and a.p2 == 0x17 for a in sent)
    notes = [n for ev in events for n in ev.notes]
    assert any(n.startswith("inject 80CA9F1700") for n in notes)


def test_mutating_pdol_uses_fci_learned_from_select():
    sent = []
    cfg = _cfg({"pdol": [{"tag": "9F02", "value": "000000000001"}]})
    send = mut.mutating(_fake_card(sent), cfg)
    send(APDU(0x00, 0xA4, 0x04, 0x00, from_hex("A0000000031010")))   # aprende PDOL
    gpo = APDU(0x80, 0xA8, 0x00, 0x00,
               tlv.encode([tlv.tlv("83", from_hex("0000000010000978"))]), le=0x00)
    send(gpo)
    gpo_seen = next(a for a in sent if a.ins == 0xA8)
    assert tlv.parse(gpo_seen.data).find("83").value == from_hex("0000000000010978")


def test_mutating_applies_response_families_in_path():
    sent = []
    cfg = _cfg({"afl": [{"mode": "skip_signed"}],
                "response": [{"tag": "8E", "mode": "replace",
                              "value": "00000000000000001F03"}]})
    events = []
    send = mut.mutating(_fake_card(sent), cfg, on_event=events.append)
    send(APDU(0x00, 0xA4, 0x04, 0x00, from_hex("A0000000031010")))
    send(APDU(0x80, 0xA8, 0x00, 0x00,
              tlv.encode([tlv.tlv("83", from_hex("0000000010000978"))]), le=0x00))
    resp = send(APDU(0x00, 0xB2, 0x01, 0x0C, b"", le=0x00))
    # el registro vio mutado su CVM list
    assert tlv.parse(resp.data).find("8E").value == from_hex("00000000000000001F03")
    # el GPO vio mutado su AFL (skip_signed)
    gpo_ev = next(e for e in events if e.cmd_before.ins == 0xA8)
    afl = tlv.parse(gpo_ev.resp_after.data).find("94")
    assert parse_afl(afl.value)[0][3] == 0
    assert gpo_ev.modified


def test_planned_injections_listing():
    cfg = _cfg({"injections": [
        {"trigger_ins": "A8", "when": "after_response", "apdu": "80CA9F1700",
         "comment": "PIN retry"},
        {"trigger_ins": "A4", "when": "before_command", "apdu": "80CA9F4F00",
         "enabled": False},
    ]})
    plan = mut.planned_injections(cfg)
    assert len(plan) == 1 and "80CA9F1700" in plan[0] and "PIN retry" in plan[0]


# ---------------------------------------------------------------------------
# preview_dump (modo offline)
# ---------------------------------------------------------------------------
def _dump() -> CardDump:
    return CardDump(applications=[{
        "aid": "A0000000031010", "scheme": "Visa", "source": "ppse", "label": "VISA",
        "cardholder": {}, "aip": "2000", "afl": to_hex(AFL_BYTES),
        "records": [
            {"sfi": 1, "record": 1,
             "hex": to_hex(tlv.encode([_tmpl("70", [
                 tlv.tlv("8C", CDOL1),
                 tlv.tlv("8E", from_hex("00000000000000001F00"))])]))},
        ],
        "get_data": {"9F36": "0031"},
    }], blobs=[])


def test_preview_dump_applies_response_families():
    cfg = _cfg({"afl": [{"mode": "truncate", "truncate_to": 1}],
                "dol": [{"target_tag": "8C", "mode": "remove_field", "field_tag": "9F02"}],
                "response": [{"tag": "9F36", "mode": "replace", "value": "0001"}]})
    lines = mut.preview_dump(_dump(), cfg)
    text = "\n".join(lines)
    assert "AFL truncate" in text
    assert "DOL 8C remove_field 9F02" in text
    assert "resp TLV replace 9F36" in text
    assert "→" in text  # diff legible original → mutado


def test_preview_dump_without_matching_rules_reports_no_changes():
    cfg = _cfg({})
    lines = mut.preview_dump(_dump(), cfg)
    assert any("sin cambios" in l for l in lines)


def test_preview_dump_requires_apps():
    cfg = _cfg({"afl": [{"mode": "skip_signed"}]})
    lines = mut.preview_dump(CardDump(), cfg)
    assert any("no tiene aplicaciones" in l for l in lines)


# ---------------------------------------------------------------------------
# Playbooks COMBO
# ---------------------------------------------------------------------------
def test_all_playbooks_build_valid_config_and_apply():
    dump = _dump()
    for pb in playbooks.playbooks():
        assert pb["id"].startswith("COMBO-") and pb["title"] and pb["description"]
        assert pb["attack_ref"] and all(r.startswith("ATTACK-") for r in pb["attack_ref"])
        cfg = mut.MutationConfig.from_dict(pb["config"])  # sin excepción
        lines = mut.preview_dump(dump, cfg)               # aplica sin excepción
        assert isinstance(lines, list) and lines
        mut.planned_injections(cfg)


def test_get_playbook():
    assert playbooks.get_playbook("combo-a")["id"] == "COMBO-A"  # case-insensitive
    assert playbooks.get_playbook("COMBO-Z") is None


def test_combo_b_defeats_offline_auth_semantics():
    cfg = mut.MutationConfig.from_dict(playbooks.get_playbook("COMBO-B")["config"])
    # skip_signed + AIP xor 2100: AFL sin registros firmados, AIP sin DDA/CDA
    new_afl, _ = mut.mutate_afl(AFL_BYTES, cfg.afl)
    assert all(e[3] == 0 for e in parse_afl(new_afl))
    out, _ = mut.apply_response(_resp_with([tlv.tlv("82", from_hex("3900"))]), None, cfg)
    aip = int.from_bytes(tlv.parse(out.data).find("82").value, "big")
    assert not (aip & 0x2100)  # bits DDA(0x2000) y CDA(0x0100) limpios


def test_combo_a_pdol_semantics():
    cfg = mut.MutationConfig.from_dict(playbooks.get_playbook("COMBO-A")["config"])
    out, notes = mut.apply_command(_gpo_apdu(), cfg, pdol=[("9F02", 6), ("5F2A", 2)])
    t83 = tlv.parse(out.data).find("83")
    assert t83.value == from_hex("0000000000010978")  # 1¢ + EUR
    assert len(cfg.injections) == 2


def test_preview_dump_respects_on_ins_of_each_source():
    """Las reglas on_ins filtran según el INS real de cada fuente: get_data se
    leyó con GET DATA (CA), así que COMBO-E (on_ins CA) sí aplica sobre él."""
    cfg = _cfg({"response": [{"tag": "9F36", "mode": "replace", "value": "0001",
                              "on_ins": ["CA"]}]})
    lines = mut.preview_dump(_dump(), cfg)
    assert any("resp TLV replace 9F36" in l for l in lines)
    cfg_b2 = _cfg({"response": [{"tag": "9F36", "mode": "replace", "value": "0001",
                                 "on_ins": ["B2"]}]})
    lines = mut.preview_dump(_dump(), cfg_b2)
    assert any("sin cambios" in l for l in lines)
