"""Tests del backend BomberCat con un serial falso (sin hardware)."""
import pytest

import fakeserial


@pytest.fixture
def fake_serial():
    fakeserial.install()
    yield
    fakeserial.uninstall()


def test_list_devices(fake_serial):
    from emvy.readers import bombercat
    devs = bombercat.list_devices()
    assert devs and devs[0].backend == "bombercat"
    assert "contactless" in devs[0].caps_str


def test_read_emv_json(fake_serial):
    from emvy.readers import bombercat
    from emvy.session import from_bombercat
    d = bombercat.read_emv(bombercat.list_devices()[0], amount_cents=500)
    assert d["aid"] == "A0000000031010" and d["arqc"]
    dump = from_bombercat(d)
    app = dump.applications[0]
    assert app["aid"] == "A0000000031010"
    assert app["get_data"]["9F26"] == "D6F5B2E0E50B0F9C"


def test_passthrough_transceive(fake_serial):
    from emvy.core import emv
    from emvy.readers import registry
    dev = [d for d in registry.list_all_devices() if d.backend == "bombercat"][0]
    with registry.open_device(dev) as r:
        apps = emv.discover(r.transceive, brute=False)
        assert apps and apps[0].aid == "A0000000041010"
        app = emv.select_application(r.transceive, apps[0].aid)
        resp, app = emv.get_processing_options(r.transceive, app)
        assert resp.ok and app.aip is not None
        assert len(r.trace) >= 3  # se registran los intercambios


def test_ndef_emulate_reports_reader_activity(fake_serial):
    """La emulación observable reporta CADA APDU del lector (SELECT app/CC/NDEF,
    READ off/len y la respuesta), no solo START/DONE — es la visibilidad nueva."""
    from emvy.readers import bombercat
    dev = bombercat.list_devices()[0]
    lines = bombercat.ndef_emulate(dev, "D101125504656D7679", timeout=0.5)
    assert any(l.startswith("EMU:START") for l in lines)
    assert any(l.startswith("EMU:RX SELECT-APP") for l in lines)
    assert any(l.startswith("EMU:RX READ off=") for l in lines)   # qué "sector" lee
    assert any(l.startswith("EMU:TX") for l in lines)
    assert any(l.startswith("EMU:MSG-SENT") for l in lines)
    assert any(l.startswith("EMU:DONE") for l in lines)           # se cerró (timeout→STOP)


def test_ndef_emulate_stop_callback(fake_serial):
    """`stop()` corta la emulación en cualquier momento (manda STOP → EMU:DONE)."""
    from emvy.readers import bombercat
    dev = bombercat.list_devices()[0]
    seen = {"msg": False}

    def on_line(line: str) -> None:
        if line.startswith("EMU:MSG-SENT"):
            seen["msg"] = True

    # sin timeout del host: solo se detiene cuando stop() lo pide
    lines = bombercat.ndef_emulate(dev, "D101125504656D7679", timeout=None,
                                   on_line=on_line, stop=lambda: seen["msg"])
    assert seen["msg"]
    assert any(l.startswith("EMU:DONE") and "stop" in l for l in lines)


def test_emv_emulate_profiles_terminal(fake_serial):
    """`emv_emulate` (EMUEMV) hace que el terminal avance y revela su config:
    PPSE → SELECT AID (con esquema) → GPO con el PDOL decodificado → GEN AC."""
    from emvy.readers import bombercat
    dev = bombercat.list_devices()[0]
    seen = {"gpo": False}

    def on_line(line: str) -> None:
        if line.startswith("EMU:RX GPO"):
            seen["gpo"] = True

    lines = bombercat.emv_emulate(dev, timeout=None, on_line=on_line,
                                  stop=lambda: seen["gpo"])
    assert any(l.startswith("EMU:START mode=emv") for l in lines)
    assert any(l.startswith("EMU:RX SELECT-PPSE") for l in lines)
    assert any("SELECT-AID" in l and "VISA" in l for l in lines)
    assert any(l.startswith("EMU:RX GPO") for l in lines)
    assert any(l.lstrip().startswith("PDOL TTQ(9F66)") for l in lines)  # dato del terminal
    assert any(l.startswith("EMU:DONE") and "stop" in l for l in lines)


