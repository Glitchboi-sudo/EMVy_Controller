"""Página de inicio de EMVy Controller: un centro de operaciones (cockpit), no un
documento. Muestra el estado del entorno (lector · tarjeta · captura), sugiere la
siguiente acción, lista proyectos recientes y ofrece acciones rápidas y creación
de proyecto — todo orientado al flujo de un pentest.

El **modelo** (`build_model`) es puro y testeable: recibe primitivas y devuelve un
`DashboardModel`. El widget lo renderiza y añade la interacción (activar/crear
proyecto, acciones rápidas). Rediseño descrito en TODO.md (§§6–27).
"""
from __future__ import annotations

from dataclasses import dataclass

from textual import on
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Button, DataTable, Input, Static

from ... import __version__
from ...project import store
from ..widgets.copyable import CopyableDataTable

# Estados accesibles: símbolo + texto (nunca solo color).
OK, OFF, WARN, ERR = "●", "○", "!", "×"


@dataclass(frozen=True)
class Panel:
    symbol: str          # ● ○ ! ×
    state: str           # etiqueta de estado ("Conectado", "Sin tarjeta"…)
    lines: tuple[str, ...] = ()   # detalle adicional


@dataclass(frozen=True)
class DashboardModel:
    version: str
    project_name: str | None
    var_count: int
    capture_count: int
    reader: Panel
    card: Panel
    capture: Panel
    next_text: str
    next_keys: str
    next_action: str = ""      # id de destino: "tab-proj"/"tab-rdr"/"capture"/"tab-fuzz"…
    next_label: str = ""       # etiqueta del botón de acción
    last_activity: str | None = None


def build_model(*, project_name: str | None, var_count: int, capture_count: int,
                reader_name: str | None, reader_backend: str | None,
                reader_caps: str | None, card_atr: str | None,
                capture_apps: int | None, capture_blobs: int | None,
                last_activity: str | None = None) -> DashboardModel:
    """Deriva el modelo del dashboard desde el estado de sesión (puro)."""
    if reader_name:
        reader = Panel(OK, "Conectado", (reader_name, (reader_backend or "").upper()))
    else:
        reader = Panel(OFF, "Desconectado", ("Pulsa L para conectar",))

    if not reader_name:
        card = Panel(OFF, "Sin lector", ())
    elif card_atr:
        card = Panel(OK, "Detectada", (reader_caps or "chip",))
    else:
        card = Panel(OFF, "Sin tarjeta", ("Presenta una tarjeta",))

    if capture_apps is not None:
        capture = Panel(OK, "Disponible",
                        (f"{capture_apps} app(s) · {capture_blobs or 0} blobs",))
    else:
        extra = (f"{capture_count} guardada(s) en el proyecto",) if capture_count else ()
        capture = Panel(OFF, "Sin captura", extra)

    if not project_name:
        nxt, keys, act, lbl = "Crea o selecciona un proyecto.", "P", "tab-proj", "Ir a Proyectos"
    elif not reader_name:
        nxt, keys, act, lbl = "Conecta un lector para continuar.", "L", "tab-rdr", "Conectar lector"
    elif not card_atr:
        nxt, keys, act, lbl = "Presenta una tarjeta al lector.", "L", "tab-rdr", "Ir a Lectores"
    elif capture_apps is None:
        nxt, keys, act, lbl = "Abre el Explorador e inicia una captura.", "E", "capture", "Capturar tarjeta"
    else:
        nxt, keys, act, lbl = "Revisa la captura o busca flags.", "E / F", "tab-fuzz", "Ir a Fuzzing"

    return DashboardModel(
        version=__version__, project_name=project_name,
        var_count=var_count, capture_count=capture_count,
        reader=reader, card=card, capture=capture,
        next_text=nxt, next_keys=keys, next_action=act, next_label=lbl,
        last_activity=last_activity,
    )


_SAFETY = (
    f"[$warning]{WARN}[/] [b]Uso autorizado de laboratorio[/]  ·  "
    "tarjetas propias/de lab  ·  sin transacciones fraudulentas"
)


