"""Secure Channel de GlobalPlatform sobre un `Transceiver`.

`open_secure_channel(send, keyset, ...)` ejecuta INITIALIZE UPDATE + EXTERNAL
AUTHENTICATE (autodetectando SCP02/SCP03), verifica el criptograma de la tarjeta
y devuelve un `SecureChannel` que **envuelve** cada APDU con C-MAC (y C-ENC si el
nivel de seguridad lo pide) para el resto de la sesión.

El `send` es un `core.apdu.Transceiver` (resuelve 61xx/6Cxx por debajo). El canal
solo añade la mensajería segura por encima.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from ..apdu import APDU, Response
from . import apdu as gpapdu
from . import crypto
from .keyset import SCP02, SCP03, SCP_AUTO, Keyset

# Niveles de seguridad (P1 de EXTERNAL AUTHENTICATE / envoltura).
SEC_CMAC = 0x01              # C-MAC
SEC_CENC = 0x03             # C-DECRYPTION + C-MAC


class GPError(RuntimeError):
    pass


@dataclass
class SecureChannel:
    """Canal seguro abierto. Mantiene el estado de mensajería (cadena de MAC /
    contador de cifrado) y envuelve/manda APDUs con `send`."""
    send_raw: "callable"        # Transceiver subyacente
    protocol: str               # "02" | "03"
    skeys: dict                 # claves de sesión (enc/mac/rmac[/dek])
    security_level: int = SEC_CMAC
    # estado SCP03
    _mac_chain: bytes = b"\x00" * 16
    _enc_ctr: int = 1
    # estado SCP02
    _cmac_icv: bytes = b"\x00" * 8
    icv_encryption: bool = True

    # -- envoltura ----------------------------------------------------------
    def wrap(self, apdu: APDU) -> APDU:
        return self._wrap03(apdu) if self.protocol == SCP03 else self._wrap02(apdu)

    def _wrap03(self, apdu: APDU) -> APDU:
        cla = apdu.cla | 0x04
        data = apdu.data
        if self.security_level & 0x02 and data:            # C-DECRYPTION
            icv = crypto.scp03_icv(self.skeys["enc"], self._enc_ctr)
            data = crypto.aes_cbc_encrypt(self.skeys["enc"], crypto.pad80(data, 16), icv)
        self._enc_ctr += 1
        lc = len(data) + 8
        header = bytes([cla, apdu.ins, apdu.p1, apdu.p2, lc])
        full = crypto.aes_cmac(self.skeys["mac"], self._mac_chain + header + data)
        self._mac_chain = full
        return APDU(cla, apdu.ins, apdu.p1, apdu.p2, data + full[:8], le=apdu.le)

    def _wrap02(self, apdu: APDU) -> APDU:
        from Crypto.Cipher import DES
        cla = apdu.cla | 0x04
        icv = self._cmac_icv
        if self.icv_encryption and icv != b"\x00" * 8:
            icv = DES.new(self.skeys["mac"][:8], DES.MODE_ECB).encrypt(icv)
        data = apdu.data
        lc = len(data) + 8
        header = bytes([cla, apdu.ins, apdu.p1, apdu.p2, lc])
        mac = crypto.des_retail_mac(self.skeys["mac"], header + data, iv=icv)
        self._cmac_icv = mac
        if self.security_level & 0x02 and data:            # C-DECRYPTION (3DES)
            data = crypto.des3_cbc_encrypt(self.skeys["enc"], crypto.pad80(data, 8))
        return APDU(cla, apdu.ins, apdu.p1, apdu.p2, data + mac, le=apdu.le)

    def send(self, apdu: APDU) -> Response:
        """Envuelve y manda un APDU por el canal seguro."""
        return self.send_raw(self.wrap(apdu))


def _parse_init_update(resp: bytes) -> dict:
    """Descompone la respuesta a INITIALIZE UPDATE (autodetecta SCP02/03)."""
    if len(resp) < 13:
        raise GPError(f"respuesta de INITIALIZE UPDATE corta ({len(resp)} bytes)")
    scp = resp[11]
    if scp == 0x02:
        return {"scp": SCP02, "key_div": resp[0:10], "kvn": resp[10],
                "seq": resp[12:14], "card_challenge": resp[14:20],
                "card_cryptogram": resp[20:28]}
    if scp == 0x03:
        return {"scp": SCP03, "key_div": resp[0:10], "kvn": resp[10], "i": resp[12],
                "card_challenge": resp[13:21], "card_cryptogram": resp[21:29]}
    raise GPError(f"protocolo SCP no soportado: 0x{scp:02X}")


def open_secure_channel(send, keyset: Keyset, *, security_level: int = SEC_CMAC,
                        host_challenge: bytes | None = None) -> SecureChannel:
    """Abre el canal seguro con el ISD ya seleccionado. Lanza `GPError` si el
    criptograma de la tarjeta no valida (claves incorrectas) o la tarjeta rechaza
    la autenticación."""
    host_challenge = host_challenge or os.urandom(8)

    r = send(gpapdu.initialize_update(host_challenge, kvn=keyset.kvn))
    if not r.ok:
        raise GPError(f"INITIALIZE UPDATE falló: {r.sw_hex} ({r.sw_str()})")
    info = _parse_init_update(r.data)
    if keyset.scp != SCP_AUTO and keyset.scp != info["scp"]:
        raise GPError(f"la tarjeta usa SCP{info['scp']} pero el keyset dice SCP{keyset.scp}")

    if info["scp"] == SCP03:
        skeys = crypto.scp03_session_keys(keyset.enc_key, keyset.mac_key,
                                          host_challenge, info["card_challenge"])
        expect = crypto.scp03_card_cryptogram(skeys["mac"], host_challenge,
                                              info["card_challenge"])
        if expect != info["card_cryptogram"]:
            raise GPError("criptograma de tarjeta inválido (¿claves incorrectas?)")
        host_crypto = crypto.scp03_host_cryptogram(skeys["mac"], host_challenge,
                                                   info["card_challenge"])
        chan = SecureChannel(send, SCP03, skeys, security_level)
        _external_authenticate(chan, host_crypto, security_level)
        return chan

    # SCP02
    skeys = crypto.scp02_session_keys(keyset.enc_key, keyset.mac_key, keyset.kek_key,
                                      info["seq"])
    expect = crypto.scp02_card_cryptogram(skeys["enc"], host_challenge, info["seq"],
                                          info["card_challenge"])
    if expect != info["card_cryptogram"]:
        raise GPError("criptograma de tarjeta inválido (¿claves incorrectas?)")
    host_crypto = crypto.scp02_host_cryptogram(skeys["enc"], info["seq"],
                                               info["card_challenge"], host_challenge)
    chan = SecureChannel(send, SCP02, skeys, security_level)
    _external_authenticate(chan, host_crypto, security_level)
    return chan


def _external_authenticate(chan: SecureChannel, host_crypto: bytes, level: int) -> None:
    """EXTERNAL AUTHENTICATE: siempre lleva C-MAC (ICV/cadena inicial = ceros).
    Deja el estado de mensajería listo para el resto de la sesión."""
    cla, ins, p1, p2 = 0x84, 0x82, level, 0x00
    lc = len(host_crypto) + 8
    header = bytes([cla, ins, p1, p2, lc])
    if chan.protocol == SCP03:
        full = crypto.aes_cmac(chan.skeys["mac"], chan._mac_chain + header + host_crypto)
        chan._mac_chain = full
        mac = full[:8]
    else:
        mac = crypto.des_retail_mac(chan.skeys["mac"], header + host_crypto)
        chan._cmac_icv = mac
    r = chan.send_raw(APDU(cla, ins, p1, p2, host_crypto + mac))
    if not r.ok:
        raise GPError(f"EXTERNAL AUTHENTICATE falló: {r.sw_hex} ({r.sw_str()})")
