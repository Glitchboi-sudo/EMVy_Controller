"""Primitivas y derivación de claves del Secure Channel de GlobalPlatform
(SCP02 = 3DES, SCP03 = AES), puro salvo la dependencia de cripto (pycryptodome).

No hace IO: recibe retos/claves como bytes y devuelve bytes. El motor de canal
(`scp.py`) orquesta el intercambio de APDUs sobre un `Transceiver`.

Referencias: GlobalPlatform Card Spec 2.3 (SCP02) y Amendment D (SCP03).
"""
from __future__ import annotations

# --- utilidades comunes ----------------------------------------------------
def xor(a: bytes, b: bytes) -> bytes:
    return bytes(x ^ y for x, y in zip(a, b))


def pad80(data: bytes, block: int = 8) -> bytes:
    """Padding ISO 9797-1 método 2 / GP: 0x80 y luego 0x00 hasta bloque."""
    data = data + b"\x80"
    while len(data) % block:
        data += b"\x00"
    return data


def _des3_key(k: bytes) -> bytes:
    """Normaliza a clave 3DES de 24 bytes (EDE). 16→ k||k[:8] (2-key), 24 tal
    cual. Evita el rechazo de claves 'degeneradas' de pycryptodome."""
    if len(k) == 16:
        return k + k[:8]
    if len(k) == 24:
        return k
    raise ValueError(f"clave 3DES de {len(k)} bytes (se esperan 16 o 24)")


def des3_cbc_encrypt(key: bytes, data: bytes, iv: bytes = b"\x00" * 8) -> bytes:
    from Crypto.Cipher import DES3
    return DES3.new(_des3_key(key), DES3.MODE_CBC, iv).encrypt(data)


def des_retail_mac(key: bytes, data: bytes, iv: bytes = b"\x00" * 8) -> bytes:
    """MAC ISO 9797-1 Algoritmo 3 (retail MAC) con padding método 2 — el C-MAC
    de SCP02. Single-DES(k1) en cadena CBC y transformación final con k2."""
    from Crypto.Cipher import DES
    k1, k2 = key[:8], key[8:16]
    des1 = DES.new(k1, DES.MODE_ECB)
    des2 = DES.new(k2, DES.MODE_ECB)
    data = pad80(data, 8)
    h = iv
    for i in range(0, len(data), 8):
        h = des1.encrypt(xor(h, data[i:i + 8]))
    return des1.encrypt(des2.decrypt(h))   # final: dec k2, enc k1


def aes_cmac(key: bytes, data: bytes) -> bytes:
    from Crypto.Cipher import AES
    from Crypto.Hash import CMAC
    return CMAC.new(key, ciphermod=AES).update(data).digest()   # 16 bytes


def aes_ecb_encrypt(key: bytes, block: bytes) -> bytes:
    from Crypto.Cipher import AES
    return AES.new(key, AES.MODE_ECB).encrypt(block)


def aes_cbc_encrypt(key: bytes, data: bytes, iv: bytes = b"\x00" * 16) -> bytes:
    from Crypto.Cipher import AES
    return AES.new(key, AES.MODE_CBC, iv).encrypt(data)


def aes_cbc_decrypt(key: bytes, data: bytes, iv: bytes = b"\x00" * 16) -> bytes:
    from Crypto.Cipher import AES
    return AES.new(key, AES.MODE_CBC, iv).decrypt(data)


# ===========================================================================
# SCP02 (3DES)
# ===========================================================================
# Constantes de derivación (2 bytes) por tipo de clave de sesión.
_SCP02_ENC = b"\x01\x82"
_SCP02_MAC = b"\x01\x01"
_SCP02_DEK = b"\x01\x81"
_SCP02_RMAC = b"\x01\x02"


def _scp02_derive(static_key: bytes, const: bytes, seq: bytes) -> bytes:
    """Clave de sesión SCP02 = 3DES-CBC(static, IV=0, const||seq||0*12)."""
    data = const + seq + b"\x00" * 12
    return des3_cbc_encrypt(static_key, data)


