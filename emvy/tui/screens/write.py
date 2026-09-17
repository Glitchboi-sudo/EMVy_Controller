"""Pestaña 'Escritura': UX guiada por intención, en dos pestañas.

* **Personalizar** — el camino amistoso: elige un preset o rellena
  PAN/caducidad/titular, mira la vista previa del registro EMV y escríbelo en un
  clic. La escritura es *inteligente*: si la tarjeta exige canal seguro, abre
  GlobalPlatform sola con el keyset elegido (barra de arriba).
* **Avanzado** — escritura directa por APDU (UPDATE RECORD/BINARY, PUT DATA,
  APPEND) e **inicializar/gestionar** la tarjeta por GlobalPlatform (auth,
  GET STATUS, instalar CAP, instanciar applet, DELETE, restaurar a virgen).

Todo comparte la barra de canal seguro (keyset) de arriba y el log del pie.
"""
from __future__ import annotations

from textual import on
from textual.containers import Horizontal, Vertical
from textual.widgets import (
    Button, Checkbox, Input, Label, RichLog, Select, Static, TabbedContent, TabPane,
)

from ...core import cardfuzz, cardwrite, tlv
from ...core.hexutil import from_hex, to_hex
from ...project import store

_OPS = [
    ("UPDATE RECORD", "record"),
    ("UPDATE BINARY", "binary"),
    ("PUT DATA", "data"),
    ("APPEND RECORD", "append"),
]

_PRESETS = [
    ("Visa (prueba)", "visa"),
    ("Mastercard (prueba)", "mc"),
    ("Amex (prueba)", "amex"),
    ("Personalizado…", "custom"),
]
_PRESET_DATA = {
    "visa": dict(pan="4111111111111111", expiry="2812", name="TEST/CARD", service_code="201"),
    "mc": dict(pan="5555555555554444", expiry="2812", name="TEST/CARD", service_code="201"),
    "amex": dict(pan="371449635398431", expiry="2812", name="TEST/CARD", service_code="201"),
}


