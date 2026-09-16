#!/usr/bin/env python3
"""EMVyController — CLI para scripting sobre el núcleo funcional.

Interfaz delgada: resuelve el lector con `readers.registry`, toma el perfil de
terminal del proyecto activo (o el por defecto) y delega en `core`/`session`.
Para la interfaz interactiva rica usa `emvy tui`.
"""
from __future__ import annotations

import argparse
import sys

from . import __version__
from . import poc as pocmod
from .core import emv, tlv
from .core.atr import describe_atr
from .core.hexutil import from_hex, hexdump, to_hex
from .core.search import search_flags, search_regex
from .core.track import parse_swipe
from .integrations import bombercat_tools as bctools
from .integrations import pcscd
from .payments import EmvCard
from .project import env as envmod
from .project import store
from .readers import ReaderError, bombercat, registry
from .readers.types import Capability, DeviceInfo
from .session import from_bombercat
from .session.capture import capture_card, find_flags
from .session.model import CardDump
from .term import c


# ---------------------------------------------------------------------------
# Apertura de lector / perfil de terminal
# ---------------------------------------------------------------------------
def open_reader(args):
    dev = registry.resolve(getattr(args, "reader", None))
    on_event = None
    if getattr(args, "verbose", False):
        def on_event(e):
            print(c(f"  >> {e.command}", "grey"))
            print(c(f"  << {e.response}  [{e.sw}]", "grey"))
    return registry.open_device(dev, protocol=getattr(args, "protocol", "any"),
                                on_event=on_event)


def current_profile() -> dict:
    """Perfil de terminal del proyecto activo, o el por defecto."""
    proj = store.active_project()
    if proj:
        return envmod.to_terminal_profile(store.load_project_variables(proj))
    return emv.default_terminal_profile()


def _send_of(reader):
    if reader.transceive is None:
        raise ReaderError(
            f"El lector {reader.device.name!r} no envía APDUs "
            f"({reader.device.caps_str}). Usa un lector de chip o NFC."
        )
    return reader.transceive


# ---------------------------------------------------------------------------
# Comandos: lectores / tarjeta
# ---------------------------------------------------------------------------
def cmd_readers(args) -> int:
    backends = registry.available_backends()
    print(c("Backends:", "bold"),
          "  ".join(f"{n}={'✓' if ok else '✗'}" for n, ok in backends.items()))
    devices = registry.list_all_devices()
    if devices:
        print(c(f"Lectores ({len(devices)}):", "bold"))
        for i, d in enumerate(devices):
            print(f"  [{i}] {c(d.backend, 'cyan')}  {d.name}  {c('(' + d.caps_str + ')', 'grey')}")

    # Diagnóstico del backend de chip (la confusión más común: intérprete sin pyscard).
    has_pcsc = any(d.backend == "pcsc" for d in devices)
    if not backends.get("pcsc"):
        print(c(f"⚠ pcsc no disponible: falta 'pyscard' en este Python ({sys.executable}).",
                "yellow"))
        print(c("  El lector de chip no aparecerá. Usa el venv: "
                ".venv/bin/python ./emvyctl.py readers", "grey"))
    elif not has_pcsc:
        print(c("⚠ pcsc activo pero sin lectores de chip: ¿pcscd? "
                "sudo systemctl start pcscd.socket", "yellow"))

    if not devices:
        print(c("Sin lectores detectados.", "red"))
        return 1
    return 0


def cmd_atr(args) -> int:
    with open_reader(args) as r:
        if r.atr is None:
            print(c("Este lector no expone ATR.", "red")); return 1
        info = describe_atr(r.atr())
        print(c("ATR:", "bold"), c(info["atr"], "yellow"))
        for k in ("convention", "protocols", "historical_count", "historical", "historical_ascii"):
            if k in info:
                print(f"  {k:18}: {info[k]}")
    return 0


def cmd_discover(args) -> int:
    with open_reader(args) as r:
        apps = emv.discover(_send_of(r), brute=not args.no_brute)
        if not apps:
            print(c("No se encontraron aplicaciones.", "red")); return 1
        print(c(f"{len(apps)} aplicación(es):", "bold"))
        for a in apps:
            label = f'  "{a.label}"' if a.label else ""
            prio = f"  prio={a.priority}" if a.priority is not None else ""
            print(f"  {c(a.aid, 'cyan')}  {a.scheme}  [{a.source}]{label}{prio}")
    return 0


def cmd_select(args) -> int:
    with open_reader(args) as r:
        send = _send_of(r)
        name = args.aid.lower()
        if name in ("pse", "1pay", "ppse", "2pay"):
            from .core.aids import PPSE, PSE
            target = PSE if name in ("pse", "1pay") else PPSE
            resp, fci = emv.select_name(send, target)
            print(fci.dump(c) if fci else f"SW {resp.sw:04X} {resp.sw_str()}")
            return 0
        app = emv.select_application(send, args.aid)
        print(c(f"AID {app.aid}  ({app.scheme})", "bold"), app.label)
        if app.fci:
            print(app.fci.dump(c))
        resp, app = emv.get_processing_options(send, app, current_profile())
        print()
        if resp.ok:
            print(c("GPO:", "bold"),
                  f"AIP={to_hex(app.aip or b'')} AFL={to_hex(app.afl or b'')}")
            app = emv.read_afl_records(send, app)
            for rec in app.records:
                print(c(f"  SFI {rec.sfi} REC {rec.number}:", "magenta"))
                print(rec.tlvs.dump(c))
        else:
            print(c(f"GPO -> {resp.sw_hex} {resp.sw_str()}", "red"))
    return 0


def cmd_records(args) -> int:
    with open_reader(args) as r:
        recs = emv.sweep_records(_send_of(r), max_sfi=args.max_sfi, max_rec=args.max_rec)
        if not recs:
            print(c("Sin registros legibles (¿seleccionaste una app primero?).", "red"))
            print("Consejo: usa 'info' o 'shell' para SELECT + GPO antes del barrido.")
            return 1
        for rec in recs:
            print(c(f"── SFI {rec.sfi}  REC {rec.number} ({len(rec.raw)} bytes) ──", "magenta", "bold"))
            print(rec.tlvs.dump(c) if rec.tlvs else hexdump(rec.raw))
            print()
    return 0


def cmd_getdata(args) -> int:
    tag = int(args.tag, 16)
    with open_reader(args) as r:
        resp = emv.get_data(_send_of(r), tag)
        print(c(f"GET DATA {tag:04X}", "bold"), f"-> {resp.sw_hex} {resp.sw_str()}")
        if resp.data:
            parsed = tlv.parse(resp.data)
            print(parsed.dump(c) if parsed else hexdump(resp.data))
    return 0


def cmd_apdu(args) -> int:
    with open_reader(args) as r:
        resp = _send_of(r)(from_hex(args.hex))
        print(c(">>", "grey"), args.hex.upper())
        print(c("<<", "grey"),
              f"{to_hex(resp.data, sep=' ')}  [{resp.sw_hex}] {resp.sw_str()}")
        if resp.data:
            parsed = tlv.parse(resp.data)
            if parsed:
                print(parsed.dump(c))
    return 0


def _capture(args, reader) -> CardDump:
    def progress(msg):
        print(c("  · ", "grey") + msg, file=sys.stderr)
    return capture_card(
        _send_of(reader),
        atr=(reader.atr() if reader.atr else b""),
        reader=reader.device.name,
        profile=current_profile(),
        brute=not getattr(args, "no_brute", False),
        sweep=not getattr(args, "no_sweep", False),
        get_data=not getattr(args, "no_getdata", False),
        raw=getattr(args, "raw", False),
        mode=getattr(args, "mode", "auto"),
        progress=progress,
    )


def cmd_dump(args) -> int:
    with open_reader(args) as r:
        dump = _capture(args, r)
    text = dump.to_json()
    if args.save:  # guardar en un proyecto (activo o el elegido con --project)
        if getattr(args, "project", None):
            proj = (store.open_project_path(args.project) if _looks_like_path(args.project)
                    else store.open_project(args.project))
        else:
            proj = store.active_project()
        if not proj:
            print(c("No hay proyecto (usa --project <n|ruta> o 'project use <n>').", "red")); return 1
        dest = store.save_capture(proj, args.save, text)
        print(c(f"Captura guardada en el proyecto {proj.name}: {dest}", "green"))
    elif args.output:
        with open(args.output, "w") as f:
            f.write(text)
        print(c(f"Dump guardado en {args.output}", "green"),
              f"({len(dump.blobs)} blobs, {len(dump.applications)} apps)")
    else:
        print(text)
    return 0


def cmd_info(args) -> int:
    with open_reader(args) as r:
        if r.atr:
            info = describe_atr(r.atr())
            print(c("═══ ATR ═══", "bold"))
            print(f"  {info['atr']}  ({info.get('convention','')}, {', '.join(info.get('protocols', []))})")
        dump = _capture(args, r)
    print()
    for app in dump.applications:
        print(c(f"═══ AID {app['aid']} ═══", "bold", "cyan"),
              f"{app['scheme']}  {app.get('label','')}  [{app['source']}]")
        ch = app.get("cardholder") or {}
        for k in ("pan", "cardholder", "expiry", "expiry_track2", "service_code", "track2", "pan_seq"):
            if k in ch:
                print(f"  {c(k, 'green'):>26}: {ch[k]}")
        if app.get("aip"):
            print(f"  {'AIP':>18}: {app['aip']}   {'AFL':>4}: {app.get('afl')}")
        for rec in app["records"]:
            raw = from_hex(rec["hex"])
            print(c(f"  ── SFI {rec['sfi']} REC {rec['record']} ──", "magenta"))
            parsed = tlv.parse(raw)
            print(_indent(parsed.dump(c) if parsed else hexdump(raw), 4))
        if app.get("get_data"):
            print(c("  ── GET DATA ──", "magenta"))
            for tg, hx in app["get_data"].items():
                print(f"    {c(tg, 'cyan')}: {hx}")
        print()
    _print_hits(find_flags(dump))
    return 0


