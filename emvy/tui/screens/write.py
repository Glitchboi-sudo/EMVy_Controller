"""Pestaña 'Escritura': dos secciones coherentes para modificar una tarjeta.

* **Escritura directa (APDU)** — UPDATE RECORD/BINARY, PUT DATA, APPEND RECORD
  (ISO 7816 / EMV, sin canal seguro). **Modifica la tarjeta**; solo tarjetas
  propias/de laboratorio. Muchas escrituras exigen canal seguro (SW 6982/6985).
* **GlobalPlatform** — canal seguro SCP02/03 con un keyset del proyecto:
  autenticar, GET STATUS, instalar un CAP, DELETE.

Ambas comparten el log del pie.
"""
from __future__ import annotations

from textual import on
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Checkbox, Input, Label, RichLog, Select

from ...core import cardwrite
from ...core.hexutil import from_hex, to_hex
from ...project import store

_OPS = [
    ("UPDATE RECORD", "record"),
    ("UPDATE BINARY", "binary"),
    ("PUT DATA", "data"),
    ("APPEND RECORD", "append"),
]


class WriteScreen(Vertical):
    def compose(self):
        yield Label("Escritura en tarjeta", classes="title")

        # -- sección 1: escritura directa (APDU) ---------------------------
        yield Label("Escritura directa (APDU)", classes="section")
        yield Label("[yellow]⚠ Modifica la tarjeta (puede ser irreversible). Solo tarjetas "
                    "propias/de laboratorio; muchas escrituras exigen canal seguro → usa "
                    "GlobalPlatform abajo.[/]", classes="hint")
        with Horizontal(classes="row"):
            yield Select(_OPS, value="record", allow_blank=False, id="w_op")
            yield Input(placeholder="SFI", id="w_sfi")
            yield Input(placeholder="registro / offset", id="w_num")
            yield Input(placeholder="tag (PUT DATA)", id="w_tag")
        with Horizontal(classes="row"):
            yield Input(placeholder="datos en hex", id="w_data")
            yield Button("Escribir", id="w_write", variant="error")

        # -- sección 2: GlobalPlatform (canal seguro) ----------------------
        yield Label("GlobalPlatform (canal seguro SCP02/03)", classes="section")
        yield Label("Elige un keyset del proyecto (gestiónalos por CLI: 'gp keyset add').",
                    classes="hint")
        with Horizontal(classes="row"):
            yield Select([], id="gp_keyset", prompt="keyset")
            yield Checkbox("C-ENC", id="gp_enc")
            yield Button("↻", id="gp_refresh")
        with Horizontal(classes="actions"):
            yield Button("Autenticar", id="gp_auth", variant="primary")
            yield Button("GET STATUS", id="gp_status")
            yield Button("Instalar CAP", id="gp_install", variant="warning")
        with Horizontal(classes="row"):
            yield Input(placeholder="ruta al .cap (para instalar)", id="gp_cap")
        with Horizontal(classes="row"):
            yield Input(placeholder="AID en hex (para DELETE)", id="gp_aid")
            yield Button("DELETE", id="gp_delete", variant="error")

        yield RichLog(id="w_log", markup=True, wrap=True)   # log compartido

    def on_mount(self) -> None:
        self.refresh_keysets()

    # -- escritura directa --------------------------------------------------
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
        self.app.write_card_ui(op, params)

    def log_write(self, op: str, resp) -> None:
        log = self.query_one("#w_log", RichLog)
        ok = resp.sw == 0x9000
        log.write(f"[b {'green' if ok else 'red'}]{op}  SW {resp.sw_hex}[/] "
                  f"{cardwrite.write_status(resp.sw)}")
        if resp.data:
            log.write(f"   data: {to_hex(resp.data)}")

    # -- GlobalPlatform -----------------------------------------------------
    def refresh_keysets(self) -> None:
        proj = store.active_project()
        names = [k.name for k in store.load_keysets(proj)] if proj else []
        sel = self.query_one("#gp_keyset", Select)
        sel.set_options([(n, n) for n in names])
        if names:
            sel.value = names[0]

    def _keyset(self):
        val = self.query_one("#gp_keyset", Select).value
        if val in (None, Select.BLANK):
            self.app.notify("Selecciona un keyset (añade con 'gp keyset add').",
                            severity="warning")
            return None
        return str(val)

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

    @on(Button.Pressed, "#gp_delete")
    def _do_delete(self):
        aid = self.query_one("#gp_aid", Input).value.strip()
        if not aid:
            self.app.notify("Indica un AID (hex).", severity="warning"); return
        if (k := self._keyset()):
            self.app.gp_op_ui("delete", k, enc=self._enc(), aid=aid)

    def log_lines(self, lines) -> None:
        log = self.query_one("#w_log", RichLog)
        for line in lines:
            log.write(line)