class WriteScreen(Vertical):
    def compose(self):
        yield Label("Escritura en tarjeta", classes="title")

        # -- barra de canal seguro compartida (Personalizar + Avanzado) ----
        with Horizontal(classes="row"):
            yield Select([], id="gp_keyset", prompt="Canal seguro · keyset")
            yield Checkbox("C-ENC", id="gp_enc")
            yield Button("↻", id="gp_refresh")
        yield Label("", id="sec_hint", classes="hint")

        with TabbedContent(id="write-tabs"):
            # ── Personalizar (amistoso) ──────────────────────────────────
            with TabPane("Personalizar", id="tab-perso"):
                yield Label("Elige un preset o rellena los campos; se genera un registro EMV "
                            "(5A/57/5F24/5F20) y se escribe en SFI 1 · registro 1.", classes="hint")
                with Horizontal(classes="row"):
                    yield Select(_PRESETS, value="visa", allow_blank=False, id="p_preset")
                with Horizontal(classes="row"):
                    yield Input(placeholder="PAN (16 díg.)", id="p_pan")
                    yield Input(placeholder="Caducidad YYMM", id="p_exp")
                    yield Input(placeholder="Titular", id="p_name")
                    yield Input(placeholder="Cód. serv.", id="p_svc")
                yield Static("", id="p_preview", classes="hint")
                with Horizontal(classes="actions"):
                    yield Button("Datos de prueba", id="p_sample")
                    yield Button("Editar en Avanzado", id="p_gen")
                    yield Button("Escribir en la tarjeta", id="p_write", variant="primary")

            # ── Avanzado (APDU directo + GlobalPlatform) ─────────────────
            with TabPane("Avanzado", id="tab-adv"):
                yield Label("Escritura directa (APDU)", classes="section")
                yield Label("[yellow]⚠ Modifica la tarjeta (puede ser irreversible). Solo tarjetas "
                            "propias/de laboratorio.[/] Si la tarjeta pide canal seguro, se "
                            "autentica sola con el keyset de arriba.", classes="hint")
                with Horizontal(classes="row"):
                    yield Select(_OPS, value="record", allow_blank=False, id="w_op")
                    yield Input(placeholder="SFI", id="w_sfi")
                    yield Input(placeholder="registro / offset", id="w_num")
                    yield Input(placeholder="tag (PUT DATA)", id="w_tag")
                with Horizontal(classes="row"):
                    yield Input(placeholder="datos en hex", id="w_data")
                    yield Button("Escribir", id="w_write", variant="error")

                yield Label("GlobalPlatform · inicializar/gestionar la tarjeta", classes="section")
                yield Label("Prepara una tarjeta EMV escribible: instala un CAP EMV abierto, o "
                            "instancia un applet ya cargado (GET STATUS lista los módulos). Luego "
                            "personaliza en «Personalizar».", classes="hint")
                with Horizontal(classes="actions"):
                    yield Button("Probar autenticación", id="gp_auth", variant="primary")
                    yield Button("Ver contenido (GET STATUS)", id="gp_status")
                    yield Button("Instalar CAP EMV", id="gp_install", variant="warning")
                with Horizontal(classes="row"):
                    yield Input(placeholder="ruta al .cap EMV (para instalar)", id="gp_cap")
                with Horizontal(classes="row"):
                    yield Input(placeholder="paquete (hex)", id="gp_inst_pkg")
                    yield Input(placeholder="módulo (hex)", id="gp_inst_mod")
                    yield Input(placeholder="instancia/AID a crear (hex)", id="gp_inst_aid")
                    yield Button("Instanciar applet", id="gp_instantiate")
                with Horizontal(classes="row"):
                    yield Input(placeholder="AID en hex (para DELETE)", id="gp_aid")
                    yield Button("DELETE", id="gp_delete", variant="error")
                    yield Button("Restaurar (virgen)", id="gp_wipe", variant="error")

        yield RichLog(id="w_log", markup=True, wrap=True)   # log compartido

    def on_mount(self) -> None:
        self.refresh_keysets()
        self._sync_fields("record")
        self._fill_fields(_PRESET_DATA["visa"])    # arranca con el preset por defecto
        self._update_preview()
        self._update_sec_hint()

    # -- personalización rápida --------------------------------------------
    def _field(self, wid: str) -> str:
        return self.query_one(f"#{wid}", Input).value.strip()

    def _build_record(self) -> bytes:
        d = cardfuzz.TEST_RECORD
        return cardfuzz.personalize_record(
            pan=self._field("p_pan") or d["pan"],
            name=self._field("p_name") or d["name"],
            expiry=self._field("p_exp") or d["expiry"],
            service_code=self._field("p_svc") or d["service_code"])

    def _fill_fields(self, d: dict) -> None:
        for wid, key in (("p_pan", "pan"), ("p_exp", "expiry"),
                         ("p_name", "name"), ("p_svc", "service_code")):
            self.query_one(f"#{wid}", Input).value = d[key]

    @on(Button.Pressed, "#p_sample")
    def _fill_sample(self):
        self._fill_fields(cardfuzz.TEST_RECORD)

    @on(Select.Changed, "#p_preset")
    def _apply_preset(self, ev: Select.Changed):
        data = _PRESET_DATA.get(ev.value)
        if data:                                  # 'custom' → no tocar campos
            self._fill_fields(data)

    @on(Input.Changed, "#p_pan, #p_exp, #p_name, #p_svc")
    def _on_perso_input(self):
        self._update_preview()

    def _update_preview(self):
        rec = self._build_record()
        try:
            kids = {n.tag: n.value for n in tlv.parse(rec)[0].children}
        except Exception:  # noqa: BLE001
            kids = {}
        pan = to_hex(kids.get("5A", b"")).rstrip("Ff")
        exp = to_hex(kids.get("5F24", b""))
        t2 = to_hex(kids.get("57", b""))
        name = kids.get("5F20", b"").decode("latin-1", "replace")
        self.query_one("#p_preview", Static).update(
            f"PAN [b]{pan}[/] · Cad [b]{exp[:2]}/{exp[2:4]}[/] · Titular [b]{name}[/]\n"
            f"Track2 (57): [cyan]{t2}[/]\nRegistro: [dim]{to_hex(rec)}[/]")

    @on(Button.Pressed, "#p_gen")
    def _generate(self):
        rec = self._build_record()
        self.query_one("#w_op", Select).value = "record"
        self.query_one("#w_sfi", Input).value = "1"
        self.query_one("#w_num", Input).value = "1"
        self.query_one("#w_data", Input).value = to_hex(rec)
        self.query_one("#write-tabs", TabbedContent).active = "tab-adv"
        self.query_one("#w_log", RichLog).write(
            f"[dim]Registro llevado a Avanzado (revisa y pulsa «Escribir»): {to_hex(rec)}[/]")

    def _write_params(self, base: dict) -> dict:
        """Añade el keyset/C-ENC seleccionados (para la escalada automática a canal
        seguro en `App.write_card_ui`)."""
        val = self.query_one("#gp_keyset", Select).value
        if isinstance(val, str) and val:          # un keyset real (no BLANK/NULL)
            return {**base, "keyset": val,
                    "enc": self.query_one("#gp_enc", Checkbox).value}
        return base

    @on(Button.Pressed, "#p_write")
    def _personalize_write(self):
        rec = self._build_record()
        self.query_one("#w_log", RichLog).write(f"[dim]→ personalizar SFI 1 · reg 1: {to_hex(rec)}[/]")
        self.app.write_card_ui("record", self._write_params({"sfi": 1, "record": 1, "data": rec}))

    @on(Select.Changed, "#gp_keyset")
    def _keyset_changed(self):
        self._update_sec_hint()

    def _update_sec_hint(self):
        val = self.query_one("#gp_keyset", Select).value
        hint = self.query_one("#sec_hint", Label)
        if isinstance(val, str) and val:
            hint.update(f"🔒 Se autentica sola con «{val}» solo si la tarjeta lo exige.")
        else:
            hint.update("🔒 Sin keyset: si la tarjeta pide canal seguro, la escritura se "
                        "detendrá (añade uno con 'gp keyset add').")

    # -- escritura directa --------------------------------------------------
    @on(Select.Changed, "#w_op")
    def _op_changed(self, ev: Select.Changed):
        self._sync_fields(ev.value)

    def _sync_fields(self, op) -> None:
        """Muestra solo los campos que el op necesita (record/append: SFI+registro;
        binary: offset+SFI; data: tag)."""
        self.query_one("#w_sfi", Input).display = op in ("record", "binary", "append")
        self.query_one("#w_num", Input).display = op in ("record", "binary")
        self.query_one("#w_tag", Input).display = op == "data"

    @on(Button.Pressed, "#w_write")
    def _write(self):
        op = self.query_one("#w_op", Select).value
        try:
            data = from_hex(self.query_one("#w_data", Input).value.strip())
        except ValueError:
            self.app.notify("Datos hex inválidos.", severity="error")
            return
        params = {"data": data}
        try:
            if op == "record":
                params["sfi"] = int(self.query_one("#w_sfi", Input).value)
                params["record"] = int(self.query_one("#w_num", Input).value)
            elif op == "binary":
                params["offset"] = int(self.query_one("#w_num", Input).value or "0")
                sfi = self.query_one("#w_sfi", Input).value.strip()
                params["sfi"] = int(sfi) if sfi else None
            elif op == "data":
                params["tag"] = int(self.query_one("#w_tag", Input).value.strip(), 16)
            elif op == "append":
                params["sfi"] = int(self.query_one("#w_sfi", Input).value)
        except ValueError:
            self.app.notify("SFI/registro/offset/tag inválido.", severity="warning")
            return
        self.query_one("#w_log", RichLog).write(f"[dim]→ {op} {to_hex(data)}…[/]")
        self.app.write_card_ui(op, self._write_params(params))

    def log_write(self, op: str, resp) -> None:
        log = self.query_one("#w_log", RichLog)
        ok = resp.sw == 0x9000
        log.write(f"[b {'green' if ok else 'red'}]{'✓' if ok else '✗'} {op}  SW {resp.sw_hex}[/] "
                  f"{cardwrite.write_status(resp.sw)}")
        if resp.data:
            log.write(f"   data: {to_hex(resp.data)}")
        hint = cardwrite.write_hint(resp.sw)
        if hint:
            log.write(f"[dim]   ℹ {hint}[/]")

    # -- GlobalPlatform -----------------------------------------------------
    def refresh_keysets(self) -> None:
        proj = store.active_project()
        names = [k.name for k in store.load_keysets(proj)] if proj else []
        sel = self.query_one("#gp_keyset", Select)
        sel.set_options([(n, n) for n in names])
        if names:
            sel.value = names[0]
        self._update_sec_hint()

    def _keyset(self):
        val = self.query_one("#gp_keyset", Select).value
        if not (isinstance(val, str) and val):    # BLANK/NULL/None → sin keyset
            self.app.notify("Selecciona un keyset (añade con 'gp keyset add').",
                            severity="warning")
            return None
        return val

    def _enc(self) -> bool:
        return self.query_one("#gp_enc", Checkbox).value

    @on(Button.Pressed, "#gp_refresh")
    def _do_refresh(self):
        self.refresh_keysets()

    @on(Button.Pressed, "#gp_auth")
    def _do_auth(self):
        if (k := self._keyset()):
            self.app.gp_op_ui("auth", k, enc=self._enc())

    @on(Button.Pressed, "#gp_status")
    def _do_status(self):
        if (k := self._keyset()):
            self.app.gp_op_ui("status", k, enc=self._enc())

    @on(Button.Pressed, "#gp_install")
    def _do_install(self):
        cap = self.query_one("#gp_cap", Input).value.strip()
        if not cap:
            self.app.notify("Indica la ruta del .cap.", severity="warning"); return
        if (k := self._keyset()):
            self.app.gp_op_ui("install", k, enc=self._enc(), cap=cap)

    @on(Button.Pressed, "#gp_instantiate")
    def _do_instantiate(self):
        pkg = self.query_one("#gp_inst_pkg", Input).value.strip()
        mod = self.query_one("#gp_inst_mod", Input).value.strip()
        inst = self.query_one("#gp_inst_aid", Input).value.strip()
        if not (pkg and mod and inst):
            self.app.notify("Indica paquete, módulo e instancia (hex); GET STATUS los lista.",
                            severity="warning"); return
        if (k := self._keyset()):
            self.app.gp_op_ui("instantiate", k, enc=self._enc(),
                              package=pkg, module=mod, instance=inst)

    @on(Button.Pressed, "#gp_delete")
    def _do_delete(self):
        aid = self.query_one("#gp_aid", Input).value.strip()
        if not aid:
            self.app.notify("Indica un AID (hex).", severity="warning"); return
        if (k := self._keyset()):
            self.app.gp_op_ui("delete", k, enc=self._enc(), aid=aid)

    @on(Button.Pressed, "#gp_wipe")
    def _do_wipe(self):
        if (k := self._keyset()):
            self.app.gp_op_ui("wipe", k, enc=self._enc())

    def log_lines(self, lines) -> None:
        log = self.query_one("#w_log", RichLog)
        for line in lines:
            log.write(line)