def _load_or_capture(args) -> CardDump:
    if getattr(args, "file", None):
        with open(args.file) as f:
            return CardDump.from_json(f.read())
    with open_reader(args) as r:
        return _capture(args, r)


def _add_write_ops(wsub, handler=None) -> None:
    """Agrega los sub-subcomandos de escritura (record/binary/data/append) a un
    `add_subparsers()`. Reutilizado por `write` y `bombercat write` (con un
    `handler` distinto para forzar el lector BomberCat antes de escribir)."""
    handler = handler or cmd_write
    q = wsub.add_parser("record", help="UPDATE RECORD")
    q.add_argument("sfi", type=int); q.add_argument("record", type=int); q.add_argument("hex")
    q.set_defaults(func=handler)
    q = wsub.add_parser("binary", help="UPDATE BINARY")
    q.add_argument("offset", type=int); q.add_argument("hex")
    q.add_argument("--sfi", type=int, default=None)
    q.set_defaults(func=handler)
    q = wsub.add_parser("data", help="PUT DATA")
    q.add_argument("tag", help="tag hex (p.ej. 9F36)"); q.add_argument("hex")
    q.set_defaults(func=handler)
    q = wsub.add_parser("append", help="APPEND RECORD")
    q.add_argument("sfi", type=int); q.add_argument("hex")
    q.set_defaults(func=handler)


def cmd_write(args) -> int:
    """ESCRIBE en la tarjeta (UPDATE RECORD/BINARY, PUT DATA, APPEND RECORD).
    Modifica la tarjeta; úsalo solo con tarjetas propias/de laboratorio."""
    from .core import cardwrite
    from .core.hexutil import from_hex, to_hex
    try:
        data = from_hex(args.hex)
    except ValueError:
        print(c("Hex inválido.", "red")); return 1
    with open_reader(args) as r:
        send = _send_of(r)
        op = args.op
        if op == "record":
            resp = cardwrite.update_record(send, args.sfi, args.record, data)
            what = f"UPDATE RECORD sfi={args.sfi} rec={args.record}"
        elif op == "binary":
            resp = cardwrite.update_binary(send, args.offset, data, sfi=getattr(args, "sfi", None))
            what = f"UPDATE BINARY offset={args.offset} sfi={getattr(args, 'sfi', None)}"
        elif op == "data":
            resp = cardwrite.put_data(send, int(args.tag, 16), data)
            what = f"PUT DATA tag={args.tag}"
        elif op == "append":
            resp = cardwrite.append_record(send, args.sfi, data)
            what = f"APPEND RECORD sfi={args.sfi}"
        else:
            print(c("Operación desconocida.", "red")); return 1
    ok = resp.sw == 0x9000
    print(c(f"{what}  <-  {to_hex(data)}", "bold"))
    print(c(f"  SW {resp.sw_hex}  {cardwrite.write_status(resp.sw)}",
            "green" if ok else "red"))
    if resp.data:
        print(f"  data: {to_hex(resp.data)}")
    return 0 if ok else 1


def _fuzz_track_kwargs(args) -> dict:
    kw = {}
    for attr, key in (("pan", "pan"), ("name", "name"), ("expiry", "expiry"),
                      ("service_code", "service_code")):
        val = getattr(args, attr, None)
        if val:
            kw[key] = val
    return kw


def cmd_fuzz_track(args) -> int:
    """Plantillas de banda magnética para probar terminales (vía BomberCat
    magspoof). No es una tarjeta real: sirve para ver cómo reacciona un
    lector/POS ante datos fuera de lo normal."""
    from .core import cardfuzz
    templates = cardfuzz.track_templates(**_fuzz_track_kwargs(args))
    if args.action == "list":
        print(c("Plantillas de banda magnética:", "bold"))
        for t in templates:
            print(f"  {c(t.id, 'cyan'):<28} {t.title}")
            print(f"    {c(t.description, 'grey')}")
        return 0
    t = cardfuzz.get_track_template(templates, args.id)
    if not t:
        print(c(f"Plantilla desconocida: {args.id!r}. Usa 'fuzz track list'.", "red"))
        return 1
    if args.action == "show":
        print(c(f"{t.title}", "bold")); print(c(t.description, "grey"))
        print(f"  track1: {t.track1}")
        print(f"  track2: {t.track2}")
        return 0
    if args.action == "send":
        tgt = _bombercat_target(args)
        print(c(f"Enviando {t.id!r} por magspoof…", "yellow"))
        out = bombercat.magspoof_emit(tgt, track1=t.track1, track2=t.track2)
        print(c("magspoof:", "bold"), out)
        return 0
    return 1


def cmd_fuzz_card(args) -> int:
    """Plantillas de registro EMV para escribir en una tarjeta de prueba
    reescribible y observar cómo reacciona un terminal real ante campos fuera
    de lo normal (CVM/AIP forzados, PAN inválido, campos truncados…)."""
    from .core import cardfuzz
    kw = {}
    for attr in ("pan", "name", "expiry"):
        val = getattr(args, attr, None)
        if val:
            kw[attr] = val
    templates = cardfuzz.emv_templates(**kw)
    if args.action == "list":
        print(c("Plantillas de registro EMV:", "bold"))
        for t in templates:
            print(f"  {c(t.id, 'cyan'):<16} {t.title}")
            print(f"    {c(t.description, 'grey')}")
        return 0
    t = cardfuzz.get_emv_template(templates, args.id)
    if not t:
        print(c(f"Plantilla desconocida: {args.id!r}. Usa 'fuzz card list'.", "red"))
        return 1
    record = t.to_record()
    if args.action == "show":
        from .core.hexutil import to_hex
        print(c(f"{t.title}", "bold")); print(c(t.description, "grey"))
        print(f"  registro: {to_hex(record)}")
        return 0
    if args.action == "write":
        from .core import cardwrite
        from .core.hexutil import to_hex
        with open_reader(args) as r:
            resp = cardwrite.update_record(_send_of(r), args.sfi, args.record, record)
        ok = resp.sw == 0x9000
        print(c(f"UPDATE RECORD sfi={args.sfi} rec={args.record}  <-  {t.id}", "bold"))
        print(c(f"  SW {resp.sw_hex}  {cardwrite.write_status(resp.sw)}",
                "green" if ok else "red"))
        return 0 if ok else 1
    return 1


def _ndef_message_from_args(args):
    """Resuelve el mensaje NDEF a emular según la fuente: `--test-card`,
    `--card <captura>`, o una plantilla por `id`. Devuelve (hex, etiqueta)."""
    from pathlib import Path

    from .core import cardfuzz
    from .core.hexutil import to_hex
    if getattr(args, "test_card", False):
        return to_hex(cardfuzz.test_card_ndef()), "tarjeta de prueba"
    card_src = getattr(args, "card", None)
    if card_src:
        from .payments import EmvCard
        p = Path(card_src)
        if not p.exists():  # nombre de captura en el proyecto activo
            proj = store.active_project()
            if proj:
                fname = card_src if card_src.endswith(".json") else card_src + ".json"
                p = proj.captures_dir / fname
        dump = CardDump.from_json(Path(p).read_text())
        card = EmvCard.from_dump(dump)
        msg = cardfuzz.card_ndef_from_fields(
            pan=card.pan_digits, expiry=card.expiry, track2=card.track2,
            aid=card.aid, label=card.label)
        return to_hex(msg), f"captura {card_src}"
    kw = {k: getattr(args, k) for k in ("url", "text") if getattr(args, k, None)}
    t = cardfuzz.get_ndef_template(cardfuzz.ndef_templates(**kw), args.id)
    if not t:
        return None, None
    return t.to_hex(), f"plantilla {t.id}"


def cmd_fuzz_ndef(args) -> int:
    """Emula un tag NFC (vía BomberCat, comando EMU:) a partir de una plantilla
    NDEF, una tarjeta de prueba (`--test-card`) o una captura guardada
    (`--card`). Equivalente NFC de magspoof. Nota: solo NDEF, no una tarjeta EMV
    funcional (limitación del firmware/PN7150)."""
    from .core import cardfuzz
    if args.action == "list":
        print(c("Plantillas NDEF (emulación NFC):", "bold"))
        for t in cardfuzz.ndef_templates():
            print(f"  {c(t.id, 'cyan'):<22} {t.title}")
            print(f"    {c(t.description, 'grey')}")
        print(c("  (además: --test-card  ·  --card <captura>)", "grey"))
        return 0
    hexmsg, label = _ndef_message_from_args(args)
    if hexmsg is None:
        print(c(f"Fuente NDEF desconocida ({args.id!r}). Usa 'fuzz ndef list'.", "red"))
        return 1
    if args.action == "show":
        print(c(label, "bold"))
        print(f"  NDEF ({len(hexmsg)//2} bytes): {hexmsg or '(vacío)'}")
        return 0
    if args.action == "emit":
        tgt = _bombercat_target(args)
        print(c(f"Emulando tag NDEF [{label}] ({len(hexmsg)//2} bytes)… "
                "acerca un lector NFC (Ctrl-C para detener).", "yellow"))

        def _show(line: str) -> None:
            if line.startswith("EMU:MSG-SENT"):
                col = "green"
            elif line.startswith("EMU:RX"):
                col = "cyan"        # lo que pide el lector (SELECT/READ off/len)
            elif line.startswith("EMU:TX"):
                col = "magenta"     # nuestra respuesta
            elif line.startswith("EMU:DONE") or line.startswith("ERR"):
                col = "yellow"
            else:
                col = "grey"
            print(c(f"  {line}", col))

        try:
            bombercat.ndef_emulate(tgt, hexmsg, timeout=None, on_line=_show)
        except KeyboardInterrupt:
            print("\ninterrumpido (STOP enviado).")
        return 0
    return 1


