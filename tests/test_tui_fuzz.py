"""Pruebas headless de la pestaña Fuzzing: generar plantillas, escribir en
tarjeta (fake transceiver) y magspoof (fake serial)."""
import pytest

pytest.importorskip("textual")


def test_fuzz_tab_generate_and_write():
    import asyncio

    from textual.widgets import Input, Select

    from emvy.core.apdu import Response
    from emvy.tui.app import EmvyApp

    async def scenario():
        app = EmvyApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_show("tab-fuzz")
            await pilot.pause()
            scr = app.query_one("#screen-fuzz")

            # generar plantilla de banda -> campos poblados
            app.query_one("#fz_track_tpl", Select).value = "bad-luhn"
            scr._gen_track()
            await pilot.pause()
            t1 = app.query_one("#fz_track1", Input).value
            assert t1.startswith("%B") and t1.endswith("?")

            # generar plantilla EMV -> hex poblado
            app.query_one("#fz_card_tpl", Select).value = "no-cvm"
            scr._gen_card()
            await pilot.pause()
            hexval = app.query_one("#fz_card_hex", Input).value
            assert hexval and all(c in "0123456789ABCDEFabcdef" for c in hexval)

            # escribir: conecta un lector fake y dispara write_card_ui
            class FakeReader:
                transceive = staticmethod(lambda a: Response(b"", 0x90, 0x00))
                atr = None
            app.reader = FakeReader()
            scr._card_write()
            await app.workers.wait_for_complete()
            await pilot.pause()   # no revienta; log recibido en ambas pestañas

    asyncio.run(scenario())


def test_fuzz_tab_magspoof(monkeypatch):
    import asyncio
    import sys

    sys.path.insert(0, "tests")
    import fakeserial
    from emvy.tui.app import EmvyApp

    fakeserial.install()
    try:
        async def scenario():
            app = EmvyApp()
            async with app.run_test() as pilot:
                await pilot.pause()
                app.action_show("tab-fuzz")
                await pilot.pause()
                scr = app.query_one("#screen-fuzz")
                scr._track_send()
                await app.workers.wait_for_complete()
                await pilot.pause()

        asyncio.run(scenario())
    finally:
        fakeserial.uninstall()


def test_fuzz_tab_ndef(monkeypatch):
    import asyncio
    import sys

    sys.path.insert(0, "tests")
    import fakeserial
    from textual.widgets import Input, Select
    from emvy.tui.app import EmvyApp

    fakeserial.install()
    try:
        async def scenario():
            app = EmvyApp()
            async with app.run_test() as pilot:
                await pilot.pause()
                app.action_show("tab-fuzz")
                await pilot.pause()
                scr = app.query_one("#screen-fuzz")
                # generar plantilla NDEF -> hex poblado
                app.query_one("#fz_ndef_tpl", Select).value = "invalid-tnf"
                scr._gen_ndef()
                await pilot.pause()
                hexval = app.query_one("#fz_ndef_hex", Input).value
                assert hexval and all(ch in "0123456789ABCDEFabcdef" for ch in hexval)
                # emular -> worker con fakeserial (corre hasta STOP, no auto-DONE)
                scr._ndef_emit()
                await pilot.pause()
                # Detener: señala al worker que mande STOP -> el worker termina
                scr._ndef_stop()
                await app.workers.wait_for_complete()
                await pilot.pause()
                # emular tarjeta EMV (perfila terminal) + detener
                scr._emv_emit()
                await pilot.pause()
                scr._ndef_stop()
                await app.workers.wait_for_complete()
                await pilot.pause()
                # Reboot: worker aparte que manda REBOOT (fakeserial responde)
                scr._ndef_reboot()
                await app.workers.wait_for_complete()
                await pilot.pause()

        asyncio.run(scenario())
    finally:
        fakeserial.uninstall()


def test_fuzz_tab_mutations_preview():
    """Carril Mutaciones: selector de playbooks y vista previa sobre el dump
    activo (con y sin captura en memoria)."""
    import asyncio

    from textual.widgets import Select
    from emvy.session.model import CardDump
    from emvy.tui.app import EmvyApp

    dump = CardDump(applications=[{
        "aid": "A0000000031010", "scheme": "Visa", "source": "ppse", "label": "VISA",
        "cardholder": {}, "aip": "3900", "afl": "0801010010010200",
        "records": [{"sfi": 1, "record": 1, "hex": "700A8C069F02069F0306"}],
        "get_data": {},
    }], blobs=[])

    async def scenario():
        app = EmvyApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_show("tab-fuzz")
            await pilot.pause()
            scr = app.query_one("#screen-fuzz")
            sel = app.query_one("#fz_mut_pb", Select)
            assert sel.value == "COMBO-A"

            collected = []
            scr.log_mut = collected.append

            # sin dump: avisa y lista las inyecciones planificadas (no inventa tarjeta)
            scr._mut_preview()
            await pilot.pause()
            assert any("Sin captura" in l for l in collected)
            assert any("inyección planificada" in l for l in collected)

            # con dump: diff real del playbook elegido
            collected.clear()
            app.last_dump = dump
            sel.value = "COMBO-B"
            scr._mut_preview()
            await pilot.pause()
            assert any("AFL skip_signed" in l for l in collected)
            assert any("resp TLV xor 82" in l for l in collected)
            assert any("→" in l for l in collected)

    asyncio.run(scenario())
