"""Backend BomberCat (Electronic Cats) por USB serie.

Cuatro modos, según el firmware flasheado en la placa:

  * **EMV reader (JSON)** — firmware `bombercat_emv_reader`: lee EMV contactless por
    NFC y emite `JSON_START`/`<json>`/`JSON_END` @115200. `read_emv()` lo captura.
  * **Passthrough APDU** — el mismo firmware con el parche de passthrough: acepta
    `APDU:<hex>` y responde `RESP:<hex>`. `open(mode="passthrough")` lo expone como
    un `OpenReader.transceive` normal, así todo `core.emv` funciona sobre BomberCat.
  * **Magspoof / banda** — firmware oficial @9600 (comandos `mode_ms`, `set_h`…):
    `magspoof_emit()` emula un swipe de banda magnética.
  * **Relay NFC** — comandos de host/client @9600 (el relay completo usa el
    coordinador MQTT); `relay_command()` es un envoltorio fino.

Degradación elegante: si falta `pyserial` o no hay dispositivo, `available()` es
False / `list_devices()` devuelve [] y `open()` lanza ReaderError con ayuda.
"""
from __future__ import annotations

import json
import os
import time

from ..core.apdu import make_transceiver
from ..core.hexutil import from_hex, to_hex
from .types import Capability, DeviceInfo, OpenReader, ReaderError, WireEvent

BACKEND = "bombercat"

BAUD_EMV = 115200   # firmware EMV reader / passthrough
BAUD_MAG = 9600     # firmware oficial magspoof / relay

# RP2040 (Raspberry Pi) es el MCU del BomberCat.
_RP2040_VID = 0x2E8A
_HINTS = ("bombercat", "electronic cats", "rp2040", "pico")

BOMBERCAT_HELP = (
    "Backend BomberCat no disponible. Para usarlo:\n"
    "  1) instala pyserial:  uv pip install --python .venv pyserial\n"
    "  2) conecta el BomberCat por USB (aparece como /dev/ttyACM*)\n"
    "  3) firmware EMV/passthrough @115200, o magspoof/relay @9600\n"
    "  4) permisos: pertenece al grupo 'uucp'/'dialout' o usa udev"
)


# ---------------------------------------------------------------------------
# disponibilidad / descubrimiento
# ---------------------------------------------------------------------------
def available() -> bool:
    try:
        import serial  # noqa: F401
        return True
    except Exception:
        return False


def list_devices() -> list[DeviceInfo]:
    try:
        from serial.tools import list_ports
    except Exception:
        return []
    out = []
    for p in list_ports.comports():
        blob = " ".join(str(x) for x in (p.description, p.manufacturer, p.product)).lower()
        is_bc = (p.vid == _RP2040_VID) or any(h in blob for h in _HINTS)
        if is_bc:
            name = p.product or p.description or p.device
            out.append(DeviceInfo(BACKEND, f"serial:{p.device}", f"BomberCat ({name})",
                                  frozenset({Capability.CONTACTLESS, Capability.MAGSTRIPE})))
    return out


def _port_of(device: DeviceInfo | str) -> str:
    ident = device if isinstance(device, str) else device.id
    return ident.split(":", 1)[1] if ident.startswith("serial:") else ident


def _resolve_port(device: DeviceInfo | str) -> str:
    """Puerto serie del `device`, con recuperación si el puerto cacheado ya no
    existe. El USB CDC del BomberCat se **re-enumera** en cada reflasheo/reboot
    (p.ej. /dev/ttyACM1 → /dev/ttyACM0), así que un DeviceInfo de un escaneo
    previo apunta a un puerto muerto. Si el puerto POSIX no existe y hay UN solo
    BomberCat presente ahora, usamos ése; si no, devolvemos el original y que
    `_open_serial` falle con su mensaje de ayuda."""
    port = _port_of(device)
    if not port.startswith("/") or os.path.exists(port):
        return port                      # no-POSIX (COMx) o existe: tal cual
    present = list_devices()
    if len(present) == 1:
        return _port_of(present[0])
    for d in present:                    # varios: el primero que exista de verdad
        p = _port_of(d)
        if os.path.exists(p):
            return p
    return port


