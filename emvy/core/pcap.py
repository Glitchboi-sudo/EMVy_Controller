"""Volcado de la comunicación con la tarjeta a **pcap** (classic pcap, stdlib).

Mismo wire format que los pcaps del relay NFC (`vendor/bombercat-tools`): el
link type es `DLT_ISO_14443` (264) y cada APDU se envuelve como un bloque
I de ISO 14443-4 con pseudo-cabecera de dirección, de modo que **Wireshark/
tshark lo disecan directo** con el disector iso14443.

`PcapTap` es el middleware de grabación: envuelve un `Transceiver` lógico
(mismo patrón que `SessionRecorder.wrap`) y escribe **en streaming** un par
de frames por intercambio — comando (PCD→PICC) y respuesta (PICC→PCD, con
los SW1/SW2) — con el timestamp real de cada lado. Si el comando lanza una
excepción, el comando queda grabado igualmente antes de propagar el error.
"""
from __future__ import annotations

import struct
import threading
import time
from pathlib import Path

from .apdu import APDU, Response, Transceiver

# libpcap LINKTYPE_ISO_14443 (pcap/dlt.h: DLT_ISO_14443 264).
DLT_ISO_14443 = 264

PCAP_MAGIC = 0xA1B2C3D4
_GLOBAL_HEADER = (
    "<LHHIILL"  # magic, ver_major, ver_minor, thiszone, sigfigs, snaplen, network
)
_PACKET_HEADER = "<LLLL"  # ts_sec, ts_usec, incl_len, orig_len
SNAPLEN = 0xFFFF

# Pseudo-cabecera ISO 14443: version(1) + event(1) + len(2, big-endian) + data.
# Valores que el disector iso14443 de Wireshark parsea (verificado contra
# tshark 4.4): 0xFE = transferencia PCD -> PICC (comando); 0xFF = PICC -> PCD
# (respuesta).
_ISO14443_VERSION = 0x00
EVT_PCD_TO_PICC = 0xFE  # comando  (terminal -> tarjeta)
EVT_PICC_TO_PCD = 0xFF  # respuesta (tarjeta -> terminal)

# I-block de ISO 14443-4 (PCB); el bit bajo es el número de bloque, alternado
# por comando para que la captura lea como un intercambio -4 real.
_IBLOCK_BASE = 0x02


def global_header(dlt: int = DLT_ISO_14443) -> bytes:
    """Cabecera global del pcap (se escribe una vez, antes de cualquier paquete)."""
    return struct.pack(_GLOBAL_HEADER, PCAP_MAGIC, 2, 4, 0, 0, SNAPLEN, dlt)


def iso14443_payload(is_command: bool, apdu: bytes, block_no: int = 0) -> bytes:
    """Envuelve un APDU como cuerpo de frame ISO 14443 (pseudo-cabecera + I-block)."""
    pcb = _IBLOCK_BASE | (block_no & 1)
    iblock = bytes([pcb]) + apdu
    event = EVT_PCD_TO_PICC if is_command else EVT_PICC_TO_PCD
    return bytes([_ISO14443_VERSION, event]) + struct.pack(">H", len(iblock)) + iblock


def record(payload: bytes, ts_seconds: float) -> bytes:
    """Un registro pcap completo: cabecera de paquete + payload. `ts_seconds`
    es epoch float (segundos + microsegundos)."""
    sec = int(ts_seconds)
    usec = int(round((ts_seconds - sec) * 1_000_000))
    if usec >= 1_000_000:  # el redondeo puede pasar de 1e6; llevar a segundos
        sec += 1
        usec -= 1_000_000
    # `<LLLL` es unsigned: un sec/usec negativo (reloj del sistema) petaría
    # struct.error a mitad de captura. Se clampa a 0 en vez de romper la
    # evidencia por un timestamp ya de por sí dudoso.
    if sec < 0:
        sec = 0
    if usec < 0:
        usec = 0
    return struct.pack(_PACKET_HEADER, sec, usec, len(payload), len(payload)) + payload


