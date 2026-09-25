"""Panel de lectores: descubre backends/dispositivos y conecta uno."""
from __future__ import annotations

from textual import on, work
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, DataTable, Static

from ...readers import registry
from ..widgets.copyable import CopyableDataTable


class ReadersScreen(Vertical):
    def compose(self):
        yield Static("Lectores", classes="title")
        yield Static("Descubre los lectores de todos los backends y conecta uno "
                     "(selecciona una fila y pulsa Conectar).", classes="subtitle")
        with Horizontal(classes="actions"):
            yield Button("Refrescar", id="rdr_refresh")
            yield Button("Conectar", id="rdr_connect", variant="success")
            yield Button("Desconectar", id="rdr_disc", variant="error")
        yield Static("", id="rdr_backends", classes="hint")
        yield CopyableDataTable(id="rdr_table")
        yield Static("", id="rdr_hint", classes="hint")

    def on_mount(self):
        t = self.query_one("#rdr_table", DataTable)
        t.add_columns("#", "backend", "nombre", "capacidades")
        t.cursor_type = "row"
        self._devices = []
        self.reload()

    def reload(self):
        """Lanza el descubrimiento en un **worker** (no bloquea la UI): enumerar
        los backends de hardware —PC/SC, NFC, serie— tarda ~1–2 s y antes
        congelaba el arranque y cada cambio de pestaña."""
        self.query_one("#rdr_hint", Static).update("Buscando lectores…")
        self._scan()

    @work(thread=True, exclusive=True, group="rdr-scan")
    def _scan(self):
        backends = registry.available_backends()
        devices = registry.list_all_devices()
        self.app.call_from_thread(self._populate, backends, devices)

    def _populate(self, backends, devices):
        line = "  ".join(f"{n}={'✓' if ok else '✗'}" for n, ok in backends.items())
        self.query_one("#rdr_backends", Static).update(f"Backends: {line}")
        t = self.query_one("#rdr_table", DataTable)
        t.clear()
        self._devices = devices
        for i, d in enumerate(self._devices):
            t.add_row(str(i), d.backend, d.name, d.caps_str)

        # Diagnóstico: por qué podría faltar un lector.
        msgs: list[str] = []
        has_pcsc = any(d.backend == "pcsc" for d in self._devices)
        if not backends.get("pcsc"):
            import sys
            msgs.append(
                "[yellow]⚠ pcsc no disponible: falta [b]pyscard[/] en este Python "
                f"({sys.executable}). El lector de chip (contacto) no aparecerá.\n"
                "  Lanza la TUI con el venv del proyecto:  "
                "[b].venv/bin/python ./emvyctl.py tui[/]   (o instala pyscard aquí).[/]"
            )
        elif not has_pcsc:
            msgs.append(
                "[yellow]⚠ pcsc activo pero sin lectores de chip: ¿está corriendo pcscd?  "
                "[b]sudo systemctl start pcscd.socket[/]  y pulsa Refrescar.[/]"
            )
        if not self._devices:
            msgs.append("Sin lectores detectados en ningún backend.")
        self.query_one("#rdr_hint", Static).update("\n".join(msgs))

    def _selected(self):
        t = self.query_one("#rdr_table", DataTable)
        if not self._devices:
            return None
        idx = t.cursor_row or 0
        return self._devices[idx] if idx < len(self._devices) else None

    @on(Button.Pressed, "#rdr_refresh")
    def _refresh(self):
        self.reload()

    @on(Button.Pressed, "#rdr_connect")
    def _connect(self):
        dev = self._selected()
        if not dev:
            self.app.notify("Selecciona un lector (o no hay ninguno).", severity="warning")
            return
        self.app.connect_reader(dev)

    @on(Button.Pressed, "#rdr_disc")
    def _disc(self):
        self.app.disconnect_reader()