# ---------------------------------------------------------------------------
# serie (helpers)
# ---------------------------------------------------------------------------
def _open_serial(port: str, baud: int):
    if not available():
        raise ReaderError(BOMBERCAT_HELP)
    import serial
    try:
        ser = serial.Serial(port, baud, timeout=1, dsrdtr=False, rtscts=False)
    except Exception as e:
        raise ReaderError(f"No se pudo abrir {port} @ {baud}: {e}\n\n{BOMBERCAT_HELP}") from e
    # DTR debe quedar asertado: el firmware (USB CDC nativo, mbed core RP2040)
    # gatea la entrega de bytes al `Serial` de Arduino según el estado de DTR.
    # Con dtr=False el BomberCat real nunca responde a PING (confirmado en
    # hardware); no forzar False aquí.
    try:
        ser.dtr = True
    except Exception:
        pass
    # Exclusividad del puerto (TIOCEXCL): si otro proceso tiene abierto el
    # mismo tty, este open falla en vez de compartirlo — sin esto, dos
    # procesos leyendo el mismo puerto se ROBAN bytes entre sí y la salida de
    # ambos queda corrupta (interleaving), un fallo silencioso y horrible de
    # diagnosticar. Se captura: plataformas sin ioctl (Windows) lo ignoran.
    try:
        import fcntl
        import termios
        fcntl.ioctl(ser.fileno(), termios.TIOCEXCL, 0)
    except Exception:
        pass
    time.sleep(0.3)
    try:
        ser.reset_input_buffer()
    except Exception:
        pass
    return ser


def _open_serial_retry(port: str, baud: int, tries: int = 8, delay: float = 0.25):
    """Como `_open_serial` pero reintenta si el puerto está momentáneamente
    ocupado (p.ej. otra operación acaba de soltarlo). Reeleva el último error."""
    last: Exception | None = None
    for _ in range(max(1, tries)):
        try:
            return _open_serial(port, baud)
        except ReaderError as e:
            last = e
            time.sleep(delay)
    assert last is not None
    raise last


def _wire(on_wire, direction: str, text: str) -> None:
    """Reporta una línea serie a `on_wire` (best-effort; nunca rompe la I/O)."""
    if on_wire is None or not text:
        return
    try:
        on_wire(WireEvent(direction, text, "serial"))
    except Exception:
        pass


def _readline(ser, deadline: float) -> str | None:
    while time.monotonic() < deadline:
        raw = ser.readline()
        if raw:
            return raw.decode("utf-8", errors="replace").strip()
    return None


def _writeline(ser, text: str) -> None:
    ser.write((text + "\r\n").encode())
    ser.flush()


def _is_ping_ack(line: str) -> bool:
    """True si la línea es el ack esperado a PING: `PONG` (dialecto histórico
    del passthrough viejo) o `+OK bombercat` (Discovery Contract). El banner de
    boot `+OK bombercat ready` NO lo es: es ruido que hay que saltar."""
    return line == "PONG" or (line.startswith("+OK bombercat")
                              and not line.startswith("+OK bombercat ready"))


def _wait_ping_ack(ser, deadline: float) -> str | None:
    """Lee líneas hasta encontrar el ack de PING (ver `_is_ping_ack`), saltando
    el banner de boot `+OK bombercat ready` y cualquier otra línea de ruido
    (`# debug`, AP WiFi…). Devuelve la línea ack o None si vence `deadline`.

    Tolerar el banner es lo que permite hablar tanto con el firmware local
    (EMVyBomberCat) como con el rework upstream de Electronic Cats, que lo emite
    al arrancar antes de aceptar comandos."""
    while time.monotonic() < deadline:
        line = _readline(ser, deadline)
        if line is None:
            break
        if _is_ping_ack(line):
            return line
        # cualquier otra línea (banner, debug) se ignora y seguimos esperando
    return None


# ---------------------------------------------------------------------------
# parseo tolerante de las líneas del firmware (dialecto local Y rework upstream)
# ---------------------------------------------------------------------------
def parse_info(lines) -> dict:
    """Parsea la respuesta del comando INFO (líneas `:<key> <value>` … `+OK`)
    en un dict clave→valor. Tolerante al dialecto: acepta tanto `:role` (firmware
    local EMVyBomberCat) como `:state` (rework upstream de Electronic Cats), con
    cualquier valor. Líneas sin marcador `:` y el terminador `+OK`/`-ERR` se
    ignoran. Devuelve también `ok` (True si terminó en `+OK`)."""
    out: dict = {}
    ok = False
    for line in lines:
        line = line.strip()
        if line.startswith("+OK"):
            ok = True
            break
        if line.startswith("-ERR"):
            break
        if line.startswith(":"):
            key, _, value = line[1:].partition(" ")
            out[key.strip()] = value.strip()
    out["ok"] = ok
    return out


def parse_emu_card(line: str) -> dict | None:
    """Parsea `EMU:CARD aid=<n> pan=<n> exp=<n> t2=<n> [cid=<x>]` (confirmación
    del firmware de la inyección de datos de tarjeta en EMUEMV). El campo `cid=`
    es OPCIONAL: el firmware local lo emite, el rework upstream NO. Devuelve un
    dict con los campos presentes (longitudes en bytes) o None si no parsea."""
    line = line.strip()
    if not line.startswith("EMU:CARD"):
        return None
    out: dict = {}
    for tok in line[len("EMU:CARD"):].split():
        if "=" not in tok:
            continue
        k, v = tok.split("=", 1)
        if k in ("aid", "pan", "exp", "t2"):
            try:
                out[k] = int(v)
            except ValueError:
                return None
        elif k == "cid":
            out["cid"] = v
    return out if "aid" in out and "t2" in out else None


