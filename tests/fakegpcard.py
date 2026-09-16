"""Tarjeta GlobalPlatform simulada (un `Transceiver` falso) para probar el
Secure Channel sin hardware: implementa INITIALIZE UPDATE, EXTERNAL AUTHENTICATE
y la verificación de C-MAC de comandos envueltos, en SCP02 y SCP03.

Usa las mismas primitivas de `core.gp.crypto` que el cliente: valida el flujo del
protocolo, el parseo, la cadena de MAC y la envoltura (que ambos lados encajan).
La corrección frente al spec la ancla RFC 4493 (CMAC) + la tarjeta real.
"""
from __future__ import annotations

from Crypto.Cipher import DES

from emvy.core.apdu import Response
from emvy.core.gp import crypto

# Plantilla GET STATUS de ejemplo: un applet SELECTABLE.
_STATUS = bytes.fromhex("E30D4F07A0000000030000" + "9F70010F")


class FakeGPCard:
    def __init__(self, enc: bytes, mac: bytes, dek: bytes, *, protocol: str = "03",
                 kvn: int = 0, card_challenge: bytes | None = None,
                 icv_encryption: bool = True):
        self.enc, self.mac, self.dek = enc, mac, dek
        self.protocol, self.kvn, self.icv_encryption = protocol, kvn, icv_encryption
        self.card_challenge = card_challenge or (b"\x11" * (8 if protocol == "03" else 6))
        self.seq = b"\x00\x2a"
        self.host_challenge = None
        self.skeys = None
        self.mac_chain = b"\x00" * 16     # SCP03
        self.cmac_icv = b"\x00" * 8       # SCP02
        self.authenticated = False

    def __call__(self, apdu) -> Response:
        b = apdu.to_bytes() if hasattr(apdu, "to_bytes") else bytes(apdu)
        cla, ins, p1, p2 = b[0], b[1], b[2], b[3]

        if ins == 0xA4:                    # SELECT
            return Response(b"", 0x90, 0x00)

        if ins == 0x50:                    # INITIALIZE UPDATE (resetea el canal)
            self.mac_chain = b"\x00" * 16
            self.cmac_icv = b"\x00" * 8
            self.authenticated = False
            self.host_challenge = b[5:5 + b[4]]
            if self.protocol == "03":
                self.skeys = crypto.scp03_session_keys(
                    self.enc, self.mac, self.host_challenge, self.card_challenge)
                cc = crypto.scp03_card_cryptogram(
                    self.skeys["mac"], self.host_challenge, self.card_challenge)
                resp = b"\x00" * 10 + bytes([self.kvn, 0x03, 0x60]) + self.card_challenge + cc
            else:
                self.skeys = crypto.scp02_session_keys(
                    self.enc, self.mac, self.dek, self.seq)
                cc = crypto.scp02_card_cryptogram(
                    self.skeys["enc"], self.host_challenge, self.seq, self.card_challenge)
                resp = (b"\x00" * 10 + bytes([self.kvn, 0x02]) + self.seq
                        + self.card_challenge + cc)
            return Response(resp, 0x90, 0x00)

        if ins == 0x82:                    # EXTERNAL AUTHENTICATE
            data = b[5:5 + b[4]]
            host_crypto, mac = data[:8], data[8:16]
            header = b[0:5]
            if self.protocol == "03":
                exp = crypto.scp03_host_cryptogram(
                    self.skeys["mac"], self.host_challenge, self.card_challenge)
                full = crypto.aes_cmac(self.skeys["mac"], self.mac_chain + header + host_crypto)
                ok = host_crypto == exp and mac == full[:8]
                if ok:
                    self.mac_chain = full
            else:
                exp = crypto.scp02_host_cryptogram(
                    self.skeys["enc"], self.seq, self.card_challenge, self.host_challenge)
                m = crypto.des_retail_mac(self.skeys["mac"], header + host_crypto)
                ok = host_crypto == exp and mac == m
                if ok:
                    self.cmac_icv = m
            if not ok:
                return Response(b"", 0x63, 0x00)
            self.authenticated = True
            return Response(b"", 0x90, 0x00)

        if cla & 0x04:                     # comando envuelto (C-MAC)
            lc = b[4]
            body = b[5:5 + lc]
            cmd_data, mac = body[:-8], body[-8:]
            header = b[0:5]
            if self.protocol == "03":
                full = crypto.aes_cmac(self.skeys["mac"], self.mac_chain + header + cmd_data)
                if mac != full[:8]:
                    return Response(b"", 0x69, 0x82)
                self.mac_chain = full
            else:
                icv = self.cmac_icv
                if self.icv_encryption and icv != b"\x00" * 8:
                    icv = DES.new(self.skeys["mac"][:8], DES.MODE_ECB).encrypt(icv)
                m = crypto.des_retail_mac(self.skeys["mac"], header + cmd_data, iv=icv)
                if mac != m:
                    return Response(b"", 0x69, 0x82)
                self.cmac_icv = m
            if ins == 0xF2:                # GET STATUS
                return Response(_STATUS, 0x90, 0x00)
            return Response(b"", 0x90, 0x00)   # DELETE/INSTALL/LOAD/STORE DATA

        return Response(b"", 0x6D, 0x00)