def test_emv_emulate_injects_capture_data(fake_serial):
    """Con una captura, `emv_emulate` codifica AID/PAN/expiry/track2 y el firmware
    presenta ESE AID (no el Visa de prueba)."""
    from emvy.payments import EmvCard
    from emvy.readers import bombercat
    card = EmvCard(pan="5555444433332222",
                   track2="5555444433332222D27122010000000000000F",
                   expiry="2712", aid="A0000000041010", label="MC")
    params = bombercat._emv_card_params(card)
    assert params.startswith("A0000000041010|5555444433332222|271231|")

    seen = {"aid": False}

    def on_line(line: str) -> None:
        if "SELECT-AID A0000000041010" in line:
            seen["aid"] = True

    lines = bombercat.emv_emulate(bombercat.list_devices()[0], card=card,
                                  timeout=None, on_line=on_line,
                                  stop=lambda: seen["aid"])
    assert seen["aid"]                                  # el terminal ve el AID de la captura
    assert any(l.startswith("EMU:CARD") for l in lines)  # el firmware confirmó la inyección


def test_emv_emulate_cid_default_tc_completes_offline(fake_serial):
    """`cid` fija la decisión de criptograma: por defecto TC (aprueba offline y
    el cobro completa) y el firmware la reporta en GENERATE-AC como ``da=TC``."""
    from emvy.readers import bombercat
    seen = {"cid": False}

    def on_line(line: str) -> None:
        if "GENERATE-AC pide=ARQC da=TC" in line:
            seen["cid"] = True

    lines = bombercat.emv_emulate(bombercat.list_devices()[0], timeout=None,
                                  on_line=on_line, stop=lambda: seen["cid"])
    assert seen["cid"]
    assert any(l.startswith("EMU:START mode=emv") for l in lines)


def test_emv_emulate_cid_arqc_with_ram_card(fake_serial):
    """cid=80 con la tarjeta en RAM: el verbo va como ``EMUEMV:RAM|80`` y la
    decisión reportada es ARQC (el terminal intentaría ir online)."""
    from emvy.readers import bombercat
    dev = bombercat.list_devices()[0]
    bombercat.card_scan_to_ram(dev)
    seen = {"cid": False}

    def on_line(line: str) -> None:
        if "GENERATE-AC pide=ARQC da=ARQC" in line:
            seen["cid"] = True

    lines = bombercat.emv_emulate(dev, from_ram=True, cid="80", timeout=None,
                                  on_line=on_line, stop=lambda: seen["cid"])
    assert seen["cid"]
    assert any("SELECT-AID A0000000031010" in l for l in lines)


def test_emv_emulate_rejects_invalid_cid(fake_serial):
    from emvy.readers import bombercat
    with pytest.raises(ValueError):
        bombercat.emv_emulate(bombercat.list_devices()[0], cid="41")
    with pytest.raises(ValueError):
        bombercat.emv_emulate(bombercat.list_devices()[0], cid="TC")


def test_card_scan_to_ram_and_emulate_from_ram(fake_serial):
    """Flujo on-device: CARDSCAN guarda la tarjeta en RAM del firmware y
    emv_emulate(from_ram=True) la reemula (EMUEMV:RAM) mostrando ese AID."""
    from emvy.readers import bombercat
    dev = bombercat.list_devices()[0]
    info = bombercat.card_scan_to_ram(dev)
    assert info.get("pan") == "4111111111111111" and info.get("aid") == "A0000000031010"

    seen = {"aid": False}

    def on_line(line: str) -> None:
        if "SELECT-AID A0000000031010" in line:
            seen["aid"] = True

    lines = bombercat.emv_emulate(dev, from_ram=True, timeout=None, on_line=on_line,
                                  stop=lambda: seen["aid"])
    assert seen["aid"]
    assert any(l.startswith("EMU:START mode=emv") for l in lines)


def test_emv_emulate_reconnects_after_mcu_reset(fake_serial):
    """Un reset del MCU a mitad de sesión (readline que falla = USB re-enumerado)
    NO aborta: `_run_emulation` reabre el puerto, relanza la emulación con el
    mismo verbo y reporta `# RECONNECT ...`."""
    import serial as serial_mod
    from emvy.readers import bombercat

    class FlakySerial(fakeserial.FakeSerial):
        _calls = 0
        _raised = False

        def readline(self):
            FlakySerial._calls += 1
            if FlakySerial._calls >= 2 and not FlakySerial._raised:
                FlakySerial._raised = True
                raise OSError("device disconnected")
            return super().readline()

    serial_mod.Serial = FlakySerial
    starts = {"n": 0}

    def on_line(line: str) -> None:
        if line.startswith("EMU:START"):
            starts["n"] += 1

    # el EMU:START de la 1ª instancia se perdió con el reset (se leyó el OSError
    # antes), así que el primero que se observa ES el del relanzamiento
    lines = bombercat.emv_emulate(bombercat.list_devices()[0], timeout=None,
                                  on_line=on_line, stop=lambda: starts["n"] >= 1)
    assert any(l.startswith("# RECONNECT") for l in lines)
    assert starts["n"] == 1                       # la emulación se relanzó
    assert any(l.startswith("EMU:DONE") for l in lines)