def parse_generate_ac(line: str) -> dict | None:
    """Parsea `EMU:RX GENERATE-AC pide=<t> [da=<TC|ARQC|AAC>] <hex>`.

    El token `da=` es OPCIONAL: el firmware local lo inserta entre `pide=` y el
    hex, el rework upstream NO. El hex del APDU es SIEMPRE el último token.
    Devuelve `{pide, da|None, hex}` o None si no parsea."""
    line = line.strip()
    if not line.startswith("EMU:RX GENERATE-AC"):
        return None
    toks = line.split()
    pide = da = None
    hex_str = None
    for tok in toks:
        if tok.startswith("pide="):
            pide = tok.split("=", 1)[1]
        elif tok.startswith("da="):
            da = tok.split("=", 1)[1]
        else:
            hex_str = tok          # el hex va siempre al final (con o sin da=)
    if pide is None or hex_str is None:
        return None
    try:
        bytes.fromhex(hex_str)
    except ValueError:
        return None
    return {"pide": pide, "da": da, "hex": hex_str}


def device_info(device, timeout: float = 5.0) -> dict:
    """Pregunta INFO al firmware por serie y devuelve el dict parseado
    (`parse_info`). Handshake tolerante: salta el banner de boot y acepta tanto
    `PONG` como `+OK bombercat` al PING. Funciona con el firmware local
    (EMVyBomberCat, dialecto `:role`) y con el rework upstream (banner +
    `:state`). Lanza ReaderError si la placa no responde."""
    ser = _open_serial(_resolve_port(device), BAUD_EMV)
    try:
        _writeline(ser, "PING")
        if _wait_ping_ack(ser, time.monotonic() + timeout) is None:
            raise ReaderError("El BomberCat no respondió a PING (¿firmware passthrough?).")
        _writeline(ser, "INFO")
        lines: list[str] = []
        dl = time.monotonic() + timeout
        while time.monotonic() < dl:
            line = _readline(ser, dl)
            if line is None:
                continue
            lines.append(line)
            if line.startswith(("+OK", "-ERR")):
                break
        info = parse_info(lines)
        if not info.get("ok"):
            raise ReaderError(f"INFO del BomberCat sin confirmación: {lines[:4]}")
        return info
    finally:
        try:
            ser.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# modo EMV reader (JSON)
# ---------------------------------------------------------------------------
def read_emv(device, amount_cents: int = 500, timeout: float = 40.0,
             on_debug=None) -> dict:
    """Pide una lectura EMV al firmware BomberCat y devuelve el dict JSON.

    Envía `SCAN <centavos>` y acumula entre `JSON_START` y `JSON_END`. Las líneas
    de depuración (`# ...`) se pasan a `on_debug` si se aporta.
    """
    ser = _open_serial(_resolve_port(device), BAUD_EMV)
    deadline = time.monotonic() + timeout
    try:
        _writeline(ser, f"SCAN {amount_cents}")
        buf: list[str] = []
        in_json = False
        while time.monotonic() < deadline:
            line = _readline(ser, deadline)
            if line is None:
                break
            if line == "JSON_START":
                in_json, buf = True, []
                continue
            if line == "JSON_END":
                try:
                    return json.loads("\n".join(buf))
                except json.JSONDecodeError as e:
                    raise ReaderError(f"JSON del BomberCat inválido: {e}")
            if in_json:
                buf.append(line)
            elif on_debug and line.startswith("#"):
                on_debug(line)
        raise ReaderError("Timeout esperando la lectura EMV del BomberCat "
                          "(¿tarjeta acercada? ¿firmware EMV reader?).")
    finally:
        ser.close()


def monitor(device, on_line, stop=None) -> None:
    """Reenvía cada línea del BomberCat a `on_line(line)` hasta que `stop()` sea
    verdadero (o Ctrl-C). Equivale a `bombercat_monitor.py`."""
    ser = _open_serial(_resolve_port(device), BAUD_EMV)
    try:
        while not (stop and stop()):
            raw = ser.readline()
            if raw:
                on_line(raw.decode("utf-8", errors="replace").rstrip())
    finally:
        ser.close()


