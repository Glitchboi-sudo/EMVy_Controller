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
    modules: tuple = ()          # AIDs de módulos ejecutables (solo en Load Files)


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


# Status words con los que la tarjeta indica que la escritura necesita un canal
# seguro / autenticación (→ escalar a GlobalPlatform).
SECURE_CHANNEL_SW = (0x6982, 0x6985)


@dataclass
class SmartWriteResult:
    """Resultado de `smart_write`: la `Response` final (directa o por canal
    seguro), si hizo falta el canal seguro, y un log legible del proceso."""
    response: Response
    secured: bool = False              # se usó GlobalPlatform
    protocol: str | None = None        # "02"/"03" si secured
    keyset: str | None = None
    log: list = field(default_factory=list)


def smart_write(send, write_fn, *, keyset=None, security_level: int = SEC_CMAC,
                sd_aid: bytes = b"", on_line=None) -> SmartWriteResult:
    """Escritura **inteligente**: intenta la escritura directa; si la tarjeta la
    rechaza pidiendo canal seguro (SW 6982/6985) y hay un `keyset`, abre
    GlobalPlatform (SELECT SD → INITIALIZE UPDATE → EXTERNAL AUTHENTICATE) y
    reintenta la escritura **envuelta** con C-MAC/C-ENC — todo en un paso, sin que
    el usuario decida de antemano entre escritura directa y GP.

    `write_fn(transceiver) -> Response` realiza la escritura sobre el transceiver
    que se le pase (el directo o el `chan.send` del canal seguro), p.ej.
    `lambda s: cardwrite.update_record(s, sfi, rec, data)`. Sin `keyset`, o si la
    tarjeta no exige canal seguro, devuelve la respuesta directa tal cual.
    """
    result = SmartWriteResult(response=None)  # type: ignore[arg-type]

    def log(msg: str) -> None:
        result.log.append(msg)
        if on_line:
            on_line(msg)

    r = write_fn(send)
    result.response = r
    if r.sw not in SECURE_CHANNEL_SW or keyset is None:
        if r.sw in SECURE_CHANNEL_SW and keyset is None:
            log("La tarjeta exige canal seguro pero no hay keyset seleccionado "
                "(añade uno con 'gp keyset add' y elígelo).")
        return result

    log(f"SW {r.sw:04X}: la tarjeta exige canal seguro → autenticando por "
        f"GlobalPlatform (keyset {keyset.name})…")
    try:
        chan = authenticate(send, keyset, security_level=security_level, sd_aid=sd_aid)
    except GPError as e:
        log(f"✗ GlobalPlatform: {e}")
        return result
    log(f"Canal seguro SCP{chan.protocol} abierto; reintentando la escritura…")
    r2 = write_fn(chan.send)
    result.response = r2
    result.secured = True
    result.protocol = chan.protocol
    result.keyset = keyset.name
    return result


def _lifecycle_name(scope: int, value: int) -> str:
    return _LIFECYCLE.get(value, f"0x{value:02X}")


def _parse_status(data: bytes) -> list:
    """Parsea la respuesta TLV de GET STATUS (plantillas E3 con 4F/9F70/C5)."""
    out = []
    for t in tlv.parse(data):
        if t.tag != "E3":            # TLV.tag es hex string, no int
            continue
        aid = life = priv = None
        modules = []
        for inner in tlv.parse(t.value):
            if inner.tag == "4F":
                aid = to_hex(inner.value)
            elif inner.tag == "9F70":
                life = inner.value[0] if inner.value else 0
            elif inner.tag == "C5":
                priv = to_hex(inner.value)
            elif inner.tag == "84":              # AID de un módulo ejecutable
                modules.append(to_hex(inner.value))
        if aid is not None:
            out.append(AppInfo(aid, _lifecycle_name(0, life or 0), priv or "",
                               tuple(modules)))
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


def list_modules(chan: SecureChannel) -> list:
    """Load Files (paquetes) con sus **módulos ejecutables** (AIDs instanciables).
    Igual que `get_status(STATUS_MODULES)` pero pensado para elegir qué instanciar:
    cada `AppInfo.modules` trae los AIDs que se pueden pasar a `install_instance`."""
    return get_status(chan, gpapdu.STATUS_MODULES)


