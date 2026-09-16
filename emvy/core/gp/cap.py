"""Parseo de ficheros CAP de JavaCard (puro).

Un `.cap` es un ZIP/JAR con los *componentes* (`Header.cap`, `Directory.cap`,
`Applet.cap`, `Class.cap`, `Method.cap`, …). Para cargarlo con GlobalPlatform hay
que concatenar los componentes en el **orden de carga** canónico y anteponer el
tag `C4` con la longitud → *Load File Data Block* que se trocea en comandos LOAD.

Extrae también el **AID del paquete** (de `Header.cap`) y los **AID de applet**
(de `Applet.cap`), necesarios para INSTALL [for load] / [for install].
"""
from __future__ import annotations

import zipfile
from dataclasses import dataclass, field

from ..hexutil import to_hex

# Orden de carga de los componentes (GlobalPlatform / JavaCard). `Debug` NUNCA se
# carga; el resto presentes se concatenan en este orden.
_LOAD_ORDER = ["Header", "Directory", "Import", "Applet", "Class", "Method",
               "StaticField", "Export", "ConstantPool", "RefLocation", "Descriptor"]


def _ber_len(n: int) -> bytes:
    if n < 0x80:
        return bytes([n])
    if n < 0x100:
        return bytes([0x81, n])
    if n < 0x10000:
        return bytes([0x82, n >> 8, n & 0xFF])
    return bytes([0x83, n >> 16, (n >> 8) & 0xFF, n & 0xFF])


@dataclass(frozen=True)
class CapFile:
    """CAP parseado: componentes por nombre, AID del paquete y AIDs de applet."""
    components: dict            # nombre -> bytes
    package_aid: bytes
    applet_aids: list = field(default_factory=list)

    @property
    def package_aid_hex(self) -> str:
        return to_hex(self.package_aid)

    def load_file(self) -> bytes:
        """Componentes concatenados en orden de carga (sin el tag C4)."""
        return b"".join(self.components[name] for name in _LOAD_ORDER
                        if name in self.components)

    def load_file_data_block(self) -> bytes:
        """Bloque para LOAD: `C4 <len> <load file>`."""
        lf = self.load_file()
        return b"\xc4" + _ber_len(len(lf)) + lf

    def load_blocks(self, block_size: int = 0xE0) -> list:
        """Trocea el Load File Data Block en fragmentos para comandos LOAD
        (deja margen para el C-MAC del canal seguro)."""
        blob = self.load_file_data_block()
        return [blob[i:i + block_size] for i in range(0, len(blob), block_size)]


def _parse_header_aid(header: bytes) -> bytes:
    """AID del paquete desde Header.cap: tras tag(1)+size(2)+magic(4)+minor(1)+
    major(1)+flags(1)+pkg.minor(1)+pkg.major(1) viene AID_length(1)+AID."""
    if len(header) < 13 or header[0] != 0x01:
        raise ValueError("Header.cap inválido")
    aid_len = header[12]
    return header[13:13 + aid_len]


def _parse_applet_aids(applet: bytes) -> list:
    """AIDs de applet desde Applet.cap: tag(1)+size(2)+count(1), luego por cada
    uno AID_length(1)+AID+install_method_offset(2)."""
    if len(applet) < 4 or applet[0] != 0x03:
        return []
    count = applet[3]
    out, off = [], 4
    for _ in range(count):
        aid_len = applet[off]
        out.append(applet[off + 1:off + 1 + aid_len])
        off += 1 + aid_len + 2
    return out


def parse_cap(path) -> CapFile:
    """Parsea un `.cap` en disco (o un objeto ruta) a `CapFile`."""
    components: dict = {}
    with zipfile.ZipFile(path) as zf:
        for entry in zf.namelist():
            base = entry.rsplit("/", 1)[-1]
            if not base.lower().endswith(".cap"):
                continue
            name = base[:-4]                      # sin extensión
            if name in _LOAD_ORDER or name == "Debug":
                components[name] = zf.read(entry)
    if "Header" not in components:
        raise ValueError("el CAP no contiene Header.cap (¿formato no soportado?)")
    package_aid = _parse_header_aid(components["Header"])
    applet_aids = _parse_applet_aids(components.get("Applet", b""))
    return CapFile(components=components, package_aid=package_aid, applet_aids=applet_aids)