# ---------------------------------------------------------------------------
# modo passthrough APDU  -> OpenReader.transceive
# ---------------------------------------------------------------------------
def open(device: DeviceInfo, mode: str = "passthrough", on_event=None,
         on_wire=None, timeout: float = 30.0) -> OpenReader:
    """Abre el BomberCat en modo passthrough y lo expone como lector `transceive`.

    Requiere el firmware con el parche de passthrough (comandos `PING`, `WAIT`,
    `APDU:<hex>`, `RELEASE`). Espera a que haya una tarjeta ISO-DEP presente.

    `on_wire` (opcional) recibe un `WireEvent` por cada línea serie enviada o
    recibida — el handshake (PING/WAIT/READY), el framing APDU:/RESP: y las
    líneas de depuración `#` del firmware — para verlo todo en vivo en la
    consola. Es la capa de transporte, por debajo del `TraceEvent` de APDU.
    """
    if mode != "passthrough":
        raise ReaderError(f"Modo BomberCat no soportado por open(): {mode!r} "
                          "(usa read_emv/magspoof_emit para otros modos).")
    ser = _open_serial(_resolve_port(device), BAUD_EMV)

    # Envoltorios de I/O serie que además reportan cada línea a `on_wire`. Todo
    # el tráfico serie de este lector pasa por aquí, así la consola ve
    # literalmente qué se manda y qué responde el firmware.
    def wl(text: str) -> None:
        _writeline(ser, text)
        _wire(on_wire, "tx", text)

    def rl(deadline: float) -> str | None:
        line = _readline(ser, deadline)
        if line is not None:
            _wire(on_wire, "rx", line)
        return line

    # Handshake: solo confirma el firmware. **No** espera tarjeta aquí — conectar
    # el lector debe ser instantáneo (como un lector de contacto), sin exigir una
    # tarjeta puesta. La detección de tarjeta (WAIT) se hace **perezosa**, en el
    # primer APDU (p.ej. al capturar): así "Conectar" no falla con ERR:NOCARD.
    # Handshake: solo confirma el firmware. **No** espera tarjeta aquí — conectar
    # el lector debe ser instantáneo (como un lector de contacto), sin exigir una
    # tarjeta puesta. La detección de tarjeta (WAIT) se hace **perezosa**, en el
    # primer APDU (p.ej. al capturar): así "Conectar" no falla con ERR:NOCARD.
    # El ack se espera con `_wait_ping_ack` (a través de `rl`, que reporta a
    # `on_wire`): salta el banner de boot `+OK bombercat ready` del rework
    # upstream y acepta tanto `+OK bombercat` como el `PONG` histórico.
    wl("PING")
    ack: str | None = None
    dl_ping = time.monotonic() + 3
    while time.monotonic() < dl_ping:
        line = rl(dl_ping)
        if line is None:
            break
        if _is_ping_ack(line):
            ack = line
            break
    if ack is None:
        ser.close()
        raise ReaderError("El BomberCat no respondió a PING (¿firmware passthrough?).")
    trace: list = []
    state = {"activated": False, "ats": b""}

    def _activate() -> bool:
        """WAIT hasta `timeout`: activa la tarjeta ISO-DEP si hay una. Guarda el
        ATS. Devuelve False si no aparece ninguna (sin lanzar)."""
        wl(f"WAIT {int(timeout * 1000)}")
        dl = time.monotonic() + timeout + 2
        while time.monotonic() < dl:
            line = rl(dl)
            if line is None:
                continue
            if line.startswith("READY"):
                state["activated"] = True
                if ":" in line:
                    try:
                        state["ats"] = from_hex(line.split(":", 1)[1])
                    except ValueError:
                        pass
                return True
            if line.startswith("ERR"):
                return False
        return False

    def transmit(apdu_bytes: bytes) -> tuple[bytes, int, int]:
        if not state["activated"] and not _activate():
            raise ReaderError("BomberCat: no hay tarjeta contactless. Acerca una "
                              "tarjeta NFC/EMV a la antena y reintenta.")
        wl("APDU:" + to_hex(apdu_bytes))
        dl2 = time.monotonic() + 8
        while time.monotonic() < dl2:
            line = rl(dl2)
            if line is None:
                break
            if line.startswith("RESP:"):
                data = from_hex(line[5:])
                if len(data) < 2:
                    return data, 0x6F, 0x00
                return data[:-2], data[-2], data[-1]
            if line.startswith("ERR"):
                state["activated"] = False   # tarjeta retirada: re-detectar la próxima
                raise ReaderError(f"BomberCat APDU: {line}")
            # ignora líneas de depuración '#'
        raise ReaderError("Timeout esperando RESP del BomberCat.")

    def emit(e):
        trace.append(e)
        if on_event:
            on_event(e)

    def close() -> None:
        try:
            wl("RELEASE")
        except Exception:
            pass
        try:
            ser.close()
        except Exception:
            pass

    send = make_transceiver(transmit, on_event=emit)
    return OpenReader(device=device, close=close, transceive=send,
                      atr=(lambda: state["ats"]), trace=trace)


# ---------------------------------------------------------------------------
# modo magspoof / banda magnética (firmware oficial @9600)
# ---------------------------------------------------------------------------
def send_command(device, cmd: str, baud: int = BAUD_MAG, timeout: float = 3.0) -> str:
    """Envía un comando de línea al firmware oficial y devuelve la respuesta."""
    ser = _open_serial(_resolve_port(device), baud)
    try:
        _writeline(ser, cmd)
        return _readline(ser, time.monotonic() + timeout) or ""
    finally:
        ser.close()


