"""Serial falso que emula el firmware BomberCat (passthrough APDU + EMV JSON),
para probar el backend `emvy.readers.bombercat` sin hardware.

`install()` inyecta un módulo `serial` falso en sys.modules, de modo que
`emvy.readers.bombercat` lo use tal cual (import perezoso).
"""
from __future__ import annotations

import json
import sys
import types

from emvy.core import apdu
from emvy.core.hexutil import from_hex, to_hex
from fakecard import AID, TRACK2, build_fake_card

_EMV_JSON = {
    "ok": True, "pan": "4189143370041827",
    "track2": "4189143370041827D29092211000002600000F",
    "expiry": "2909", "aid": "A0000000031010", "aidName": "VISA",
    "aip": "2000", "atc": "002F", "arqc": "D6F5B2E0E50B0F9C",
    "iad": "06011203A02000", "un": "ED999B69",
}


class FakeSerial:
    """Emula la placa: procesa líneas escritas y encola respuestas."""

    # Estado de emulación a NIVEL CLASE: persiste entre conexiones serie como
    # la RAM del firmware real (una sesión huérfana sobrevive al reabrir el puerto).
    _emulating = False

    def __init__(self, port, baud, timeout=1, dsrdtr=False, rtscts=False, **kw):
        self.port = port
        self.baudrate = baud
        self.timeout = timeout
        self.dtr = True
        self._in = bytearray()     # líneas pendientes del host
        self._out = bytearray()    # bytes listos para readline()
        self._card, _ = build_fake_card()

    # -- API pyserial usada por el backend ---------------------------------
    def reset_input_buffer(self):
        self._out.clear()

    def write(self, data: bytes):
        self._in.extend(data)
        while b"\n" in self._in:
            idx = self._in.index(b"\n")
            line = bytes(self._in[:idx]).decode("utf-8", "replace").strip()
            del self._in[:idx + 1]
            self._handle(line)
        return len(data)

    def flush(self):
        pass

    def readline(self) -> bytes:
        if b"\n" not in self._out:
            return b""
        idx = self._out.index(b"\n")
        line = bytes(self._out[:idx + 1])
        del self._out[:idx + 1]
        return line

    def close(self):
        pass

    # -- firmware simulado --------------------------------------------------
    def _emit(self, text: str):
        self._out.extend((text + "\n").encode())

    def _handle(self, line: str):
        if not line:
            return
        up = line.upper()
        if up == "PING":
            self._emit("PONG")
        elif up == "INFO":
            # dialecto local EMVyBomberCat: :role + :state (el rework upstream
            # NO emite :role). El estado refleja la emulación activa, como el
            # firmware real (gEmuActive → emulating).
            self._emit(":fw_name emvybombercat")
            self._emit(":fw 1.1")
            self._emit(":role emv-multitool")
            self._emit(":state emulating" if FakeSerial._emulating else ":state idle")
            self._emit("+OK")
        elif up.startswith("WAIT"):
            self._emit("READY:")
        elif up.startswith("APDU:"):
            resp = self._card(from_hex(line[5:]))
            self._emit("RESP:" + to_hex(resp.data + bytes([resp.sw1, resp.sw2])))
        elif up == "RELEASE":
            if FakeSerial._emulating:
                FakeSerial._emulating = False
                self._emit("EMU:DONE sent=1 reason=release")
            else:
                self._emit("OK")
        elif up in ("REBOOT", "RESET"):
            # el firmware real reinicia el MCU; el falso solo confirma la línea
            self._emit("# REBOOT")
        elif up == "STOP":
            if FakeSerial._emulating:
                FakeSerial._emulating = False
                self._emit("EMU:DONE sent=1 reason=stop")
            else:
                self._emit("OK")
        elif up == "CARDSCAN" or up.startswith("CARDSCAN "):
            # Simula leer una tarjeta y guardarla en la RAM del firmware.
            self._ram_card = {"aid": "A0000000031010", "pan": "4111111111111111",
                              "exp": "2909"}
            self._emit("# CARDSCAN: acerca la tarjeta contactless a leer...")
            self._emit(f"EMU:SCANNED aid={self._ram_card['aid']} "
                       f"pan={self._ram_card['pan']} exp={self._ram_card['exp']} t2len=19")
        elif up.startswith("EMUEMV"):
            # Emulación de tarjeta EMV: simula el flujo de un terminal de pago
            # (PPSE → SELECT AID → GPO con PDOL decodificado → READ RECORD →
            # GENERATE AC con CDOL1), como el firmware nuevo. Activa hasta STOP.
            # `EMUEMV:<aid>|<pan>|<exp>|<track2>` inyecta desde host; `EMUEMV:RAM`
            # usa la tarjeta guardada por CARDSCAN. Refleja el AID resultante.
            # Como el firmware: si ya había una emulación activa, el comando la
            # reemplaza y primero se reporta su `EMU:DONE reason=restart`.
            if FakeSerial._emulating:
                FakeSerial._emulating = False
                self._emit("EMU:DONE sent=0 reason=restart")
            aid, scheme = "A0000000031010", "VISA"
            cid = "40"                                    # default del host: TC
            if ":" in line:
                rest = line.split(":", 1)[1].strip()
                if rest.upper().startswith("RAM"):
                    ram = getattr(self, "_ram_card", None)
                    if ram:
                        aid = ram["aid"]
                    if "|" in rest:                       # RAM|<cid>
                        cid = rest.split("|", 1)[1].strip() or cid
                else:
                    fields = (rest + "||||").split("|")
                    cid = (fields[4] or cid).upper()
                    self._emit(f"EMU:CARD aid={len(fields[0])//2 if fields[0] else 0} "
                               f"pan={len(fields[1])//2 if fields[1] else 0} "
                               f"exp={len(fields[2])//2 if fields[2] else 0} "
                               f"t2={len(fields[3])//2 if fields[3] else 0} "
                               f"cid={cid}")
                    if fields[0]:
                        aid = fields[0].upper()
            da = {"40": "TC", "80": "ARQC", "00": "AAC"}.get(cid, cid)
            self._emit("EMU:START mode=emv")
            self._emit("EMU:RX SELECT-PPSE 2PAY.SYS.DDF01 00A404000E325041592E5359532E444446303100")
            self._emit("EMU:TX 6F...9000")
            self._emit(f"EMU:RX SELECT-AID {aid} ({scheme}) 00A40400")
            self._emit("EMU:TX 6F...9000")
            self._emit("EMU:RX GPO 80A8000023832136000000000000001000000000000000048400000000000000098409090000009000")
            self._emit("  PDOL TTQ(9F66)=36000000")
            self._emit("  PDOL Monto(9F02)=000000001000")
            self._emit("  PDOL Pais(9F1A)=0484")
            self._emit("EMU:TX 7746820219809404080101009F3602...9000")  # GPO qVSDC (77)
            self._emit("EMU:RX READ-RECORD rec=1 sfi=1 00B2010C00")
            self._emit("EMU:TX 70..9000")
            self._emit(f"EMU:RX GENERATE-AC pide=ARQC da={da} 80AE8000...")
            self._emit("  CDOL1 Monto(9F02)=000000001000")
            self._emit("EMU:TX 771E...9000")
            FakeSerial._emulating = True
        elif up.startswith("EMU:"):
            # Emulación NDEF observable: arranca y simula un lector Type 4 que lee
            # el tag de inmediato (SELECT app/CC/NDEF + READ), reportando cada APDU
            # como el firmware nuevo. Queda "activa" hasta STOP/RELEASE. Si ya
            # había emulación, primero el `EMU:DONE reason=restart` (como el firmware).
            if FakeSerial._emulating:
                FakeSerial._emulating = False
                self._emit("EMU:DONE sent=0 reason=restart")
            body = line[4:]
            self._emit(f"EMU:START len={len(body)//2}")
            self._emit("EMU:RX SELECT-APP D2760000850101 00A4040007D276000085010100")
            self._emit("EMU:TX 9000")
            self._emit("EMU:RX SELECT-CC E103 00A4000C02E103")
            self._emit("EMU:TX 9000")
            self._emit("EMU:RX READ off=0 len=15 00B0000F")
            self._emit("EMU:TX " + (body.upper() or "") + "9000")
            self._emit("EMU:MSG-SENT n=1")
            FakeSerial._emulating = True
        elif up.startswith("SCAN"):
            self._emit("# Esperando tarjeta ISO-DEP...")
            self._emit("JSON_START")
            self._emit(json.dumps(_EMV_JSON))
            self._emit("JSON_END")
            self._emit("# Listo.")


class _Port:
    def __init__(self, device):
        self.device = device
        self.description = "BomberCat RP2040"
        self.manufacturer = "Electronic Cats"
        self.product = "BomberCat"
        self.vid = 0x2E8A
        self.pid = 0x000A


def install():
    """Inyecta un módulo `serial` falso en sys.modules (idempotente)."""
    serial_mod = types.ModuleType("serial")
    serial_mod.Serial = FakeSerial
    tools = types.ModuleType("serial.tools")
    lp = types.ModuleType("serial.tools.list_ports")
    lp.comports = lambda: [_Port("/dev/ttyACM0")]
    tools.list_ports = lp
    serial_mod.tools = tools
    sys.modules["serial"] = serial_mod
    sys.modules["serial.tools"] = tools
    sys.modules["serial.tools.list_ports"] = lp
    return serial_mod


def uninstall():
    for m in ("serial.tools.list_ports", "serial.tools", "serial"):
        sys.modules.pop(m, None)