def test_emv_emulate_gives_up_after_repeated_disconnects(fake_serial):
    """Si el puerto no vuelve (reintentos agotados), se eleva ReaderError en
    vez de un SerialException crudo."""
    import serial as serial_mod
    from emvy.readers import bombercat
    from emvy.readers.types import ReaderError

    class DeadSerial(fakeserial.FakeSerial):
        _calls = 0

        def readline(self):
            DeadSerial._calls += 1
            if DeadSerial._calls > 1:      # el PING inicial pasa; luego muere
                raise OSError("device disconnected")
            return super().readline()

    serial_mod.Serial = DeadSerial
    monkey_reopen = lambda *a, **k: (_ for _ in ()).throw(
        ReaderError("puerto no disponible"))
    old = bombercat._open_serial_retry
    bombercat._open_serial_retry = monkey_reopen
    try:
        with pytest.raises(ReaderError, match="no volvió"):
            bombercat.emv_emulate(bombercat.list_devices()[0], timeout=None)
    finally:
        bombercat._open_serial_retry = old


def test_emv_emulate_survives_stale_restart_done(fake_serial):
    """Si la placa quedó con una emulación huérfana (host anterior murió sin
    STOP), el firmware responde al nuevo EMUEMV con `EMU:DONE reason=restart`
    (de la sesión que reemplaza) y luego arranca la nueva. El host NO debe
    confundir ese DONE con el fin de su sesión: sigue hasta ver el flujo real."""
    import serial as serial_mod
    from emvy.readers import bombercat

    # Huérfana: abrir el puerto a pelo, emular y cerrar SIN mandar STOP.
    orphan = serial_mod.Serial("/dev/ttyACM0", 115200, timeout=1)
    orphan.write(b"EMUEMV:||||40\r\n")
    orphan.readline()  # EMU:CARD
    orphan.readline()  # EMU:START (la huérfana queda activa)
    orphan.close()

    seen = {"ppse": False}

    def on_line(line: str) -> None:
        if "SELECT-PPSE" in line:
            seen["ppse"] = True

    lines = bombercat.emv_emulate(bombercat.list_devices()[0], timeout=None,
                                  on_line=on_line, stop=lambda: seen["ppse"])
    assert any(l.startswith("EMU:DONE") and "reason=restart" in l for l in lines)
    assert seen["ppse"]            # el flujo NUEVO siguió tras el DONE de restart
    assert any(l.startswith("EMU:START mode=emv") for l in lines)


def test_probe_card_follows_real_terminal_flow(fake_serial):
    """`probe_card` ejecuta PPSE → SELECT AID → GPO (con el PDOL anunciado por
    la tarjeta) → READ RECORD del AFL, y devuelve las respuestas crudas. El Lc
    del GPO debe ser len(83 <len> <pdol>) — un off-by-one hace que tarjetas
    reales respondan 6985 (regresión de un bug real encontrado en hardware)."""
    from emvy.readers import bombercat
    out = bombercat.probe_card(bombercat.list_devices()[0], wait_s=1)
    assert out["ppse"].endswith("9000")
    assert out["aid"] == "A0000000041010"
    assert out["fci"].endswith("9000")
    gpo = out.get("gpo", "")
    assert gpo.endswith("9000"), f"GPO devolvió {gpo[-4:] if gpo else 'nada'} (¿Lc mal?)"
    # si el GPO trae AFL, los registros se leen; si es fast path (sin 94),
    # "records" queda vacío — ambos válidos
    assert isinstance(out.get("records"), list)
    if out.get("afl"):
        assert out["records"]


def test_cli_bombercat_cardscan(fake_serial, capsys):
    from emvy.cli import main
    rc = main(["bombercat", "cardscan"])
    assert rc == 0
    assert "4111111111111111" in capsys.readouterr().out