def magspoof_emit(device, track1: str | None = None, track2: str | None = None,
                  baud: int = BAUD_MAG) -> str:
    """Emula un swipe de banda magnética con el firmware magspoof.

    Selecciona modo banda (`mode_ms`) y envía las pistas. El firmware oficial
    espera la(s) pista(s); mandamos Track1 y/o Track2 con centinelas estándar.
    """
    ser = _open_serial(_resolve_port(device), baud)
    try:
        _writeline(ser, "mode_ms")
        _readline(ser, time.monotonic() + 2)
        payload = ""
        if track1:
            payload += track1 if track1.startswith("%") else f"%{track1}?"
        if track2:
            payload += track2 if track2.startswith(";") else f";{track2}?"
        _writeline(ser, payload)
        return _readline(ser, time.monotonic() + 3) or "OK"
    finally:
        ser.close()


# ---------------------------------------------------------------------------
# emulación (firmware EMVyBomberCat @115200): tag NDEF (EMU:) o tarjeta EMV (EMUEMV)
# ---------------------------------------------------------------------------
def _run_emulation(device, start_line: str, timeout: float | None,
                   on_line, stop) -> list[str]:
    """Motor común de las emulaciones observables/cancelables. Manda `start_line`
    (`EMU:<hex>` para NDEF, `EMUEMV` para tarjeta EMV) y transmite las líneas de
    estado del firmware hasta `EMU:DONE`/`ERR`, `stop()` o `timeout` (manda
    `STOP`). `timeout=None` = sin límite del host (el firmware auto-para).

    Si el MCU se resetea a mitad de sesión (el USB CDC se re-enumera y la lectura
    serie falla), reabre el puerto y relanza la emulación con el mismo
    `start_line` (hasta 5 reconexiones), reportando `# RECONNECT ...` — así un
    apagón del enlace RF o un reset remoto no abortan el cobro en curso."""
    ser = _open_serial(_resolve_port(device), BAUD_EMV)
    lines: list[str] = []

    def _consume(line: str) -> None:
        lines.append(line)
        if on_line:
            on_line(line)

    try:
        _writeline(ser, "PING")
        if _wait_ping_ack(ser, time.monotonic() + 3) is None:
            raise ReaderError("El BomberCat no respondió a PING "
                              "(¿firmware EMVyBomberCat?).")
        _writeline(ser, start_line)
        deadline = None if timeout is None else time.monotonic() + timeout
        requested_stop = False
        reconnects = 0
        while True:
            if stop is not None and stop():
                requested_stop = True
                break
            if deadline is not None and time.monotonic() >= deadline:
                requested_stop = True
                break
            # deadline corto por iteración: así reaccionamos a stop()/timeout
            # sin bloquear en la lectura mientras el lector no manda nada.
            try:
                line = _readline(ser, time.monotonic() + 0.2)
            except Exception as e:
                # El MCU se resetó a mitad de sesión (USB CDC re-enumera, p.ej.
                # apagón del enlace RF o un REBOOT remoto). En vez de morir con
                # SerialException, reabrir el puerto y relanzar la emulación
                # deja al POS seguir el cobro sin tocar la placa a mano.
                reconnects += 1
                if reconnects > 5:
                    raise ReaderError(
                        f"El BomberCat se desconectó a mitad de la emulación "
                        f"({e}) y no volvió tras reintentar.") from e
                _consume(f"# RECONNECT intento={reconnects} motivo={e}")
                try:
                    ser.close()
                except Exception:
                    pass
                try:
                    ser = _open_serial_retry(_resolve_port(device), BAUD_EMV,
                                             tries=20, delay=0.5)
                except ReaderError:
                    continue      # agotada la apertura; el ciclo reintenta
                _consume("# RECONNECT ok: relanzando emulación")
                _writeline(ser, start_line)
                continue
            if line is None:
                continue
            _consume(line)
            # Un EMU:DONE "reason=restart" es el de la sesión que NUESTRO propio
            # comando acaba de reemplazar (el firmware para la vieja antes de
            # arrancar la nueva): NO es el fin de la sesión actual — la nueva
            # arranca justo detrás con su EMU:START. Sucede cuando la sesión
            # anterior quedó huérfana (p.ej. el host murió sin mandar STOP).
            if line.startswith("EMU:DONE") and "reason=restart" in line:
                continue
            if line.startswith("EMU:DONE") or line.startswith("ERR"):
                return lines
        if requested_stop:
            _writeline(ser, "STOP")
            end = time.monotonic() + 2          # consumir el EMU:DONE de confirmación
            while time.monotonic() < end:
                line = _readline(ser, end)
                if line is None:
                    break
                _consume(line)
                if line.startswith("EMU:DONE"):
                    break
        return lines
    finally:
        try:
            _writeline(ser, "STOP")
        except Exception:
            pass
        ser.close()


