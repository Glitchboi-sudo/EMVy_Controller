"""Modal de ayuda: atajos de teclado agrupados + flujo sugerido de un pentest.

Se abre con `?` desde cualquier pestaña y se cierra con `escape`, `?` o `q`. Se
mantiene aquí (no en el footer, que se saturaba) toda la lista de atajos; el
footer sólo muestra los esenciales.
"""
from __future__ import annotations

from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

_SECTIONS = (
    ("Navegación (pestañas)", (
        ("p", "Proyectos"), ("v", "Variables"), ("l", "Lectores"),
        ("e", "Explorador (captura + consola APDU)"), ("b", "Cobros"),
        ("o", "PoC"), ("i", "Intercept"), ("m", "BomberCat"), ("u", "Fuzzing"),
    )),
    ("Herramientas (pestaña Consola)", (
        ("f", "Flags — busca flags en la última captura"),
        ("8", "ISO 8583 — constructor + traducción + envío"),
        ("w", "Escritura — UPDATE RECORD/BINARY, PUT DATA…"),
        ("s", "Sesiones — grabaciones APDU del proyecto (ver / replay)"),
    )),
    ("Copiar al portapapeles", (
        ("Ctrl+C", "copia: nodo del árbol · fila de tabla · selección de texto"),
        ("arrastra", "en paneles de texto (consola, ISO, flags): selecciona y Ctrl+C"),
    )),
    ("General", (
        ("r", "Refrescar"), ("?", "Esta ayuda"), ("q", "Salir"),
    )),
)

_FLOW = (
    "1. Crea/activa un proyecto  (p)",
    "2. Conecta un lector  (l)",
    "3. Abre el Explorador y captura la tarjeta  (e)",
    "4. Analiza la captura o busca flags  (e · f)",
    "5. Prueba terminales con Fuzzing  (u)",
)


class HelpScreen(ModalScreen):
    """Superposición modal con la referencia de atajos."""

    BINDINGS = [
        Binding("escape", "dismiss", "Cerrar"),
        Binding("question_mark", "dismiss", "Cerrar"),
        Binding("q", "dismiss", "Cerrar"),
    ]

    DEFAULT_CSS = """
    HelpScreen { align: center middle; }
    HelpScreen > VerticalScroll {
        width: 78; max-width: 96%; height: auto; max-height: 90%;
        background: $surface; border: thick $accent; padding: 1 2;
    }
    HelpScreen .help-title { text-style: bold; color: $accent; }
    HelpScreen .help-sub { color: $text-muted; padding: 0 0 1 0; }
    HelpScreen .help-h {
        text-style: bold; color: $accent; padding: 1 0 0 0;
    }
    HelpScreen .help-row { height: auto; }
    HelpScreen .help-foot { color: $text-muted; padding: 1 0 0 0; }
    """

    def compose(self):
        with VerticalScroll():
            yield Static("EMVy Controller — Ayuda", classes="help-title")
            yield Static("Atajos de teclado y flujo de trabajo", classes="help-sub")
            for header, rows in _SECTIONS:
                yield Static(header, classes="help-h")
                for key, desc in rows:
                    yield Static(f"  [b cyan]{key:<8}[/] {desc}", classes="help-row")
            yield Static("Flujo sugerido", classes="help-h")
            for step in _FLOW:
                yield Static(f"  [green]{step}[/]", classes="help-row")
            yield Static("Pulsa escape, ? o q para cerrar.", classes="help-foot")