def test_resolve_port_recovers_after_renumeration(fake_serial):
    """Un DeviceInfo con un puerto POSIX que ya no existe (típico tras reflashear
    el BomberCat: el USB CDC se re-enumera) se recupera al puerto presente."""
    from emvy.readers import bombercat
    from emvy.readers.types import Capability, DeviceInfo
    stale = DeviceInfo("bombercat", "serial:/dev/does-not-exist-xyz",
                       "BomberCat (viejo)", frozenset({Capability.CONTACTLESS}))
    assert bombercat._resolve_port(stale) == "/dev/ttyACM0"   # el fake presente


def test_reboot(fake_serial):
    """`reboot()` manda REBOOT y el firmware confirma la línea."""
    from emvy.readers import bombercat
    dev = bombercat.list_devices()[0]
    assert "REBOOT" in bombercat.reboot(dev)


def test_cli_bombercat_emv_emulate_registered():
    """El verbo `bombercat emv-emulate` está registrado en el parser."""
    from emvy.cli import build_parser
    args = build_parser().parse_args(["bombercat", "emv-emulate"])
    assert args.action == "emv-emulate"


def test_cli_bombercat_reboot(fake_serial, capsys):
    from emvy.cli import main
    rc = main(["bombercat", "reboot"])
    assert rc == 0
    assert "REBOOT" in capsys.readouterr().out


def test_passthrough_on_wire_reports_serial_lines(fake_serial):
    """`on_wire` debe recibir cada línea serie de bajo nivel (el handshake y el
    framing APDU:/RESP:), que es lo que se muestra en la consola en vivo."""
    from emvy.core import emv
    from emvy.readers import registry

    wire: list = []
    dev = [d for d in registry.list_all_devices() if d.backend == "bombercat"][0]
    with registry.open_device(dev, on_wire=wire.append) as r:
        # al conectar solo hay handshake PING/PONG (la tarjeta se detecta perezoso)
        tx = [w.text for w in wire if w.direction == "tx"]
        rx = [w.text for w in wire if w.direction == "rx"]
        assert "PING" in tx and "PONG" in rx
        assert not any(t.startswith("WAIT") for t in tx)   # aún no

        emv.discover(r.transceive, brute=False)
        # el primer APDU dispara WAIT/READY (activación perezosa) + el framing APDU:/RESP:
        tx = [w.text for w in wire if w.direction == "tx"]
        rx = [w.text for w in wire if w.direction == "rx"]
        assert any(t.startswith("WAIT") for t in tx) and any(t.startswith("READY") for t in rx)
        assert any(t.startswith("APDU:") for t in tx) and any(t.startswith("RESP:") for t in rx)
        assert all(w.transport == "serial" for w in wire)


# --- interacción directa desde la CLI: dump / write / analyze --------------
# EMVy usa el mismo `Transceiver` que cualquier lector, así que dump/escritura/
# análisis funcionan igual sobre el passthrough del firmware BomberCat.
def test_cli_bombercat_dump_full(fake_serial, capsys):
    from emvy.cli import main
    rc = main(["bombercat", "dump"])
    assert rc == 0
    out = capsys.readouterr().out
    assert '"aid": "A0000000041010"' in out
    assert '"9F36"' in out                      # GET DATA llegó al dump


def test_cli_bombercat_write_reaches_card(fake_serial, capsys):
    from emvy.cli import main
    # el fakecard no soporta PUT DATA -> 6A82, pero prueba que el byte-path
    # (CLI -> passthrough -> tarjeta) funciona de punta a punta sin excepción.
    rc = main(["bombercat", "write", "data", "9F36", "0001"])
    out = capsys.readouterr().out
    assert "PUT DATA tag=9F36" in out and "6A82" in out
    assert rc == 1                              # SW != 9000 -> código de salida distinto de 0