def ndef_emulate(device, ndef_hex: str, timeout: float | None = 200.0,
                 on_line=None, stop=None) -> list[str]:
    """Emula un tag NFC Forum Type 4 sirviendo `ndef_hex` como mensaje NDEF.

    Equivalente NFC de `magspoof_emit`, pero **observable** y **cancelable**:
    el firmware reporta cada APDU que manda el lector (`EMU:RX SELECT-APP/
    SELECT-CC/SELECT-NDEF/READ off=..len=../WRITE..`, la respuesta `EMU:TX ..`
    y `EMU:MSG-SENT n=..` al entregar un mensaje completo), lo que deja ver qué
    está leyendo el lector. Corre hasta `stop()`, `timeout` o `EMU:DONE`/`ERR`.
    Requiere el firmware **EMVyBomberCat** (comando `EMU:`)."""
    return _run_emulation(device, "EMU:" + ndef_hex, timeout, on_line, stop)


def _emv_card_params(card) -> str:
    """Codifica los datos de una tarjeta (`EmvCard`) al formato que espera el
    firmware: `<aid>|<pan>|<exp>|<track2>` (todo hex; campos vacíos permitidos).
      * aid  = AID tal cual (hex).
      * pan  = valor del tag 5A: BCD de los dígitos, padding 'F' si impar.
      * exp  = valor del tag 5F24 (YYMMDD): del `expiry` (YYMM→+"31") a 3 bytes.
      * t2   = valor del tag 57 (Track2 equivalent), ya en hex en la captura."""
    aid = (getattr(card, "aid", "") or "").replace(" ", "")
    pan = (card.pan_digits or "")
    pan_hex = pan + ("F" if len(pan) % 2 else "")
    exp = (getattr(card, "expiry", "") or "").strip()
    if len(exp) == 4:
        exp += "31"                      # YYMM → YYMMDD (día 31 por convención)
    exp_hex = exp[:6]
    t2 = (getattr(card, "track2", "") or "").replace(" ", "")
    return f"{aid}|{pan_hex}|{exp_hex}|{t2}"


def card_scan_to_ram(device, timeout: float = 25.0, on_line=None) -> dict:
    """Lee una tarjeta EMV por NFC en el BomberCat y la guarda en la **RAM del
    firmware** (comando `CARDSCAN`), para reemularla luego con
    `emv_emulate(from_ram=True)`. Flujo on-device: acerca la tarjeta al leer,
    después acerca la placa al terminal. Devuelve un dict con lo escaneado
    (`aid/pan/exp/t2len`) o lanza ReaderError si no hubo tarjeta / falló.
    Requiere el firmware **EMVyBomberCat** (comando `CARDSCAN`)."""
    ser = _open_serial(_resolve_port(device), BAUD_EMV)
    try:
        _writeline(ser, "PING")
        if _wait_ping_ack(ser, time.monotonic() + 3) is None:
            raise ReaderError("El BomberCat no respondió a PING (¿firmware EMVyBomberCat?).")
        _writeline(ser, "CARDSCAN")
        dl = time.monotonic() + timeout
        while time.monotonic() < dl:
            line = _readline(ser, dl)
            if line is None:
                continue
            if on_line:
                on_line(line)
            if line.startswith("EMU:SCANNED"):
                out = {"raw": line}
                for tok in line[len("EMU:SCANNED"):].split():
                    if "=" in tok:
                        k, v = tok.split("=", 1)
                        out[k] = v
                return out
            if line.startswith("ERR"):
                raise ReaderError(f"CARDSCAN: {line} (¿tarjeta contactless acercada?)")
        raise ReaderError("CARDSCAN: timeout esperando la lectura de la tarjeta.")
    finally:
        ser.close()


# ---------------------------------------------------------------------------
# probe de tarjeta real (passthrough): PPSE → SELECT AID → GPO (PDOL dinámico)
# → READ RECORD del AFL. Vuelca respuestas crudas para usarlas como referencia
# al ajustar la emulación. NO persiste nada: la salida va a la consola (y puede
# contener el PAN real — no la compartas tal cual).
# ---------------------------------------------------------------------------
def _parse_dol(dol: bytes) -> list[tuple[int, int]]:
    """Un DOL (Data Object List, p.ej. el 9F38) es tag+longitud SIN valor."""
    items = []
    i = 0
    while i < len(dol):
        tag = dol[i]; i += 1
        if tag & 0x1F == 0x1F:
            tag = (tag << 8) | dol[i]; i += 1
        items.append((tag, dol[i])); i += 1
    return items


