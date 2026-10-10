"""Pestaña 'Fuzzing': plantillas para **probar terminales/lectores/POS reales**
(no tarjetas). Tres carriles, cada uno con su canal de disparo:

  * **Banda magnética** → BomberCat magspoof (pistas mutadas).
  * **Registro EMV** → UPDATE RECORD en una tarjeta de prueba reescribible.
  * **NDEF** → BomberCat emula un tag NFC Type 4 con un mensaje NDEF mutado.

Cada plantilla se puede **editar en caliente** antes de disparar.
"""
from __future__ import annotations

from textual import on
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Input, RichLog, Select, Static

from ...core import cardfuzz
from ...core import playbooks
from ...core.hexutil import from_hex, to_hex


class FuzzScreen(Vertical):
    DEFAULT_CSS = """
    FuzzScreen { padding: 0 1; }
    FuzzScreen .fz-sub { color: $text-muted; padding: 0 0 1 0; }
    FuzzScreen #fz-lanes { height: 1fr; }
    FuzzScreen .fz-lane {
        border: round $primary; padding: 0 1; margin: 0 0 1 0; height: auto;
    }
    FuzzScreen .fz-row { height: auto; padding: 0 0 1 0; }
    FuzzScreen .fz-row Input { width: 1fr; margin: 0 1 0 0; }
    FuzzScreen .fz-row Button { margin: 0 1 0 0; min-width: 10; }
    FuzzScreen .fz-desc { color: $text-muted; height: auto; padding: 0 0 1 0; }
    FuzzScreen .fz-narrow { width: 12; }
    FuzzScreen #fuzz_log { height: 8; border: round $primary; }
    """

    def compose(self):
        yield Static("Fuzzing de terminales / lectores / POS", classes="title")
        yield Static("⚠ Genera datos de tarjeta/NFC fuera de norma para observar cómo "
                     "reacciona un lector real. Solo hardware propio o autorizado.",
                     classes="fz-sub")

        with VerticalScroll(id="fz-lanes"):
            # -- Banda magnética (magspoof) --------------------------------
            with Vertical(classes="fz-lane", id="fz-lane-track"):
                with Horizontal(classes="fz-row"):
                    yield Select([(t.title, t.id) for t in cardfuzz.track_templates()],
                                 value="baseline", allow_blank=False, id="fz_track_tpl")
                    yield Button("Generar", id="fz_track_gen")
                    yield Button("Enviar", id="fz_track_send", variant="error")
                yield Static("", id="fz_track_desc", classes="fz-desc")
                with Horizontal(classes="fz-row"):
                    yield Input(placeholder="track1 (editable)", id="fz_track1")
                with Horizontal(classes="fz-row"):
                    yield Input(placeholder="track2 (editable)", id="fz_track2")

            # -- Registro EMV (escritura en tarjeta de prueba) -------------
            with Vertical(classes="fz-lane", id="fz-lane-card"):
                with Horizontal(classes="fz-row"):
                    yield Select([(t.title, t.id) for t in cardfuzz.emv_templates()],
                                 value="baseline", allow_blank=False, id="fz_card_tpl")
                    yield Button("Generar", id="fz_card_gen")
                yield Static("", id="fz_card_desc", classes="fz-desc")
                with Horizontal(classes="fz-row"):
                    yield Input(placeholder="registro en hex (editable)", id="fz_card_hex")
                with Horizontal(classes="fz-row"):
                    yield Input(placeholder="SFI", id="fz_card_sfi", value="1",
                                classes="fz-narrow")
                    yield Input(placeholder="registro", id="fz_card_rec", value="1",
                                classes="fz-narrow")
                    yield Button("Escribir", id="fz_card_write", variant="error")

            # -- Mutaciones (motor EMV + playbooks COMBO) -----------------
            with Vertical(classes="fz-lane", id="fz-lane-mut"):
                with Horizontal(classes="fz-row"):
                    yield Select([(f"{p['id']} · {p['title']}", p['id'])
                                  for p in playbooks.playbooks()],
                                 value="COMBO-A", allow_blank=False, id="fz_mut_pb")
                    yield Button("Vista previa", id="fz_mut_preview")
                yield Static("", id="fz_mut_desc", classes="fz-desc")

            # -- NDEF (emular tag NFC vía BomberCat) -----------------------
            with Vertical(classes="fz-lane", id="fz-lane-ndef"):
                with Horizontal(classes="fz-row"):
                    yield Select([(t.title, t.id) for t in cardfuzz.ndef_templates()],
                                 value="baseline", allow_blank=False, id="fz_ndef_tpl")
                    yield Button("Generar", id="fz_ndef_gen")
                    yield Button("Emular (NFC)", id="fz_ndef_emit", variant="error")
                    yield Button("Detener", id="fz_ndef_stop")
                    yield Button("Reboot", id="fz_ndef_reboot", variant="warning")
                yield Static("", id="fz_ndef_desc", classes="fz-desc")
                with Horizontal(classes="fz-row"):
                    yield Input(placeholder="mensaje NDEF en hex (editable)", id="fz_ndef_hex")
                yield Static("Emular una TARJETA EMV (perfila/fuzzea un terminal de pago: "
                             "responde PPSE/SELECT/GPO y muestra qué pide — TTQ/monto/país…):",
                             classes="fz-desc")
                with Horizontal(classes="fz-row"):
                    yield Button("Emular tarjeta EMV", id="fz_emv_emit", variant="error")

        yield Static("SALIDA", classes="fz-sub")
        yield RichLog(id="fuzz_log", markup=True, wrap=True)

    def on_mount(self):
        for lane, title in (("#fz-lane-track", "Banda magnética · magspoof"),
                            ("#fz-lane-card", "Registro EMV · escribir en tarjeta"),
                            ("#fz-lane-mut", "Mutaciones · motor EMV + COMBO"),
                            ("#fz-lane-ndef", "NDEF · emular tag NFC")):
            try:
                self.query_one(lane).border_title = title
            except Exception:
                pass
        self._gen_track()
        self._gen_card()
        self._gen_ndef()
        self._mut_changed_desc()

    # -- banda magnética ------------------------------------------------
    @on(Button.Pressed, "#fz_track_gen")
    def _track_gen_btn(self):
        self._gen_track()

    def _gen_track(self):
        tpl_id = self.query_one("#fz_track_tpl", Select).value
        t = cardfuzz.get_track_template(cardfuzz.track_templates(), tpl_id)
        if not t:
            return
        self.query_one("#fz_track_desc", Static).update(t.description)
        self.query_one("#fz_track1", Input).value = t.track1 or ""
        self.query_one("#fz_track2", Input).value = t.track2 or ""

    @on(Button.Pressed, "#fz_track_send")
    def _track_send(self):
        t1 = self.query_one("#fz_track1", Input).value.strip() or None
        t2 = self.query_one("#fz_track2", Input).value.strip() or None
        if not (t1 or t2):
            self.app.notify("No hay track1/track2 que enviar.", severity="warning")
            return
        self.log(f"[yellow]→ magspoof[/]  t1={t1}  t2={t2}")
        self.app.fuzz_magspoof_ui(t1, t2)

    # -- registro EMV -----------------------------------------------------
    @on(Button.Pressed, "#fz_card_gen")
    def _card_gen_btn(self):
        self._gen_card()

    def _gen_card(self):
        tpl_id = self.query_one("#fz_card_tpl", Select).value
        t = cardfuzz.get_emv_template(cardfuzz.emv_templates(), tpl_id)
        if not t:
            return
        self.query_one("#fz_card_desc", Static).update(t.description)
        self.query_one("#fz_card_hex", Input).value = to_hex(t.to_record())

    @on(Button.Pressed, "#fz_card_write")
    def _card_write(self):
        hexval = self.query_one("#fz_card_hex", Input).value.strip()
        try:
            data = from_hex(hexval)
            sfi = int(self.query_one("#fz_card_sfi", Input).value)
            record = int(self.query_one("#fz_card_rec", Input).value)
        except ValueError:
            self.app.notify("Hex/SFI/registro inválido.", severity="error")
            return
        self.log(f"[yellow]→ UPDATE RECORD[/] sfi={sfi} rec={record}  {hexval}")
        self.app.write_card_ui("record", {"data": data, "sfi": sfi, "record": record})

    # -- mutaciones (motor EMV + playbooks COMBO) ---------------------------
    def _mut_changed_desc(self):
        pb = playbooks.get_playbook(self.query_one("#fz_mut_pb", Select).value)
        if pb:
            self.query_one("#fz_mut_desc", Static).update(pb["description"])

    @on(Select.Changed, "#fz_mut_pb")
    def _mut_changed(self, event: Select.Changed):
        self._mut_changed_desc()

    @on(Button.Pressed, "#fz_mut_preview")
    def _mut_preview(self):
        from ...core import mutations
        pb = playbooks.get_playbook(self.query_one("#fz_mut_pb", Select).value)
        if not pb:
            return
        config = mutations.MutationConfig.from_dict(pb["config"])
        self.log(f"[yellow]→ MUT[/] {pb['id']} · {pb['title']}")
        dump = getattr(self.app, "last_dump", None)
        if dump is None:
            self.log_mut("Sin captura en memoria: captura una tarjeta primero "
                         "(pestaña Capturar) para ver el diff. Inyecciones del playbook:")
        else:
            for line in mutations.preview_dump(dump, config):
                self.log_mut(line)
        for line in mutations.planned_injections(config):
            self.log_mut(line)

    # -- NDEF (emulación NFC) --------------------------------------------
    @on(Button.Pressed, "#fz_ndef_gen")
    def _ndef_gen_btn(self):
        self._gen_ndef()

    def _gen_ndef(self):
        tpl_id = self.query_one("#fz_ndef_tpl", Select).value
        t = cardfuzz.get_ndef_template(cardfuzz.ndef_templates(), tpl_id)
        if not t:
            return
        self.query_one("#fz_ndef_desc", Static).update(t.description)
        self.query_one("#fz_ndef_hex", Input).value = t.to_hex()

    @on(Button.Pressed, "#fz_ndef_emit")
    def _ndef_emit(self):
        hexval = self.query_one("#fz_ndef_hex", Input).value.strip()
        try:
            from_hex(hexval)                 # valida (vacío también vale)
        except ValueError:
            self.app.notify("Mensaje NDEF hex inválido.", severity="error")
            return
        self.log(f"[yellow]→ EMU NDEF[/]  {hexval or '(vacío)'}")
        self.app.emu_arm()
        self.app.fuzz_ndef_ui(hexval)

    @on(Button.Pressed, "#fz_emv_emit")
    def _emv_emit(self):
        self.log("[yellow]→ EMU tarjeta EMV (perfilar terminal)[/]")
        self.app.emu_arm()
        self.app.fuzz_emv_ui()

    @on(Button.Pressed, "#fz_ndef_stop")
    def _ndef_stop(self):
        self.log("[yellow]→ STOP emulación[/]")
        self.app.fuzz_ndef_stop_ui()

    @on(Button.Pressed, "#fz_ndef_reboot")
    def _ndef_reboot(self):
        self.log("[yellow]→ REBOOT BomberCat[/]")
        self.app.bombercat_reboot_ui()

    # -- salida -------------------------------------------------------------
    def log(self, text: str):
        self.query_one("#fuzz_log", RichLog).write(text)

    def log_magspoof(self, out: str):
        self.log(f"[green]← magspoof:[/] {out}")

    def log_ndef(self, line: str):
        # Colorea según el tipo de evento del firmware para leer la actividad
        # del lector de un vistazo: lo que pide (RX) vs. lo que respondemos (TX).
        stripped = line.lstrip()
        if line.startswith("EMU:MSG-SENT"):
            color = "bold green"        # mensaje NDEF completo entregado
        elif stripped.startswith("PDOL") or stripped.startswith("CDOL1"):
            color = "bold green"        # datos del terminal decodificados (EMV)
        elif line.startswith("EMU:RX GPO") or line.startswith("EMU:RX GENERATE-AC"):
            color = "bold yellow"       # pasos clave del flujo EMV
        elif line.startswith("EMU:RX"):
            color = "cyan"              # el lector pide algo (SELECT/READ/…)
        elif line.startswith("EMU:TX"):
            color = "magenta"           # nuestra respuesta
        elif line.startswith("EMU:DONE") or line.startswith("ERR"):
            color = "yellow"
        else:
            color = "blue"              # EMU:START, banners (#), etc.
        self.log(f"[{color}]← {line}[/]")

    def log_mut(self, line: str):
        # Diff del motor de mutaciones: flechas = cambio real, 'resp'/'cmd' =
        # nota del motor, 'inyección'/'(' = informativo.
        if "→" in line:
            color = "green"
        elif line.startswith(("resp", "cmd")):
            color = "cyan"
        elif line.startswith("inyección") or line.startswith("(") or "Sin captura" in line:
            color = "yellow"
        else:
            color = "dim"
        self.log(f"[{color}]{line}[/]")

    def log_write(self, op: str, resp) -> None:
        """Reusa el mismo callback que la pestaña Escritura (mismo worker)."""
        ok = resp.sw == 0x9000
        color = "green" if ok else "red"
        self.log(f"[{color}]← SW {resp.sw_hex}[/]")
