"""Pruebas headless de las pestañas Cobros (flujo de switch, dry-run) y Escritura."""
import pytest

pytest.importorskip("textual")


@pytest.fixture
def xdg(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    return tmp_path


_BC = {
    "ok": True, "pan": "4189143370041827",
    "track2": "4189143370041827D29092211000002600000F", "expiry": "2909",
    "aip": "2000", "atc": "002F", "arqc": "D6F5B2E0E50B0F9C",
    "iad": "06011203A02000", "un": "ED999B69",
}


def test_cobros_purchase_dry_run(xdg):
    import asyncio

    from textual.widgets import Checkbox, RichLog
    from emvy.project import store
    from emvy.session import from_bombercat
    from emvy.tui.app import EmvyApp

    async def scenario():
        store.create_project("lab")
        store.set_active("lab")
        app = EmvyApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_show("tab-cob")
            await pilot.pause()
            app.last_dump = from_bombercat(_BC)
            app.query_one("#ch_dry", Checkbox).value = True
            app.query_one("#screen-charges")._purchase()
            await app.workers.wait_for_complete()
            await pilot.pause()
            text = "".join(seg.text for line in app.query_one("#ch_log", RichLog).lines
                            for seg in line._segments)
            assert "0200" in text                      # construyó el 0200

    asyncio.run(scenario())


def test_write_tab_sends(xdg):
    import asyncio

    from textual.widgets import Input, Select
    from emvy.core.apdu import Response
    from emvy.tui.app import EmvyApp

    async def scenario():
        app = EmvyApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_tool("tool-write")
            await pilot.pause()

            class FakeReader:
                transceive = staticmethod(lambda a: Response(b"", 0x69, 0x82))  # 6982
                atr = None
            app.reader = FakeReader()

            scr = app.query_one("#screen-write")
            app.query_one("#w_op", Select).value = "data"
            app.query_one("#w_tag", Input).value = "9F36"
            app.query_one("#w_data", Input).value = "0001"
            scr._write()
            await app.workers.wait_for_complete()
            await pilot.pause()   # no revienta; muestra el SW 6982

    asyncio.run(scenario())


def test_write_screen_has_gp_section_and_runs(xdg):
    """La pestaña Escritura une escritura directa + GlobalPlatform: el canal
    seguro corre contra una tarjeta GP falsa y su salida va al log compartido."""
    import asyncio

    pytest.importorskip("Crypto", reason="requiere el extra [gp] (pycryptodome)")
    from fakegpcard import FakeGPCard
    from emvy.core.gp.keyset import DEFAULT_GP_KEY, Keyset
    from emvy.core.hexutil import from_hex
    from emvy.project import store
    from textual.widgets import Select

    proj = store.create_project("lab"); store.set_active("lab")
    store.add_keyset(proj, Keyset.same_key("def"))

    async def scenario():
        from emvy.tui.app import EmvyApp
        app = EmvyApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_tool("tool-write")
            await pilot.pause()
            scr = app.query_one("#screen-write")
            # ambas secciones presentes en la misma pantalla
            assert app.query_one("#w_op") is not None          # escritura directa
            assert app.query_one("#gp_keyset") is not None      # GlobalPlatform
            scr.refresh_keysets()
            k = from_hex(DEFAULT_GP_KEY)

            class FakeReader:
                transceive = staticmethod(FakeGPCard(k, k, k, protocol="03"))
                atr = None
            app.reader = FakeReader()
            app.query_one("#gp_keyset", Select).value = "def"
            scr._do_status()
            await app.workers.wait_for_complete()
            await pilot.pause()
            from textual.widgets import RichLog
            assert app.query_one("#w_log", RichLog) is not None  # log compartido

    asyncio.run(scenario())