class PcapBuilder:
    """Fábrica de frames con estado: mantiene el número de I-block alternado
    (un comando abre bloque nuevo; la respuesta lo repite, como en ISO 14443-4)."""

    def __init__(self) -> None:
        self._block_no = 0

    def frame(self, direction: str, apdu: bytes, ts_seconds: float) -> bytes:
        """Un registro pcap para un APDU ``cmd`` o ``resp``."""
        is_command = direction == "cmd"
        if is_command:
            self._block_no ^= 1  # nuevo intercambio
        payload = iso14443_payload(is_command, apdu, self._block_no)
        return record(payload, ts_seconds)


def _to_bytes(command) -> bytes:
    return command.to_bytes() if isinstance(command, APDU) else bytes(command)


class PcapTap:
    """Graba en streaming cada intercambio lógico de un `Transceiver` en un
    .pcap. Escribe y hace flush por intercambio (forense: no se pierde nada
    si el proceso cae). Si la escritura falla (disco lleno, etc.) se desactiva
    a sí mismo y deja el error en `.error` sin romper la operación de tarjeta.

    Uso: ``tap.wrap(send)`` — mismo contrato que `SessionRecorder.wrap`.
    """

    def __init__(self, path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self.path.open("wb")
        self._fh.write(global_header())
        self._builder = PcapBuilder()
        self._lock = threading.Lock()
        self.exchanges = 0
        self.error: str | None = None

    def wrap(self, send: Transceiver) -> Transceiver:
        """Devuelve un `send` que graba cada intercambio y delega en `send`.
        Graba lo que **realmente** se envía: si el envoltorio se aplica como el
        más externo, los comandos ya mutados por el interceptor quedan reflejados.
        """

        def wrapped(command) -> Response:
            cmd_bytes = _to_bytes(command)
            t0 = time.time()
            try:
                resp = send(command)
            except Exception:
                self._write("cmd", cmd_bytes, t0)  # el comando se disparó igualmente
                raise
            t1 = time.time()
            self._write("cmd", cmd_bytes, t0)
            self._write("resp", resp.data + bytes((resp.sw1, resp.sw2)), t1)
            self.exchanges += 1
            return resp

        return wrapped

    def _write(self, direction: str, apdu: bytes, ts: float) -> None:
        if self.error is not None:
            return
        try:
            with self._lock:
                self._fh.write(self._builder.frame(direction, apdu, ts))
                self._fh.flush()
        except OSError as e:
            self.error = str(e)

    def record_wire_line(self, line: str) -> bool:
        """Graba una línea de wire del firmware de emulación del BomberCat.

        La emulación (NDEF o tarjeta EMV) no pasa APDUs por el host: el
        intercambio lo hace el firmware y EMVy solo lo ve como líneas de
        texto. El firmware reporta el APDU completo en hex como **último
        token**: ``EMU:RX <etiqueta> <hex>`` (comando del lector/POS,
        PCD→PICC) y ``EMU:TX <hex>`` (respuesta de la tarjeta emulada, con
        los SW incluidos, PICC→PCD). Devuelve True si la línea se grabó.
        """
        line = line.strip()
        if line.startswith("EMU:RX"):
            direction = "cmd"
        elif line.startswith("EMU:TX"):
            direction = "resp"
        else:
            return False
        token = line.rsplit(None, 1)[-1]
        try:
            apdu = bytes.fromhex(token)
        except ValueError:
            return False
        if not apdu:
            return False
        self._write(direction, apdu, time.time())
        if direction == "cmd":
            self.exchanges += 1
        return True

    def close(self) -> None:
        with self._lock:
            if not self._fh.closed:
                self._fh.close()

    @property
    def closed(self) -> bool:
        return self._fh.closed

    def __enter__(self) -> "PcapTap":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
