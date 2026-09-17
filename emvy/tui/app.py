"""Aplicación TUI (Textual) de EMVyController.

La lógica de negocio vive en `core`/`session`/`project` (puro/efectos aislados);
esta capa solo orquesta: mantiene el estado de sesión (proyecto activo, lector
conectado, última captura) y llama a las funciones del núcleo. Las operaciones
de hardware (conectar, capturar, enviar APDU) corren en hilos de trabajo para no
congelar la interfaz.
"""
from __future__ import annotations

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.theme import Theme
from textual.widgets import Footer, Header, TabbedContent, TabPane

# Tema oscuro profesional "slate/OLED + run green" (mismo sistema visual que la
# GUI: emvy/gui/theme.py). Recolorea todos los tokens $primary/$accent/$panel…
EMVY_THEME = Theme(
    name="emvy",
    primary="#334155",      # estructura/bordes (slate-700)
    secondary="#1E293B",
    accent="#22C55E",       # acción/acento (green-500)
    foreground="#F8FAFC",
    background="#0B1220",    # fondo profundo
    surface="#0F172A",       # base de pantallas
    panel="#1B2336",         # paneles/cabeceras
    success="#22C55E",
    warning="#F59E0B",
    error="#EF4444",
    dark=True,
)

from .. import __release__, __version__
from ..core import emv
from ..core.hexutil import from_hex, to_hex
from ..project import env as envmod
from ..project import store
from ..readers import registry
from ..session.capture import capture_card
from .screens.charges import ChargesScreen
from .screens.console import ConsoleScreen
from .screens.dashboard import DashboardScreen
from .screens.explorer import ExplorerScreen
from .screens.firmware import BombercatScreen
from .screens.fuzz import FuzzScreen
from .screens.help import HelpScreen
from .screens.intercept import InterceptScreen
from .screens.iso8583 import Iso8583Screen
from .screens.pocs import PocScreen
from .screens.projects import ProjectsScreen
from .screens.readers import ReadersScreen
from .screens.tools import ToolsScreen
from .screens.variables import VariablesScreen
from .widgets.common import StatusBar


