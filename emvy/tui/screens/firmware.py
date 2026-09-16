"""Pestaña 'BomberCat': gestiona y flashea firmware.

- Firmwares del release oficial (bombercat-tools) + **fuentes alternas** (GitHub
  `owner/repo` o URL directa a un `.uf2`): agregar → descargar → flashear → limpiar.
- **Tu propio firmware**: compilar los sketches de `firmware/` con arduino-cli y
  flashear el `.uf2` resultante, o apuntar a un `.uf2` local.

Todo el trabajo (subprocess/red) corre en workers de la app; la salida se captura.
"""
from __future__ import annotations

from textual import on
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Button, Input, Label, ListItem, ListView, RichLog, Select

from ...integrations import arduino as ard
from ...integrations import bombercat_tools as bt
from ...integrations import firmware_sources as fs


def discover_local_uf2() -> list:
    """`.uf2` compilados propios bajo `firmware/` (salida de arduino-cli)."""
    from ... import config
    root = config.repo_root() / "firmware"
    if not root.exists():
        return []
    try:
        return sorted(root.rglob("*.uf2"))
    except Exception:
        return []


class BombercatScreen(VerticalScroll):
    DEFAULT_CSS = """
    BombercatScreen #fw_list { height: 9; border: round $primary; }
    BombercatScreen #fw_log { height: 8; border: round $primary; }
    BombercatScreen Select { width: 1fr; }
    """

    def compose(self):
        yield Label("BomberCat — firmware", classes="title")
        yield Label("", id="fw_status", classes="hint")
        with Horizontal(classes="row"):
            yield Input(placeholder="fuente: owner/repo (GitHub) o URL .uf2", id="fw_source")
            yield Button("Agregar + descargar", id="fw_addsrc", variant="primary")
            yield Button("Limpiar descargas", id="fw_clean")
        with Horizontal(classes="row"):
            yield Button("Refrescar lista", id="fw_refresh")
            yield Button("Dispositivos", id="fw_devices")
            yield Button("Preparar venv", id="fw_setup")
            yield Button("Permisos USB", id="fw_setupenv")
        yield ListView(id="fw_list")
        with Horizontal(classes="row"):
            yield Input(placeholder="puerto (opcional)", id="fw_port")
            yield Button("Flashear seleccionado", id="fw_flash", variant="error")
            yield Button("Eliminar (caché)", id="fw_del")
        with Horizontal(classes="row"):
            yield Input(placeholder=".uf2 local (ruta manual)", id="fw_local")
            yield Button("Flashear .uf2 local", id="fw_flash_local", variant="warning")
        with Horizontal(classes="row"):
            yield Select([], prompt="sketch a compilar…", allow_blank=True, id="fw_sketch")
            yield Button("Compilar", id="fw_compile", variant="success")
            yield Button("Compilar y subir (picotool)", id="fw_compileflash", variant="warning")
        yield RichLog(id="fw_log", markup=True, wrap=True)

    def on_mount(self):
        self._names: list[str] = []
        self._loaded = False
        self._update_status()
        self._load_sketches()

    def _update_status(self):
        try:
            root, ver, ready = bt.locate(), bt.version(), bt.venv_ready()
            tools = (f"bombercat-tools v{ver} · " + ("venv listo" if ready
                     else "[yellow]venv NO listo[/]"))
        except Exception as e:
            tools = f"[red]bombercat-tools no disponible: {e}[/]"
        acli = "arduino-cli ✓" if ard.arduino_cli_available() else "[yellow]arduino-cli ✗[/]"
        self.query_one("#fw_status", Label).update(f"{tools}  ·  {acli}")

    def _load_sketches(self):
        opts = [(p.name, str(p)) for p in ard.list_sketches()]
        try:
            self.query_one("#fw_sketch", Select).set_options(opts)
        except Exception:
            pass

    def ensure_loaded(self):
        if not self._loaded:
            self._loaded = True
            self.app.bombercat_fw_list_ui()

    def set_firmwares(self, items: list):
        """`items` = [(etiqueta, objetivo)]; objetivo = nombre de release o ruta .uf2."""
        self._names = [t for _, t in items]
        lv = self.query_one("#fw_list", ListView)
        lv.clear()
        for label, _ in items:
            lv.append(ListItem(Label(label)))
        self.log(f"[green]{len(items)} firmware(s) disponibles.[/]")

    def _selected(self) -> str | None:
        idx = self.query_one("#fw_list", ListView).index
        if idx is None or not (0 <= idx < len(self._names)):
            return None
        return self._names[idx]

    def log(self, text: str):
        self.query_one("#fw_log", RichLog).write(text)

    # -- fuentes ------------------------------------------------------------
    @on(Button.Pressed, "#fw_addsrc")
    def _addsrc(self):
        ref = self.query_one("#fw_source", Input).value.strip()
        if not ref:
            self.app.notify("Indica owner/repo o una URL .uf2.", severity="warning")
            return
        self.query_one("#fw_source", Input).value = ""
        self.log(f"[dim]agregando y descargando de {ref}…[/]")
        self.app.bombercat_add_source_ui(ref)

    @on(Button.Pressed, "#fw_clean")
    def _clean(self):
        self.log("[dim]limpiando descargas…[/]")
        self.app.bombercat_clean_ui(None)

    # -- listar / dispositivos / setup -------------------------------------
    @on(Button.Pressed, "#fw_refresh")
    def _refresh(self):
        self.log("[dim]listando firmwares…[/]")
        self.app.bombercat_fw_list_ui()

    @on(Button.Pressed, "#fw_devices")
    def _devices(self):
        self.log("[dim]buscando dispositivos…[/]")
        self.app.bombercat_devices_ui()

    @on(Button.Pressed, "#fw_setup")
    def _setup(self):
        self.log("[dim]preparando venv de bombercat-tools…[/]")
        self.app.bombercat_setup_ui()

    @on(Button.Pressed, "#fw_setupenv")
    def _setupenv(self):
        self.log("[dim]configurando permisos USB (udev + grupos); acepta la "
                 "elevación si aparece…[/]")
        self.app.bombercat_setup_env_ui()

    # -- flashear / eliminar ------------------------------------------------
    @on(Button.Pressed, "#fw_flash")
    def _flash(self):
        target = self._selected()
        if not target:
            self.app.notify("Selecciona un firmware de la lista.", severity="warning")
            return
        self._do_flash(target)

    @on(Button.Pressed, "#fw_flash_local")
    def _flash_local(self):
        path = self.query_one("#fw_local", Input).value.strip()
        if not path:
            self.app.notify("Indica la ruta a tu .uf2.", severity="warning")
            return
        self._do_flash(path)

    def _do_flash(self, target: str):
        port = self.query_one("#fw_port", Input).value.strip() or None
        kind = "tu .uf2" if target.endswith(".uf2") else "el release"
        self.log(f"[yellow]⚠ Flasheando {kind} [b]{target}[/]… no desconectes la placa.[/]")
        self.app.bombercat_flash_ui(target, port)

    @on(Button.Pressed, "#fw_del")
    def _del(self):
        target = self._selected()
        if not target or not target.endswith(".uf2"):
            self.app.notify("Solo se pueden eliminar descargas (.uf2 de la caché).",
                            severity="warning")
            return
        self.app.bombercat_clean_ui(target)

    # -- compilar firmware propio ------------------------------------------
    def _sketch(self):
        val = self.query_one("#fw_sketch", Select).value
        return val if isinstance(val, str) else None

    @on(Button.Pressed, "#fw_compile")
    def _compile(self):
        sk = self._sketch()
        if not sk:
            self.app.notify("Elige un sketch de firmware/.", severity="warning")
            return
        self.log(f"[dim]compilando {sk}… (puede tardar)[/]")
        self.app.bombercat_compile_ui(sk, False)

    @on(Button.Pressed, "#fw_compileflash")
    def _compileflash(self):
        sk = self._sketch()
        if not sk:
            self.app.notify("Elige un sketch de firmware/.", severity="warning")
            return
        port = self.query_one("#fw_port", Input).value.strip() or None
        self.log(f"[dim]compilando y subiendo {sk} por picotool…[/]")
        self.app.bombercat_compile_ui(sk, True, port)