def test_cli_bombercat_analyze(fake_serial, capsys):
    from emvy.cli import main
    rc = main(["bombercat", "analyze"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Análisis EMV" in out and "A0000000041010" in out


# --- compatibilidad bidireccional con el rework upstream (firmware v1.1.x) ---
# El firmware local (EMVyBomberCat) y el rework de Electronic Cats difieren en
# el dialecto serie: banner `+OK bombercat ready` al boot, INFO con `:state`
# (sin `:role`), `EMU:CARD` sin `cid=` y GENERATE-AC sin token `da=`. El host
# debe aceptar AMBOS dialectos.
def test_parse_info_accepts_state_and_role():
    """INFO del rework upstream trae `:state` (sin `:role`); el firmware local
    trae `:role` (y ahora también `:state`). `parse_info` acepta cualquiera."""
    from emvy.readers import bombercat
    upstream = bombercat.parse_info([":fw 1.1.0", ":state scanning", "+OK"])
    assert upstream["state"] == "scanning" and upstream["ok"]
    assert "role" not in upstream
    local = bombercat.parse_info([":fw_name emvybombercat", ":fw 1.1",
                                  ":role emv-multitool", ":state idle", "+OK"])
    assert local["role"] == "emv-multitool" and local["state"] == "idle"
    assert local["fw_name"] == "emvybombercat" and local["ok"]
    # terminador -ERR / timeout: ok=False
    assert not bombercat.parse_info([":state idle", "-ERR hw-error"])["ok"]


def test_device_info_over_serial(fake_serial):
    """`device_info` hace PING+INFO por serie y parsea la respuesta del
    firmware local (que emite tanto `:role` como `:state`)."""
    from emvy.readers import bombercat
    info = bombercat.device_info(bombercat.list_devices()[0])
    assert info["ok"] and info["fw_name"] == "emvybombercat"
    assert info["role"] == "emv-multitool"
    assert info["state"] in ("idle", "emulating")


def test_ping_ack_skips_boot_banner(fake_serial):
    """El banner `+OK bombercat ready` del boot upstream NO cuenta como ack de
    PING: el handshake lo salta y acepta el `+OK bombercat`/`PONG` real."""
    import serial as serial_mod
    from emvy.readers import bombercat
    from emvy.readers import registry

    class BannerSerial(fakeserial.FakeSerial):
        def _handle(self, line):
            if line.upper() == "PING":
                # la placa estaba a mitad de boot cuando llegó el PING:
                # suelta el banner ANTES del ack
                self._emit("+OK bombercat ready")
            super()._handle(line)

    serial_mod.Serial = BannerSerial
    dev = [d for d in registry.list_all_devices() if d.backend == "bombercat"][0]
    with registry.open_device(dev) as r:          # handshake: salta el banner
        assert r.device.backend == "bombercat"
    # igual en el handshake de bajo nivel de device_info / emulación
    info = bombercat.device_info(dev)
    assert info["ok"] and info["fw_name"] == "emvybombercat"


def test_parse_emu_card_cid_optional():
    """`EMU:CARD`: el firmware local añade `cid=` (5º campo); el rework upstream
    NO lo emite. Ambas variantes deben parsear (cid=None si falta)."""
    from emvy.readers import bombercat
    local = bombercat.parse_emu_card(
        "EMU:CARD aid=7 pan=8 exp=3 t2=19 cid=40")
    assert local == {"aid": 7, "pan": 8, "exp": 3, "t2": 19, "cid": "40"}
    upstream = bombercat.parse_emu_card(
        "EMU:CARD aid=7 pan=8 exp=3 t2=19")
    assert upstream == {"aid": 7, "pan": 8, "exp": 3, "t2": 19}
    assert upstream.get("cid") is None
    assert bombercat.parse_emu_card("EMU:RX SELECT-PPSE ...") is None


def test_parse_generate_ac_da_optional():
    """`EMU:RX GENERATE-AC`: el firmware local inserta `da=<TC|ARQC|AAC>` entre
    `pide=` y el hex; el rework upstream va directo `pide=<t> <hex>`. El hex es
    siempre el último token — extraerlo bien en AMBOS dialectos."""
    from emvy.readers import bombercat
    local = bombercat.parse_generate_ac(
        "EMU:RX GENERATE-AC pide=ARQC da=TC 80AE80002B")
    assert local == {"pide": "ARQC", "da": "TC", "hex": "80AE80002B"}
    upstream = bombercat.parse_generate_ac(
        "EMU:RX GENERATE-AC pide=TC 80AE40001F")
    assert upstream == {"pide": "TC", "da": None, "hex": "80AE40001F"}
    # regresión: el token da= no se confunde con el hex
    assert bombercat.parse_generate_ac("EMU:RX READ-RECORD rec=1 sfi=1 00B2010C00") is None
    assert bombercat.parse_generate_ac("EMU:RX GENERATE-AC pide=ARQC") is None
