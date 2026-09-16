"""Operaciones de alto nivel de gestión de contenido GlobalPlatform, sobre un
canal seguro ya abierto (o abriéndolo): autenticar, listar (GET STATUS), borrar
(DELETE) e instalar un CAP (INSTALL [for load] → LOAD → INSTALL [for install]).

Todo se apoya en `scp.SecureChannel` (envoltura C-MAC/C-ENC) y `apdu`/`cap`. Puro
salvo el `send` inyectado.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .. import tlv
from ..apdu import Response
from ..hexutil import to_hex
from . import apdu as gpapdu
from .cap import CapFile
from .scp import GPError, SecureChannel, SEC_CMAC, open_secure_channel

# Ciclo de vida (lifecycle) de aplicaciones/paquetes (valores comunes GP).
_LIFECYCLE = {0x01: "LOADED", 0x03: "INSTALLED", 0x07: "SELECTABLE",
              0x0F: "PERSONALIZED", 0x83: "LOCKED", 0x7F: "LOCKED"}


@dataclass(frozen=True)
class AppInfo:
    aid: str
    lifecycle: str
    privileges: str = ""


@dataclass
class InstallResult:
    load_blocks: int = 0
    package_aid: str = ""
    instance_aid: str = ""
    steps: list = field(default_factory=list)   # (paso, sw_hex)


def authenticate(send, keyset, *, security_level: int = SEC_CMAC,
                 sd_aid: bytes = b"", host_challenge: bytes | None = None) -> SecureChannel:
    """Selecciona el Security Domain (ISD por defecto) y abre el canal seguro."""
    r = send(gpapdu.select(sd_aid))
    if not r.ok:
        raise GPError(f"SELECT del SD falló: {r.sw_hex} ({r.sw_str()})")
    return open_secure_channel(send, keyset, security_level=security_level,
                               host_challenge=host_challenge)


def _lifecycle_name(scope: int, value: int) -> str:
    return _LIFECYCLE.get(value, f"0x{value:02X}")


def _parse_status(data: bytes) -> list:
    """Parsea la respuesta TLV de GET STATUS (plantillas E3 con 4F/9F70/C5)."""
    out = []
    for t in tlv.parse(data):
        if t.tag != "E3":            # TLV.tag es hex string, no int
            continue
        aid = life = priv = None
        for inner in tlv.parse(t.value):
            if inner.tag == "4F":
                aid = to_hex(inner.value)
            elif inner.tag == "9F70":
                life = inner.value[0] if inner.value else 0
            elif inner.tag == "C5":
                priv = to_hex(inner.value)
        if aid is not None:
            out.append(AppInfo(aid, _lifecycle_name(0, life or 0), priv or ""))
    return out


def get_status(chan: SecureChannel, p1: int) -> list:
    """GET STATUS de un ámbito (STATUS_ISD/APPS/LOAD_FILES/MODULES), siguiendo las
    'siguientes ocurrencias' (SW=6310) hasta agotarlas.

    Acumula los bytes crudos de todas las páginas y parsea **una sola vez**: la
    tarjeta puede partir un template `E3` justo en el corte de página (6310), así
    que parsear por chunk perdería esa entrada."""
    raw, first = b"", True
    while True:
        r = chan.send(gpapdu.get_status(p1, next_occurrence=not first))
        first = False
        raw += r.data
        if r.sw == 0x6310:      # hay más → siguiente ocurrencia
            continue
        if r.ok or r.sw == 0x6A88:   # 6A88 = no hay nada en ese ámbito
            break
        raise GPError(f"GET STATUS falló: {r.sw_hex} ({r.sw_str()})")
    return _parse_status(raw)


def list_all(chan: SecureChannel) -> dict:
    """Inventario completo: ISD, aplicaciones/SDs y paquetes (load files)."""
    return {
        "isd": get_status(chan, gpapdu.STATUS_ISD),
        "apps": get_status(chan, gpapdu.STATUS_APPS),
        "load_files": get_status(chan, gpapdu.STATUS_MODULES),
    }


def delete(chan: SecureChannel, aid: bytes, related: bool = True) -> Response:
    """DELETE de un AID (por defecto también sus dependencias)."""
    r = chan.send(gpapdu.delete(aid, related=related))
    if not r.ok:
        raise GPError(f"DELETE {to_hex(aid)} falló: {r.sw_hex} ({r.sw_str()})")
    return r


def install_cap(chan: SecureChannel, cap: CapFile, *, instance_aid: bytes | None = None,
                module_aid: bytes | None = None, privileges: bytes = b"\x00",
                params: bytes = b"", make_selectable: bool = True,
                force: bool = False, block_size: int = 0xE0) -> InstallResult:
    """Carga e instala un CAP: INSTALL [for load] → LOAD (troceado) → INSTALL
    [for install and make selectable]. Con `force`, borra antes el paquete
    existente (y sus instancias)."""
    res = InstallResult(package_aid=cap.package_aid_hex)

    if force:
        try:
            delete(chan, cap.package_aid, related=True)
            res.steps.append(("delete-previo", "9000"))
        except GPError:
            res.steps.append(("delete-previo", "n/a"))

    r = chan.send(gpapdu.install_for_load(cap.package_aid))
    res.steps.append(("install-for-load", r.sw_hex))
    if not r.ok:
        raise GPError(f"INSTALL [for load] falló: {r.sw_hex} ({r.sw_str()})")

    blocks = cap.load_blocks(block_size)
    for i, block in enumerate(blocks):
        r = chan.send(gpapdu.load(i, block, last=(i == len(blocks) - 1)))
        if not r.ok:
            raise GPError(f"LOAD bloque {i} falló: {r.sw_hex} ({r.sw_str()})")
    res.load_blocks = len(blocks)
    res.steps.append(("load", f"{len(blocks)} bloques"))

    if make_selectable:
        module = module_aid or (cap.applet_aids[0] if cap.applet_aids else None)
        if module is None:
            raise GPError("el CAP no tiene applets; nada que instanciar "
                          "(usa make_selectable=False para solo cargar el paquete)")
        instance = instance_aid or module
        r = chan.send(gpapdu.install_for_install(cap.package_aid, module, instance,
                                                 privileges=privileges, params=params))
        res.steps.append(("install-for-install", r.sw_hex))
        if not r.ok:
            raise GPError(f"INSTALL [for install] falló: {r.sw_hex} ({r.sw_str()})")
        res.instance_aid = to_hex(instance)
    return res
