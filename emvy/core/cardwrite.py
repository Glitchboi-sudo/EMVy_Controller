"""Escritura en tarjetas ISO 7816 / EMV sobre un `Transceiver` (efecto sobre la
tarjeta, no sobre disco). Envuelve los constructores de APDU de escritura y
traduce el status word.

**Cuidado**: escribir modifica la tarjeta de forma potencialmente irreversible y
suele requerir un canal seguro/autenticación (SW 6982/6985). Usar solo con
tarjetas propias/de laboratorio y con autorización.
"""
from __future__ import annotations

from . import apdu as apdumod
from .apdu import Response, Transceiver

WRITE_SW = {
    0x9000: "OK",
    0x6200: "aviso: sin cambios",
    0x6581: "fallo de memoria al escribir",
    0x6700: "longitud (Lc) incorrecta",
    0x6982: "seguridad no satisfecha (requiere autenticación/canal seguro)",
    0x6985: "condiciones de uso no satisfechas",
    0x6986: "no hay EF actual seleccionado",
    0x6A82: "fichero/registro no encontrado",
    0x6A84: "sin espacio en el fichero",
    0x6A86: "parámetros P1-P2 incorrectos",
    0x6B00: "offset/parámetros fuera de rango",
    0x6D00: "instrucción (INS) no soportada por la tarjeta",
    0x6E00: "clase (CLA) no soportada",
}


def write_status(sw: int) -> str:
    if sw in WRITE_SW:
        return WRITE_SW[sw]
    if (sw >> 8) == 0x63:
        return f"aviso/contador ({sw & 0xFF} intentos)"
    return f"SW {sw:04X}"


# Pistas accionables para los status words de escritura más habituales, en
# lenguaje llano (para la UI: qué hacer a continuación). Presentación pura.
def write_hint(sw: int) -> str | None:
    if sw == 0x9000:
        return None
    if sw in (0x6982, 0x6985):
        return ("La tarjeta exige canal seguro/autenticación para escribir. Si es "
                "una JavaCard/GlobalPlatform en blanco, primero instala/personaliza "
                "un applet EMV vía GlobalPlatform (sección de abajo).")
    if sw == 0x6986:
        return ("No hay fichero (EF) seleccionado. Selecciona antes una aplicación "
                "EMV (Explorador → Capturar) o usa una tarjeta ya personalizada.")
    if sw in (0x6A82, 0x6A83):
        return "El fichero/registro no existe en la tarjeta — prueba otro SFI/registro."
    if sw == 0x6A84:
        return "No queda espacio en el fichero para ese registro."
    if sw == 0x6700:
        return "Longitud de datos incorrecta para ese registro/fichero."
    return None


def update_record(send: Transceiver, sfi: int, record: int, data: bytes) -> Response:
    return send(apdumod.update_record(record, sfi, data))


def write_record(send: Transceiver, sfi: int, record: int, data: bytes) -> Response:
    return send(apdumod.write_record(record, sfi, data))


def append_record(send: Transceiver, sfi: int, data: bytes) -> Response:
    return send(apdumod.append_record(sfi, data))


def update_binary(send: Transceiver, offset: int, data: bytes,
                  sfi: int | None = None) -> Response:
    return send(apdumod.update_binary(offset, data, sfi))


def put_data(send: Transceiver, tag: int, data: bytes) -> Response:
    return send(apdumod.put_data(tag, data))
