"""Pestaña 'Sesiones': grabaciones APDU del proyecto activo.

Lista las sesiones guardadas por el recorder (`-R/--record` o `SessionRecorder`),
permite ver su detalle con el APDU printer en un modal, y reproducirlas contra
la tarjeta conectada (worker en hilo, patrón `capture_card_ui`).
"""
from __future__ import annotations

from textual import on, work
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Static

from ...core import apduprint
from ...project import store
from ...session.recorder import list_sessions, load_session, replay_session
from ..widgets.copyable import CopyableDataTable


class SessionViewScreen(ModalScreen):
    """Modal con el intercambio completo (comando+respuesta) de una sesión."""

    BINDINGS = [
        Binding("escape", "dismiss", "Cerrar"),
        Binding("q", "dismiss", "Cerrar"),
    ]

    DEFAULT_CSS = """
    SessionViewScreen { align: center middle; }
    SessionViewScreen > VerticalScroll {
        width: 110; max-width: 96%; height: auto; max-height: 90%;
        background: $surface; border: thick $accent; padding: 1 2;
    }
    SessionViewScreen .det-title { text-style: bold; color: $accent; }
    SessionViewScreen .det-meta { color: $text-muted; padding: 0 0 1 0; }
    SessionViewScreen .det-ex { padding: 1 0 0 0; }
    """

    def __init__(self, session, title: str = "") -> None:
        super().__init__()
        self._session = session
        self._title = title

    def compose(self):
        s = self._session
        with VerticalScroll():
            yield Static(self._title or f"Sesión {s.sid}", classes="det-title")
            meta = (f"inicio={s.started or '?'}"
                    + (f"  cierre={s.closed}" if s.closed else "  (sin cerrar)")
                    + (f"  lector={s.reader}" if s.reader else "")
                    + (f"  ATR={s.atr}" if s.atr else ""))
            yield Static(meta, classes="det-meta")
            for i, ex in enumerate(s.exchanges):
                cat = apduprint.sw_category(ex.response.sw1, ex.response.sw2)
                color = {"ok": "green", "warning": "yellow", "info": "cyan"}.get(
                    cat, "red")
                body = apduprint.format_exchange(ex)
                yield Static(f"── #{i + 1}  [{ex.response.sw_hex}] ──\n{body}",
                             classes=f"det-ex {color}")


class SessionsScreen(Vertical):
    """Lista de sesiones grabadas en el proyecto activo."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._paths: list = []

    def compose(self):
        yield Label("Sesiones grabadas del proyecto", classes="title")
        with Horizontal(classes="row"):
            yield Button("Refrescar", id="ses_refresh", variant="primary")
            yield Button("Ver", id="ses_view")
            yield Button("Reproducir", id="ses_replay")
        yield CopyableDataTable(id="ses_table")

    def on_mount(self) -> None:
        table = self.query_one("#ses_table", CopyableDataTable)
        table.add_columns("sid", "inicio", "intercambios", "criptogramas")
        self.refresh_sessions()

    def refresh_sessions(self) -> None:
        table = self.query_one("#ses_table", CopyableDataTable)
        table.clear()
        self._paths = []
        proj = store.active_project()
        if not proj:
            self.notify("Sin proyecto activo: activa uno en Proyectos.", severity="warning")
            return
        from ...core import sessionlog
        for path in list_sessions(proj):
            try:
                s = load_session(path)
            except Exception:
                continue
            n_crypto = len(sessionlog.extract_cryptograms(s))
            table.add_row(s.sid, s.started or "?", str(len(s.exchanges)),
                          str(n_crypto) if n_crypto else "")
            self._paths.append(s)

    def _selected(self):
        table = self.query_one("#ses_table", CopyableDataTable)
        if table.row_count == 0 or table.cursor_row >= len(self._paths):
            self.notify("Selecciona una sesión de la tabla.", severity="warning")
            return None
        return self._paths[table.cursor_row]

    @on(Button.Pressed, "#ses_refresh")
    def _on_refresh(self) -> None:
        self.refresh_sessions()

    @on(Button.Pressed, "#ses_view")
    def _on_view(self) -> None:
        s = self._selected()
        if s is not None:
            self.app.push_screen(SessionViewScreen(s))

    @on(Button.Pressed, "#ses_replay")
    def _on_replay(self) -> None:
        s = self._selected()
        if s is not None:
            self._replay(s)

    @work(thread=True, exclusive=True, group="card")
    def _replay(self, session) -> None:
        app = self.app
        if not getattr(app, "reader", None) or not app.reader.transceive:
            self.app.call_from_thread(
                app.notify, "Conecta un lector primero (pestaña Lectores).",
                severity="warning")
            return
        try:
            send = app.active_send()
            new = replay_session(session, send)
        except Exception as e:  # noqa: BLE001
            self.app.call_from_thread(app.notify, f"Replay falló: {e}", severity="error")
            return
        from ...core.sessionlog import LogSession
        replayed = LogSession(sid=session.sid, started=session.started,
                              closed=session.closed, reader=session.reader,
                              atr=session.atr, exchanges=tuple(new))
        self.app.call_from_thread(
            app.push_screen,
            SessionViewScreen(replayed, title=f"Replay de {session.sid}"))
