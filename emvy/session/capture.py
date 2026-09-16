"""Captura/volcado completo de una tarjeta, sobre un `Transceiver`.

Refactor funcional de la antigua `ctf.full_dump`: recorre PPSE/PSE/AIDs, hace
SELECT + GPO + lectura de registros (AFL + barrido bruto) + GET DATA, y acumula
todo en un `CardDump` inmutable con `blobs` para búsqueda de flags.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Callable

from ..core import emv
from ..core.apdu import Transceiver
from ..core.atr import describe_atr
from ..core.emv import TerminalProfile
from ..core.hexutil import to_hex
from ..core.search import Hit, search_flags
from .model import CardDump, app_to_dict, fci_hex

Progress = Callable[[str], None]


def capture_card(
    send: Transceiver,
    *,
    atr: bytes = b"",
    reader: str = "",
    profile: TerminalProfile | None = None,
    brute: bool = True,
    sweep: bool = True,
    get_data: bool = True,
    raw: bool = False,
    mode: str = "auto",
    progress: Progress | None = None,
) -> CardDump:
    """Recorre toda la tarjeta y devuelve un `CardDump`.

    `mode` decide cómo interpretar lo que hay en la antena/contacto:
      - "auto" (por defecto): intenta EMV; si no hay apps (o se pide `raw`),
        cae a lectura cruda + NDEF Type 4 — igual que el comportamiento previo.
      - "emv": solo el flujo EMV (SELECT/GPO/AFL/GET DATA); no cae a crudo
        aunque no encuentre apps (útil para no perder tiempo/ruido en una
        tarjeta que se sabe de pago).
      - "nfc": tag NFC genérico (no de pago) — se salta el descubrimiento EMV
        y va directo a NDEF Type 4 + escaneo crudo (AIDs no-EMV, ficheros).
    """
    def log(msg: str) -> None:
        if progress:
            progress(msg)

    dump = CardDump(reader=reader)
    if atr:
        dump.atr = to_hex(atr, sep=" ")
        dump.atr_info = describe_atr(atr)
        dump.add_blob("ATR", atr)

    if mode == "nfc":
        log("Modo NFC genérico: se omite el descubrimiento EMV.")
        apps = []
    else:
        log("Descubriendo aplicaciones (PPSE/PSE/AIDs)...")
        apps = emv.discover(send, brute=brute)
        log(f"  {len(apps)} aplicación(es) encontrada(s)")

    for found in apps:
        log(f"SELECT {found.aid} ({found.scheme}) [{found.source}]")
        app = emv.select_application(send, found.aid)
        app = replace(app, source=found.source, label=(app.label or found.label))
        if app.fci:
            dump.blobs.append({"source": f"{app.aid}:FCI", "hex": fci_hex(app)})

        # GPO -> AIP/AFL -> registros del AFL
        try:
            resp, app = emv.get_processing_options(send, app, profile)
            if resp.ok:
                log(f"  GPO ok (AIP={to_hex(app.aip or b'')}, AFL={to_hex(app.afl or b'')})")
                app = emv.read_afl_records(send, app)
        except Exception as e:  # una app rara no debe abortar el volcado
            log(f"  GPO falló: {e}")

        # Barrido bruto de registros (encuentra registros fuera del AFL)
        if sweep:
            app = emv.merge_records(app, emv.sweep_records(send))

        for r in app.records:
            dump.blobs.append({"source": f"{app.aid}:SFI{r.sfi}/REC{r.number}",
                               "hex": to_hex(r.raw)})

        # GET DATA (contadores, logs, saldos, propietarios)
        if get_data:
            app = app.with_data_objects(emv.get_data_sweep(send))
            for tag, val in app.data_objects.items():
                dump.blobs.append({"source": f"{app.aid}:GETDATA {tag}",
                                   "hex": to_hex(val)})

        dump.applications.append(app_to_dict(app))

    # Escaneo crudo: si se pide (raw), si se pidió modo "nfc", o si no se
    # halló ninguna app EMV (y no se pidió modo "emv" a secas), lee lo que
    # haya en la tarjeta (AIDs, registros, GET DATA, binarios) + NDEF Type 4.
    if raw or mode == "nfc" or (mode != "emv" and not apps):
        from ..core.rawscan import raw_scan, read_type4_ndef
        log("Intentando NDEF (NFC Forum Type 4)...")
        try:
            ndef_result = read_type4_ndef(send)
        except Exception:
            ndef_result = None
        if ndef_result:
            log(f"  NDEF: {ndef_result['summary']}")
            dump.blobs.append({"source": "NDEF:mensaje", "hex": ndef_result["ndef_hex"]})
            dump.applications.append({
                "aid": "D2760000850101", "scheme": "NDEF Type 4 (NFC Forum)",
                "source": "ndef", "label": "tag NDEF", "aip": None, "afl": None,
                "cardholder": {}, "records": [],
                "get_data": {"CC": ndef_result["cc_hex"], "NDEF_FILE": ndef_result["ndef_file_id"]},
                "ndef_records": ndef_result["records"],
            })

        log("Escaneo crudo (lee lo que haya conectado)...")
        # En modo "nfc" se salta el barrido ciego READ RECORD/GET DATA (hasta
        # cientos de intercambios EMV-específicos que casi nunca aplican a un
        # tag no bancario) y se va directo a SELECT de AIDs + READ BINARY: es
        # lo que de verdad encuentra contenido en tags no-EMV, y con muchos
        # menos intercambios se pierde bastante menos el campo RF de una
        # tarjeta/tag de rango corto sostenida a mano.
        scan = raw_scan(send, progress=log,
                        do_records=(mode != "nfc"), do_getdata=(mode != "nfc"))
        dump.blobs.extend(scan.blobs())
        if not scan.is_empty():
            gd = dict(scan.get_data)
            gd.update({f"SELECT {label}": hx for label, hx in scan.selects})
            gd.update({f"BINARY {label}": hx for label, hx in scan.binaries})
            dump.applications.append({
                "aid": "RAW", "scheme": "lectura cruda", "source": "rawscan",
                "label": "contenido en crudo", "aip": None, "afl": None,
                "cardholder": {},
                "records": [{"sfi": s, "record": r, "hex": h} for s, r, h in scan.records],
                "get_data": gd,
            })
            log(f"  crudo: {len(scan.selects)} SELECT, {len(scan.records)} registros, "
                f"{len(scan.get_data)} GET DATA, {len(scan.binaries)} binarios")

    log("Volcado completo.")
    return dump


def capture_reader(reader, **kw) -> CardDump:
    """Conveniencia: captura desde un `OpenReader` (toma ATR y nombre de él).

    Si el lector es de **banda magnética** (sin `transceive`, con `read_swipe`)
    lee un swipe y lo convierte con `swipe_to_dump`; si no, hace captura EMV."""
    name = reader.device.name if reader.device else ""
    if reader.transceive is None and reader.read_swipe is not None:
        timeout = kw.get("timeout", 30.0)
        return swipe_to_dump(reader.swipe(timeout=timeout), reader=name)
    atr = reader.atr() if reader.atr else b""
    return capture_card(reader.transceive, atr=atr, reader=name, **kw)


def swipe_to_dump(raw: str, reader: str = "") -> CardDump:
    """Convierte una lectura HID cruda en un `CardDump` visualizable.

    Estos lectores de banda "teclean" el swipe por HID. El contenido decide:

    * si hay **pistas** (`%B...?;...?`) → app ``MAGSTRIPE`` con PAN/nombre/
      caducidad/código de servicio y las pistas crudas;
    * si hay texto pero **sin centinelas de pista** (p.ej. `2202081151`) → sigue
      siendo una lectura de **banda** (muchas tarjetas de acceso/regalo llevan en
      la banda solo un número): app ``MAGSTRIPE`` con el dato crudo, más su
      interpretación hex por si fuese un UID (el mismo canal HID sirve también
      los taps NFC de los combos, indistinguibles por contenido);
    * si está vacío (timeout) → dump sin aplicaciones.

    El valor crudo se guarda como blob (búsqueda de flags/guardado). Sin TLV: no
    es EMV."""
    from ..core.track import parse_swipe

    parsed = parse_swipe(raw)
    t1, t2, t3 = parsed.get("track1"), parsed.get("track2"), parsed.get("track3")
    has_tracks = any(t is not None for t in (t1, t2, t3))

    apps: list[dict] = []
    if has_tracks:
        fields: dict[str, str] = {}
        pan = getattr(t2, "pan", None) or getattr(t1, "pan", None) or getattr(t3, "pan", None)
        expiry = getattr(t2, "expiry", None) or getattr(t1, "expiry", None)
        service = getattr(t2, "service_code", None) or getattr(t1, "service_code", None)
        name = getattr(t1, "name", None)
        if pan:
            fields["PAN"] = pan
        if name:
            fields["Nombre"] = name
        if expiry:
            fields["Caducidad (YYMM)"] = expiry
        if service:
            fields["Código de servicio"] = service
        for label, t in (("Track 1", t1), ("Track 2", t2), ("Track 3", t3)):
            if t is not None:
                fields[label] = getattr(t, "raw", "")
        apps.append({"aid": "MAGSTRIPE", "scheme": "Banda magnética", "label": "",
                     "source": reader or "swipe", "cardholder": fields, "records": []})
    elif raw.strip():
        token = raw.strip()
        fields = {"Datos": token}
        if token.isdigit():
            hx = f"{int(token):X}"                # por si fuese un UID/número en hex
            if len(hx) % 2:
                hx = "0" + hx
            fields["Hex"] = hx
            # algunos lectores dan los bytes en orden inverso (LSB primero)
            rev = bytes.fromhex(hx)[::-1].hex().upper()
            if rev != hx:
                fields["Hex (LSB primero)"] = rev
        apps.append({"aid": "MAGSTRIPE", "scheme": "Banda magnética", "label": "",
                     "source": reader or "swipe", "cardholder": fields, "records": []})

    dump = CardDump(reader=reader, applications=apps)
    if raw:
        dump.add_blob("hid-read", raw.encode("latin-1", "replace"))
    return dump


def find_flags(dump: CardDump, patterns=None) -> list[Hit]:
    """Busca flags en todos los blobs del volcado."""
    return search_flags(dump.all_blobs(), patterns)