def cmd_analyze(args) -> int:
    """Análisis de seguridad EMV: capacidades (AIP/AUC/TTQ), CVM y ODA."""
    from pathlib import Path

    from .core import analyze
    from .core.hexutil import from_hex
    from .session.model import tlvs_from_dump
    if args.file:
        dump = CardDump.from_json(Path(args.file).read_text())
    else:
        with open_reader(args) as r:
            dump = _capture(args, r)
    app, tlvs = tlvs_from_dump(dump, args.aid)
    if not tlvs:
        print(c("No hay datos de aplicación para analizar.", "red")); return 1
    ca_mod = from_hex(args.ca_modulus) if args.ca_modulus else None
    a = analyze.assess(tlvs, ca_modulus=ca_mod, ca_exponent=int(args.ca_exponent))
    print(c(f"═══ Análisis EMV — AID {app['aid']} ({app.get('scheme','?')}) ═══", "bold"))
    print(a.summary(color=c))
    return 0


def cmd_flags(args) -> int:
    dump = _load_or_capture(args)
    if not _print_hits(search_flags(dump.all_blobs())):
        print(c("Sin coincidencias con patrones de flag por defecto.", "yellow"))
        print("Prueba 'search <patrón>' con un patrón específico del CTF.")
        return 1
    return 0


def cmd_search(args) -> int:
    dump = _load_or_capture(args)
    hits = search_regex(dump.all_blobs(), args.pattern, case_insensitive=not args.case_sensitive)
    if not _print_hits(hits):
        print(c(f"Sin coincidencias para /{args.pattern}/.", "yellow"))
        return 1
    return 0


def _print_hits(hits) -> bool:
    if not hits:
        return False
    print(c(f"╔══ {len(hits)} posible(s) flag(s) ══╗", "green", "bold"))
    for h in hits:
        print(f"  {c(h.match, 'green', 'bold')}")
        print(f"    {c('en', 'grey')} {h.source}  {c('(' + h.where + ')', 'grey')}")
        print(f"    {c('ctx:', 'grey')} …{h.context}…")
    return True


def _indent(text: str, n: int) -> str:
    pad = " " * n
    return "\n".join(pad + line for line in text.splitlines())


# ---------------------------------------------------------------------------
# Comandos: banda magnética
# ---------------------------------------------------------------------------
def cmd_track(args) -> int:
    if args.read:
        with open_reader(args) as r:
            if r.read_swipe is None:
                print(c("El lector seleccionado no lee banda magnética.", "red")); return 1
            print(c("Pasa la tarjeta por el lector…", "yellow"))
            raw = r.swipe(timeout=args.timeout)
    else:
        raw = args.swipe or ""
    parsed = parse_swipe(raw)
    print(c("raw:", "grey"), parsed.get("raw", ""))
    for key in ("track1", "track2", "track3"):
        if key in parsed:
            t = parsed[key]
            print(c(f"{key}:", "bold"))
            for field_name in ("pan", "name", "expiry", "service_code", "discretionary"):
                val = getattr(t, field_name, None)
                if val:
                    print(f"  {c(field_name, 'green')}: {val}")
    if len(parsed) <= 1:
        print(c("No se pudo parsear ninguna pista.", "yellow")); return 1
    return 0


def cmd_iso8583(args) -> int:
    """Traduce un mensaje ISO 8583 crudo (hex) a algo legible. Auto-detecta la
    dirección (envío/recepción) desde el MTI, así que sirve para SEND y RCV."""
    from .payments import iso8583
    raw_hex = args.hex
    if raw_hex == "-":                       # leer de stdin (para pipelines)
        raw_hex = sys.stdin.read()
    raw_hex = "".join(raw_hex.split())       # tolera espacios/saltos de línea
    try:
        data = bytes.fromhex(raw_hex)
    except ValueError:
        print(c("Hex inválido.", "red")); return 1
    try:
        view = iso8583.translate(data)
    except Exception as e:                    # bitmap/DE inconsistente con el spec
        print(c(f"No se pudo parsear como ISO 8583: {e}", "red"))
        print(c("¿Falta algún DE en el spec o el mensaje está truncado?", "grey"))
        return 1
    print(view.text(color=c))
    return 0


# ---------------------------------------------------------------------------
# Comandos: proyectos
# ---------------------------------------------------------------------------
def _looks_like_path(s: str) -> bool:
    from pathlib import Path
    return ("/" in s) or s.startswith(".") or s.startswith("~") or Path(s).is_dir()


def cmd_project(args) -> int:
    action = args.action
    if action == "list":
        active = store.active_project()
        active_rp = active.path.resolve() if active else None

        def _mark(p):
            return c(" *", "green", "bold") if active_rp and p.path.resolve() == active_rp else "  "

        xdg = store.list_projects()
        path_projs = store.list_path_projects()
        if not xdg and not path_projs and not active_rp:
            print("Sin proyectos. Crea uno con: emvy project new <nombre>"); return 0
        if xdg:
            print(c("Proyectos (XDG):", "bold"))
            for p in xdg:
                print(f"{_mark(p)} {c(p.name, 'cyan')}  {c(p.created, 'grey')}  {p.description}")
        if path_projs:
            print(c("Engagements (en ruta):", "bold"))
            for p in path_projs:
                print(f"{_mark(p)} {c(p.name, 'cyan')}  {c(str(p.path), 'grey')}  {p.description}")
        # el activo es una ruta fuera de las raíces conocidas -> muéstralo igual
        shown = {p.path.resolve() for p in xdg} | {p.path.resolve() for p in path_projs}
        if active_rp and active_rp not in shown:
            print(f"{c(' *', 'green', 'bold')} {c(str(active_rp), 'cyan')}  {c('(ruta activa)', 'grey')}")
        return 0
    if action == "new":
        if getattr(args, "path", None):
            p = store.create_project_at(args.path, name=args.name,
                                        description=args.desc or "", reader=args.reader or "")
            store.set_active_path(p.path)
        else:
            p = store.create_project(args.name, description=args.desc or "", reader=args.reader or "")
            store.set_active(p.name)
        print(c(f"Proyecto {p.name!r} creado y activado.", "green"), f"({p.path})")
        return 0
    if action == "use":
        if _looks_like_path(args.name):
            store.set_active_path(args.name)
        else:
            store.set_active(args.name)
        print(c(f"Proyecto activo: {store.active_label()}", "green"))
        return 0
    if action == "rm":
        store.delete_project(args.name)
        print(c(f"Proyecto {args.name!r} eliminado.", "yellow"))
        return 0
    if action == "show":
        if args.name:
            p = store.open_project_path(args.name) if _looks_like_path(args.name) \
                else store.open_project(args.name)
        else:
            p = store.active_project()
        if not p:
            print(c("No hay proyecto activo.", "red")); return 1
        print(c(f"Proyecto {p.name}", "bold"))
        print(f"  ruta        : {p.path}")
        print(f"  descripción : {p.description}")
        print(f"  creado      : {p.created}")
        print(f"  lector      : {p.reader or '(auto)'}")
        print(f"  capturas    : {len(store.list_captures(p))}")
        return 0
    if action == "export":
        if args.name:
            p = store.open_project_path(args.name) if _looks_like_path(args.name) \
                else store.open_project(args.name)
        else:
            p = store.active_project()
        if not p:
            print(c("No hay proyecto (indica uno o activa alguno).", "red")); return 1
        out = store.export_project(p, args.output or ".", include_runs=not args.no_runs)
        size = out.stat().st_size
        print(c(f"Proyecto {p.name!r} exportado.", "green"), f"→ {out} ({size} bytes)")
        return 0
    if action == "import":
        p = store.import_project(args.archive, name=args.name,
                                 overwrite=args.overwrite, dest_path=args.path)
        print(c(f"Proyecto {p.name!r} importado.", "green"), f"({p.path})")
        if args.use:
            store.set_active_path(p.path) if args.path else store.set_active(p.name)
            print(c(f"Proyecto activo: {store.active_label()}", "green"))
        return 0
    return 1


# ---------------------------------------------------------------------------
# Comandos: variables de entorno
# ---------------------------------------------------------------------------
def _require_project():
    proj = store.active_project()
    if not proj:
        raise ReaderError("No hay proyecto activo. Usa 'emvy project use <nombre>'.")
    return proj


def cmd_gp_keyset(args) -> int:
    """Gestiona los keysets de GlobalPlatform (claves del Secure Channel) del
    proyecto activo: las claves ENC/MAC/KEK que autentican el canal seguro para
    escribir/gestionar contenido en una JavaCard."""
    from .core.gp.keyset import Keyset
    proj = _require_project()
    action = args.action

    if action == "add":
        try:
            if args.same:
                ks = Keyset.same_key(args.name, key=args.same, kvn=args.kvn,
                                     scp=args.scp, description=args.desc or "")
            else:
                if not (args.enc and args.mac and args.kek):
                    print(c("Da --enc/--mac/--kek, o --same <clave> para las tres.", "red"))
                    return 1
                ks = Keyset(name=args.name, enc=args.enc, mac=args.mac, kek=args.kek,
                            kvn=args.kvn, scp=args.scp, description=args.desc or "")
        except ValueError as e:
            print(c(f"Keyset inválido: {e}", "red")); return 1
        store.add_keyset(proj, ks)
        print(c(f"Keyset {ks.name!r} guardado en {proj.name} "
                f"(kvn={ks.kvn}, scp={ks.scp}).", "green"))
        return 0

    if action == "list":
        keysets = store.load_keysets(proj)
        if not keysets:
            print(c("(sin keysets; añade con 'gp keyset add')", "grey")); return 0
        print(c("Keysets de GlobalPlatform:", "bold"))
        for k in keysets:
            m = k.masked()
            print(f"  {c(k.name, 'cyan'):<20} kvn={k.kvn} scp={k.scp}  "
                  f"enc={m['enc']} mac={m['mac']} kek={m['kek']}  {c(k.description, 'grey')}")
        return 0

    if action == "show":
        k = store.get_keyset(proj, args.name)
        if not k:
            print(c(f"No existe el keyset {args.name!r}.", "red")); return 1
        v = k.to_dict() if args.reveal else k.masked()
        for field in ("name", "kvn", "scp", "enc", "mac", "kek", "description"):
            print(f"  {c(field, 'green'):<14} {v[field]}")
        if not args.reveal:
            print(c("  (usa --reveal para ver las claves completas)", "grey"))
        return 0

    if action == "rm":
        if not store.get_keyset(proj, args.name):
            print(c(f"No existe el keyset {args.name!r}.", "red")); return 1
        store.remove_keyset(proj, args.name)
        print(c(f"Keyset {args.name!r} borrado.", "green"))
        return 0
    return 1


