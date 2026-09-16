"""Keyset de GlobalPlatform (puro): las claves estáticas del Secure Channel de
una tarjeta (ENC / MAC / KEK) más su versión y protocolo.

Un keyset es el material que autentica el canal seguro con el Security Domain
(ISD) para gestionar contenido (LOAD/INSTALL/DELETE, STORE DATA). No hace IO ni
cripto — solo modela y valida el material de claves.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..hexutil import from_hex, to_hex

# Claves de prueba **públicas** de GlobalPlatform (keyset por defecto de muchas
# tarjetas de laboratorio/JCOP de desarrollo). NUNCA usar en producción.
DEFAULT_GP_KEY = "404142434445464748494A4B4C4D4E4F"

SCP_AUTO = "auto"
SCP02 = "02"
SCP03 = "03"


@dataclass(frozen=True)
class Keyset:
    """Material estático del Secure Channel de una tarjeta GP.

    `enc`/`mac`/`kek` son claves de 16 bytes (AES-128 para SCP03, o 3DES de
    doble longitud para SCP02) en hex. `kvn` es el Key Version Number (0 = dejar
    que la tarjeta elija el primero disponible). `scp` fija el protocolo o
    'auto' para detectarlo desde INITIALIZE UPDATE.
    """
    name: str
    enc: str
    mac: str
    kek: str
    kvn: int = 0
    scp: str = SCP_AUTO
    description: str = ""

    def __post_init__(self) -> None:
        for label, val in (("enc", self.enc), ("mac", self.mac), ("kek", self.kek)):
            raw = from_hex(val)            # valida hex; lanza si es inválido
            if len(raw) not in (16, 24):
                raise ValueError(
                    f"clave {label!r} de {len(raw)} bytes; se esperan 16 (AES-128/"
                    f"3DES-2key) o 24 (3DES-3key)")
        if self.scp not in (SCP_AUTO, SCP02, SCP03):
            raise ValueError(f"scp {self.scp!r} inválido (auto|02|03)")
        if not 0 <= self.kvn <= 0xFF:
            raise ValueError(f"kvn {self.kvn} fuera de rango (0..255)")

    # -- bytes de cada clave (derivación/uso por el motor SCP) --------------
    @property
    def enc_key(self) -> bytes:
        return from_hex(self.enc)

    @property
    def mac_key(self) -> bytes:
        return from_hex(self.mac)

    @property
    def kek_key(self) -> bytes:
        return from_hex(self.kek)

    def masked(self) -> dict:
        """Vista con las claves ofuscadas (para mostrar sin filtrar material)."""
        def mask(h: str) -> str:
            return h[:4] + "…" + h[-4:] if len(h) > 8 else "…"
        return {"name": self.name, "enc": mask(self.enc), "mac": mask(self.mac),
                "kek": mask(self.kek), "kvn": self.kvn, "scp": self.scp,
                "description": self.description}

    def to_dict(self) -> dict:
        return {"name": self.name, "enc": self.enc, "mac": self.mac, "kek": self.kek,
                "kvn": self.kvn, "scp": self.scp, "description": self.description}

    @classmethod
    def from_dict(cls, d: dict) -> "Keyset":
        return cls(
            name=d["name"], enc=d["enc"], mac=d["mac"], kek=d["kek"],
            kvn=int(d.get("kvn", 0)), scp=d.get("scp", SCP_AUTO),
            description=d.get("description", ""),
        )

    @classmethod
    def same_key(cls, name: str, key: str = DEFAULT_GP_KEY, **kw) -> "Keyset":
        """Keyset con la misma clave para ENC/MAC/KEK (caso común: las tres
        iguales, p.ej. el keyset por defecto de GP)."""
        return cls(name=name, enc=key, mac=key, kek=key, **kw)
