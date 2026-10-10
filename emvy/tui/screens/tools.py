"""Pestaña 'Consola': agrupa las herramientas de entrada→salida que comparten la
misma forma (patrón/mensaje → log): **Flags** (búsqueda sobre la última
captura), **ISO 8583** (constructor + envío) y **Escritura**. La consola APDU
cruda vive en el Explorador (dentro de su `Collapsible` "Consola APDU en
vivo"), junto a la captura que la necesita — ver `explorer.py`.

Cada sub-panel sigue siendo su propio widget autónomo (mismos ids que antes:
`#screen-flags`, `#screen-iso8583`), así que la app los sigue encontrando
igual; aquí solo se agrupan bajo un `TabbedContent` interno.
"""
from __future__ import annotations

from textual.containers import Vertical
from textual.widgets import TabbedContent, TabPane

from .flags import FlagsScreen
from .iso8583 import Iso8583Screen
from .sessions import SessionsScreen
from .write import WriteScreen


class ToolsScreen(Vertical):
    def compose(self):
        with TabbedContent(initial="tool-flags", id="tools-tabs"):
            with TabPane("Flags", id="tool-flags"):
                yield FlagsScreen(id="screen-flags")
            with TabPane("ISO 8583", id="tool-iso"):
                yield Iso8583Screen(id="screen-iso8583")
            with TabPane("Escritura", id="tool-write"):
                yield WriteScreen(id="screen-write")
            with TabPane("Sesiones", id="tool-sessions"):
                yield SessionsScreen(id="screen-sessions")

    def show_tool(self, tab_id: str) -> None:
        try:
            self.query_one("#tools-tabs", TabbedContent).active = tab_id
        except Exception:
            pass
