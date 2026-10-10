"""Tests del volcado pcap (core.pcap): formato classic pcap con linktype
ISO 14443, envoltorio I-block con dirección PCD/PICC, y el `PcapTap` como
middleware de un Transceiver (1 intercambio = comando + respuesta con SW).

Cobertura: cabecera global, dirección/toggle de bloque, round-trip de
registros, conteo de intercambios, comando fallido queda grabado, acepta
comandos APDU y bytes crudos, cierre idempotente.
"""
import struct

import pytest

from emvy.core import pcap
from emvy.core.apdu import APDU, Response, select

AID = bytes.fromhex("A0000000031010")


def _read_records(path):
    """Parsea un .pcap clásico y devuelve [(ts_sec, ts_usec, payload), …]."""
    data = path.read_bytes()
    magic, _vmaj, _vmin, _tz, _sig, _snap, dlt = struct.unpack(
        pcap._GLOBAL_HEADER, data[:struct.calcsize(pcap._GLOBAL_HEADER)])
    assert magic == pcap.PCAP_MAGIC
    assert dlt == pcap.DLT_ISO_14443
    off = struct.calcsize(pcap._GLOBAL_HEADER)
    hlen = struct.calcsize(pcap._PACKET_HEADER)
    out = []
    while off < len(data):
        _sec, _usec, incl, _orig = struct.unpack(
            pcap._PACKET_HEADER, data[off:off + hlen])
        out.append(data[off + hlen:off + hlen + incl])
        off += hlen + incl
    return out


def _frame_parts(payload: bytes):
    """Descompone el cuerpo ISO 14443: (event, block_no, apdu)."""
    _ver, event = payload[0], payload[1]
    (ilen,) = struct.unpack(">H", payload[2:4])
    iblock = payload[4:4 + ilen]
    assert len(iblock) == ilen
    return event, iblock[0] & 1, iblock[1:]


def test_global_header_linktype_iso14443():
    h = pcap.global_header()
    assert len(h) == struct.calcsize(pcap._GLOBAL_HEADER)
    # magic little-endian en el alambre
    assert h[:4] == struct.pack("<L", pcap.PCAP_MAGIC)


def test_builder_directions_and_block_toggle():
    b = pcap.PcapBuilder()
    f1 = b.frame("cmd", b"\x00\xA4\x04\x00", 1_000.5)
    f2 = b.frame("resp", b"\x6F\x00\x90\x00", 1_000.7)
    f3 = b.frame("cmd", b"\x80\xA8\x00\x00", 1_001.0)
    f4 = b.frame("resp", b"\x77\x0A\x90\x00", 1_001.2)

    e1, blk1, apdu1 = _frame_parts(f1[struct.calcsize(pcap._PACKET_HEADER):])
    e2, blk2, _ = _frame_parts(f2[struct.calcsize(pcap._PACKET_HEADER):])
    e3, blk3, _ = _frame_parts(f3[struct.calcsize(pcap._PACKET_HEADER):])
    e4, blk4, _ = _frame_parts(f4[struct.calcsize(pcap._PACKET_HEADER):])

    assert (e1, e2, e3, e4) == (pcap.EVT_PCD_TO_PICC, pcap.EVT_PICC_TO_PCD,
                                pcap.EVT_PCD_TO_PICC, pcap.EVT_PICC_TO_PCD)
    # el bloque se alterna por comando y la respuesta lo repite
    assert blk1 == 1 and blk2 == 1
    assert blk3 == 0 and blk4 == 0
    assert apdu1 == b"\x00\xA4\x04\x00"


def test_tap_records_full_exchange(tmp_path):
    out = tmp_path / "sniff.pcap"
    tap = pcap.PcapTap(out)
    sent = []

    def fake_send(command):
        cmd = command.to_bytes() if isinstance(command, APDU) else bytes(command)
        sent.append(cmd)
        return Response(bytes.fromhex("6F108407"), 0x90, 0x00)

    send = tap.wrap(fake_send)
    r1 = send(select(AID))
    r2 = send(APDU(0x80, 0xA8, 0x00, 0x00, bytes.fromhex("8300"), le=0))
    tap.close()

    assert r1.ok and r2.ok
    assert tap.exchanges == 2
    frames = _read_records(out)
    assert len(frames) == 4  # 2 intercambios × (comando + respuesta)
    evs = [_frame_parts(f)[0] for f in frames]
    assert evs == [pcap.EVT_PCD_TO_PICC, pcap.EVT_PICC_TO_PCD] * 2
    # la respuesta grabada lleva los SW1/SW2 detrás de los datos
    assert _frame_parts(frames[1])[2] == bytes.fromhex("6F1084079000")
    assert _frame_parts(frames[0])[2] == sent[0]