def install_instance(chan: SecureChannel, package_aid: bytes, module_aid: bytes,
                     instance_aid: bytes, *, privileges: bytes = b"\x00",
                     params: bytes = b"", make_selectable: bool = True) -> Response:
    """INSTALL [for install (and make selectable)] de un **módulo ya cargado** en la
    tarjeta: crea una instancia seleccionable de un applet cuyo paquete ya está
    LOADED (p.ej. los applets EMV/Visa de fábrica, o uno recién cargado con un CAP
    abierto). No carga código nuevo — solo instancia. Devuelve la `Response` del
    INSTALL (SW 9000 = instancia creada).

    Para cargar **e** instanciar un CAP de una vez, usa `install_cap`."""
    apdu = gpapdu.install_for_install(package_aid, module_aid, instance_aid,
                                      privileges=privileges, params=params)
    if not make_selectable:                       # P1 sin el bit 'make selectable'
        import dataclasses
        apdu = dataclasses.replace(apdu, p1=0x04)
    r = chan.send(apdu)
    if not r.ok:
        raise GPError(f"INSTALL [for install] falló: {r.sw_hex} ({r.sw_str()})")
    return r


def delete(chan: SecureChannel, aid: bytes, related: bool = True) -> Response:
    """DELETE de un AID (por defecto también sus dependencias)."""
    r = chan.send(gpapdu.delete(aid, related=related))
    if not r.ok:
        raise GPError(f"DELETE {to_hex(aid)} falló: {r.sw_hex} ({r.sw_str()})")
    return r


def _has_sd_privilege(privileges_hex: str) -> bool:
    """True si el primer byte de privilegios tiene el bit de Security Domain (0x80)."""
    try:
        raw = bytes.fromhex(privileges_hex or "")
    except ValueError:
        return False
    return bool(raw) and bool(raw[0] & 0x80)


@dataclass
class WipeResult:
    deleted: list = field(default_factory=list)     # AIDs borrados (orden)
    kept: list = field(default_factory=list)        # AIDs conservados
    log: list = field(default_factory=list)


def restore_virgin(chan: SecureChannel, *, keep_aids=(), delete_packages: bool = False,
                   on_line=None) -> WipeResult:
    """Deja la tarjeta **'virgen'**: borra las **instancias de aplicación** que no
    sean el ISD, un Security Domain (privilegio 0x80) ni estén en `keep_aids`. Con
    `delete_packages=True` borra además los Load Files (paquetes) que no estén en
    `keep_aids` — **cuidado**: puede eliminar applets de fábrica (Visa/EMV cargados
    por el fabricante), dejando la tarjeta sin nada que instanciar.

    Pensado para revertir lo que instalamos/instanciamos y poder repetir el flujo
    de inicialización desde cero. Devuelve un `WipeResult` con lo borrado/conservado.
    """
    keep = {a.upper() for a in keep_aids}
    res = WipeResult()

    def log(m):
        res.log.append(m)
        if on_line:
            on_line(m)

    isd = {a.aid.upper() for a in get_status(chan, gpapdu.STATUS_ISD)}
    for app in get_status(chan, gpapdu.STATUS_APPS):
        aid = app.aid.upper()
        if aid in isd or aid in keep or _has_sd_privilege(app.privileges):
            res.kept.append(app.aid)
            log(f"conservar app {app.aid} ({app.lifecycle})")
            continue
        delete(chan, bytes.fromhex(aid), related=True)
        res.deleted.append(app.aid)
        log(f"DELETE app {app.aid} OK")

    if delete_packages:
        for pkg in get_status(chan, gpapdu.STATUS_LOAD_FILES):
            aid = pkg.aid.upper()
            if aid in isd or aid in keep:
                res.kept.append(pkg.aid)
                continue
            delete(chan, bytes.fromhex(aid), related=True)
            res.deleted.append(pkg.aid)
            log(f"DELETE paquete {pkg.aid} OK")

    log(f"Virgen: {len(res.deleted)} borrado(s), {len(res.kept)} conservado(s).")
    return res


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