def cmd_gp_op(args) -> int:
    """Operaciones de GlobalPlatform contra la tarjeta: abre el canal seguro con
    un keyset del proyecto y ejecuta auth/status/install/delete/store-data."""
    from .core.gp import apdu as gpapdu
    from .core.gp import cap as capmod
    from .core.gp import content
    from .core.gp.scp import GPError, SEC_CENC, SEC_CMAC
    proj = _require_project()
    ks = store.get_keyset(proj, args.keyset)
    if not ks:
        print(c(f"No existe el keyset {args.keyset!r}. Añádelo con 'gp keyset add'.", "red"))
        return 1
    level = SEC_CENC if getattr(args, "enc", False) else SEC_CMAC
    try:
        with open_reader(args) as r:
            if r.transceive is None:
                print(c("El lector conectado no soporta APDUs (no es de chip/NFC).", "red"))
                return 1
            chan = content.authenticate(r.transceive, ks, security_level=level)
            print(c(f"Canal seguro abierto: SCP{chan.protocol}, keyset {ks.name} "
                    f"(nivel {'C-ENC+C-MAC' if level == SEC_CENC else 'C-MAC'}).", "green"))

            if args.gpcmd == "auth":
                return 0
            if args.gpcmd == "status":
                inv = content.list_all(chan)
                for key, label in (("isd", "ISD"), ("apps", "Aplicaciones / SD"),
                                   ("load_files", "Paquetes (load files)")):
                    print(c(f"── {label} ──", "bold", "cyan"))
                    if not inv[key]:
                        print(c("  (ninguno)", "grey"))
                    for a in inv[key]:
                        print(f"  {c(a.aid, 'green'):<34} {a.lifecycle:<12} {c(a.privileges, 'grey')}")
                return 0
            if args.gpcmd == "delete":
                content.delete(chan, from_hex(args.aid), related=not args.no_related)
                print(c(f"DELETE {args.aid} OK.", "green"))
                return 0
            if args.gpcmd == "store-data":
                resp = chan.send(gpapdu.store_data(from_hex(args.hex)))
                if not resp.ok:
                    print(c(f"STORE DATA: {resp.sw_hex} ({resp.sw_str()})", "red")); return 1
                print(c("STORE DATA OK.", "green")); return 0
            if args.gpcmd == "install":
                capf = capmod.parse_cap(args.cap)
                print(c(f"CAP: paquete {capf.package_aid_hex}, applets "
                        f"{[to_hex(a) for a in capf.applet_aids]}", "grey"))
                res = content.install_cap(
                    chan, capf,
                    instance_aid=from_hex(args.instance) if args.instance else None,
                    module_aid=from_hex(args.module) if args.module else None,
                    privileges=from_hex(args.priv) if args.priv else b"\x00",
                    params=from_hex(args.params) if args.params else b"",
                    make_selectable=not args.load_only, force=args.force)
                for step, sw in res.steps:
                    print(f"  {c(step, 'cyan'):<22} {sw}")
                print(c(f"Instalado: paquete {res.package_aid}"
                        + (f", instancia {res.instance_aid}" if res.instance_aid else "")
                        + f" ({res.load_blocks} bloques).", "green"))
                return 0
    except GPError as e:
        print(c(f"GlobalPlatform: {e}", "red")); return 1
    except ReaderError as e:
        print(c(str(e), "red")); return 1
    return 1


def cmd_var(args) -> int:
    action = args.action
    if action == "profiles":
        from .project import profiles as profilesmod
        print(c("Perfiles de terminal preconfigurados:", "bold"))
        for p in profilesmod.list_profiles():
            print(f"  {c(p.id, 'cyan'):<24} {p.title}")
            print(f"    {c(p.description, 'grey')}")
        print("Uso: emvy var apply <id>")
        return 0

    proj = _require_project()
    variables = store.load_project_variables(proj)

    if action == "apply":
        from .project import profiles as profilesmod
        try:
            variables = profilesmod.apply_profile(variables, args.id)
        except ValueError as e:
            print(c(str(e), "red")); return 1
        store.save_project_variables(proj, variables)
        p = profilesmod.get(args.id)
        print(c(f"Perfil {p.id!r} aplicado: {p.title}", "green"))
        for alias, value in p.values.items():
            print(f"  {c(alias, 'green')} = {value}")
        return 0
    if action == "list":
        term = [v for v in variables if v.kind == "terminal"]
        user = [v for v in variables if v.kind == "user"]
        print(c("── Perfil de terminal (EMV) ──", "bold", "cyan"))
        for v in sorted(term, key=lambda x: x.tag or ""):
            print(f"  {c(v.tag, 'cyan')} {c(v.name, 'green'):<22} = {v.value}   {c(v.description, 'grey')}")
        print(c("── Variables libres ──", "bold", "cyan"))
        if not user:
            print(c("  (ninguna)", "grey"))
        for v in user:
            print(f"  {c(v.name, 'green'):<22} = {v.value}   {c(v.description, 'grey')}")
        return 0
    if action == "get":
        v = envmod.get_var(variables, args.name)
        if not v:
            print(c(f"No existe la variable {args.name!r}.", "red")); return 1
        print(v.value)
        return 0
    if action == "set":
        kind = "user" if args.user else None
        variables = envmod.set_var(variables, args.name, args.value, kind=kind,
                                   description=args.desc or "")
        store.save_project_variables(proj, variables)
        v = envmod.get_var(variables, args.name)
        print(c(f"{v.name} = {v.value}", "green"),
              c(f"[{v.kind}{'/' + v.tag if v.tag else ''}]", "grey"))
        return 0
    if action == "rm":
        if not envmod.get_var(variables, args.name):
            print(c(f"No existe la variable {args.name!r}.", "red")); return 1
        variables = envmod.del_var(variables, args.name)
        store.save_project_variables(proj, variables)
        print(c(f"Variable {args.name!r} eliminada.", "yellow"))
        return 0
    return 1


# ---------------------------------------------------------------------------
# Comando: TUI
# ---------------------------------------------------------------------------
def cmd_tui(args) -> int:
    try:
        from .tui.app import run as run_tui
    except ModuleNotFoundError as e:
        if "textual" in str(e).lower() or e.name == "textual":
            print(c("La TUI requiere Textual.", "red"))
            print("Instálalo con:  uv pip install --python .venv textual")
            print("Mientras tanto puedes usar la CLI o 'emvy shell'.")
            return 1
        raise
    return run_tui()


def cmd_gui(args) -> int:
    try:
        from .gui import launch
    except ModuleNotFoundError as e:
        if "PySide6" in str(e) or getattr(e, "name", "") == "PySide6":
            print(c("La GUI requiere PySide6.", "red"))
            print("Instálalo con:  uv pip install --python .venv 'emvyctl[gui]'")
            print("               (o:  uv pip install --python .venv PySide6)")
            return 1
        raise
    return launch()


# ---------------------------------------------------------------------------
# Shell interactivo
# ---------------------------------------------------------------------------
SHELL_HELP = """\
Comandos del shell EMVy:
  atr                     ATR y protocolo
  discover [nobrute]      lista aplicaciones (PPSE/PSE/bruteforce)
  select <aid|pse|ppse>   SELECT (por AID hex o nombre PSE)
  gpo                     GET PROCESSING OPTIONS de la app actual
  afl                     lee los registros del AFL de la app actual
  records [maxsfi]        barrido bruto de registros
  getdata <tag>           GET DATA (tag hex, p.ej. 9F36)
  raw <hex> | apdu <hex>  envía un APDU crudo
  dump [archivo.json]     volcado completo (opcionalmente a archivo)
  flags                   busca flags en el volcado completo
  search <patrón>         busca un regex en el volcado completo
  vars                    muestra el perfil de terminal activo
  trace                   muestra el historial de APDUs
  help                    esta ayuda
  quit | exit             salir
"""