def scp02_session_keys(enc: bytes, mac: bytes, dek: bytes, seq: bytes) -> dict:
    """Deriva las claves de sesión SCP02 desde las estáticas y el contador de
    secuencia (2 bytes) de la respuesta a INITIALIZE UPDATE."""
    return {
        "enc": _scp02_derive(enc, _SCP02_ENC, seq),
        "mac": _scp02_derive(mac, _SCP02_MAC, seq),
        "rmac": _scp02_derive(mac, _SCP02_RMAC, seq),
        "dek": _scp02_derive(dek, _SCP02_DEK, seq),
    }


def scp02_card_cryptogram(s_enc: bytes, host_chal: bytes, seq: bytes,
                          card_chal: bytes) -> bytes:
    """Criptograma de la tarjeta: 3DES-CBC de host||seq||card (con padding),
    último bloque, con la clave de sesión ENC."""
    data = pad80(host_chal + seq + card_chal, 8)
    return des3_cbc_encrypt(s_enc, data)[-8:]


def scp02_host_cryptogram(s_enc: bytes, seq: bytes, card_chal: bytes,
                          host_chal: bytes) -> bytes:
    """Criptograma del host: 3DES-CBC de seq||card||host (con padding)."""
    data = pad80(seq + card_chal + host_chal, 8)
    return des3_cbc_encrypt(s_enc, data)[-8:]


# ===========================================================================
# SCP03 (AES)
# ===========================================================================
# Constantes de derivación (1 byte) para la KDF (SP 800-108, modo contador).
_SCP03_ENC = 0x04
_SCP03_MAC = 0x06
_SCP03_RMAC = 0x07
_SCP03_CARD_CRYPTO = 0x00
_SCP03_HOST_CRYPTO = 0x01


def scp03_kdf(key: bytes, const: int, context: bytes, outlen_bits: int) -> bytes:
    """KDF de SCP03 (NIST SP 800-108 en modo contador con CMAC-AES).

    Datos por bloque: label(11×00 || const) || 0x00 || L(2) || i(1) || context.
    """
    out = b""
    i = 1
    label = b"\x00" * 11 + bytes([const])
    l_bytes = outlen_bits.to_bytes(2, "big")
    while len(out) * 8 < outlen_bits:
        block = label + b"\x00" + l_bytes + bytes([i]) + context
        out += aes_cmac(key, block)
        i += 1
    return out[: outlen_bits // 8]


def scp03_session_keys(enc: bytes, mac: bytes, host_chal: bytes,
                       card_chal: bytes) -> dict:
    """Deriva S-ENC/S-MAC/S-RMAC (AES-128) desde las claves estáticas y los
    retos (contexto = host||card)."""
    ctx = host_chal + card_chal
    return {
        "enc": scp03_kdf(enc, _SCP03_ENC, ctx, 128),
        "mac": scp03_kdf(mac, _SCP03_MAC, ctx, 128),
        "rmac": scp03_kdf(mac, _SCP03_RMAC, ctx, 128),
    }


def scp03_card_cryptogram(s_mac: bytes, host_chal: bytes, card_chal: bytes) -> bytes:
    return scp03_kdf(s_mac, _SCP03_CARD_CRYPTO, host_chal + card_chal, 64)


def scp03_host_cryptogram(s_mac: bytes, host_chal: bytes, card_chal: bytes) -> bytes:
    return scp03_kdf(s_mac, _SCP03_HOST_CRYPTO, host_chal + card_chal, 64)


def scp03_icv(s_enc: bytes, counter: int, response: bool = False) -> bytes:
    """ICV de cifrado SCP03: AES-ECB(S-ENC, contador de 16 bytes). Para la
    respuesta, el bit más significativo del bloque se pone a 1."""
    block = counter.to_bytes(16, "big")
    if response:
        block = bytes([block[0] | 0x80]) + block[1:]
    return aes_ecb_encrypt(s_enc, block)
