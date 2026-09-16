"""GlobalPlatform: keysets, cripto SCP02/SCP03. La cripto se ancla a vectores
conocidos (AES-CMAC de RFC 4493) y a propiedades estructurales; la validación
end-to-end del canal es contra la tarjeta real (JCOP)."""
from emvy.core.gp import crypto
from emvy.core.gp.keyset import DEFAULT_GP_KEY, Keyset
from emvy.core.hexutil import from_hex, to_hex


# --- keyset ----------------------------------------------------------------
def test_keyset_roundtrip_and_validation():
    k = Keyset.same_key("def")               # 404142… en las tres
    assert k.enc_key == from_hex(DEFAULT_GP_KEY)
    assert Keyset.from_dict(k.to_dict()) == k
    assert k.masked()["enc"].endswith("4E4F")

    import pytest
    with pytest.raises(ValueError):
        Keyset(name="x", enc="ZZ", mac=DEFAULT_GP_KEY, kek=DEFAULT_GP_KEY)
    with pytest.raises(ValueError):
        Keyset(name="x", enc="4041", mac=DEFAULT_GP_KEY, kek=DEFAULT_GP_KEY)  # 2 bytes


# --- AES-CMAC contra RFC 4493 (ancla el motor CMAC) ------------------------
def test_aes_cmac_rfc4493():
    key = from_hex("2b7e151628aed2a6abf7158809cf4f3c")
    assert to_hex(crypto.aes_cmac(key, b"")) == "BB1D6929E95937287FA37D129B756746"
    msg = from_hex("6bc1bee22e409f96e93d7e117393172a")
    assert to_hex(crypto.aes_cmac(key, msg)) == "070A16B46B4D4144F79BDD9DD04A287C"


# --- SCP03 -----------------------------------------------------------------
def test_scp03_kdf_lengths_and_determinism():
    key = from_hex(DEFAULT_GP_KEY)
    ctx = from_hex("00112233445566778899AABBCCDDEEFF")
    k128 = crypto.scp03_kdf(key, 0x04, ctx, 128)
    k64 = crypto.scp03_kdf(key, 0x00, ctx, 64)
    assert len(k128) == 16 and len(k64) == 8
    assert crypto.scp03_kdf(key, 0x04, ctx, 128) == k128       # determinista
    # distinta constante → distinta salida
    assert crypto.scp03_kdf(key, 0x06, ctx, 128) != k128


def test_scp03_session_and_cryptograms_distinct():
    enc = mac = from_hex(DEFAULT_GP_KEY)
    host, card = from_hex("0102030405060708"), from_hex("1122334455667788")
    sk = crypto.scp03_session_keys(enc, mac, host, card)
    assert {len(sk[x]) for x in ("enc", "mac", "rmac")} == {16}
    cc = crypto.scp03_card_cryptogram(sk["mac"], host, card)
    hc = crypto.scp03_host_cryptogram(sk["mac"], host, card)
    assert len(cc) == 8 and len(hc) == 8 and cc != hc          # card != host


# --- SCP02 -----------------------------------------------------------------
def test_scp02_session_keys_and_cryptograms():
    enc = mac = dek = from_hex(DEFAULT_GP_KEY)
    seq = from_hex("0001")
    sk = crypto.scp02_session_keys(enc, mac, dek, seq)
    assert {len(sk[x]) for x in ("enc", "mac", "rmac", "dek")} == {16}
    host, card = from_hex("0102030405060708"), from_hex("AABBCCDDEEFF")
    cc = crypto.scp02_card_cryptogram(sk["enc"], host, seq, card)
    hc = crypto.scp02_host_cryptogram(sk["enc"], seq, card, host)
    assert len(cc) == 8 and len(hc) == 8 and cc != hc


def test_retail_mac_length_and_padding():
    key = from_hex(DEFAULT_GP_KEY)
    m = crypto.des_retail_mac(key, b"\x84\x82\x01\x00\x10")
    assert len(m) == 8


