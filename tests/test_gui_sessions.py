"""Pruebas headless de la sub-pestaña Sesiones de la GUI (offscreen)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")


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
    settings.apply(settings.load())
    from emvy.gui.app import MainWindow
    w = MainWindow()
    yield w
    w.close()


def _grabar_sesion(proj):
    from emvy.core.apdu import select
    from emvy.core.hexutil import from_hex
    from emvy.session.recorder import SessionRecorder
    from fakecard import AID, build_fake_card
    rec = SessionRecorder(proj, reader="fake")
    send = rec.wrap(build_fake_card()[0])
    send(select(b"2PAY.SYS.DDF01"))
    send(select(from_hex(AID)))
    rec.save_all()


def test_tools_subtabs_incluyen_sesiones(win):
    tp = win.tools_panel
    assert [tp.tabText(i) for i in range(tp.count())] == \
        ["Flags", "ISO 8583", "Escritura", "Sesiones"]


def test_sessions_tool_lists_and_views(win):
    from emvy.project import store
    store.create_project("lab"); store.set_active("lab")
    _grabar_sesion(store.active_project())

    ses = win.tools_panel.sessions
    ses.refresh_sessions()
    assert ses._table.rowCount() == 2
    ses._table.selectRow(1)
    s = ses._selected()
    assert s is not None and s.reader == "fake"

    # Ver abre el diálogo con el detalle formateado (stub de exec(): el modal
    # real bloquearía el event loop offscreen)
    from PySide6.QtWidgets import QDialog
    seen = []
    orig = QDialog.exec

    def spy(self):
        seen.append(self)
        return 0

    QDialog.exec = spy
    try:
        ses._view()
    finally:
        QDialog.exec = orig
    assert seen and "Sesi" in seen[-1].windowTitle()


def test_sessions_replay_requires_reader(win):
    ses = win.tools_panel.sessions
    ses.refresh_sessions()          # sin proyecto: avisa, no revienta
    ses._table.setRowCount(0)
    ses._sessions = []
    ses._replay()                   # sin selección: avisa
    assert ses._sessions == []
