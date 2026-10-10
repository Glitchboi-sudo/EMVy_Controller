"""Pruebas de humo (headless) de la sub-pestaña Sesiones de la TUI."""
import pytest

pytest.importorskip("textual")


@pytest.fixture
def xdg(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    return tmp_path


def _grabar_sesion(proj):
    from emvy.core.apdu import select
    from emvy.core.hexutil import from_hex
    from emvy.session.recorder import SessionRecorder
    from fakecard import AID, build_fake_card
    rec = SessionRecorder(proj, reader="fake")
    send = rec.wrap(build_fake_card()[0])
    send(select(b"2PAY.SYS.DDF01"))
    send(select(from_hex(AID)))
    return rec.save_all()


def test_sessions_tab_lists_and_views(xdg):
    import asyncio

    from emvy.project import store
    from emvy.tui.app import EmvyApp
    from emvy.tui.screens.sessions import SessionViewScreen

    async def scenario():
        app = EmvyApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            # sin proyecto: la tabla existe y no revienta
            app.action_tool("tool-sessions")
            await pilot.pause()
            scr = app.query_one("#screen-sessions")
            scr.refresh_sessions()
            await pilot.pause()

            # con proyecto + sesión grabada: aparece en la tabla
            store.create_project("lab"); store.set_active("lab")
            _grabar_sesion(store.active_project())
            scr.refresh_sessions()
            await pilot.pause()
            table = scr.query_one("#ses_table")
            assert table.row_count == 2

            # Ver abre el modal con el detalle
            scr._on_view()
            await pilot.pause()
            assert isinstance(app.screen, SessionViewScreen)
            await pilot.press("escape")
            await pilot.pause()
            assert not isinstance(app.screen, SessionViewScreen)

    asyncio.run(scenario())


def test_sessions_tab_replay_requires_reader(xdg):
    import asyncio

    from emvy.project import store
    from emvy.tui.app import EmvyApp

    async def scenario():
        app = EmvyApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            store.create_project("lab"); store.set_active("lab")
            _grabar_sesion(store.active_project())
            app.action_tool("tool-sessions")
            await pilot.pause()
            scr = app.query_one("#screen-sessions")
            scr.refresh_sessions()
            await pilot.pause()
            scr._on_replay()          # sin lector conectado: avisa y no revienta
            await pilot.pause()
            await pilot.pause(0.2)

    asyncio.run(scenario())