class DashboardScreen(VerticalScroll):
    """Centro de operaciones de EMVy Controller (orientado a estado + acciones)."""

    DEFAULT_CSS = """
    DashboardScreen { padding: 1 1; }
    DashboardScreen .dash-title { text-style: bold; color: $text; padding: 0; }
    DashboardScreen .dash-sub   { color: $text-muted; padding: 0 0 1 0; }
    DashboardScreen .dash-label {
        text-style: bold; color: $text-muted; padding: 1 0 0 0;
    }
    /* fila de tarjetas de estado (proyecto/lector/tarjeta) */
    DashboardScreen #dash-env { height: auto; }
    DashboardScreen #dash-env Static {
        width: 1fr; border: round $primary; background: $panel;
        padding: 0 1; margin: 0 1 0 0; height: auto;
    }
    /* tarjeta hero: siguiente acción */
    DashboardScreen #dash-next-row {
        border: round $accent; background: $accent-muted;
        padding: 0 1; height: auto; margin: 0 0 1 0;
    }
    DashboardScreen #dash-next { width: 1fr; padding: 0 1 0 0; }
    DashboardScreen #dash-next-btn { min-width: 20; margin: 0; }
    DashboardScreen #dash-project {
        border: round $primary; background: $panel; padding: 0 1; height: auto;
    }
    DashboardScreen #dash-recent { height: auto; max-height: 9; margin: 0 0 1 0; }
    DashboardScreen .dash-actions { height: auto; padding: 1 0 0 0; }
    DashboardScreen .dash-actions Button { margin: 0 1 0 0; min-width: 8; }
    DashboardScreen .dash-newrow { height: auto; padding: 1 0 0 0; }
    DashboardScreen .dash-newrow Input { width: 1fr; margin: 0 1 0 0; }
    DashboardScreen #dash-safety { color: $text-muted; padding: 1 0 0 0; }
    """

    def compose(self):
        yield Static(id="dash-header", classes="dash-title")
        yield Static("EMV security testing & card exploration", classes="dash-sub")

        yield Static("PROYECTO ACTIVO", classes="dash-label")
        yield Static(id="dash-project")

        yield Static("ENTORNO", classes="dash-label")
        with Horizontal(id="dash-env"):
            yield Static(id="dash-reader", classes="dash-panel")
            yield Static(id="dash-card", classes="dash-panel")
            yield Static(id="dash-capture", classes="dash-panel")

        yield Static("SIGUIENTE ACCIÓN", classes="dash-label")
        with Horizontal(id="dash-next-row"):
            yield Static(id="dash-next")
            yield Button("Continuar", id="dash-next-btn", variant="success")

        yield Static("PROYECTOS RECIENTES", classes="dash-label")
        yield CopyableDataTable(id="dash-recent")
        with Horizontal(classes="dash-newrow"):
            yield Input(placeholder="nombre del nuevo proyecto…", id="dash-new-name")
            yield Input(placeholder="ruta (opcional)", id="dash-new-path")
            yield Button("Crear", id="dash-new-btn", variant="success")

        yield Static("ACCIONES RÁPIDAS", classes="dash-label")
        with Horizontal(classes="dash-actions"):
            yield Button("Lectores", id="dash-qa-reader", variant="primary")
            yield Button("Capturar", id="dash-qa-capture", variant="success")
            yield Button("Consola", id="dash-qa-console")
            yield Button("Flags", id="dash-qa-flags")
            yield Button("PoCs", id="dash-qa-pocs")

        yield Static(_SAFETY, id="dash-safety")

    def on_mount(self) -> None:
        t = self.query_one("#dash-recent", DataTable)
        t.add_columns("", "proyecto", "tipo", "info")
        t.cursor_type = "row"
        self._recent: list[tuple[str, object]] = []   # (name, path|None)
        self.reload()

    # -- render de un panel de entorno (símbolo + estado + detalle) ---------
    @staticmethod
    def _panel_text(title: str, p: Panel) -> str:
        color = {OK: "$success", OFF: "$text-muted", WARN: "$warning", ERR: "$error"}[p.symbol]
        head = f"[b]{title}[/]\n[{color}]{p.symbol}[/] {p.state}"
        detail = "\n".join(f"[$text-muted]{ln}[/]" for ln in p.lines if ln)
        return f"{head}\n{detail}" if detail else head

    def reload(self) -> None:
        """Recolecta el estado de sesión y repinta el dashboard."""
        app = self.app
        proj = store.active_project()
        var_count = capture_count = 0
        if proj:
            try:
                var_count = len(store.load_project_variables(proj))
                capture_count = len(store.list_captures(proj))
            except Exception:
                pass

        dev = getattr(app, "reader_device", None)
        dump = getattr(app, "last_dump", None)
        model = build_model(
            project_name=store.active_label() if proj else None,
            var_count=var_count, capture_count=capture_count,
            reader_name=(dev.name if dev else None),
            reader_backend=(dev.backend if dev else None),
            reader_caps=(dev.caps_str if dev else None),
            card_atr=getattr(app, "card_atr", None),
            capture_apps=(len(dump.applications) if dump else None),
            capture_blobs=(len(dump.blobs) if dump else None),
            last_activity=self._last_activity(app),
        )
        self._paint(model)
        self._paint_recent(proj)

    @staticmethod
    def _last_activity(app) -> str | None:
        reader = getattr(app, "reader", None)
        trace = getattr(reader, "trace", None) if reader else None
        if not trace:
            return None
        ev = trace[-1]
        cmd = getattr(ev, "command", "")
        sw = getattr(ev, "sw", "")
        head = (cmd[:14] + "…") if len(cmd) > 14 else cmd
        return f"{head} → {sw}"

    def _paint(self, m: DashboardModel) -> None:
        def up(sid: str, text: str):
            try:
                self.query_one("#" + sid, Static).update(text)
            except Exception:
                pass

        up("dash-header", f"EMVy Controller   [$text-muted]v{m.version}[/]")
        if m.project_name:
            up("dash-project",
               f"[b]{m.project_name}[/]\n"
               f"[$text-muted]Activo · {m.var_count} variables · {m.capture_count} capturas[/]")
        else:
            up("dash-project",
               "[b]Sin proyecto seleccionado[/]\n"
               "[$text-muted]Crea uno abajo o pulsa P[/]")
        up("dash-reader", self._panel_text("LECTOR", m.reader))
        up("dash-card", self._panel_text("TARJETA", m.card))
        up("dash-capture", self._panel_text("CAPTURA", m.capture))

        nxt = f"{m.next_text}   [b][{m.next_keys}][/]"
        if m.last_activity:
            nxt = f"[$text-muted]Última actividad: {m.last_activity}[/]\n{nxt}"
        up("dash-next", nxt)
        self._next_action = m.next_action
        try:
            self.query_one("#dash-next-btn", Button).label = m.next_label or "Continuar"
        except Exception:
            pass

    def _paint_recent(self, active) -> None:
        t = self.query_one("#dash-recent", DataTable)
        t.clear()
        self._recent = []
        active_rp = active.path.resolve() if active else None
        xdg_paths = {p.path.resolve() for p in store.list_projects()}
        for p in store.recent_projects(limit=6):
            rp = p.path.resolve()
            is_xdg = rp in xdg_paths
            mark = "●" if active_rp and rp == active_rp else ""
            try:
                info = f"{len(store.load_project_variables(p))} vars · {len(store.list_captures(p))} capt."
            except Exception:
                info = ""
            t.add_row(mark, p.name, "XDG" if is_xdg else "engagement", info)
            self._recent.append((p.name, None if is_xdg else p.path))
        if not self._recent:
            t.add_row("", "(sin proyectos)", "", "crea uno abajo ↓")

    # -- interacción: activar / crear proyecto ------------------------------
    def _activate(self, entry) -> None:
        name, path = entry
        try:
            store.set_active_path(path) if path is not None else store.set_active(name)
        except Exception as e:
            self.app.notify(str(e), severity="error")
            return
        self.app.refresh_ui()
        self.app.notify(f"Proyecto activo: {store.active_label()}")

    @on(DataTable.RowSelected, "#dash-recent")
    def _row_selected(self, event) -> None:
        idx = event.cursor_row
        if 0 <= idx < len(self._recent):
            self._activate(self._recent[idx])

    @on(Button.Pressed, "#dash-new-btn")
    @on(Input.Submitted, "#dash-new-name")
    def _new_project(self, _event=None) -> None:
        inp = self.query_one("#dash-new-name", Input)
        name = inp.value.strip()
        path = self.query_one("#dash-new-path", Input).value.strip()
        if not name and not path:
            self.app.notify("Indica un nombre (o una ruta).", severity="warning")
            return
        try:
            if path:                                   # elige dónde: proyecto en ruta
                p = store.create_project_at(path, name=name or None)
                store.set_active_path(p.path)
            else:                                      # XDG por defecto
                store.create_project(name)
                store.set_active(name)
        except Exception as e:
            self.app.notify(str(e), severity="error")
            return
        inp.value = ""
        self.query_one("#dash-new-path", Input).value = ""
        self.app.refresh_ui()
        self.app.notify(f"Proyecto creado y activado: {store.active_label()}")

    # -- botón "siguiente acción" (ejecuta el paso sugerido) ----------------
    @on(Button.Pressed, "#dash-next-btn")
    def _do_next(self) -> None:
        act = getattr(self, "_next_action", "")
        if act == "capture":
            self.app.action_show("tab-exp")
            self.app.capture_card_ui()
        elif act:
            self.app.action_show(act)

    # -- acciones rápidas ---------------------------------------------------
    @on(Button.Pressed, "#dash-qa-reader")
    def _qa_reader(self) -> None:
        self.app.action_show("tab-rdr")

    @on(Button.Pressed, "#dash-qa-capture")
    def _qa_capture(self) -> None:
        self.app.action_show("tab-exp")
        self.app.capture_card_ui()

    @on(Button.Pressed, "#dash-qa-console")
    def _qa_console(self) -> None:
        # la consola APDU vive embebida en el Explorador (Collapsible "en vivo")
        self.app.action_show("tab-exp")

    @on(Button.Pressed, "#dash-qa-flags")
    def _qa_flags(self) -> None:
        self.app.action_tool("tool-flags")

    @on(Button.Pressed, "#dash-qa-pocs")
    def _qa_pocs(self) -> None:
        self.app.action_show("tab-poc")