def _tlv_find(data: bytes, want: int, depth: int = 0) -> bytes | None:
    """Busca `want` en `data` (iterando constructed tags de EMV)."""
    if depth > 6:
        return None
    i = 0
    while i + 2 <= len(data):
        tag = data[i]; i += 1
        if tag & 0x1F == 0x1F:
            if i >= len(data):
                return None
            tag = (tag << 8) | data[i]; i += 1
        if i >= len(data):
            return None
        ln = data[i]; i += 1
        if ln & 0x80:
            n = ln & 0x7F
            if i + n > len(data):
                return None
            ln = int.from_bytes(data[i:i + n], "big"); i += n
        val = data[i:i + ln]
        if tag == want:
            return val
        if tag in (0x6F, 0xA5, 0xBF0C, 0x61, 0x77, 0x70):
            hit = _tlv_find(val, want, depth + 1)
            if hit is not None:
                return hit
        i += ln
    return None


def probe_card(device, amount_cents: int = 0, country: str = "0484",
               currency: str | None = None, wait_s: int = 60,
               on_line=None) -> dict:
    """Lee una tarjeta EMV real por NFC siguiendo el flujo de un terminal de
    pago y devuelve las respuestas CRUDAS (PPSE/FCI/GPO/registros) en un dict
    `{"ppse": hex, "fci": hex, "gpo": hex, "records": [(cmd, hex)], ...}`.
    El GPO se construye con el PDOL **real** anunciado por la tarjeta (9F38) —
    un Lc mal calculado aquí hace que tarjetas reales respondan 6985. Solo
    lectura; nada se guarda. Requiere firmware **EMVyBomberCat**."""
    import random
    currency = currency or country
    ppse = bytes.fromhex("00A404000E325041592E5359532E444446303100")

    def emit(line):
        if on_line:
            on_line(line)

    ser = _open_serial(_resolve_port(device), BAUD_EMV)
    try:
        _writeline(ser, "PING")
        if _wait_ping_ack(ser, time.monotonic() + 3) is None:
            raise ReaderError("El BomberCat no respondió a PING (¿firmware EMVyBomberCat?).")
        _writeline(ser, f"WAIT {wait_s * 1000}")
        dl = time.monotonic() + wait_s + 2
        while True:
            line = _readline(ser, dl)
            if line is None:
                raise ReaderError("probe_card: timeout esperando la tarjeta.")
            emit(line)
            if line.startswith("READY:"):
                break
            if line.startswith("ERR"):
                raise ReaderError(f"probe_card: {line} (¿tarjeta contactless acercada?)")

        def apdu(cmd: bytes, what: str, deadline_s: float = 6.0) -> bytes:
            _writeline(ser, "APDU:" + to_hex(cmd, sep=""))
            dl = time.monotonic() + deadline_s
            while time.monotonic() < dl:
                line = _readline(ser, dl)
                if line is None:
                    continue
                if line.startswith("RESP:"):
                    emit(f"{what} <- {line[5:]}")
                    return from_hex(line[5:])
                if line.startswith("ERR"):
                    raise ReaderError(f"{what}: {line}")
            raise ReaderError(f"{what}: timeout esperando RESP.")

        out: dict = {}
        r = apdu(ppse, "PPSE")
        out["ppse"] = r.hex().upper()
        aid = _tlv_find(r[:-2], 0x4F) or bytes.fromhex("A0000000031010")
        out["aid"] = aid.hex().upper()
        sel_aid = bytes([0x00, 0xA4, 0x04, 0x00, len(aid)]) + aid + b"\x00"
        r = apdu(sel_aid, "SELECT-AID")
        out["fci"] = r.hex().upper()
        if r[-2:] != b"\x90\x00":
            raise ReaderError(f"SELECT AID {out['aid']}: SW {r[-2:].hex().upper()} "
                              "(¿AID no disponible?)")
        pdol = _tlv_find(r[:-2], 0x9F38) or b""
        out["pdol"] = pdol.hex().upper()
        today = time.strftime("%y%m%d")
        values = {
            0x9F66: "32804000", 0x9F02: f"{amount_cents:012d}",
            0x9F03: "0" * 12, 0x9F1A: country, 0x95: "0" * 10,
            0x5F2A: currency, 0x9A: today, 0x9C: "00",
            0x9F37: f"{random.getrandbits(32):08X}", 0x9F35: "22",
        }
        body = bytearray()
        for tag, ln in _parse_dol(pdol):
            v = values.get(tag, "")
            v = (v[: ln * 2]).ljust(ln * 2, "0")
            body.extend(bytes.fromhex(v))
        # Lc = bytes del campo de datos (83 <len> <pdol…>) — NO incluye el Le.
        gpo = bytes([0x80, 0xA8, 0x00, 0x00, 2 + len(body), 0x83, len(body)]) \
            + bytes(body) + b"\x00"
        r = apdu(gpo, "GPO")
        out["gpo"] = r.hex().upper()
        if r[-2:] != b"\x90\x00":
            out["sw"] = r[-2:].hex().upper()
            return out                       # p.ej. 6985: la tarjeta no coopera
        gpo_body = r[:-2]
        afl = _tlv_find(gpo_body, 0x94)
        aip = _tlv_find(gpo_body, 0x82)
        out["aip"] = aip.hex().upper() if aip else None
        out["afl"] = afl.hex().upper() if afl else None
        out["records"] = []
        if afl:
            for e in range(0, len(afl), 4):
                sfi, r1, r2 = afl[e] >> 3, afl[e + 1], afl[e + 2]
                for rec in range(r1, r2 + 1):
                    cmd = bytes([0x00, 0xB2, rec, (sfi << 3) | 4, 0x00])
                    rr = apdu(cmd, f"RECORD sfi={sfi} rec={rec}")
                    out["records"].append((to_hex(cmd, sep=""), rr.hex().upper()))
        return out
    finally:
        try:
            _writeline(ser, "RELEASE")
        except Exception:
            pass
        ser.close()