def cmd_shell(args) -> int:
    try:
        reader = open_reader(args)
        send = _send_of(reader)
    except ReaderError as e:
        print(c(str(e), "red")); return 1
    print(c(f"EMVyController shell v{__version__}", "bold"), f"— {reader.device}")
    print("Escribe 'help' para ver comandos. 'quit' para salir.\n")
    profile = current_profile()
    current = None
    try:
        while True:
            try:
                line = input(c("emvy> ", "cyan", "bold")).strip()
            except EOFError:
                break
            if not line:
                continue
            parts = line.split()
            cmd, rest = parts[0].lower(), parts[1:]
            try:
                if cmd in ("quit", "exit", "q"):
                    break
                elif cmd in ("help", "?", "h"):
                    print(SHELL_HELP)
                elif cmd == "atr":
                    print(c(describe_atr(reader.atr())["atr"], "yellow"))
                elif cmd == "discover":
                    for a in emv.discover(send, brute="nobrute" not in rest):
                        print(f"  {c(a.aid, 'cyan')} {a.scheme} [{a.source}] {a.label}")
                elif cmd == "select":
                    if not rest:
                        print("uso: select <aid|pse|ppse>"); continue
                    tgt = rest[0].lower()
                    if tgt in ("pse", "ppse"):
                        from .core.aids import PPSE, PSE
                        resp, fci = emv.select_name(send, PSE if tgt == "pse" else PPSE)
                        print(fci.dump(c) if fci else f"SW {resp.sw:04X}")
                    else:
                        current = emv.select_application(send, rest[0])
                        print(c(f"App actual: {current.aid}", "green"), f"{current.scheme} {current.label}")
                        if current.fci:
                            print(current.fci.dump(c))
                elif cmd == "gpo":
                    if not current:
                        print(c("Primero 'select <aid>'.", "red")); continue
                    resp, current = emv.get_processing_options(send, current, profile)
                    print(f"AIP={to_hex(current.aip or b'')} AFL={to_hex(current.afl or b'')}"
                          if resp.ok else c(f"SW {resp.sw_hex} {resp.sw_str()}", "red"))
                elif cmd == "afl":
                    if not current:
                        print(c("Primero 'select' y 'gpo'.", "red")); continue
                    current = emv.read_afl_records(send, current)
                    for rec in current.records:
                        print(c(f"SFI {rec.sfi} REC {rec.number}:", "magenta"))
                        print(rec.tlvs.dump(c))
                elif cmd == "records":
                    mx = int(rest[0]) if rest else 31
                    for rec in emv.sweep_records(send, max_sfi=mx):
                        print(c(f"SFI {rec.sfi} REC {rec.number}:", "magenta"))
                        print(rec.tlvs.dump(c) if rec.tlvs else hexdump(rec.raw))
                elif cmd == "getdata":
                    if not rest:
                        print("uso: getdata <tag hex>"); continue
                    resp = emv.get_data(send, int(rest[0], 16))
                    print(f"[{resp.sw_hex}] {resp.sw_str()}")
                    if resp.data:
                        print(tlv.parse(resp.data).dump(c) or hexdump(resp.data))
                elif cmd in ("raw", "apdu"):
                    if not rest:
                        print("uso: raw <hex>"); continue
                    resp = send(from_hex("".join(rest)))
                    print(c("<<", "grey"), f"{to_hex(resp.data, sep=' ')} [{resp.sw_hex}] {resp.sw_str()}")
                    if resp.data:
                        p = tlv.parse(resp.data)
                        if p:
                            print(p.dump(c))
                elif cmd == "dump":
                    d = capture_card(send, atr=(reader.atr() if reader.atr else b""),
                                     reader=reader.device.name, profile=profile)
                    if rest:
                        with open(rest[0], "w") as f:
                            f.write(d.to_json())
                        print(c(f"Guardado en {rest[0]}", "green"))
                    else:
                        print(d.to_json())
                elif cmd == "flags":
                    d = capture_card(send, atr=(reader.atr() if reader.atr else b""),
                                     reader=reader.device.name, profile=profile)
                    if not _print_hits(find_flags(d)):
                        print(c("Sin flags con patrones por defecto.", "yellow"))
                elif cmd == "search":
                    if not rest:
                        print("uso: search <patrón>"); continue
                    d = capture_card(send, atr=(reader.atr() if reader.atr else b""),
                                     reader=reader.device.name, profile=profile)
                    if not _print_hits(search_regex(d.all_blobs(), " ".join(rest))):
                        print(c("Sin coincidencias.", "yellow"))
                elif cmd == "vars":
                    for tag, val in sorted(profile.items()):
                        print(f"  {c(tag, 'cyan')} = {to_hex(val)}")
                elif cmd == "trace":
                    for e in reader.trace[-40:]:
                        print(c(f"  >> {e.command}", "grey"))
                        print(c(f"  << {e.response}  [{e.sw}]", "grey"))
                else:
                    print(c(f"Comando desconocido: {cmd} (help)", "red"))
            except ReaderError as e:
                print(c(f"Error de lector: {e}", "red"))
            except Exception as e:  # no matar el shell por un APDU malo
                print(c(f"Error: {type(e).__name__}: {e}", "red"))
    finally:
        reader.close()
    print("bye.")
    return 0


# ---------------------------------------------------------------------------
# Comandos: BomberCat
# ---------------------------------------------------------------------------
def _bombercat_target(args):
    """Devuelve un puerto (--port) o un DeviceInfo BomberCat detectado."""
    port = getattr(args, "port", None)
    if port:
        return port
    devs = [d for d in registry.list_all_devices() if d.backend == "bombercat"]
    if not devs:
        raise ReaderError("No se detectó un BomberCat. Conéctalo (aparece como "
                          "/dev/ttyACM*) o usa --port; requiere pyserial.")
    return devs[0]


def cmd_bombercat_write(args) -> int:
    """ESCRIBE en la tarjeta a través del firmware BomberCat (passthrough).
    Fuerza el lector antes de delegar en `cmd_write` (misma escritura genérica
    que cualquier otro lector — UPDATE RECORD/BINARY, PUT DATA, APPEND RECORD)."""
    args.reader = f"serial:{args.port}" if getattr(args, "port", None) else "bombercat"
    return cmd_write(args)


def _bombercat_devinfo(tgt) -> DeviceInfo:
    if isinstance(tgt, DeviceInfo):
        return tgt
    return DeviceInfo("bombercat", f"serial:{tgt}", f"BomberCat ({tgt})",
                      frozenset({Capability.CONTACTLESS, Capability.MAGSTRIPE}))


def cmd_bombercat(args) -> int:
    tgt = _bombercat_target(args)
    if args.action == "monitor":
        print(c("Monitor BomberCat (Ctrl-C para salir)…", "yellow"))
        try:
            bombercat.monitor(tgt, on_line=print)
        except KeyboardInterrupt:
            pass
        return 0
    if args.action == "read":
        dbg = (lambda l: print(c(l, "grey"))) if args.verbose else None
        data = bombercat.read_emv(tgt, amount_cents=args.amount, on_debug=dbg)
        card = EmvCard.from_bombercat_json(data)
        print(c("Tarjeta EMV leída (BomberCat):", "bold"))
        for k in ("pan", "expiry", "aid", "label", "aip", "atc", "arqc", "un", "iad", "cdol1"):
            v = getattr(card, k)
            if v:
                print(f"  {c(k, 'green'):>22}: {v}")
        dump = from_bombercat(data)
        _print_hits(find_flags(dump))
        if args.save:
            proj = store.active_project()
            if not proj:
                print(c("No hay proyecto activo (usa 'project use <n>').", "red")); return 1
            dest = store.save_capture(proj, args.save, dump.to_json())
            print(c(f"Captura guardada en {proj.name}: {dest}", "green"))
        return 0
    if args.action == "apdu":
        with registry.open_device(_bombercat_devinfo(tgt)) as r:
            resp = r.transceive(from_hex(args.hex))
            print(c("<<", "grey"),
                  f"{to_hex(resp.data, sep=' ')} [{resp.sw_hex}] {resp.sw_str()}")
            if resp.data:
                p = tlv.parse(resp.data)
                if p:
                    print(p.dump(c))
        return 0
    if args.action in ("dump", "analyze"):
        # Interacción directa con el firmware: mismo `send` (passthrough APDU)
        # que cualquier otro lector — discover/select/GPO/registros/GET DATA y
        # el análisis de seguridad funcionan igual sobre el BomberCat.
        args.reader = f"serial:{args.port}" if getattr(args, "port", None) else "bombercat"
        return (cmd_dump if args.action == "dump" else cmd_analyze)(args)
    if args.action == "magspoof":
        out = bombercat.magspoof_emit(tgt, track1=args.track1, track2=args.track2)
        print(c("magspoof:", "bold"), out)
        return 0
    if args.action == "cmd":
        print(bombercat.send_command(tgt, args.text))
        return 0
    if args.action == "reboot":
        out = bombercat.reboot(tgt)
        print(c("REBOOT:", "bold"), out)
        print(c("La placa se reinicia y el USB CDC se re-enumera; reconecta el "
                "lector antes de seguir.", "grey"))
        return 0
    if args.action == "cardscan":
        print(c("CARDSCAN — acerca la tarjeta contactless a leer (se guarda en la "
                "RAM del BomberCat)…", "yellow"))
        info = bombercat.card_scan_to_ram(tgt, on_line=lambda l: print(c(f"  {l}", "grey")))
        print(c(f"Escaneada a RAM: PAN {info.get('pan','?')} AID {info.get('aid','?')} "
                f"exp {info.get('exp','?')}", "green"))
        print(c("Ahora: emvy bombercat emv-emulate --ram (acerca el terminal).", "grey"))
        return 0
    if args.action == "emv-emulate":
        card = None
        if getattr(args, "ram", False):
            pass  # emula desde la RAM del firmware (no se pasa card)
        elif getattr(args, "card", None):
            from pathlib import Path
            from .payments import EmvCard
            from .session.model import CardDump
            raw = Path(args.card).read_text()
            try:
                card = EmvCard.from_dump(CardDump.from_json(raw))
            except Exception:               # noqa: BLE001 — quizás JSON de BomberCat
                card = EmvCard.from_bombercat_json(json.loads(raw))
            print(c(f"Tarjeta de la captura: PAN {card.pan_digits or '?'} "
                    f"AID {card.aid or '?'}", "grey"))
        print(c("Emulando una TARJETA EMV para perfilar el terminal… acerca el "
                "lector/POS (Ctrl-C para detener).", "yellow"))

        def _show(line: str) -> None:
            if line.startswith("EMU:RX SELECT-PPSE"):
                col = "bold cyan"
            elif line.startswith("EMU:RX SELECT-AID"):
                col = "cyan"
            elif line.startswith("EMU:RX GPO") or line.startswith("EMU:RX GENERATE-AC"):
                col = "bold yellow"
            elif line.startswith("  PDOL") or line.startswith("  CDOL1"):
                col = "green"        # los datos del terminal decodificados
            elif line.startswith("EMU:TX"):
                col = "magenta"
            elif line.startswith("EMU:RX"):
                col = "cyan"
            else:
                col = "grey"
            print(c(f"  {line}", col))

        try:
            bombercat.emv_emulate(tgt, card=card, from_ram=getattr(args, "ram", False),
                                  timeout=None, on_line=_show)
        except KeyboardInterrupt:
            print("\ninterrumpido (STOP enviado).")
        return 0
    return 1