class EmvyApp(App):
    TITLE = "EMVy Controller"
    SUB_TITLE = f"v{__version__} {__release__} · EMV security testing & card exploration"

    # Sistema visual compartido por todas las pantallas (profesional, coherente,
    # y válido en tema claro/oscuro vía tokens de diseño de Textual).
    CSS = """
    Screen { background: $surface; }

    /* Cabecera/pie con fondo de panel y subrayado de pestaña en acento */
    Header { background: $panel; color: $accent; text-style: bold; }
    Footer { background: $panel; }
    Underline > .underline--bar { color: $accent; }

    /* Encabezados de sección y ayudas contextuales (compartidos por todas las
       pantallas para un aspecto coherente: título de pantalla, subtítulo
       descriptivo, etiquetas de sección y pistas). */
    .title {
        text-style: bold; color: $accent;
        border-bottom: heavy $primary; padding: 1 1 0 0; margin: 0 0 1 0;
    }
    .subtitle { color: $text-muted; padding: 0 0 1 0; }
    .section  { text-style: bold; color: $accent; padding: 1 0 0 0; }
    .hint  { color: $text-muted; padding: 0 0 1 0; }

    /* Filas de controles (input + botones) */
    .row   { height: auto; padding: 1 0; }
    .row Input { width: 1fr; margin: 0 1 0 0; }
    .row Button { margin: 0 1 0 0; min-width: 10; }
    /* Barra de acciones compacta (botones agrupados, sin padding vertical
       extra) — para las cabeceras de acción de cada pantalla. */
    .actions { height: auto; padding: 0 0 1 0; }
    .actions Button { margin: 0 1 0 0; min-width: 12; }

    /* Tablas: cabecera y cursor destacados */
    DataTable { height: 1fr; border: round $primary; }
    DataTable:focus { border: round $accent; }
    DataTable > .datatable--header { text-style: bold; background: $panel; color: $accent; }
    DataTable > .datatable--cursor { background: $accent; color: $text; }

    /* Árboles / logs */
    Tree { height: 1fr; border: round $primary; padding: 0 1; }
    RichLog { height: 1fr; border: round $primary; padding: 0 1; }

    /* Pestañas con acento profesional */
    TabPane { padding: 0 1; }
    Tabs:focus .-active { text-style: bold; }
    Tab.-active { color: $accent; text-style: bold; }

    /* Barra de estado inferior */
    StatusBar { background: $panel; color: $text; }
    """

    # Solo los esenciales se muestran en el footer (antes se desbordaba con 14
    # atajos); el resto siguen activos pero `show=False` y viven en la Ayuda (?).
    BINDINGS = [
        Binding("q", "quit", "Salir"),
        Binding("question_mark", "help", "Ayuda"),
        Binding("r", "refresh", "Refrescar"),
        Binding("p", "show('tab-proj')", "Proyectos", show=False),
        Binding("v", "show('tab-vars')", "Variables", show=False),
        Binding("l", "show('tab-rdr')", "Lectores", show=False),
        Binding("e", "show('tab-exp')", "Explorador", show=False),
        Binding("f", "tool('tool-flags')", "Flags", show=False),
        Binding("b", "show('tab-cob')", "Cobros", show=False),
        Binding("o", "show('tab-poc')", "PoCs", show=False),
        Binding("i", "show('tab-int')", "Intercept", show=False),
        Binding("m", "show('tab-bc')", "BomberCat", show=False),
        Binding("8", "tool('tool-iso')", "ISO 8583", show=False),
        Binding("w", "tool('tool-write')", "Escritura", show=False),
        Binding("u", "show('tab-fuzz')", "Fuzzing", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.reader = None
        self.reader_device = None
        self.last_dump = None
        self.card_atr: str | None = None
        self.intercept_rules: list = []
        self.intercept_active: bool = False
        import threading
        self._emu_stop = threading.Event()   # señal para detener la emulación NDEF
        self.register_theme(EMVY_THEME)      # tema visual profesional (ver EMVY_THEME)

    # -- interceptor de APDUs (Burp para EMV) ------------------------------
    def active_send(self):
        """Transceiver a usar: envuelto por el interceptor si está activo."""
        send = self.reader.transceive
        if self.intercept_active and self.intercept_rules:
            from ..core import intercept
            return intercept.intercepting(send, self.intercept_rules,
                                          on_event=self._intercept_event)
        return send

    def _intercept_event(self, ex) -> None:
        try:
            self.call_from_thread(self._log_intercept, ex)
        except Exception:
            pass

    def _log_intercept(self, ex) -> None:
        try:
            self.query_one("#screen-intercept").log_exchange(ex)
        except Exception:
            pass

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent(initial="tab-home", id="main-tabs"):
            with TabPane("Inicio", id="tab-home"):
                yield DashboardScreen(id="screen-dashboard")
            with TabPane("Proyectos", id="tab-proj"):
                yield ProjectsScreen(id="screen-projects")
            with TabPane("Variables", id="tab-vars"):
                yield VariablesScreen(id="screen-variables")
            with TabPane("Lectores", id="tab-rdr"):
                yield ReadersScreen(id="screen-readers")
            with TabPane("Explorador", id="tab-exp"):
                yield ExplorerScreen(id="screen-explorer")
            with TabPane("Consola", id="tab-con"):
                yield ToolsScreen(id="screen-tools")
            with TabPane("Cobros", id="tab-cob"):
                yield ChargesScreen(id="screen-charges")
            with TabPane("PoC", id="tab-poc"):
                yield PocScreen(id="screen-pocs")
            with TabPane("Intercept", id="tab-int"):
                yield InterceptScreen(id="screen-intercept")
            with TabPane("BomberCat", id="tab-bc"):
                yield BombercatScreen(id="screen-firmware")
            with TabPane("Fuzzing", id="tab-fuzz"):
                yield FuzzScreen(id="screen-fuzz")
        yield StatusBar()
        yield Footer()

    def on_mount(self) -> None:
        self.theme = "emvy"      # aplica el tema profesional
        self.update_status()

    # -- navegación / refresco ---------------------------------------------
    def action_show(self, tab_id: str) -> None:
        self.query_one("#main-tabs", TabbedContent).active = tab_id

    def action_tool(self, tool_id: str) -> None:
        """Navega a la pestaña Consola y activa una de sus herramientas
        (tool-flags / tool-iso / tool-write)."""
        self.action_show("tab-con")
        try:
            self.query_one("#screen-tools", ToolsScreen).show_tool(tool_id)
        except Exception:
            pass

    def action_refresh(self) -> None:
        self.refresh_ui()
        self.notify("Actualizado.")

    def action_help(self) -> None:
        # evita apilar varias ayudas si se pulsa ? repetido
        if not isinstance(self.screen, HelpScreen):
            self.push_screen(HelpScreen())

    @on(TabbedContent.TabActivated)
    def _on_tab(self, event) -> None:
        # Solo refrescar en cambios de la barra principal (no de las sub-pestañas).
        if getattr(event.tabbed_content, "id", None) != "main-tabs":
            return
        self.refresh_ui()
        if self.query_one("#main-tabs", TabbedContent).active == "tab-bc":
            try:  # lista de firmware perezosa (no corre el subprocess al arrancar)
                self.query_one("#screen-firmware", BombercatScreen).ensure_loaded()
            except Exception:
                pass

    def refresh_ui(self) -> None:
        for sid in ("#screen-dashboard", "#screen-projects", "#screen-variables",
                    "#screen-readers", "#screen-pocs", "#screen-charges", "#screen-explorer"):
            try:
                w = self.query_one(sid)
                if hasattr(w, "reload"):
                    w.reload()
            except Exception:
                pass
        self.update_status()

    def update_status(self) -> None:
        try:
            bar = self.query_one(StatusBar)
        except Exception:
            return
        rdr = self.reader_device.name if self.reader_device else None
        bar.show(store.active_label(), rdr, self.card_atr)
        try:  # mantener el dashboard en sync con el estado de sesión
            self.query_one("#screen-dashboard").reload()
        except Exception:
            pass

    # -- perfil de terminal del proyecto activo ----------------------------
    def current_profile(self) -> dict:
        proj = store.active_project()
        if proj:
            return envmod.to_terminal_profile(store.load_project_variables(proj))
        return emv.default_terminal_profile()

    # -- lector: conectar / desconectar (hilo de trabajo) ------------------
    @work(thread=True, exclusive=True, group="reader")
    def connect_reader(self, device) -> None:
        self.call_from_thread(self.notify, f"Conectando a {device.name}…")
        # Banner en la consola ANTES de abrir: el handshake del BomberCat (PING/
        # WAIT/READY) ocurre dentro de open() y ya se ve en vivo por `on_wire`.
        self.call_from_thread(self._console_banner,
                              f"conectando: {device.name} [{device.backend}]")
        try:
            reader = registry.open_device(device, on_event=self._on_reader_trace,
                                          on_wire=self._on_reader_wire)
            atr = reader.atr() if reader.atr else b""
        except Exception as e:
            self.call_from_thread(self.notify, str(e).splitlines()[0], severity="error")
            return
        self.reader = reader
        self.reader_device = device
        self.call_from_thread(self._on_connected, atr)

    def _on_reader_trace(self, e) -> None:
        """`on_event` del lector activo: retransmite cada intercambio APDU
        (ya parseado, con status word) a la consola en vivo del Explorador,
        útil para ver qué pasa (o si se pierde algo) durante una captura."""
        try:
            self.call_from_thread(self._log_trace_live, e)
        except Exception:
            pass

    def _on_reader_wire(self, e) -> None:
        """`on_wire` del lector activo: retransmite cada línea de transporte de
        bajo nivel (serie del BomberCat: PING/WAIT/READY/APDU:/RESP:) a la
        consola — literalmente 'qué mando, qué responde' el hardware."""
        try:
            self.call_from_thread(self._log_wire_live, e)
        except Exception:
            pass

    def _log_trace_live(self, e) -> None:
        try:
            self.query_one("#screen-console", ConsoleScreen).live_log(e)
        except Exception:
            pass

    def _log_wire_live(self, e) -> None:
        try:
            self.query_one("#screen-console", ConsoleScreen).wire_log(e)
        except Exception:
            pass

    def _console_banner(self, text: str) -> None:
        try:
            self.query_one("#screen-console", ConsoleScreen).banner(text)
        except Exception:
            pass

    def _on_connected(self, atr: bytes) -> None:
        self.card_atr = to_hex(atr, sep=" ") if atr else None
        self.update_status()
        atr_txt = f" · ATR {self.card_atr}" if self.card_atr else ""
        self._console_banner(f"conectado: {self.reader_device.name}"
                             f" [{self.reader_device.backend}]{atr_txt}")
        self.notify("Lector conectado.")

    def disconnect_reader(self) -> None:
        name = self.reader_device.name if self.reader_device else "lector"
        if self.reader:
            try:
                self.reader.close()
            except Exception:
                pass
        self.reader = None
        self.reader_device = None
        self.card_atr = None
        self.update_status()
        self._console_banner(f"desconectado: {name}")
        self.notify("Lector desconectado.")

    # -- captura / descubrimiento (hilo de trabajo) ------------------------
    def _need_card_reader(self) -> bool:
        if self.reader and self.reader.transceive:
            return True
        self.notify("Conecta un lector de chip o NFC primero (pestaña Lectores).",
                    severity="warning")
        return False

    @work(thread=True, exclusive=True, group="card")
    def capture_card_ui(self, raw: bool = False, mode: str = "auto") -> None:
        if not self._need_card_reader():
            return
        # Contactless (BomberCat): flujo EMV mínimo (sin bruteforce/barrido) —
        # cientos de APDUs sobre NFC de rango milimétrico pierden la tarjeta a
        # media lectura (ERR:TXFAIL). PPSE→SELECT→GPO→AFL basta y es fiable.
        lean = getattr(self.reader_device, "backend", None) == "bombercat"
        try:
            dump = capture_card(
                self.active_send(),
                atr=(self.reader.atr() if self.reader.atr else b""),
                reader=(self.reader_device.name if self.reader_device else ""),
                profile=self.current_profile(),
                raw=raw,
                mode=mode,
                brute=not lean, sweep=not lean, get_data=not lean,
            )
        except Exception as e:
            self.call_from_thread(self.notify, f"Captura falló: {e}", severity="error")
            return
        self.last_dump = dump
        self.call_from_thread(self._on_dump, dump)

    def _on_dump(self, dump) -> None:
        try:
            self.query_one("#screen-explorer", ExplorerScreen).show_dump(dump)
        except Exception:
            pass
        self.update_status()   # refleja la captura en el dashboard
        backend = getattr(self.reader_device, "backend", None)
        empty = not dump.applications and len(dump.blobs) <= 1  # <=1: solo el blob ATR, si acaso
        if backend == "bombercat" and empty:
            self.notify("Sin datos: la tarjeta probablemente se movió durante la lectura "
                        "(el rango NFC es de milímetros). Sosténla firme y pegada a la "
                        "antena, y vuelve a intentar.", severity="warning")
            return
        self.notify(f"Captura: {len(dump.applications)} app(s), {len(dump.blobs)} blobs.")

    # -- APDU crudo (hilo de trabajo) --------------------------------------
    @work(thread=True, exclusive=True, group="card")
    def send_apdu_ui(self, hexstr: str) -> None:
        if not self._need_card_reader():
            return
        try:
            resp = self.active_send()(from_hex(hexstr))
        except Exception as e:
            self.call_from_thread(self.notify, str(e), severity="error")
            return
        self.call_from_thread(self._on_apdu, hexstr, resp)

    def _on_apdu(self, hexstr, resp) -> None:
        try:
            self.query_one("#screen-console", ConsoleScreen).log_response(hexstr, resp)
        except Exception:
            pass

    # -- PoC: ejecutar un plugin del proyecto (hilo de trabajo) ------------
    @work(thread=True, exclusive=True, group="poc")
    def run_poc_ui(self, poc_id: str, *, card_source: str = "session",
                   capture_name: str | None = None, dry_run: bool = True,
                   allow_write: bool = False) -> None:
        from .. import poc as pocmod
        from ..payments import EmvCard
        from ..session.model import CardDump
        proj = store.active_project()
        if not proj:
            self.call_from_thread(self.notify, "No hay proyecto activo.", severity="warning")
            return
        pocmod.clear()
        pocmod.load_plugins(proj)
        p = pocmod.get(poc_id)
        if not p:
            self.call_from_thread(self.notify, f"PoC {poc_id!r} no encontrado.", severity="error")
            return

        # Resuelve la tarjeta según la fuente elegida (IO en el hilo de trabajo).
        dump = None
        try:
            if card_source == "session":
                dump = self.last_dump
            elif card_source == "saved" and capture_name:
                path = proj.captures_dir / capture_name
                dump = CardDump.from_json(path.read_text())
            elif card_source == "live":
                if not (self.reader and self.reader.transceive):
                    self.call_from_thread(self.notify,
                                          "Conecta un lector de chip/NFC para capturar en vivo.",
                                          severity="warning")
                    return
                self.call_from_thread(self.notify, "Capturando del lector para el PoC…")
                dump = capture_card(
                    self.active_send(),
                    atr=(self.reader.atr() if self.reader.atr else b""),
                    reader=(self.reader_device.name if self.reader_device else ""),
                    profile=self.current_profile(),
                )
                self.last_dump = dump
        except Exception as e:  # noqa: BLE001
            self.call_from_thread(self.notify, f"Tarjeta: {e}", severity="error")
            return

        try:
            card = EmvCard.from_dump(dump) if dump else None
        except Exception:  # noqa: BLE001 — una captura rara no debe tumbar el run
            card = None
        run_dir = pocmod.runner.run_dir_for(proj, p.meta.id)
        ctx = pocmod.make_context(proj, card=card, run_dir=run_dir,
                                  dry_run=dry_run, allow_write=allow_write)
        result = pocmod.run_poc(p, ctx)
        pocmod.save_result(ctx, p.meta, result)
        self.call_from_thread(self._on_poc, p.meta, result, run_dir)
        self.call_from_thread(self.update_status)

    def _on_poc(self, meta, result, run_dir) -> None:
        try:
            self.query_one("#screen-pocs", PocScreen).log_result(meta, result, run_dir)
        except Exception:
            pass
        self.notify(f"PoC {meta.id}: {result.status}")

    # -- Cobros / switch: flujo completo (hilo de trabajo) -----------------
    def _resolve_dump(self, card_source: str, capture_name: str | None):
        """Resuelve un CardDump según la fuente (sesión/guardada/lector en vivo)."""
        from ..session.model import CardDump
        if card_source == "session":
            return self.last_dump
        if card_source == "saved" and capture_name:
            proj = store.active_project()
            if proj:
                return CardDump.from_json((proj.captures_dir / capture_name).read_text())
        if card_source == "live" and self.reader and self.reader.transceive:
            dump = capture_card(
                self.active_send(),
                atr=(self.reader.atr() if self.reader.atr else b""),
                reader=(self.reader_device.name if self.reader_device else ""),
                profile=self.current_profile())
            self.last_dump = dump
            return dump
        return None

    @work(thread=True, exclusive=True, group="switch")
    def run_switch_flow_ui(self, kind: str, *, card_source: str = "session",
                           capture_name: str | None = None, amount: int = 500,
                           dry_run: bool = True, sign_on: bool = True) -> None:
        from ..payments import EmvCard, SwitchConfig, switch
        proj = store.active_project()
        variables = ({v.name: v.value for v in store.load_project_variables(proj)}
                     if proj else {})
        cfg = SwitchConfig.from_vars(lambda k: variables.get(k))
        try:
            if kind == "signon":
                res = switch.run_signon(cfg)
            elif kind == "reversal":
                res = switch.run_reversal(cfg, stan=variables.get("stan", "000001"),
                                          rrn=variables.get("rrn", ""),
                                          amount_cents=amount, dry_run=dry_run,
                                          sign_on=sign_on)
            else:
                dump = self._resolve_dump(card_source, capture_name)
                card = EmvCard.from_dump(dump) if dump else None
                if card is None:
                    self.call_from_thread(self.notify,
                                          "Necesitas una tarjeta (captura o lector).",
                                          severity="warning")
                    return
                res = switch.run_purchase(cfg, card, amount, dry_run=dry_run, sign_on=sign_on)
        except Exception as e:  # noqa: BLE001
            self.call_from_thread(self.notify, f"Switch: {e}", severity="error")
            return
        # evidencia en el proyecto
        if proj:
            try:
                from datetime import datetime
                tdir = proj.path / "transactions"
                tdir.mkdir(parents=True, exist_ok=True)
                (tdir / f"{datetime.now():%Y%m%d-%H%M%S}-{kind}.txt").write_text(res.summary())
            except Exception:
                pass
        self.call_from_thread(self._on_switch, kind, res)

    def _on_switch(self, kind: str, res) -> None:
        try:
            self.query_one("#screen-charges").log_flow(kind, res)
        except Exception:
            pass
        self.update_status()

    # -- Escritura en tarjeta (hilo de trabajo) ----------------------------
    @work(thread=True, exclusive=True, group="card")
    def write_card_ui(self, op: str, params: dict) -> None:
        """Escritura **inteligente**: directa y, si la tarjeta exige canal seguro
        (6982/6985), autentica sola por GlobalPlatform con el keyset elegido y
        reintenta. `params` puede traer `keyset` (nombre) y `enc`."""
        from ..core import cardwrite
        from ..core.gp import content
        from ..core.gp.scp import SEC_CENC, SEC_CMAC
        if not (self.reader and self.reader.transceive):
            self.call_from_thread(self.notify, "Conecta un lector de chip/NFC primero.",
                                  severity="warning")
            return
        send = self.active_send()
        data = params["data"]
        ks = None
        if params.get("keyset"):
            proj = store.active_project()
            ks = store.get_keyset(proj, params["keyset"]) if proj else None

        def write_fn(s):
            if op == "record":
                return cardwrite.update_record(s, params["sfi"], params["record"], data)
            if op == "binary":
                return cardwrite.update_binary(s, params["offset"], data, sfi=params.get("sfi"))
            if op == "data":
                return cardwrite.put_data(s, params["tag"], data)
            if op == "append":
                return cardwrite.append_record(s, params["sfi"], data)
            raise ValueError(op)

        try:
            res = content.smart_write(
                send, write_fn, keyset=ks,
                security_level=SEC_CENC if params.get("enc") else SEC_CMAC)
        except Exception as e:  # noqa: BLE001
            self.call_from_thread(self.notify, f"Escritura: {e}", severity="error")
            return
        self.call_from_thread(self._on_write, op, res)

    def _on_write(self, op: str, res) -> None:
        # write_card_ui() lo usan tanto la pestaña Escritura como Fuzzing.
        for sid in ("#screen-write", "#screen-fuzz"):
            try:
                screen = self.query_one(sid)
                if res.log and hasattr(screen, "log_lines"):
                    screen.log_lines(res.log)
                screen.log_write(op, res.response)
            except Exception:
                pass

    # -- GlobalPlatform: canal seguro + gestión (hilo de trabajo) ----------
    @work(thread=True, exclusive=True, group="card")
    def gp_op_ui(self, action: str, keyset_name: str, *, enc: bool = False, **kw) -> None:
        from ..core.gp import apdu as gpapdu   # noqa: F401
        from ..core.gp import cap as capmod
        from ..core.gp import content
        from ..core.gp.scp import GPError, SEC_CENC, SEC_CMAC
        from ..core.hexutil import from_hex
        if not (self.reader and self.reader.transceive):
            self.call_from_thread(self.notify, "Conecta un lector de chip/NFC primero.",
                                  severity="warning")
            return
        proj = store.active_project()
        ks = store.get_keyset(proj, keyset_name) if proj else None
        if not ks:
            self.call_from_thread(self.notify, f"Keyset {keyset_name!r} no existe.",
                                  severity="error")
            return
        send = self.active_send()
        try:
            chan = content.authenticate(send, ks, security_level=SEC_CENC if enc else SEC_CMAC)
            lines = [f"[green]Canal seguro: SCP{chan.protocol} (keyset {ks.name})[/]"]
            if action == "status":
                inv = content.list_all(chan)
                for key, label in (("isd", "ISD"), ("apps", "Apps/SD"),
                                   ("load_files", "Paquetes")):
                    lines.append(f"[b]── {label} ──[/]")
                    if not inv[key]:
                        lines.append("  [dim](ninguno)[/]")
                    for a in inv[key]:
                        lines.append(f"  {a.aid}  {a.lifecycle}  {a.privileges}")
                        lines += [f"      [cyan]└ módulo {m}[/]" for m in a.modules]
            elif action == "delete":
                content.delete(chan, from_hex(kw["aid"]), related=True)
                lines.append(f"DELETE {kw['aid']} OK")
            elif action == "wipe":
                res = content.restore_virgin(
                    chan, keep_aids=kw.get("keep", ()),
                    delete_packages=kw.get("packages", False))
                lines += [f"[green]{m}[/]" if "Virgen" in m else m for m in res.log]
            elif action == "instantiate":
                content.install_instance(
                    chan, from_hex(kw["package"]), from_hex(kw["module"]),
                    from_hex(kw["instance"]),
                    make_selectable=not kw.get("no_selectable", False))
                lines.append(f"[green]Instancia creada: {kw['instance']} "
                             f"(módulo {kw['module']})[/]")
            elif action == "install":
                capf = capmod.parse_cap(kw["cap"])
                lines.append(f"CAP: paquete {capf.package_aid_hex}")
                res = content.install_cap(chan, capf)
                lines += [f"  {s}: {v}" for s, v in res.steps]
                lines.append(f"[green]Instalado: paquete {res.package_aid}"
                             + (f", instancia {res.instance_aid}" if res.instance_aid else "") + "[/]")
        except GPError as e:
            self.call_from_thread(self._on_gp_lines, [f"[red]✗ GP: {e}[/]"])
            return
        except Exception as e:  # noqa: BLE001
            self.call_from_thread(self._on_gp_lines, [f"[red]✗ {e}[/]"])
            return
        self.call_from_thread(self._on_gp_lines, lines)

    def _on_gp_lines(self, lines) -> None:
        try:
            self.query_one("#screen-write").log_lines(lines)   # Escritura (sección GP)
        except Exception:
            pass

    # -- Fuzzing de terminales: magspoof (hilo de trabajo) ------------------
    @work(thread=True, exclusive=True, group="card")
    def fuzz_magspoof_ui(self, track1: str | None, track2: str | None) -> None:
        from ..readers import bombercat
        devs = [d for d in registry.list_all_devices() if d.backend == "bombercat"]
        if not devs:
            self.call_from_thread(self.notify,
                                  "No se detectó BomberCat (¿pyserial? ¿conectado?).",
                                  severity="warning")
            return
        try:
            out = bombercat.magspoof_emit(devs[0], track1=track1, track2=track2)
        except Exception as e:  # noqa: BLE001
            self.call_from_thread(self.notify, f"magspoof: {e}", severity="error")
            return
        self.call_from_thread(self._on_fuzz_magspoof, out)

    def _on_fuzz_magspoof(self, out: str) -> None:
        try:
            self.query_one("#screen-fuzz").log_magspoof(out)
        except Exception:
            pass
        self.notify(f"magspoof: {out}")

    # -- Fuzzing de terminales: emulación NDEF (NFC) -----------------------
    @work(thread=True, exclusive=True, group="card")
    def fuzz_ndef_ui(self, ndef_hex: str) -> None:
        from ..readers import bombercat
        devs = [d for d in registry.list_all_devices() if d.backend == "bombercat"]
        if not devs:
            self.call_from_thread(self.notify,
                                  "No se detectó BomberCat (¿pyserial? ¿conectado?).",
                                  severity="warning")
            return
        self.call_from_thread(self.notify,
                              "Emulando tag NDEF… acerca un lector NFC (Detener para parar).")
        try:
            bombercat.ndef_emulate(
                devs[0], ndef_hex, timeout=None, stop=self._emu_stop.is_set,
                on_line=lambda l: self.call_from_thread(self._on_fuzz_ndef_line, l))
        except Exception as e:  # noqa: BLE001
            self.call_from_thread(self.notify, f"NDEF EMU: {e}", severity="error")

    @work(thread=True, exclusive=True, group="card")
    def fuzz_emv_ui(self) -> None:
        """Emula una tarjeta EMV para perfilar/fuzzear un terminal de pago."""
        from ..readers import bombercat
        devs = [d for d in registry.list_all_devices() if d.backend == "bombercat"]
        if not devs:
            self.call_from_thread(self.notify,
                                  "No se detectó BomberCat (¿pyserial? ¿conectado?).",
                                  severity="warning")
            return
        self.call_from_thread(self.notify,
                              "Emulando tarjeta EMV… acerca el terminal/POS (Detener para parar).")
        try:
            bombercat.emv_emulate(
                devs[0], timeout=None, stop=self._emu_stop.is_set,
                on_line=lambda l: self.call_from_thread(self._on_fuzz_ndef_line, l))
        except Exception as e:  # noqa: BLE001
            self.call_from_thread(self.notify, f"EMV EMU: {e}", severity="error")

    def emu_arm(self) -> None:
        """Arma la emulación: limpia la señal de STOP en el hilo principal ANTES
        de lanzar el worker (evita la carrera clear()-en-hilo vs. set() de Detener)."""
        self._emu_stop.clear()

    def fuzz_ndef_stop_ui(self) -> None:
        """Detiene la emulación (NDEF o EMV) en curso (señala al worker STOP)."""
        self._emu_stop.set()
        self.notify("Deteniendo emulación…")

    @work(thread=True, exclusive=True, group="fw")
    def bombercat_reboot_ui(self) -> None:
        """Reinicia el BomberCat (REBOOT). Detiene antes cualquier emulación para
        soltar el puerto; tras el reset hay que reconectar el lector."""
        from ..readers import bombercat
        self._emu_stop.set()
        devs = [d for d in registry.list_all_devices() if d.backend == "bombercat"]
        if not devs:
            self.call_from_thread(self.notify,
                                  "No se detectó BomberCat (¿pyserial? ¿conectado?).",
                                  severity="warning")
            return
        try:
            out = bombercat.reboot(devs[0])
        except Exception as e:  # noqa: BLE001
            self.call_from_thread(self.notify, f"REBOOT: {e}", severity="error")
            return
        self.call_from_thread(self._on_fuzz_ndef_line, f"# REBOOT → {out}")
        # el USB CDC se re-enumera: el lector conectado deja de ser válido
        if self.reader_device and self.reader_device.backend == "bombercat":
            self.call_from_thread(self._disconnect_after_reboot)
        self.call_from_thread(
            self.notify,
            "BomberCat reiniciado. Reconecta el lector en la pestaña Lectores.")

    def _disconnect_after_reboot(self) -> None:
        try:
            if self.reader and self.reader.close:
                self.reader.close()
        except Exception:
            pass
        self.reader = None
        self.reader_device = None

    def _on_fuzz_ndef_line(self, line: str) -> None:
        try:
            self.query_one("#screen-fuzz").log_ndef(line)
        except Exception:
            pass

    # -- BomberCat: firmware (subprocess en hilo de trabajo) ---------------
    def _fw_log(self, text: str) -> None:
        try:
            self.query_one("#screen-firmware", BombercatScreen).log(text)
        except Exception:
            pass

    @work(thread=True, exclusive=True, group="fw")
    def bombercat_fw_list_ui(self) -> None:
        self._fw_refresh_inline()

    @work(thread=True, exclusive=True, group="fw")
    def bombercat_add_source_ui(self, ref: str) -> None:
        from ..integrations import firmware_sources as fs
        try:
            src = fs.add_source(ref)
            paths = fs.download_source(src, progress=lambda m: self.call_from_thread(
                self._fw_log, f"[dim]{m}[/]"))
        except Exception as e:  # noqa: BLE001
            self.call_from_thread(self._fw_log, f"[red]Fuente falló: {e}[/]")
            return
        self.call_from_thread(self._fw_log,
                              f"[green]{src.name}: {len(paths)} .uf2 descargado(s).[/]")
        self._fw_refresh_inline()

    @work(thread=True, exclusive=True, group="fw")
    def bombercat_clean_ui(self, target) -> None:
        from ..integrations import firmware_sources as fs
        try:
            n = fs.clean_cache(target)
        except Exception as e:  # noqa: BLE001
            self.call_from_thread(self._fw_log, f"[red]Limpieza falló: {e}[/]")
            return
        self.call_from_thread(self._fw_log, f"[green]{n} archivo(s) eliminado(s).[/]")
        self._fw_refresh_inline()

    @work(thread=True, exclusive=True, group="fw")
    def bombercat_compile_ui(self, sketch_dir: str, flash_after: bool,
                             port: str | None = None) -> None:
        from rich.markup import escape
        from ..integrations import arduino as ard
        if not ard.arduino_cli_available():
            self.call_from_thread(self._fw_log,
                                  "[red]Falta arduino-cli (instálalo para compilar).[/]")
            return
        try:
            cp = ard.compile_sketch(sketch_dir)
        except Exception as e:  # noqa: BLE001
            self.call_from_thread(self._fw_log, f"[red]Compilación falló: {e}[/]")
            return
        out = (cp.stdout or "") + (("\n" + cp.stderr) if cp.stderr else "")
        self.call_from_thread(self._fw_log, escape(out.strip()[-1500:]) or "(sin salida)")
        if cp.returncode != 0:
            self.call_from_thread(self._fw_log, f"[red]✗ compilación rc={cp.returncode}[/]")
            return
        uf2 = ard.latest_uf2(sketch_dir)
        self.call_from_thread(self._fw_log,
                              f"[green]✔ compilado: {uf2}[/]" if uf2 else "[green]✔ compilado[/]")
        self._fw_refresh_inline()
        if not flash_after:
            return
        # Tu firmware sube por picotool (arduino-cli upload), NO por .uf2: el
        # flasheo .uf2 de bombercat-tools es solo para las imágenes oficiales.
        self.call_from_thread(self._fw_log, "[yellow]⚠ subiendo por picotool (arduino-cli)…[/]")
        try:
            up = ard.upload_sketch(sketch_dir, port=port)
        except Exception as e:  # noqa: BLE001
            self.call_from_thread(self._fw_log, f"[red]Subida falló: {e}[/]")
            return
        uout = (up.stdout or "") + (("\n" + up.stderr) if up.stderr else "")
        self.call_from_thread(self._fw_log, escape(uout.strip()[-1500:]) or "(sin salida)")
        ok = up.returncode == 0
        self.call_from_thread(self._fw_log,
                              "[green]✔ Subida OK[/]" if ok
                              else f"[red]✗ Subida falló (rc={up.returncode})[/]")

    def _flash_inline(self, name: str, port: str | None) -> None:
        """Flashea (en el hilo del worker) y registra el resultado."""
        from rich.markup import escape
        from ..integrations import bombercat_tools as bt
        try:
            cp = bt.flash_capture(name, port=port)
        except Exception as e:  # noqa: BLE001
            self.call_from_thread(self._fw_log, f"[red]Flasheo falló: {e}[/]")
            return
        out = (cp.stdout or "") + (("\n" + cp.stderr) if cp.stderr else "")
        self.call_from_thread(self._fw_log, escape(out.strip()) or "(sin salida)")
        ok = cp.returncode == 0
        self.call_from_thread(self._fw_log,
                              f"[green]✔ Flasheo de {name} OK[/]" if ok
                              else f"[red]✗ Flasheo de {name} falló (rc={cp.returncode})[/]")
        self.call_from_thread(self.notify, f"Firmware {name}: {'OK' if ok else 'error'}",
                              severity=("information" if ok else "error"))

    def _fw_refresh_inline(self) -> None:
        """Recalcula la lista (release + descargados + locales) en el hilo del worker."""
        from ..integrations import bombercat_tools as bt
        from ..integrations import firmware_sources as fs
        from .screens.firmware import discover_local_uf2
        try:
            names = bt.fw_list_names()
        except Exception as e:  # noqa: BLE001
            names = []
            self.call_from_thread(self._fw_log, f"[red]No se pudo listar el release: {e}[/]")
        items = [(f"📦 {n}", n) for n in names]
        for p in fs.cached_firmwares():
            items.append((f"⬇ {p.name}  [dim]{p.parent.name}/ (descargado)[/]", str(p)))
        for p in discover_local_uf2():
            items.append((f"🛠 {p.name}  [dim]{p.parent.name}/ (local)[/]", str(p)))
        self.call_from_thread(
            lambda: self.query_one("#screen-firmware", BombercatScreen).set_firmwares(items))

    @work(thread=True, exclusive=True, group="fw")
    def bombercat_flash_ui(self, name: str, port: str | None = None) -> None:
        self._flash_inline(name, port)

    @work(thread=True, exclusive=True, group="fw")
    def bombercat_devices_ui(self) -> None:
        from rich.markup import escape
        from ..integrations import bombercat_tools as bt
        try:
            txt = bt.devices_text()
        except Exception as e:  # noqa: BLE001
            self.call_from_thread(self._fw_log, f"[red]{e}[/]")
            return
        self.call_from_thread(self._fw_log, escape(txt.strip()) or "(sin dispositivos)")

    @work(thread=True, exclusive=True, group="fw")
    def bombercat_setup_ui(self) -> None:
        from ..integrations import bombercat_tools as bt
        try:
            bt.ensure_venv(log=lambda m: self.call_from_thread(self._fw_log, f"[dim]{m}[/]"))
            self.call_from_thread(self._fw_log, "[green]venv de bombercat-tools listo.[/]")
            self.call_from_thread(
                lambda: self.query_one("#screen-firmware", BombercatScreen)._update_status())
        except Exception as e:  # noqa: BLE001
            self.call_from_thread(self._fw_log, f"[red]setup falló: {e}[/]")

    @work(thread=True, exclusive=True, group="fw")
    def bombercat_setup_env_ui(self) -> None:
        """Permisos USB (reglas udev + grupos) via bombercat-tools setup-env,
        elevado con pkexec. Resuelve fallos de picotool/serie."""
        from ..integrations import bombercat_tools as bt
        try:
            cp = bt.setup_env_gui()
            out = (cp.stdout or "") + (cp.stderr or "")
            self.call_from_thread(self._fw_log, escape(out.strip()) or "(sin salida)")
            ok = cp.returncode == 0
            self.call_from_thread(
                self._fw_log,
                "[green]Permisos aplicados. Reconecta el BomberCat.[/]" if ok
                else f"[red]setup-env devolvió returncode {cp.returncode}.[/]")
        except Exception as e:  # noqa: BLE001
            self.call_from_thread(self._fw_log, f"[red]permisos USB: {e}[/]")

    # -- ISO 8583: envío a un host (hilo de trabajo) -----------------------
    @work(thread=True, exclusive=True, group="iso")
    def send_iso8583_ui(self, host: str, port: str, data: bytes, header: str) -> None:
        from ..payments import iso_host
        try:
            resp = iso_host.send_message(host, int(port), data,
                                         header=int(header), timeout=8.0)
        except Exception as e:  # noqa: BLE001
            self.call_from_thread(self.notify, f"ISO host: {e}", severity="error")
            return
        self.call_from_thread(self._on_iso_resp, resp)

    def _on_iso_resp(self, resp: bytes) -> None:
        try:
            self.query_one("#screen-iso8583", Iso8583Screen).show_response(resp)
        except Exception:
            pass
        self.notify(f"ISO 8583: respuesta de {len(resp)} bytes.")


def run() -> int:
    EmvyApp().run()
    return 0