def test_tap_accepts_raw_bytes_commands(tmp_path):
    out = tmp_path / "raw.pcap"
    with pcap.PcapTap(out) as tap:
        send = tap.wrap(lambda b: Response(b"", 0x90, 0x00))
        send(bytes.fromhex("00B2010C00"))
        assert tap.exchanges == 1
    frames = _read_records(out)
    assert _frame_parts(frames[0])[2] == bytes.fromhex("00B2010C00")


def test_tap_records_command_when_send_raises(tmp_path):
    out = tmp_path / "fail.pcap"
    tap = pcap.PcapTap(out)

    def boom(_command):
        raise ConnectionError("tarjeta extraída")

    send = tap.wrap(boom)
    with pytest.raises(ConnectionError):
        send(select(AID))
    tap.close()

    # el comando que se disparó queda en evidencia aunque no hubo respuesta
    frames = _read_records(out)
    assert len(frames) == 1
    assert _frame_parts(frames[0])[0] == pcap.EVT_PCD_TO_PICC
    assert tap.exchanges == 0


def test_tap_close_is_idempotent(tmp_path):
    tap = pcap.PcapTap(tmp_path / "x.pcap")
    tap.close()
    assert tap.closed
    tap.close()  # no debe petar


# --- líneas de wire del firmware de emulación (EMU:RX/EMU:TX) ----------------
# La emulación NDEF/EMV no pasa APDUs por el host: el intercambio lo hace el
# firmware del BomberCat y el tap lo reconstruye desde sus líneas de texto,
# donde el APDU completo en hex es siempre el último token.

_WIRE_LINES = [
    # (línea, se_graba)
    ("EMU:RX SELECT-PPSE 2PAY.SYS.DDF01 "
     "00A404000E325041592E5359532E444446303100", True),
    ("EMU:TX 6F23840E325041592E5359532E4444463031A511BF0C0E61087F60813B"
     "7F009000", True),
    ("EMU:RX SELECT-AID A0000000031010 (VISA) "
     "00A4040007A000000003101000", True),
    ("EMU:TX 6F1E8407A0000000031010A513500B5649534120435245444954870101"
     "9000", True),
    ("  PDOL 9F660426C08600 9F0206000000000100", False),   # decodificado, no APDU
    ("EMU:RX GPO 80A8000002830000", True),
    ("EMU:TX 80069800080101009000", True),
    ("EMU:MSG-SENT n=1", False),
    ("EMU:DONE", False),
    ("ERR:TXFAIL", False),
]


def test_record_wire_line_grabs_emulation_exchange(tmp_path):
    out = tmp_path / "emu.pcap"
    tap = pcap.PcapTap(out)
    written = [tap.record_wire_line(line) for line, _ in _WIRE_LINES]
    tap.close()

    assert written == [grab for _, grab in _WIRE_LINES]
    assert tap.exchanges == 3  # un comando por EMU:RX

    frames = _read_records(out)
    assert len(frames) == 6  # 3 intercambios × (comando + respuesta)
    evs = [_frame_parts(f)[0] for f in frames]
    assert evs == [pcap.EVT_PCD_TO_PICC, pcap.EVT_PICC_TO_PCD] * 3
    # comando SELECT-PPSE y respuesta con SW, byte a byte
    assert _frame_parts(frames[0])[2] == bytes.fromhex(
        "00A404000E325041592E5359532E444446303100")
    assert _frame_parts(frames[1])[2].endswith(b"\x90\x00")
    # el toggle de bloque alterna por comando y lo repite la respuesta
    assert [_frame_parts(f)[1] for f in frames] == [1, 1, 0, 0, 1, 1]


def test_record_wire_line_rejects_garbage(tmp_path):
    tap = pcap.PcapTap(tmp_path / "g.pcap")
    assert not tap.record_wire_line("EMU:TX")            # sin hex
    assert not tap.record_wire_line("EMU:TX NOTHEX")     # token no hex
    assert not tap.record_wire_line("EMU:TX ABC")        # longitud impar
    assert not tap.record_wire_line("PONG")              # línea ajena al emu
    tap.close()
    assert len(_read_records(tmp_path / "g.pcap")) == 0