# ---------------------------------------------------------------------------
# Comandos: BomberCat — puente al framework bombercat-tools (vendorizado)
# ---------------------------------------------------------------------------
def cmd_bombercat_bridge(args) -> int:
    action = args.action
    port = getattr(args, "port", None)
    try:
        if action == "setup":
            bctools.ensure_venv(log=lambda m: print(c("  · ", "grey") + m))
            print(c(f"bombercat-tools listo (v{bctools.version()})", "green"),
                  f"en {bctools.locate()}")
            return 0
        if action == "devices":
            return bctools.devices()
        if action == "status":
            return bctools.status(port)
        if action == "tools":
            rest = list(args.args or [])
            if rest and rest[0] == "--":
                rest = rest[1:]
            if not rest:
                print("uso: emvy bombercat tools -- <args del framework>"); return 1
            return bctools.run_passthrough(rest)
        if action == "fw":
            if args.op == "list":
                return bctools.fw_list()
            if not args.name:
                print(c("Indica el firmware: emvy bombercat fw flash <NOMBRE>", "red"))
                print("Ver disponibles: emvy bombercat fw list")
                return 1
            print(c(f"Flasheando {args.name} (UF2). El board debe estar en bootloader "
                    "(doble-tap RESET si no entra solo).", "yellow"))
            return bctools.flash(args.name, port=port, yes=args.yes,
                                 log=lambda m: print(c("  · ", "grey") + m))
        if action == "tags":
            if args.save:
                data = bctools.tags_read(args.timeout)
                proj = store.active_project()
                if not proj:
                    print(c("No hay proyecto activo para --save.", "red")); return 1
                import json as _j
                dest = store.save_capture(proj, args.save, _j.dumps(data, indent=2))
                print(c(f"Tag(s) guardado(s) en {proj.name}: {dest}", "green"))
                return 0
            return bctools.run_passthrough(["tags", "read", "-t", str(args.timeout)])
        if action == "readers":
            return bctools.run_passthrough(["readers", "read", "-t", str(args.timeout)])
        if action == "relay":
            rest = list(args.args or [])
            if rest and rest[0] == "--":
                rest = rest[1:]
            return bctools.run_passthrough(["relay", *rest])
    except bctools.BombercatToolsError as e:
        print(c(str(e), "red"), file=sys.stderr)
        return 2
    return 1


# ---------------------------------------------------------------------------
# Comandos: PoCs
# ---------------------------------------------------------------------------
def _load_project_pocs(proj):
    pocmod.clear()
    loaded, errors = pocmod.load_plugins(proj)
    for e in errors:
        print(c(f"  plugin con error: {e}", "red"), file=sys.stderr)
    return loaded


_STATUS_COLOR = {
    "vulnerable": "red", "error": "red", "failed": "yellow",
    "passed": "green", "not_vulnerable": "green", "skipped": "grey", "info": "cyan",
}


def _print_poc_result(meta, result, run_dir) -> None:
    col = _STATUS_COLOR.get(str(result.status), "bold")
    print(c(f"[{result.status}]", col, "bold"), c(meta.title, "bold"),
          f"({meta.id})")
    if result.summary:
        print(f"  {result.summary}")
    for f in result.findings:
        print(f"  · {c('[' + str(f.severity) + ']', 'yellow')} {f.title}"
              + (f" — {f.detail}" if f.detail else ""))
    if result.error:
        print(c(f"  error: {result.error}", "red"))
    print(c(f"  run: {run_dir}", "grey"))


