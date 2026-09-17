"""Tests de las primitivas de escritura en tarjeta (APDU + cardwrite)."""
from emvy.core import apdu, cardwrite
from emvy.core.apdu import Response
from emvy.core.hexutil import from_hex


def test_write_apdu_constructors():
    a = apdu.update_record(1, 2, from_hex("AABB"))       # rec=1, sfi=2
    assert a.ins == 0xDC and a.p1 == 1 and a.p2 == ((2 << 3) | 4) and a.data == from_hex("AABB")

    b = apdu.update_binary(5, from_hex("CC"), sfi=3)
    assert b.ins == 0xD6 and b.p1 == (0x80 | 3) and b.p2 == 5

    b2 = apdu.update_binary(0x0102, from_hex("CC"))       # sin SFI: offset en P1P2
    assert b2.p1 == 0x01 and b2.p2 == 0x02

    c = apdu.put_data(0x9F36, from_hex("0001"))
    assert c.ins == 0xDA and c.cla == 0x80 and c.p1 == 0x9F and c.p2 == 0x36

    d = apdu.append_record(2, from_hex("DD"))
    assert d.ins == 0xE2 and d.p2 == ((2 << 3) | 4)


def test_write_status():
    assert cardwrite.write_status(0x9000) == "OK"
    assert "seguridad" in cardwrite.write_status(0x6982)
    assert cardwrite.write_status(0x63C3).startswith("aviso")
    assert cardwrite.write_status(0x1234) == "SW 1234"


def test_cardwrite_helpers_send():
    seen = {}

    def send(a):
        seen["apdu"] = a
        return Response(b"", 0x90, 0x00)

    r = cardwrite.update_record(send, sfi=1, record=2, data=from_hex("AA"))
    assert seen["apdu"].ins == 0xDC and r.sw == 0x9000
    cardwrite.put_data(send, 0x9F36, from_hex("0001"))
    assert seen["apdu"].ins == 0xDA


def test_write_hint_actionable():
    assert cardwrite.write_hint(0x9000) is None
    for sw in (0x6982, 0x6985):
        assert "GlobalPlatform" in cardwrite.write_hint(sw)
    assert "SFI/registro" in cardwrite.write_hint(0x6A82)
    assert cardwrite.write_hint(0x1234) is None            # SW sin pista específica
