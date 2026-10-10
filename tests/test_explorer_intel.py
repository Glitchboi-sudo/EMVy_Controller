"""Smoke tests de la Feature 2 en las UIs: identidad de tarjeta + sección INTEL
en el Explorador (TUI y GUI). No añaden pestañas: todo vive dentro del
Explorador existente."""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from fakecard import AID  # noqa: E402

from emvy.session.model import CardDump  # noqa: E402


def _dump():
    rec = "700E" + "8E0C" + "00000000000000001F000103" + "9F36020031"
    return CardDump(
        atr="3B00", reader="test",
        applications=[{
            "aid": AID, "scheme": "Mastercard", "source": "ppse", "label": "LAB",
            "cardholder": {"pan": "4761739001010010"},
            "aip": "1980", "afl": "08010100",
            "records": [{"sfi": 1, "record": 1, "hex": rec}],
            "get_data": {"9F36": "0005", "9F17": "03"},
        }],
        blobs=[{"source": f"{AID}:FCI", "hex": "6F0B8407A0000000041010A500"}],
    )


@pytest.fixture
def xdg(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    return tmp_path


# --- TUI ----------------------------------------------------------------------
def test_tui_explorer_identity_and_intel(xdg):
    pytest.importorskip("textual")
    import asyncio

    from textual.widgets import Static

    from emvy.project import store
    from emvy.tui.app import EmvyApp

    async def scenario():
        store.create_project("lab")
        store.set_active("lab")
        app = EmvyApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            exp = app.query_one("#screen-explorer")
            exp.show_dump(_dump())
            await pilot.pause()

            ident = app.query_one("#exp_identity", Static)
            assert AID[:8] not in str(ident.content)  # lo relevante es el hash
            assert "Vista 1 vez" in str(ident.content)
            assert "Mastercard" in str(ident.content)

            # la tabla INTEL se repuebla con la tarjeta registrada
            from emvy.tui.widgets.copyable import CopyableDataTable
            table = app.query_one("#exp_intel_table", CopyableDataTable)
            assert table.row_count == 1
            row = table.get_row_at(0)
            assert "Mastercard" in str(row[1])

            # segunda captura: la identidad cuenta 2 veces
            exp.show_dump(_dump())
            await pilot.pause()
            assert "Vista 2 veces" in str(ident.content)

            # recomendaciones: modal con el top-N (y se cierra con escape)
            exp._intel_recs()
            await pilot.pause()
            from emvy.tui.screens.intelrecs import IntelRecsScreen
            assert isinstance(app.screen, IntelRecsScreen)
            await pilot.press("escape")
            await pilot.pause()

    asyncio.run(scenario())


def test_tui_explorer_identity_sin_proyecto(xdg):
    pytest.importorskip("textual")
    import asyncio

    from textual.widgets import Static

    from emvy.tui.app import EmvyApp

    async def scenario():
        app = EmvyApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            exp = app.query_one("#screen-explorer")
            exp.show_dump(_dump())
            await pilot.pause()
            ident = app.query_one("#exp_identity", Static)
            text = str(ident.content)
            assert "Sin proyecto activo" in text
            assert "…" in text                    # hash corto aun así
            # sin proyecto el botón de recomendaciones avisa, sin explotar
            exp._intel_recs()
            await pilot.pause()

    asyncio.run(scenario())


# --- GUI ----------------------------------------------------------------------
def test_gui_explorer_identity_and_intel():
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    qapp = QApplication.instance() or QApplication([])

    import tempfile
    from emvy import settings
    with tempfile.TemporaryDirectory() as td:
        os.environ["XDG_DATA_HOME"] = f"{td}/data"
        os.environ["XDG_CONFIG_HOME"] = f"{td}/config"
        settings.apply(settings.load())
        from emvy.gui.app import MainWindow
        from emvy.project import store
        win = MainWindow()
        try:
            # sin proyecto: hash + nota, tabla vacía, sin explotar
            win.explorer_panel.show_dump(_dump())
            assert "Sin proyecto activo" in win.explorer_panel._identity.text()
            assert win.explorer_panel._intel_table.rowCount() == 0
            win.explorer_panel._intel_recs()   # avisa por notify, no bloquea

            # con proyecto: upsert + tabla INTEL poblada
            store.create_project("lab")
            store.set_active("lab")
            win.explorer_panel.show_dump(_dump())
            assert "Vista 1 vez" in win.explorer_panel._identity.text()
            assert win.explorer_panel._intel_table.rowCount() == 1
            assert "Mastercard" in win.explorer_panel._intel_table.item(0, 1).text()

            # recomendaciones: diálogo (exec mockeado para no bloquear headless)
            from emvy.gui.panels import explorer as exmod
            orig_exec = exmod.QDialog.exec
            exmod.QDialog.exec = lambda self: 0
            try:
                win.explorer_panel._intel_recs()
            finally:
                exmod.QDialog.exec = orig_exec
        finally:
            win.close()
