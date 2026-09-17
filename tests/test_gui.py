"""Pruebas headless de la GUI PySide6 (plataforma offscreen).

Verifican que la ventana y los paneles construyen y que la lógica de generación
(plantillas/tarjeta de prueba, árbol TLV, formato de consola) funciona. Las
operaciones de hardware (workers) se prueban en sus módulos de core/backend.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from emvy.core import cardfuzz, ndef                    # noqa: E402
from emvy.core.hexutil import to_hex                    # noqa: E402
from emvy.session.model import CardDump                 # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def win(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    from emvy import settings
    settings.apply(settings.load())        # idioma/datos deterministas (por defecto)
    from emvy.gui.app import MainWindow
    w = MainWindow()
    yield w
    w.close()


def test_tools_subtabs_and_iso_build(win):
    tp = win.tools_panel
    assert [tp.tabText(i) for i in range(tp.count())] == ["Flags", "ISO 8583", "Escritura"]
    tp.iso._de.setText("3"); tp.iso._val.setText("000000"); tp.iso._set()
    tp.iso._build()
    assert "Construido:" in tp.iso._log.toPlainText()


def test_explorer_assign_and_save(win, tmp_path):
    from emvy.project import env, store
    from emvy.session.model import CardDump
    store.create_project("lab"); store.set_active("lab")
    win.refresh_all()
    dump = CardDump(applications=[{
        "aid": "A0000000031010", "scheme": "Visa", "source": "ppse", "label": "VISA",
        "cardholder": {}, "aip": "2000",
        "records": [{"sfi": 1, "record": 1, "hex": "70059F36020031"}], "get_data": {}}], blobs=[])
    win.last_dump = dump
    ep = win.explorer_panel
    ep._sel = {"tag": "9F36", "value": "0031", "ascii": "", "is_hex": True, "suggest": "9F36"}
    ep._assign()
    v = env.get_var(store.load_project_variables(store.active_project()), "9F36")
    assert v and v.value == "0031"
    # guardar como captura en el proyecto activo
    ep._dest.setCurrentIndex(0)  # → proyecto activo
    ep._savename.setText("cap1"); ep._save()
    assert [p.name for p in store.list_captures(store.active_project())] == ["cap1.json"]


def test_fuzz_ndef_template_source(win):
    fz = win.fuzz_panel
    fz._ndef_src.setCurrentIndex(0)          # Plantilla
    fz._ndef_tpl.setCurrentIndex(fz._ndef_tpl.findData("invalid-tnf"))
    fz._gen_ndef()
    assert fz._ndef_hex.text() == to_hex(
        cardfuzz.get_ndef_template(cardfuzz.ndef_templates(), "invalid-tnf").message)


def test_fuzz_ndef_test_card_source(win):
    fz = win.fuzz_panel
    fz._ndef_src.setCurrentIndex(fz._ndef_src.findData("test"))
    fz._gen_ndef()
    dec = ndef.parse_records(bytes.fromhex(fz._ndef_hex.text()))[0].decoded()
    assert "TEST VISA" in dec and "PAN=4111111111111111" in dec


def test_fuzz_ndef_capture_source(win):
    from emvy.project import store
    store.create_project("lab")
    store.set_active("lab")
    dump = CardDump(applications=[{
        "aid": "A0000000031010", "scheme": "Visa", "source": "ppse", "label": "VISA",
        "cardholder": {"pan": "5555444433332222", "expiry": "2704"},
        "aip": "2000", "records": [], "get_data": {}}], blobs=[])
    store.save_capture(store.active_project(), "cap1", dump.to_json())

    fz = win.fuzz_panel
    fz._ndef_src.setCurrentIndex(fz._ndef_src.findData("capture"))
    fz._reload_captures()
    fz._ndef_cap.setCurrentIndex(0)
    fz._gen_ndef()
    dec = ndef.parse_records(bytes.fromhex(fz._ndef_hex.text()))[0].decoded()
    assert "PAN=5555444433332222" in dec


def test_fuzz_track_and_emv_generate(win):
    fz = win.fuzz_panel
    fz._gen_track()
    assert fz._track1.text().startswith("%B")
    fz._gen_emv()
    assert all(ch in "0123456789ABCDEFabcdef" for ch in fz._emv_hex.text())


def test_fuzz_emit_dispatches_by_source(win):
    """El botón único 'Emular' elige NFC o EMV según el MODO de la Fuente."""
    fz = win.fuzz_panel
    calls = []
    win.emit_emv = lambda card=None: calls.append(("emv",))    # stubs: sin hardware
    win.emit_ndef = lambda h: calls.append(("ndef", h))
    # Fuente NFC (tarjeta de prueba) -> emit_ndef con el hex generado
    fz._ndef_src.setCurrentIndex(fz._ndef_src.findData("test"))
    fz._gen_ndef()
    fz._emit()
    assert calls[-1][0] == "ndef" and calls[-1][1]
    # Fuente EMV -> emit_emv (perfilar terminal)
    fz._ndef_src.setCurrentIndex(fz._ndef_src.findData("emv"))
    fz._emit()
    assert calls[-1] == ("emv",)


def test_fuzz_emv_source_uses_capture(win):
    """La fuente 'EMV' usa el selector de captura: una captura → emit_emv(card)
    con sus datos; la 'tarjeta de prueba fija' → emit_emv(None)."""
    from emvy.project import store
    store.create_project("emvlab"); store.set_active("emvlab")
    dump = CardDump(applications=[{
        "aid": "A0000000041010", "scheme": "Mastercard", "source": "ppse", "label": "MC",
        "cardholder": {"pan": "5555444433332222", "expiry": "2712"},
        "aip": "2000", "records": [], "get_data": {}}], blobs=[])
    store.save_capture(store.active_project(), "mc1", dump.to_json())

    fz = win.fuzz_panel
    cards = []
    win.emit_emv = lambda card=None: cards.append(card)
    fz._ndef_src.setCurrentIndex(fz._ndef_src.findData("emv"))   # → _reload_captures(canned+RAM)
    fz._ndef_cap.setCurrentIndex(fz._ndef_cap.findText("mc1"))   # la captura guardada
    fz._emit()
    assert cards[-1] is not None and cards[-1].aid == "A0000000041010"
    fz._ndef_cap.setCurrentIndex(0)                              # tarjeta de prueba fija
    fz._emit()
    assert cards[-1] is None


def test_fuzz_emv_ram_sources(win):
    """Las fuentes EMV en RAM: '(en RAM del BomberCat)' → emit_emv(from_ram=True);
    '(en memoria de la app)' → emit_emv(card=self._scanned_card)."""
    from emvy.payments import EmvCard
    fz = win.fuzz_panel
    calls = []
    win.emit_emv = lambda card=None, from_ram=False: calls.append((card, from_ram))
    fz._ndef_src.setCurrentIndex(fz._ndef_src.findData("emv"))   # puebla el picker (canned+RAM+capturas)
    # RAM del BomberCat
    fz._ndef_cap.setCurrentIndex(fz._ndef_cap.findData("__ram__"))
    fz._emit()
    assert calls[-1] == (None, True)
    # memoria de la app: sin tarjeta escaneada aún → no emula
    fz._ndef_cap.setCurrentIndex(fz._ndef_cap.findData("__mem__"))
    fz._emit()
    assert calls[-1] == (None, True)                             # no cambió (avisó y volvió)
    # con una tarjeta en memoria → emit_emv(card=...)
    win._scanned_card = EmvCard(pan="4111111111111111", aid="A0000000031010")
    fz._emit()
    assert calls[-1][0] is win._scanned_card and calls[-1][1] is False


def test_card_editor_load_edit_emulate(win):
    """El editor de tarjeta: cargar una captura, editar el PAN, y emular con el
    PAN nuevo + Track2 regenerado."""
    from emvy.core import track
    from emvy.project import store
    store.create_project("edlab"); store.set_active("edlab")
    dump = CardDump(applications=[{
        "aid": "A0000000031010", "scheme": "Visa", "source": "ppse", "label": "VISA",
        "cardholder": {"pan": "4189143370041827", "track2": "4189143370041827D29092211000002600000F",
                       "expiry": "2909"},
        "aip": "2000", "records": [], "get_data": {}}], blobs=[])
    store.save_capture(store.active_project(), "v1", dump.to_json())

    fz = win.fuzz_panel
    cards = []
    win.emit_emv = lambda card=None, from_ram=False: cards.append(card)
    # AUTO-LLENADO: al elegir 'captura' se carga sola la primera (sin pulsar nada)
    fz._ed_src.setCurrentIndex(fz._ed_src.findData("capture"))
    assert fz._ed_pan.text() == "4189143370041827"
    assert fz._ed_svc.text() == "221"                       # servicio parseado del track2
    # editar el PAN y emular (auto-regenera track2)
    fz._ed_pan.setText("4111111111111111")
    fz._ed_emit()
    assert cards and cards[-1].pan_digits == "4111111111111111"
    # el track2 emulado lleva el PAN nuevo (regenerado)
    assert track.parse_track2_emv(cards[-1].track2).pan == "4111111111111111"


def test_card_editor_autofills_on_scan(win):
    """Al escanear, el editor se llena solo (win._fill_card_editor → _ed_populate)."""
    from emvy.payments import EmvCard
    card = EmvCard(pan="5555444433332222", expiry="2712", aid="A0000000041010",
                   track2="5555444433332222D27122010000000F")
    win._fill_card_editor(card)
    fz = win.fuzz_panel
    assert fz._ed_pan.text() == "5555444433332222"
    assert fz._ed_exp.text() == "2712" and fz._ed_aid.text() == "A0000000041010"
    assert fz._ed_t2.text().startswith("5555444433332222D2712")


def test_console_export_and_save_to_project(win, tmp_path):
    from emvy.project import store
    store.create_project("loglab"); store.set_active("loglab")
    win.console.info("línea de consola de prueba")
    # exportar a archivo arbitrario
    dest = tmp_path / "salida.log"
    with open(dest, "w", encoding="utf-8") as fh:
        fh.write(win.console.plain_text())
    assert "línea de consola de prueba" in dest.read_text()
    # guardar en el proyecto (emite la señal -> slot de MainWindow -> store.save_log)
    win.console.save_to_project.emit(win.console.plain_text())
    logs = store.list_logs(store.active_project())
    assert logs and "línea de consola de prueba" in logs[0].read_text()


def test_explorer_show_dump_builds_tree(win):
    dump = CardDump(applications=[{
        "aid": "A0000000031010", "scheme": "Visa", "source": "ppse", "label": "VISA",
        "cardholder": {"pan": "4111111111111111"}, "aip": "2000", "afl": "08010100",
        "records": [{"sfi": 1, "record": 1, "hex": "70059F36020031"}],
        "get_data": {"9F17": "03"}}], blobs=[])
    win.explorer_panel.show_dump(dump)
    tree = win.explorer_panel._tree
    assert tree.topLevelItemCount() == 1
    top = tree.topLevelItem(0)
    assert "A0000000031010" in top.text(0)
    labels = [top.child(i).text(0) for i in range(top.childCount())]
    assert any("Titular" in x for x in labels)
    assert any("SFI 1" in x for x in labels)


def test_all_tabs(win):
    from emvy import i18n
    tabs = win.tabs
    assert win._tab_ids == [
        "home", "projects", "variables", "readers", "explorer", "tools",
        "charges", "poc", "intercept", "firmware", "fuzzing", "settings"]
    assert [tabs.tabText(i) for i in range(tabs.count())] == [
        i18n.t("nav." + tid) for tid in win._tab_ids]


def test_intercept_apply_and_toggle(win):
    rules, errors = win.apply_intercept("resp set-tag 82 3900\nresp set-sw 9000 @A8")
    assert len(rules) == 2 and not errors
    win.intercept_active = True
    # active_send debe envolver con el interceptor cuando hay reglas + activo
    class _R:
        transceive = staticmethod(lambda a: None)
        atr = None
    win.reader = _R()
    assert win.active_send() is not _R.transceive     # está envuelto


def test_firmware_lists_sketches(win):
    win.firmware_panel.reload()
    names = [win.firmware_panel._sketch.itemText(i)
             for i in range(win.firmware_panel._sketch.count())]
    assert any("EMVyBomberCat" in n for n in names)


def test_charges_and_poc_construct(win):
    win.charges_panel.log_flow("signon", type("R", (), {"summary": lambda s: "demo"})())
    assert "demo" in win.charges_panel._log.toPlainText()
    win.poc_panel.reload()   # no debe reventar aunque no haya proyecto/PoCs


def test_poc_ide_create_edit_save(win):
    """El IDE de PoCs: crear desde plantilla, cargar en el editor y guardar."""
    from emvy.project import store
    store.create_project("poclab"); store.set_active("poclab")
    p = win.poc_panel
    p.reload()
    p._new_id.setText("my-poc"); p._new()
    assert (store.active_project().pocs_dir / "my-poc.py").exists()
    p._select_file("my-poc.py")
    assert p._open_file == "my-poc.py" and "def run(ctx)" in p._editor.toPlainText()
    p._editor.setPlainText("# editado\n" + p._editor.toPlainText())
    p._save()
    assert (store.active_project().pocs_dir / "my-poc.py").read_text().startswith("# editado")
    # la fuente de tarjeta incluye la sesión
    assert p._card_src.itemData(0) is None


def test_worker_delivers_result(qapp):
    """El worker debe entregar `result` al hilo GUI (regresión: el pool
    auto-borraba el QRunnable y la señal en cola se perdía)."""
    from PySide6.QtCore import QEventLoop, QThreadPool, QTimer
    from emvy.gui.worker import submit
    pool = QThreadPool()
    got, loop = [], QEventLoop()
    submit(pool, lambda: 42, on_result=lambda r: got.append(r), on_finished=loop.quit)
    QTimer.singleShot(4000, loop.quit)     # guarda de timeout
    loop.exec()
    assert got == [42]


def test_worker_delivers_error(qapp):
    from PySide6.QtCore import QEventLoop, QThreadPool, QTimer
    from emvy.gui.worker import submit

    def boom():
        raise RuntimeError("fallo x")
    pool = QThreadPool()
    errs, loop = [], QEventLoop()
    submit(pool, boom, on_error=lambda m: errs.append(m), on_finished=loop.quit)
    QTimer.singleShot(4000, loop.quit)
    loop.exec()
    assert errs and "fallo x" in errs[0]


def test_console_formatting_does_not_crash(win):
    c = win.console
    c.banner("conectado: X")
    c.apdu("00A40400", "6F00", "9000")
    c.apdu("00B2010C", "", "6A83")
    c.wire("tx", "PING", "serial")
    c.wire("rx", "ERR:NOCARD", "serial")
    c.info("nota")
    assert c._log.toPlainText()          # algo se escribió