# --- canal seguro end-to-end (tarjeta falsa) -------------------------------
def _fake(protocol):
    from fakegpcard import FakeGPCard
    k = from_hex(DEFAULT_GP_KEY)
    return FakeGPCard(k, k, k, protocol=protocol)


def _keyset():
    return Keyset.same_key("k")


def test_scp03_open_channel_and_get_status():
    from emvy.core.gp import content
    from emvy.core.gp.apdu import STATUS_APPS
    card = _fake("03")
    chan = content.authenticate(card, _keyset())
    assert card.authenticated and chan.protocol == "03"
    apps = content.get_status(chan, STATUS_APPS)
    assert apps and apps[0].aid == "A0000000030000"       # C-MAC verificado por la tarjeta


def test_scp02_open_channel_and_get_status():
    from emvy.core.gp import content
    from emvy.core.gp.apdu import STATUS_APPS
    card = _fake("02")
    chan = content.authenticate(card, _keyset())
    assert card.authenticated and chan.protocol == "02"
    assert content.get_status(chan, STATUS_APPS)[0].aid == "A0000000030000"


def test_wrong_keys_rejected():
    import pytest
    from emvy.core.gp import content
    from emvy.core.gp.scp import GPError
    card = _fake("03")
    bad = Keyset.same_key("bad", key="00" * 16)
    with pytest.raises(GPError):                          # criptograma no valida
        content.authenticate(card, bad)


def test_delete_over_secure_channel():
    from emvy.core.gp import content
    card = _fake("03")
    chan = content.authenticate(card, _keyset())
    r = content.delete(chan, from_hex("A0000000030000"))
    assert r.ok


# --- parseo de CAP ---------------------------------------------------------
def _synthetic_cap(tmp_path):
    import zipfile
    aid = from_hex("A00000006203010C01")            # AID de paquete
    applet_aid = from_hex("A00000006203010C0101")
    header = (b"\x01" + b"\x00\x00" + b"\xde\xca\xff\xed" + b"\x00\x01"
              + b"\x00" + b"\x01\x00" + bytes([len(aid)]) + aid)
    applet = (b"\x03" + b"\x00\x00" + b"\x01" + bytes([len(applet_aid)]) + applet_aid
              + b"\x00\x00")
    directory = b"\x02\x00\x03\x00\x00\x00"
    method = b"\x07\x00\x02\x00\x00"
    p = tmp_path / "test.cap"
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("pkg/javacard/Header.cap", header)
        zf.writestr("pkg/javacard/Directory.cap", directory)
        zf.writestr("pkg/javacard/Applet.cap", applet)
        zf.writestr("pkg/javacard/Method.cap", method)
    return p, aid, applet_aid


def test_parse_cap_aids_and_load_block(tmp_path):
    from emvy.core.gp import cap
    p, aid, applet_aid = _synthetic_cap(tmp_path)
    c = cap.parse_cap(p)
    assert c.package_aid == aid
    assert c.applet_aids == [applet_aid]
    lfdb = c.load_file_data_block()
    assert lfdb[0] == 0xC4                              # tag del Load File Data Block
    # orden de carga: Header primero
    assert c.load_file().startswith(c.components["Header"])
    assert len(c.load_blocks(0x80)) >= 1


def test_install_cap_full_flow(tmp_path):
    from emvy.core.gp import cap, content
    p, aid, applet_aid = _synthetic_cap(tmp_path)
    card = _fake("03")
    chan = content.authenticate(card, _keyset())
    res = content.install_cap(chan, cap.parse_cap(p))     # load + install por canal seguro
    assert res.package_aid == to_hex(aid)
    assert res.instance_aid == to_hex(applet_aid)
    assert res.load_blocks >= 1
    steps = dict(res.steps)
    assert steps["install-for-load"] == "9000"
    assert steps["install-for-install"] == "9000"