def cmd_poc(args) -> int:
    if args.action == "templates":
        from .poc.templates import list_templates
        print(c("Plantillas genéricas de PoC:", "bold"))
        for t in list_templates():
            print(f"  · {c(t, 'cyan')}")
        print("Uso: emvy poc new <id> --template <nombre>")
        return 0

    proj = store.active_project()
    if not proj:
        print(c("No hay proyecto activo. Usa 'emvy project use <nombre>'.", "red")); return 1

    if args.action == "new":
        from .poc.scaffold import scaffold_poc
        try:
            path = scaffold_poc(proj.pocs_dir, args.id, template=getattr(args, "template", None))
        except (FileExistsError, KeyError) as e:
            print(c(str(e), "red")); return 1
        print(c(f"Plugin de PoC creado: {path}", "green"))
        print("Edítalo y ejecútalo con: emvy poc run " + args.id)
        return 0

    _load_project_pocs(proj)

    if args.action == "list":
        pocs = pocmod.list_pocs()
        if not pocs:
            print(f"Sin PoCs en {proj.pocs_dir}. Crea uno con: emvy poc new <id>")
            return 0
        print(c(f"PoCs del proyecto {proj.name} ({len(pocs)}):", "bold"))
        for p in pocs:
            m = p.meta
            print(f"  {c(m.id, 'cyan')}  [{m.category}/{m.severity}]  {m.title}")
        return 0

    if args.action == "runs":
        runs = store.list_poc_runs(proj)
        if not runs:
            print("Sin ejecuciones previas."); return 0
        for d in runs:
            print(f"  {d.name}")
        return 0

    if args.action == "show":
        runs = store.list_poc_runs(proj)
        if args.id:
            runs = [d for d in runs if args.id in d.name]
        if not runs:
            print(c("No hay ejecuciones que mostrar.", "yellow")); return 1
        import json
        data = json.loads((runs[0] / "result.json").read_text())
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return 0

    if args.action == "run":
        p = pocmod.get(args.id)
        if not p:
            print(c(f"No existe el PoC {args.id!r}. Usa 'emvy poc list'.", "red")); return 1
        card = None
        if args.card:
            import json as _json
            text = open(args.card).read()
            raw = _json.loads(text)
            # acepta tanto un CardDump ({atr,applications,blobs}) como un JSON
            # de BomberCat ({ok,pan,arqc,...}).
            if "applications" in raw or "blobs" in raw:
                card = EmvCard.from_dump(CardDump.from_json(text))
            else:
                card = EmvCard.from_bombercat_json(raw)
        variables = {v.name: v.value for v in store.load_project_variables(proj)}
        for kv in (args.var or []):
            if "=" in kv:
                k, v = kv.split("=", 1)
                variables[k] = v
        run_dir = pocmod.runner.run_dir_for(proj, p.meta.id)
        ctx = pocmod.make_context(proj, card=card, variables=variables, run_dir=run_dir,
                                  dry_run=args.dry_run, allow_write=args.allow_write,
                                  log=lambda m: print(c("  · ", "grey") + m))
        result = pocmod.run_poc(p, ctx)
        pocmod.save_result(ctx, p.meta, result)
        _print_poc_result(p.meta, result, run_dir)
        return 1 if result.status == pocmod.Status.ERROR else 0
    return 1


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="emvyctl",
        description="EMVyController — suite de pruebas de seguridad para tarjetas bancarias.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--version", action="version", version=f"EMVyController {__version__}")
    p.add_argument("-r", "--reader", help="lector por índice, nombre, backend o id (subcadena)")
    p.add_argument("-p", "--protocol", default="any", choices=["t0", "t1", "any"])
    p.add_argument("-v", "--verbose", action="store_true", help="traza cada APDU")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("readers", help="lista lectores (todos los backends)").set_defaults(func=cmd_readers)
    sub.add_parser("atr", help="muestra e interpreta el ATR").set_defaults(func=cmd_atr)

    sp = sub.add_parser("discover", help="descubre aplicaciones EMV")
    sp.add_argument("--no-brute", action="store_true", help="no probar AIDs conocidos")
    sp.set_defaults(func=cmd_discover)

    sp = sub.add_parser("select", help="SELECT de un AID o PSE/PPSE + GPO")
    sp.add_argument("aid", help="AID hex, o 'pse'/'ppse'")
    sp.set_defaults(func=cmd_select)

    sp = sub.add_parser("records", help="barrido bruto de registros")
    sp.add_argument("--max-sfi", type=int, default=31)
    sp.add_argument("--max-rec", type=int, default=16)
    sp.set_defaults(func=cmd_records)

    sp = sub.add_parser("getdata", help="GET DATA de un tag")
    sp.add_argument("tag", help="tag hex, p.ej. 9F36")
    sp.set_defaults(func=cmd_getdata)

    sp = sub.add_parser("apdu", help="envía un APDU crudo (hex)")
    sp.add_argument("hex", help="APDU en hex")
    sp.set_defaults(func=cmd_apdu)

    sp = sub.add_parser("dump", help="volcado completo a JSON")
    sp.add_argument("-o", "--output", help="archivo de salida .json (elige la ruta)")
    sp.add_argument("--save", help="guardar como captura con este nombre (en el proyecto)")
    sp.add_argument("--project", help="proyecto destino para --save (nombre o ruta; por defecto: activo)")
    sp.add_argument("--raw", action="store_true", help="fuerza escaneo crudo (lee cualquier tarjeta ISO 7816)")
    sp.add_argument("--mode", choices=["auto", "emv", "nfc"], default="auto",
                    help="auto (por defecto: EMV, si no hay apps cae a NFC genérico) | "
                         "emv (solo EMV) | nfc (tag NFC genérico: NDEF Type 4 + crudo)")
    sp.add_argument("--no-brute", action="store_true")
    sp.add_argument("--no-sweep", action="store_true")
    sp.add_argument("--no-getdata", action="store_true")
    sp.set_defaults(func=cmd_dump)

    sp = sub.add_parser("info", help="resumen legible + búsqueda de flags")
    sp.add_argument("--raw", action="store_true", help="fuerza escaneo crudo (lee cualquier tarjeta ISO 7816)")
    sp.add_argument("--mode", choices=["auto", "emv", "nfc"], default="auto",
                    help="auto | emv (solo EMV) | nfc (tag NFC genérico)")
    sp.add_argument("--no-brute", action="store_true")
    sp.add_argument("--no-sweep", action="store_true")
    sp.add_argument("--no-getdata", action="store_true")
    sp.set_defaults(func=cmd_info)

    sp = sub.add_parser("write", help="ESCRIBE en la tarjeta (¡modifica la tarjeta!)")
    _add_write_ops(sp.add_subparsers(dest="op", required=True))

    # fuzz: plantillas para probar terminales/POS reales (no tarjetas)
    sp = sub.add_parser("fuzz", help="plantillas para probar terminales/lectores/POS")
    fsub = sp.add_subparsers(dest="kind", required=True)

    tp = fsub.add_parser("track", help="banda magnética (envío vía BomberCat magspoof)")
    tp.add_argument("--port", help="puerto serie del BomberCat (p.ej. /dev/ttyACM0)")
    tsub = tp.add_subparsers(dest="action", required=True)
    tsub.add_parser("list", help="lista plantillas de banda").set_defaults(func=cmd_fuzz_track)
    for name in ("show", "send"):
        q = tsub.add_parser(name, help=f"{'muestra' if name == 'show' else 'envía'} una plantilla")
        q.add_argument("id", help="ver 'fuzz track list'")
        q.add_argument("--pan"); q.add_argument("--name"); q.add_argument("--expiry")
        q.add_argument("--service-code")
        q.set_defaults(func=cmd_fuzz_track)

    cp = fsub.add_parser("card", help="registro EMV (escritura en tarjeta de prueba)")
    csub = cp.add_subparsers(dest="action", required=True)
    csub.add_parser("list", help="lista plantillas de registro").set_defaults(func=cmd_fuzz_card)
    q = csub.add_parser("show", help="muestra el registro (hex) de una plantilla")
    q.add_argument("id", help="ver 'fuzz card list'")
    q.add_argument("--pan"); q.add_argument("--name"); q.add_argument("--expiry")
    q.set_defaults(func=cmd_fuzz_card)
    q = csub.add_parser("write", help="escribe la plantilla en la tarjeta (¡la modifica!)")
    q.add_argument("id", help="ver 'fuzz card list'")
    q.add_argument("sfi", type=int); q.add_argument("record", type=int)
    q.add_argument("--pan"); q.add_argument("--name"); q.add_argument("--expiry")
    q.set_defaults(func=cmd_fuzz_card)

    np = fsub.add_parser("ndef", help="mensaje NDEF (emula un tag NFC vía BomberCat)")
    np.add_argument("--port", help="puerto serie del BomberCat (p.ej. /dev/ttyACM0)")
    nsub = np.add_subparsers(dest="action", required=True)
    nsub.add_parser("list", help="lista plantillas NDEF").set_defaults(func=cmd_fuzz_ndef)
    for name in ("show", "emit"):
        q = nsub.add_parser(name, help=f"{'muestra' if name == 'show' else 'emula'} un NDEF")
        q.add_argument("id", nargs="?", default="baseline", help="plantilla (ver 'fuzz ndef list')")
        q.add_argument("--card", help="emula los datos de una captura guardada (nombre o ruta .json)")
        q.add_argument("--test-card", action="store_true", help="emula una tarjeta de prueba canónica")
        q.add_argument("--url"); q.add_argument("--text")
        q.set_defaults(func=cmd_fuzz_ndef)

    sp = sub.add_parser("analyze", help="análisis de seguridad EMV (AIP/AUC/CVM/ODA)")
    sp.add_argument("--file", help="analizar un dump JSON en vez de la tarjeta")
    sp.add_argument("--aid", help="AID a analizar (por defecto: el primero)")
    sp.add_argument("--ca-modulus", help="módulo de la CA (hex) para verificar el cert. del emisor")
    sp.add_argument("--ca-exponent", default="3", help="exponente de la CA (3 o 65537)")
    sp.add_argument("--no-brute", action="store_true")
    sp.add_argument("--no-sweep", action="store_true")
    sp.add_argument("--no-getdata", action="store_true")
    sp.set_defaults(func=cmd_analyze)

    sp = sub.add_parser("flags", help="busca flags (tarjeta o --file dump.json)")
    sp.add_argument("--file", help="buscar en un dump JSON en vez de la tarjeta")
    sp.add_argument("--no-brute", action="store_true")
    sp.add_argument("--no-sweep", action="store_true")
    sp.add_argument("--no-getdata", action="store_true")
    sp.set_defaults(func=cmd_flags)

    sp = sub.add_parser("search", help="busca un regex (tarjeta o --file dump.json)")
    sp.add_argument("pattern", help="expresión regular")
    sp.add_argument("--file", help="buscar en un dump JSON")
    sp.add_argument("--case-sensitive", action="store_true")
    sp.add_argument("--no-brute", action="store_true")
    sp.add_argument("--no-sweep", action="store_true")
    sp.add_argument("--no-getdata", action="store_true")
    sp.set_defaults(func=cmd_search)

    sp = sub.add_parser("track", help="parsea banda magnética (arg o --read del lector)")
    sp.add_argument("swipe", nargs="?", help="cadena del swipe (%%B..?;..?)")
    sp.add_argument("--read", action="store_true", help="leer del lector MSR seleccionado")
    sp.add_argument("--timeout", type=float, default=30.0)
    sp.set_defaults(func=cmd_track)

    for alias in ("iso8583", "iso"):
        sp = sub.add_parser(alias, help="traduce un mensaje ISO 8583 crudo (SEND/RCV)")
        sp.add_argument("hex", help="mensaje ISO 8583 en hex ('-' = stdin)")
        sp.set_defaults(func=cmd_iso8583)

    # project
    sp = sub.add_parser("project", help="gestiona proyectos")
    psub = sp.add_subparsers(dest="action", required=True)
    psub.add_parser("list", help="lista proyectos").set_defaults(func=cmd_project)
    q = psub.add_parser("new", help="crea y activa un proyecto")
    q.add_argument("name"); q.add_argument("--desc"); q.add_argument("--reader")
    q.add_argument("--path", help="crear en una ruta arbitraria (p.ej. engagements/x)")
    q.set_defaults(func=cmd_project)
    q = psub.add_parser("use", help="activa un proyecto (nombre o ruta)"); q.add_argument("name"); q.set_defaults(func=cmd_project)
    q = psub.add_parser("rm", help="elimina un proyecto"); q.add_argument("name"); q.set_defaults(func=cmd_project)
    q = psub.add_parser("show", help="detalles del proyecto"); q.add_argument("name", nargs="?"); q.set_defaults(func=cmd_project)
    q = psub.add_parser("export", help="empaqueta un proyecto completo a .zip")
    q.add_argument("name", nargs="?", help="proyecto (nombre o ruta; por defecto: activo)")
    q.add_argument("-o", "--output", help="archivo .zip o directorio destino (por defecto: .)")
    q.add_argument("--no-runs", action="store_true", help="excluir poc_runs/ del paquete")
    q.set_defaults(func=cmd_project)
    q = psub.add_parser("import", help="importa un proyecto completo desde .zip")
    q.add_argument("archive", help="archivo .zip del proyecto")
    q.add_argument("--name", help="nombre destino (por defecto: el del manifest)")
    q.add_argument("--path", help="importar en una ruta arbitraria (p.ej. engagements/x)")
    q.add_argument("--overwrite", action="store_true", help="sobrescribe si ya existe")
    q.add_argument("--use", action="store_true", help="activar el proyecto tras importar")
    q.set_defaults(func=cmd_project)

    # var (alias env)
    for alias in ("var", "env"):
        sp = sub.add_parser(alias, help="gestiona variables del proyecto activo")
        vsub = sp.add_subparsers(dest="action", required=True)
        vsub.add_parser("list", help="lista variables").set_defaults(func=cmd_var)
        q = vsub.add_parser("get", help="valor de una variable"); q.add_argument("name"); q.set_defaults(func=cmd_var)
        q = vsub.add_parser("set", help="crea/modifica una variable")
        q.add_argument("name"); q.add_argument("value")
        q.add_argument("--user", action="store_true", help="forzar variable libre (no terminal)")
        q.add_argument("--desc")
        q.set_defaults(func=cmd_var)
        q = vsub.add_parser("rm", help="borra una variable"); q.add_argument("name"); q.set_defaults(func=cmd_var)
        vsub.add_parser("profiles", help="lista perfiles de terminal preconfigurados").set_defaults(func=cmd_var)
        q = vsub.add_parser("apply", help="aplica un perfil de terminal preconfigurado")
        q.add_argument("id", help="ver 'var profiles'"); q.set_defaults(func=cmd_var)

    # gp (GlobalPlatform: keysets del Secure Channel; escritura de JavaCards)
    sp = sub.add_parser("gp", help="GlobalPlatform (keysets / Secure Channel)")
    gsub = sp.add_subparsers(dest="gpcmd", required=True)
    ksp = gsub.add_parser("keyset", help="gestiona keysets (claves ENC/MAC/KEK)")
    kacts = ksp.add_subparsers(dest="action", required=True)
    q = kacts.add_parser("add", help="añade/reemplaza un keyset")
    q.add_argument("name")
    q.add_argument("--enc", help="clave ENC (hex, 16/24 bytes)")
    q.add_argument("--mac", help="clave MAC (hex)")
    q.add_argument("--kek", help="clave KEK/DEK (hex)")
    q.add_argument("--same", help="usar la misma clave para ENC/MAC/KEK (hex)")
    q.add_argument("--kvn", type=lambda x: int(x, 0), default=0, help="Key Version Number (0=auto)")
    q.add_argument("--scp", choices=["auto", "02", "03"], default="auto")
    q.add_argument("--desc")
    q.set_defaults(func=cmd_gp_keyset)
    kacts.add_parser("list", help="lista keysets del proyecto").set_defaults(func=cmd_gp_keyset)
    q = kacts.add_parser("show", help="muestra un keyset (claves ofuscadas)")
    q.add_argument("name"); q.add_argument("--reveal", action="store_true", help="mostrar claves completas")
    q.set_defaults(func=cmd_gp_keyset)
    q = kacts.add_parser("rm", help="borra un keyset"); q.add_argument("name")
    q.set_defaults(func=cmd_gp_keyset)

    def _gp_op(name, help):
        o = gsub.add_parser(name, help=help)
        o.add_argument("--keyset", required=True, help="nombre del keyset (gp keyset list)")
        o.add_argument("--enc", action="store_true", help="canal con C-ENC además de C-MAC")
        o.set_defaults(func=cmd_gp_op, gpcmd=name)
        return o
    _gp_op("auth", "abre el canal seguro (verifica las claves)")
    _gp_op("status", "GET STATUS: ISD, aplicaciones y paquetes")
    o = _gp_op("delete", "DELETE de un AID")
    o.add_argument("aid", help="AID en hex")
    o.add_argument("--no-related", action="store_true", help="no borrar dependencias")
    o = _gp_op("install", "carga e instala un CAP (load + install)")
    o.add_argument("cap", help="ruta al fichero .cap")
    o.add_argument("--instance", help="AID de la instancia (por defecto = módulo)")
    o.add_argument("--module", help="AID del módulo/applet (por defecto el primero)")
    o.add_argument("--priv", help="privilegios en hex (por defecto 00)")
    o.add_argument("--params", help="parámetros de instalación en hex (tag C9)")
    o.add_argument("--load-only", action="store_true", help="solo cargar el paquete, sin instanciar")
    o.add_argument("--force", action="store_true", help="borrar el paquete previo si existe")
    o = _gp_op("store-data", "STORE DATA (un bloque)")
    o.add_argument("hex", help="datos en hex")

    # bombercat
    sp = sub.add_parser("bombercat", help="integración con BomberCat (serie)")
    sp.add_argument("--port", help="puerto serie (p.ej. /dev/ttyACM0)")
    bsub = sp.add_subparsers(dest="action", required=True)
    bsub.add_parser("monitor", help="monitorea la salida serial").set_defaults(func=cmd_bombercat)
    q = bsub.add_parser("read", help="lee EMV (firmware JSON) -> captura")
    q.add_argument("--amount", type=int, default=500, help="monto en centavos")
    q.add_argument("--save", help="guardar la captura en el proyecto activo")
    q.set_defaults(func=cmd_bombercat)
    q = bsub.add_parser("apdu", help="APDU crudo vía passthrough")
    q.add_argument("hex", help="APDU en hex"); q.set_defaults(func=cmd_bombercat)
    q = bsub.add_parser("dump", help="volcado completo (interactúa directo con el firmware)")
    q.add_argument("-o", "--output", help="archivo de salida .json")
    q.add_argument("--save", help="guardar como captura con este nombre")
    q.add_argument("--project", help="proyecto destino para --save (nombre o ruta)")
    q.add_argument("--raw", action="store_true", help="escaneo crudo (cualquier ISO 7816)")
    q.add_argument("--mode", choices=["auto", "emv", "nfc"], default="auto",
                  help="auto | emv (solo EMV) | nfc (tag NFC genérico: NDEF Type 4 + crudo)")
    q.add_argument("--no-brute", action="store_true"); q.add_argument("--no-sweep", action="store_true")
    q.add_argument("--no-getdata", action="store_true")
    q.set_defaults(func=cmd_bombercat)
    q = bsub.add_parser("analyze", help="análisis de seguridad EMV (interactúa directo con el firmware)")
    q.add_argument("--file", help="analizar un dump JSON en vez de la tarjeta")
    q.add_argument("--aid", help="AID a analizar (por defecto: el primero)")
    q.add_argument("--ca-modulus", help="módulo de la CA (hex) para verificar el cert. del emisor")
    q.add_argument("--ca-exponent", default="3")
    q.add_argument("--no-brute", action="store_true"); q.add_argument("--no-sweep", action="store_true")
    q.add_argument("--no-getdata", action="store_true")
    q.set_defaults(func=cmd_bombercat)
    q = bsub.add_parser("write", help="ESCRIBE en la tarjeta vía el firmware (¡la modifica!)")
    _add_write_ops(q.add_subparsers(dest="op", required=True), handler=cmd_bombercat_write)
    q = bsub.add_parser("magspoof", help="emula un swipe de banda magnética")
    q.add_argument("--track1"); q.add_argument("--track2"); q.set_defaults(func=cmd_bombercat)
    q = bsub.add_parser("cmd", help="envía un comando de línea crudo")
    q.add_argument("text"); q.set_defaults(func=cmd_bombercat)
    bsub.add_parser("reboot", help="reinicia el MCU del BomberCat (REBOOT)").set_defaults(func=cmd_bombercat)
    bsub.add_parser("cardscan",
                    help="lee una tarjeta EMV por NFC y la guarda en la RAM del BomberCat"
                    ).set_defaults(func=cmd_bombercat)
    q = bsub.add_parser("emv-emulate",
                        help="emula una tarjeta EMV para perfilar/fuzzear un terminal de pago")
    q.add_argument("--card", help="captura (CardDump/JSON de BomberCat) para presentar sus "
                   "datos reales; sin esto usa una Visa de prueba")
    q.add_argument("--ram", action="store_true",
                   help="emula la tarjeta guardada en la RAM del firmware (tras 'cardscan')")
    q.set_defaults(func=cmd_bombercat)
    # --- puente al framework bombercat-tools (vendorizado) ---
    bsub.add_parser("setup", help="prepara bombercat-tools (venv del framework)").set_defaults(func=cmd_bombercat_bridge)
    bsub.add_parser("devices", help="lista dispositivos (framework)").set_defaults(func=cmd_bombercat_bridge)
    bsub.add_parser("status", help="firmware flasheado (framework)").set_defaults(func=cmd_bombercat_bridge)
    q = bsub.add_parser("tools", help="passthrough al framework: bombercat tools -- <args>")
    q.add_argument("args", nargs=argparse.REMAINDER); q.set_defaults(func=cmd_bombercat_bridge)
    q = bsub.add_parser("fw", help="firmware oficial UF2 (list|flash)")
    q.add_argument("op", choices=["list", "flash"])
    q.add_argument("name", nargs="?", help="nombre de firmware (para flash)")
    q.add_argument("-y", "--yes", action="store_true", help="no pedir confirmación")
    q.set_defaults(func=cmd_bombercat_bridge)
    q = bsub.add_parser("tags", help="detección de tags NFC (framework/DetectTags)")
    q.add_argument("--save", help="guardar el tag en el proyecto activo")
    q.add_argument("-t", "--timeout", type=int, default=20)
    q.set_defaults(func=cmd_bombercat_bridge)
    q = bsub.add_parser("readers", help="detección de lectores (framework/DetectReaders)")
    q.add_argument("-t", "--timeout", type=int, default=20)
    q.set_defaults(func=cmd_bombercat_bridge)
    q = bsub.add_parser("relay", help="relay NFCGate (framework): relay -- <args>")
    q.add_argument("args", nargs=argparse.REMAINDER); q.set_defaults(func=cmd_bombercat_bridge)

    # poc
    sp = sub.add_parser("poc", help="framework de PoCs (plugins del proyecto)")
    csub = sp.add_subparsers(dest="action", required=True)
    csub.add_parser("list", help="lista PoCs del proyecto").set_defaults(func=cmd_poc)
    csub.add_parser("runs", help="lista ejecuciones previas").set_defaults(func=cmd_poc)
    q = csub.add_parser("new", help="crea un plugin de PoC (opcional --template)")
    q.add_argument("id")
    q.add_argument("--template", help="plantilla genérica (ver 'poc templates')")
    q.set_defaults(func=cmd_poc)
    csub.add_parser("templates", help="lista plantillas genéricas de PoC").set_defaults(func=cmd_poc)
    q = csub.add_parser("show", help="muestra el resultado de una ejecución")
    q.add_argument("id", nargs="?", help="subcadena del run/PoC"); q.set_defaults(func=cmd_poc)
    q = csub.add_parser("run", help="ejecuta un PoC")
    q.add_argument("id")
    q.add_argument("--card", help="captura JSON con datos de tarjeta (EmvCard)")
    q.add_argument("--var", action="append", help="override de variable k=v (repetible)")
    q.add_argument("--dry-run", action="store_true", help="no envía nada; registra la intención")
    q.add_argument("--allow-write", action="store_true", help="permite métodos HTTP no idempotentes")
    q.set_defaults(func=cmd_poc)

    sub.add_parser("shell", help="shell interactivo").set_defaults(func=cmd_shell)
    sub.add_parser("tui", help="interfaz TUI (Textual)").set_defaults(func=cmd_tui)
    sub.add_parser("gui", help="interfaz GUI de escritorio (PySide6/Qt)").set_defaults(func=cmd_gui)
    return p


def main(argv=None) -> int:
    started_pcscd = pcscd.ensure_started()
    try:
        args = build_parser().parse_args(argv)
        try:
            return args.func(args)
        except ReaderError as e:
            print(c(str(e), "red"), file=sys.stderr)
            return 2
        except KeyboardInterrupt:
            print("\ninterrumpido.")
            return 130
    finally:
        if started_pcscd:
            pcscd.stop()


if __name__ == "__main__":
    sys.exit(main())
