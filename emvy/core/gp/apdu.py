"""Constructores de comandos de GlobalPlatform (puro). Devuelven `APDU` de
`core.apdu`; el envoltorio de canal seguro (C-MAC/C-ENC) lo aplica `scp.py`.

Comandos: SELECT (ISD), INITIALIZE UPDATE, GET STATUS, DELETE, INSTALL [for
load] / [for install and make selectable], LOAD, STORE DATA.
"""
from __future__ import annotations

from ..apdu import APDU

# GET STATUS P1 (ámbito de la consulta).
STATUS_ISD = 0x80            # Issuer Security Domain
STATUS_APPS = 0x40           # aplicaciones + SDs
STATUS_LOAD_FILES = 0x20     # Executable Load Files
STATUS_MODULES = 0x10        # Executable Load Files + módulos


def _lv(data: bytes) -> bytes:
    """Campo longitud(1)||valor (Length-Value de GP)."""
    return bytes([len(data)]) + data


def select(aid: bytes = b"") -> APDU:
    """SELECT de un Security Domain / applet (AID vacío = ISD por defecto)."""
    return APDU(0x00, 0xA4, 0x04, 0x00, aid, le=0)


def initialize_update(host_challenge: bytes, kvn: int = 0, key_id: int = 0) -> APDU:
    return APDU(0x80, 0x50, kvn, key_id, host_challenge, le=0)


def get_status(p1: int = STATUS_APPS, tag_list: bytes = b"\x4f\x00",
               next_occurrence: bool = False) -> APDU:
    """GET STATUS. P2 bit0=formato TLV(0x02); bit1=siguiente ocurrencia(0x01)."""
    p2 = 0x02 | (0x01 if next_occurrence else 0x00)
    return APDU(0x80, 0xF2, p1, p2, tag_list, le=0)


def delete(aid: bytes, related: bool = False) -> APDU:
    """DELETE de un objeto por AID. `related=True` (P2=0x80) borra también los
    objetos dependientes (p.ej. un paquete y sus instancias)."""
    return APDU(0x80, 0xE4, 0x00, 0x80 if related else 0x00, b"\x4f" + _lv(aid), le=0)


def install_for_load(load_file_aid: bytes, sd_aid: bytes = b"") -> APDU:
    """INSTALL [for load]: prepara la carga de un paquete (Load File)."""
    data = _lv(load_file_aid) + _lv(sd_aid) + _lv(b"") + _lv(b"") + _lv(b"")
    return APDU(0x80, 0xE6, 0x02, 0x00, data, le=0)


def install_for_install(package_aid: bytes, module_aid: bytes, instance_aid: bytes,
                        privileges: bytes = b"\x00", params: bytes = b"") -> APDU:
    """INSTALL [for install and make selectable] (P1=0x0C): instancia un applet.

    `params` son los parámetros específicos de la aplicación (se envuelven en el
    tag C9)."""
    app_params = b"\xc9" + bytes([len(params)]) + params
    data = (_lv(package_aid) + _lv(module_aid) + _lv(instance_aid)
            + _lv(privileges) + _lv(app_params) + _lv(b""))   # token vacío
    return APDU(0x80, 0xE6, 0x0C, 0x00, data, le=0)


def load(block_number: int, data: bytes, last: bool) -> APDU:
    """LOAD de un bloque del Load File Data Block. P1=0x80 en el último bloque."""
    return APDU(0x80, 0xE8, 0x80 if last else 0x00, block_number & 0xFF, data, le=0)


def store_data(data: bytes, block_number: int = 0, last: bool = True,
               p1_flags: int = 0x00) -> APDU:
    """STORE DATA. P1 bit7=último bloque(0x80), bits de formato en `p1_flags`."""
    p1 = p1_flags | (0x80 if last else 0x00)
    return APDU(0x80, 0xE2, p1, block_number & 0xFF, data, le=0)