def emv_emulate(device, card=None, from_ram: bool = False, cid: str = "40",
                timeout: float | None = None, on_line=None, stop=None) -> list[str]:
    """Emula una **tarjeta EMV** para perfilar/fuzzear un TERMINAL de pago.

    En vez de un tag NDEF, el firmware responde al flujo EMV contactless
    (PPSE→FCI→SELECT AID→GPO→READ RECORD→GENERATE AC), para que el terminal
    AVANCE y revele su configuración: reporta `EMU:RX SELECT-PPSE`,
    `EMU:RX SELECT-AID <hex> (ESQUEMA)`, `EMU:RX GPO` con el PDOL **decodificado**
    (`  PDOL TTQ(9F66)=..`, monto, país, divisa, UN…), `READ-RECORD` y
    `GENERATE-AC` con el CDOL1 decodificado.

    `cid` fija la **decisión de criptograma** (tag 9F27) que devuelve la tarjeta
    emulada — el AC es dummy (sin la clave del emisor), pero sin ODA anunciada
    el terminal acepta la decisión igual que en un cobro contactless real:
      * ``"40"`` (default) **TC**: el terminal aprueba OFFLINE y el cobro
        **completa** (como los pagos de bajo monto). Úsalo para validar el
        flujo completo del POS.
      * ``"80"`` **ARQC**: el terminal intenta ir ONLINE y el cobro se queda
        esperando una autorización que el criptograma fake jamás obtendrá.
      * ``"00"`` **AAC**: transacción declinada.

    Fuente de la tarjeta emulada:
      * `from_ram=True`  → la tarjeta guardada en la RAM del firmware por
        `card_scan_to_ram()` (comando `EMUEMV:RAM|<cid>`), flujo on-device.
      * `card=<EmvCard>` → sus datos reales, inyectados desde el host
        (`EMUEMV:<aid>|<pan>|<exp>|<track2>|<cid>`).
      * ninguno         → una Visa de prueba canned (`EMUEMV:||||<cid>`).
    Cancelable con `stop()`/`timeout`. Requiere el firmware **EMVyBomberCat**
    (con campo `<cid>`; firmware antiguo ignora el 5º campo y siempre va online)."""
    cid = (cid or "40").upper().removeprefix("0X")
    if cid not in ("00", "40", "80"):
        raise ValueError(f"cid inválido {cid!r}: usa '40' (TC), '80' (ARQC) o '00' (AAC)")
    if from_ram:
        start = f"EMUEMV:RAM|{cid}"
    elif card is not None and _emv_card_params(card).strip("|"):
        start = "EMUEMV:" + _emv_card_params(card) + f"|{cid}"
    else:
        start = f"EMUEMV:||||{cid}"
    return _run_emulation(device, start, timeout, on_line, stop)


def reboot(device) -> str:
    """Reinicia el MCU del BomberCat (comando serie `REBOOT`).

    Para salir de un estado atascado (p.ej. una emulación colgada) sin apagar la
    placa a mano. El USB CDC se re-enumera tras el reset, así que **hay que
    reconectar** el lector después. Reintenta abrir el puerto si está ocupado
    (una emulación puede acabar de soltarlo)."""
    ser = _open_serial_retry(_resolve_port(device), BAUD_EMV, tries=8, delay=0.25)
    try:
        _writeline(ser, "REBOOT")
        return _readline(ser, time.monotonic() + 2) or "REBOOT"
    finally:
        try:
            ser.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# modo relay NFC (firmware oficial @9600)
# ---------------------------------------------------------------------------
def relay_command(device, cmd: str, baud: int = BAUD_MAG) -> str:
    """Envoltorio fino del protocolo de línea de relay (host/client).

    El relay NFC completo requiere el coordinador MQTT (`BomberCat/scripts/
    cordinator.py`) y dos unidades host/client; aquí solo enviamos comandos de
    control (p.ej. `mode_relay`, `set_h<NN>`, `get_config`)."""
    return send_command(device, cmd, baud=baud)
