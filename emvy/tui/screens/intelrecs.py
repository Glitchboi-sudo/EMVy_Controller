"""Modal de recomendaciones de ataques para una tarjeta (inteligencia del proyecto).

Se abre desde el Explorador (botón «Recomendaciones» de la sección INTEL) con
el top-N del recomendador puro (`core.intel.recommend`) sobre el hash mostrado.
"""
from __future__ import annotations

from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static


class IntelRecsScreen(ModalScreen):
    """Top-N de ataques recomendados: id, título, razón y notas (relay/COMBO)."""

    BINDINGS = [
        Binding("escape", "dismiss", "Cerrar"),
        Binding("q", "dismiss", "Cerrar"),
    ]

    DEFAULT_CSS = """
    IntelRecsScreen { align: center middle; }
    IntelRecsScreen > VerticalScroll {
        width: 84; max-width: 96%; height: auto; max-height: 90%;
        background: $surface; border: thick $accent; padding: 1 2;
    }
    IntelRecsScreen .rec-title { text-style: bold; color: $accent; }
    IntelRecsScreen .rec-sub { color: $text-muted; padding: 0 0 1 0; }
    IntelRecsScreen .rec-item { padding: 1 0 0 0; }
    IntelRecsScreen .rec-reason { color: $text-muted; }
    IntelRecsScreen .rec-note { color: $warning; }
    """

    def __init__(self, hash_prefix: str, recommendations, title: str = "") -> None:
        super().__init__()
        self._hash_prefix = hash_prefix
        self._recs = list(recommendations)
        self._title = title or "Recomendaciones"

    def compose(self):
        with VerticalScroll():
            yield Static(self._title, classes="rec-title")
            yield Static(f"tarjeta {self._hash_prefix}… — ordenadas por prioridad "
                         "(parciales primero, luego casan con el perfil)",
                         classes="rec-sub")
            if not self._recs:
                yield Static("[dim]Sin recomendaciones para esta tarjeta.[/]")
            for i, r in enumerate(self._recs, 1):
                tried = ""
                if r.tried is not None:
                    tried = f"  [yellow](previo: {r.tried.result})[/]"
                yield Static(f"{i}. [b cyan]{r.attack_id}[/]  [b]{r.title}[/]{tried}",
                             classes="rec-item")
                yield Static(f"   {r.reason}", classes="rec-reason")
                notes = []
                if r.requires_relay:
                    notes.append("requiere relay NFC — EMVy aún no lo integra")
                if r.combo:
                    notes.append(f"COMBO: {r.combo}")
                if notes:
                    yield Static("   ⚠ " + " · ".join(notes), classes="rec-note")
