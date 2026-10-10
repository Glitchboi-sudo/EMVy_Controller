"""Tests del APDU printer (apduprint): nombres de comando CLA-aware,
categorización de status words y parseo TLV de las respuestas."""
from emvy.core import apduprint, tlv
from emvy.core.apdu import APDU, Response
from emvy.core.hexutil import from_hex

from fakecard import _record


def test_format_command_nombres_cla_aware():
    sel = apduprint.format_command(APDU(0x00, 0xA4, 0x04, 0x00,
                                        from_hex("A0000000041010"), le=0))
    assert "SELECT FILE" in sel and "CLA=00 INS=A4" in sel

    gpo = apduprint.format_command(APDU(0x80, 0xA8, 0x00, 0x00, from_hex("8300"), le=0))
    assert "GET PROCESSING OPTIONS" in gpo

    rec = apduprint.format_command(APDU(0x00, 0xB2, 0x01, 0x0C, le=0))
    assert "READ RECORD" in rec

    # CLA-aware: 0x80/0xAE es GENERATE AC; con CLA 0x00 cae al fallback genérico
    ga = apduprint.format_command(APDU(0x80, 0xAE, 0x00, 0x00, bytes(20), le=0))
    assert "GENERATE AUTHORISATION CRYPTOGRAM" in ga
    raro = apduprint.format_command(APDU(0x00, 0xAE, 0x00, 0x00, le=0))
    assert "GENERATE AUTHORISATION CRYPTOGRAM" in raro          # fallback por INS

    unk = apduprint.format_command(APDU(0xDE, 0xAD, 0x00, 0x00))
    assert "COMANDO DESCONOCIDO" in unk


def test_format_response_sw_categorizados():
    ok = apduprint.format_response(Response(b"", 0x90, 0x00))
    assert "[9000]" in ok and "(I)" in ok and "correctamente" in ok

    not_found = apduprint.format_response(Response(b"", 0x6A, 0x82))
    assert "(E)" in not_found and "no encontrada" in not_found

    sec = apduprint.format_response(Response(b"", 0x69, 0x82))
    assert "seguridad" in sec

    # comodines: 61xx y 6Cxx informativos de longitud (SW2 en hex, como atrium)
    more = apduprint.format_response(Response(b"", 0x61, 0x10))
    assert "hay 10 bytes" in more and "GET RESPONSE" in more
    wrong_le = apduprint.format_response(Response(b"", 0x6C, 0x00))
    assert "Longitud" in wrong_le
    # 6Cxx con SW2 concreto informa de la longitud exacta
    assert "0A" in apduprint.format_response(Response(b"", 0x6C, 0x0A))

    # categorías de presentación
    assert apduprint.sw_category(0x90, 0x00) == "ok"
    assert apduprint.sw_category(0x6A, 0x82) == "error"
    assert apduprint.sw_category(0x62, 0x83) == "warning"
    assert apduprint.sw_category(0x61, 0x10) == "info"


def test_format_response_parsea_tlv_emv():
    data = _record()   # template 70 con 5A/57/5F24/5F20 (datos EMV reales)
    out = apduprint.format_response(Response(data, 0x90, 0x00))
    assert "Application Primary Account Number" in out or "5A" in out
    assert "4761739001010010" in out          # PAN interpretado

    atc = tlv.encode_tlv(tlv.tlv("9F36", from_hex("0005")))
    out2 = apduprint.format_response(Response(atc, 0x90, 0x00))
    assert "Application Transaction Counter" in out2


def test_format_response_degrada_sin_tlv():
    out = apduprint.format_response(Response(b"\xDE\xAD\xBE\xEF", 0x90, 0x00))
    assert "[9000]" in out                       # no revienta y muestra el SW
    assert "DE AD BE EF" in out                  # datos en crudo


def test_format_exchange_combina():
    ex = type("E", (), {})()
    ex.command = APDU(0x00, 0xA4, 0x04, 0x00, from_hex("A0000000041010"), le=0)
    ex.response = Response(b"", 0x90, 0x00)
    out = apduprint.format_exchange(ex)
    assert "SELECT FILE" in out and "[9000]" in out
