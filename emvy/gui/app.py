"""GUI de escritorio (PySide6) de EMVy Controller.

Frontend nativo alternativo a la TUI. Reutiliza **el mismo núcleo puro**
(`core`/`session`/`project`/`readers`/`cardfuzz`): esta capa solo orquesta
estado (lector, captura) y lanza las operaciones de hardware en hilos de trabajo
(`gui.worker`), devolviendo resultados/traza a la GUI por señales Qt.

`MainWindow` mantiene el estado de sesión y expone métodos que los paneles
llaman (`connect_reader`, `capture`, `send_apdu`, `emit_ndef`…). La traza de
cada intercambio (APDU + transporte, en crudo) fluye a la **consola cruda** del
dock inferior por las señales `apdu_event`/`wire_event`.
"""
from __future__ import annotations

import sys

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication, QDockWidget, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QMainWindow, QStatusBar, QTabWidget, QWidget,
)

from .. import __release__, __version__
from ..core import emv
from ..core.hexutil import from_hex, to_hex
from ..project import env as envmod
from ..project import store
from ..readers import registry
from ..session.capture import capture_card
from .panels.charges import ChargesPanel
from .panels.console import RawConsole
from .panels.dashboard import DashboardPanel
from .panels.explorer import ExplorerPanel
from .panels.firmware import FirmwarePanel
from .panels.fuzz import FuzzPanel
from .panels.intercept import InterceptPanel
from .panels.poc import PocPanel
from .panels.projects import ProjectsPanel
from .panels.readers import ReadersPanel
from .panels.tools import ToolsPanel
from .panels.variables import VariablesPanel
from .worker import submit


class MainWindow(QMainWindow):
    # Señales de sesión / traza (emitidas desde hilos de trabajo → GUI).
    apdu_event = Signal(object)      # core.apdu.TraceEvent
    wire_event = Signal(object)      # readers.types.WireEvent
    reader_changed = Signal()
    dump_ready = Signal(object)      # session.CardDump
    notify = Signal(str)             # mensaje breve a la barra de estado
    intercept_event = Signal(object) # core.intercept.Exchange (MITM en vivo)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"EMVy Controller {__version__} {__release__}")
        from .brand import brand_icon
        from .theme import ACCENT
        self.setWindowIcon(brand_icon("logo", ACCENT))
        self.resize(1120, 760)

        # -- estado de sesión ----------------------------------------------
        self.reader = None
        self.reader_device = None
        self.last_dump = None
        self.card_atr: str | None = None
        self.intercept_rules: list = []
        self.intercept_active: bool = False
        import threading
        self._emu_stop = threading.Event()   # señal para detener la emulación NDEF
        self._scanned_card = None            # tarjeta escaneada a memoria (RAM app), EmvCard

        from PySide6.QtCore import QThreadPool
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)   # serializa las operaciones de hardware

        # -- consola cruda (dock inferior) ---------------------------------
        self.console = RawConsole()
        dock = QDockWidget("Consola cruda — envío / recepción", self)
        dock.setObjectName("console-dock")
        dock.setWidget(self.console)
        dock.setAllowedAreas(Qt.BottomDockWidgetArea | Qt.TopDockWidgetArea)
        self.addDockWidget(Qt.BottomDockWidgetArea, dock)
        self._console_dock = dock
        self.console.send_apdu.connect(self.send_apdu)
        self.console.save_to_project.connect(self._save_console_to_project)

        # -- pestañas -------------------------------------------------------
        self.dashboard_panel = DashboardPanel(self)
        self.projects_panel = ProjectsPanel(self)
        self.variables_panel = VariablesPanel(self)
        self.readers_panel = ReadersPanel(self)
        self.explorer_panel = ExplorerPanel(self)
        self.tools_panel = ToolsPanel(self)
        self.charges_panel = ChargesPanel(self)
        self.poc_panel = PocPanel(self)
        self.intercept_panel = InterceptPanel(self)
        self.firmware_panel = FirmwarePanel(self)
        self.fuzz_panel = FuzzPanel(self)
        self.tabs = QTabWidget()
        self.tabs.addTab(self.dashboard_panel, "Inicio")
        self.tabs.addTab(self.projects_panel, "Proyectos")
        self.tabs.addTab(self.variables_panel, "Variables")
        self.tabs.addTab(self.readers_panel, "Lectores")
        self.tabs.addTab(self.explorer_panel, "Explorador")
        self.tabs.addTab(self.tools_panel, "Herramientas")
        self.tabs.addTab(self.charges_panel, "Cobros")
        self.tabs.addTab(self.poc_panel, "PoC")
        self.tabs.addTab(self.intercept_panel, "Intercept")
        self.tabs.addTab(self.firmware_panel, "BomberCat")
        self.tabs.addTab(self.fuzz_panel, "Fuzzing")
        # Navegación por **barra lateral** (más limpia que 11 pestañas arriba):
        # el QTabWidget conserva las páginas (y `self.tabs` sigue siendo la API)
        # pero su barra de pestañas se oculta y se conduce desde la lista lateral.
        self.tabs.tabBar().hide()
        self.nav = self._build_sidebar()
        central = QWidget()
        h = QHBoxLayout(central); h.setContentsMargins(0, 0, 0, 0); h.setSpacing(0)
        h.addWidget(self.nav); h.addWidget(self.tabs, 1)
        self.setCentralWidget(central)
        # La consola cruda solo es útil donde hay tráfico con el hardware; se
        # oculta en Inicio/Proyectos/Variables para una vista más limpia.
        self.tabs.currentChanged.connect(self._on_tab_changed)

        # -- barra de estado ------------------------------------------------
        self.setStatusBar(QStatusBar())
        self._status = QLabel()
        self.statusBar().addWidget(self._status)

        # -- cableado de señales -------------------------------------------
        self.apdu_event.connect(self._on_apdu_event)
        self.wire_event.connect(self._on_wire_event)
        self.reader_changed.connect(self._update_status)
        self.dump_ready.connect(self._on_dump)
        self.notify.connect(lambda m: self.statusBar().showMessage(m, 6000))

        self._update_status()
        self._on_tab_changed(self.tabs.currentIndex())   # estado inicial de la consola

    # Pestañas donde la consola cruda (APDU/transporte) aporta; en el resto se
    # oculta para reducir ruido visual.
    _CONSOLE_TABS = frozenset({"Lectores", "Explorador", "Herramientas", "Cobros",
                               "PoC", "Intercept", "BomberCat", "Fuzzing"})

    # Navegación agrupada de la barra lateral: (grupo, [(etiqueta, icono)…]).
    _NAV_GROUPS = (
        ("SESIÓN", (("Inicio", "home"), ("Proyectos", "folder"),
                    ("Variables", "sliders"), ("Lectores", "plug"))),
        ("TARJETA", (("Explorador", "search"), ("Herramientas", "wrench"))),
        ("OPERACIONES", (("Cobros", "credit-card"), ("PoC", "flask"),
                         ("Intercept", "shield"), ("Fuzzing", "zap"))),
        ("HARDWARE", (("BomberCat", "cpu"),)),
    )

    def _build_sidebar(self) -> QListWidget:
        from .icons import icon
        nav = QListWidget(); nav.setObjectName("nav")
        nav.setFixedWidth(198); nav.setIconSize(QSize(18, 18))
        nav.setUniformItemSizes(False)
        tab_index = {self.tabs.tabText(i): i for i in range(self.tabs.count())}
        self._nav_to_tab: dict[int, int] = {}
        first_row = None
        for gname, items in self._NAV_GROUPS:
            hdr = QListWidgetItem(gname); hdr.setFlags(Qt.NoItemFlags)
            nav.addItem(hdr)
            for label, ic in items:
                if label not in tab_index:
                    continue
                it = QListWidgetItem(icon(ic, color="#CBD5E1"), label)
                nav.addItem(it)
                row = nav.row(it)
                self._nav_to_tab[row] = tab_index[label]
                if first_row is None:
                    first_row = row
        nav.currentRowChanged.connect(self._on_nav_changed)
        if first_row is not None:
            nav.setCurrentRow(first_row)
        return nav

    def _on_nav_changed(self, row: int) -> None:
        idx = self._nav_to_tab.get(row)
        if idx is not None:
            self.tabs.setCurrentIndex(idx)

    def _on_tab_changed(self, index: int) -> None:
        name = self.tabs.tabText(index) if index >= 0 else ""
        self._console_dock.setVisible(name in self._CONSOLE_TABS)
        if name == "Herramientas":
            self.tools_panel.gp_refresh()      # keysets del proyecto activo
        # mantener la selección de la barra lateral en sincronía
        for row, ti in getattr(self, "_nav_to_tab", {}).items():
            if ti == index and self.nav.currentRow() != row:
                self.nav.blockSignals(True); self.nav.setCurrentRow(row)
                self.nav.blockSignals(False)
                break

    # -- perfil de terminal del proyecto activo ----------------------------
    def current_profile(self) -> dict:
        proj = store.active_project()
        if proj:
            return envmod.to_terminal_profile(store.load_project_variables(proj))
        return emv.default_terminal_profile()

    def active_send(self):
        if not self.reader:
            return None
        send = self.reader.transceive
        if self.intercept_active and self.intercept_rules:
            from ..core import intercept
            return intercept.intercepting(
                send, self.intercept_rules,
                on_event=lambda ex: self.intercept_event.emit(ex))
        return send

    # -- traza en vivo → consola cruda -------------------------------------
    def _on_apdu_event(self, e) -> None:
        self.console.apdu(e.command, e.response, e.sw)

    def _on_wire_event(self, e) -> None:
        self.console.wire(e.direction, e.text, e.transport)

    def _update_status(self) -> None:
        proj = store.active_label() if hasattr(store, "active_label") else None
        if proj is None:
            p = store.active_project()
            proj = p.name if p else "—"
        rdr = self.reader_device.name if self.reader_device else "—"
        crd = self.card_atr or "—"
        self._status.setText(f"  proyecto: {proj}    │    lector: {rdr}    │    tarjeta: {crd}")
        try:
            self.dashboard_panel.reload()
        except Exception:
            pass

    def refresh_all(self) -> None:
        """Recarga los paneles dependientes de proyecto/estado (tras crear/
        activar un proyecto, guardar variables, etc.) — como refresh_ui de la TUI."""
        for panel in (self.dashboard_panel, self.projects_panel, self.variables_panel,
                      self.readers_panel, self.explorer_panel, self.poc_panel):
            try:
                panel.reload()
            except Exception:
                pass
        # el combo de capturas del fuzz depende del proyecto activo
        try:
            self.fuzz_panel._reload_captures()
        except Exception:
            pass
        self._update_status()

    # -- lector: conectar / desconectar ------------------------------------
    def connect_reader(self, device) -> None:
        if device is None:
            self.notify.emit("Selecciona un lector.")
            return
        self.console.banner(f"conectando: {device.name} [{device.backend}]")

        def _open():
            r = registry.open_device(
                device,
                on_event=lambda e: self.apdu_event.emit(e),
                on_wire=lambda e: self.wire_event.emit(e))
            atr = r.atr() if r.atr else b""
            return r, atr

        def _ok(res):
            self.reader, atr = res
            self.reader_device = device
            self.card_atr = to_hex(atr, sep=" ") if atr else None
            self.console.banner(f"conectado: {device.name}"
                                + (f" · ATR {self.card_atr}" if self.card_atr else ""))
            self.reader_changed.emit()
            self.notify.emit("Lector conectado.")

        submit(self.pool, _open, on_result=_ok,
               on_error=lambda m: self.notify.emit(f"Conexión: {m}"))

    def disconnect_reader(self) -> None:
        name = self.reader_device.name if self.reader_device else "lector"
        if self.reader:
            try:
                self.reader.close()
            except Exception:
                pass
        self.reader = None
        self.reader_device = None
        self.card_atr = None
        self.console.banner(f"desconectado: {name}")
        self.reader_changed.emit()
        self.notify.emit("Lector desconectado.")

    def _need_reader(self) -> bool:
        if self.reader and self.reader.transceive:
            return True
        self.notify.emit("Conecta un lector primero (pestaña Lectores).")
        return False

    # -- captura -----------------------------------------------------------
    def capture(self, mode: str = "auto", raw: bool = False) -> None:
        # Banda magnética: el lector no tiene `transceive` (no es EMV), sino
        # `read_swipe`. Se lee un swipe y se decodifican las pistas — no pasa por
        # `_need_reader` (que exige APDUs).
        if self.reader and self.reader.transceive is None and self.reader.read_swipe:
            self._capture_swipe()
            return
        if not self._need_reader():
            return
        self.notify.emit("Capturando…")

        send = self.active_send()
        # Contactless (BomberCat): flujo EMV **mínimo** — sin bruteforce de AIDs
        # ni barrido ciego de registros/GET DATA. Esos exhaustivos son cientos de
        # APDUs y, sobre NFC de rango milimétrico sostenido a mano, la tarjeta se
        # mueve a media lectura → ERR:TXFAIL. Con PPSE→SELECT→GPO→AFL basta y es
        # ~15 APDUs (rápido y fiable). En lectores de contacto (estables) se hace
        # el barrido completo.
        lean = getattr(self.reader_device, "backend", None) == "bombercat"

        def _cap(progress=None):
            return capture_card(
                send,
                atr=(self.reader.atr() if self.reader.atr else b""),
                reader=(self.reader_device.name if self.reader_device else ""),
                profile=self.current_profile(), raw=raw, mode=mode,
                brute=not lean, sweep=not lean, get_data=not lean, progress=progress)

        submit(self.pool, _cap, want_progress=True,
               on_line=lambda m: self.console.info(m),
               on_result=lambda d: self.dump_ready.emit(d),
               on_error=lambda m: self.notify.emit(f"Captura: {m}"))

    def _capture_swipe(self) -> None:
        """Lee un swipe del lector de banda y decodifica las pistas."""
        self.notify.emit("Pasa la tarjeta por el lector…")
        self.console.banner("banda magnética: esperando swipe (30 s)…")
        reader = self.reader
        name = self.reader_device.name if self.reader_device else ""

        def _do(progress=None):
            # OJO: corre en el hilo del worker → NO tocar widgets aquí. El swipe
            # crudo se manda a la consola por `progress` (señal → hilo GUI).
            from ..session.capture import swipe_to_dump
            raw = reader.swipe(timeout=30.0)
            if raw and progress:
                progress(f"swipe crudo: {raw}")
            return swipe_to_dump(raw, reader=name)

        submit(self.pool, _do, want_progress=True,
               on_line=lambda m: self.console.info(m),
               on_result=lambda d: self.dump_ready.emit(d),
               on_error=lambda m: self.notify.emit(f"Swipe: {m}"))

    def _on_dump(self, dump) -> None:
        self.last_dump = dump
        self.explorer_panel.show_dump(dump)
        self.dashboard_panel.reload()
        n_apps, n_blobs = len(dump.applications), len(dump.blobs)
        backend = getattr(self.reader_device, "backend", None)
        aid0 = dump.applications[0].get("aid") if dump.applications else None
        if aid0 == "MAGSTRIPE":
            ch = dump.applications[0].get("cardholder") or {}
            if ch.get("PAN"):
                self.notify.emit(f"Banda leída: PAN {ch['PAN']}"
                                 + (f" · exp {ch['Caducidad (YYMM)']}" if ch.get("Caducidad (YYMM)") else ""))
            else:
                self.notify.emit(f"Banda leída: {ch.get('Datos', '(sin datos)')}")
        elif backend == "msr" and not dump.applications:
            self.notify.emit("No se leyó nada (timeout). Pasa la tarjeta de nuevo.")
        elif backend == "bombercat" and not dump.applications and n_blobs <= 1:
            self.notify.emit("Sin datos: la tarjeta pudo moverse (rango NFC de mm). "
                             "Sosténla firme y reintenta.")
        else:
            self.notify.emit(f"Captura: {n_apps} app(s), {n_blobs} blobs.")

    # -- APDU manual (desde la consola) ------------------------------------
    def send_apdu(self, hexstr: str) -> None:
        if not self._need_reader():
            return
        try:
            data = from_hex(hexstr)
        except ValueError:
            self.notify.emit("APDU hex inválido.")
            return
        send = self.active_send()
        submit(self.pool, lambda: send(data),
               on_error=lambda m: self.notify.emit(f"APDU: {m}"))

    # -- fuzzing: magspoof / NDEF ------------------------------------------
    def emit_magspoof(self, track1, track2) -> None:
        from ..readers import bombercat
        devs = [d for d in registry.list_all_devices() if d.backend == "bombercat"]
        if not devs:
            self.notify.emit("No se detectó BomberCat.")
            return
        self.console.banner("magspoof")
        submit(self.pool, lambda: bombercat.magspoof_emit(devs[0], track1, track2),
               on_result=lambda out: self.console.info(f"magspoof: {out}"),
               on_error=lambda m: self.notify.emit(f"magspoof: {m}"))

    def emit_ndef(self, ndef_hex: str) -> None:
        from ..readers import bombercat
        devs = [d for d in registry.list_all_devices() if d.backend == "bombercat"]
        if not devs:
            self.notify.emit("No se detectó BomberCat.")
            return
        self._emu_stop.clear()
        self.console.banner(f"emulación NDEF ({len(ndef_hex)//2} bytes) — acerca un "
                            "lector (Detener para parar)")
        submit(self.pool,
               lambda progress=None: bombercat.ndef_emulate(
                   devs[0], ndef_hex, timeout=None, stop=self._emu_stop.is_set,
                   on_line=progress),
               want_progress=True,
               on_line=lambda l: self.console.wire("rx", l, "emu"),
               on_error=lambda m: self.notify.emit(f"NDEF EMU: {m}"))

    def emit_emv(self, card=None, from_ram: bool = False) -> None:
        from ..readers import bombercat
        devs = [d for d in registry.list_all_devices() if d.backend == "bombercat"]
        if not devs:
            self.notify.emit("No se detectó BomberCat.")
            return
        self._emu_stop.clear()
        who = ("RAM del BomberCat" if from_ram else
               "tarjeta de prueba" if card is None else
               f"captura (PAN {card.pan_digits or '?'})")
        self.console.banner(f"emulación de tarjeta EMV [{who}] — acerca el "
                            "terminal/POS (Detener para parar)")
        submit(self.pool,
               lambda progress=None: bombercat.emv_emulate(
                   devs[0], card=card, from_ram=from_ram, timeout=None,
                   stop=self._emu_stop.is_set, on_line=progress),
               want_progress=True,
               on_line=lambda l: self.console.wire("rx", l, "emu"),
               on_error=lambda m: self.notify.emit(f"EMV EMU: {m}"))

    def scan_to_memory(self, then=None) -> None:
        """Escanea (captura) la tarjeta con el lector conectado y la guarda en la
        memoria de la app (`self._scanned_card`) para emularla como tarjeta EMV.
        Si `then` se aporta, se llama con el `EmvCard` resultante (p.ej. para
        volcarlo al editor)."""
        if not self._need_reader():
            return
        from ..payments import EmvCard
        self.notify.emit("Escaneando a memoria…")
        send = self.active_send()
        lean = getattr(self.reader_device, "backend", None) == "bombercat"

        def _cap(progress=None):
            return capture_card(
                send, atr=(self.reader.atr() if self.reader.atr else b""),
                reader=(self.reader_device.name if self.reader_device else ""),
                profile=self.current_profile(), raw=False, mode="auto",
                brute=not lean, sweep=not lean, get_data=not lean, progress=progress)

        def _ok(dump):
            self.last_dump = dump
            card = EmvCard.from_dump(dump)
            self._scanned_card = card
            self.explorer_panel.show_dump(dump)
            self.dashboard_panel.reload()
            self.notify.emit(f"Tarjeta en memoria: PAN {card.pan_digits or '?'} "
                             f"AID {card.aid or '?'}.")
            self._fill_card_editor(card)      # el editor se llena solo al escanear
            if then:
                then(card)

        submit(self.pool, _cap, want_progress=True,
               on_line=lambda m: self.console.info(m),
               on_result=_ok,
               on_error=lambda m: self.notify.emit(f"Escaneo: {m}"))

    def scan_to_bombercat_ram(self, then=None) -> None:
        """Lee una tarjeta por NFC y la guarda en la RAM del firmware (CARDSCAN),
        para reemularla con la fuente EMV '(tarjeta en RAM del BomberCat)'. Si
        `then` se aporta, se llama con un `EmvCard` de los campos escaneados."""
        from ..payments import EmvCard
        from ..readers import bombercat
        devs = [d for d in registry.list_all_devices() if d.backend == "bombercat"]
        if not devs:
            self.notify.emit("No se detectó BomberCat.")
            return
        self.console.banner("CARDSCAN — acerca la tarjeta a leer (se guarda en la RAM del BomberCat)")

        def _ok(d):
            self._scanned_card = EmvCard(pan=d.get("pan", ""), expiry=d.get("exp", ""),
                                         aid=d.get("aid", ""), track2=d.get("t2", ""))
            self.notify.emit(f"Escaneada a RAM: PAN {d.get('pan', '?')} AID {d.get('aid', '?')}.")
            self._fill_card_editor(self._scanned_card)   # el editor se llena solo
            if then:
                then(self._scanned_card)

        submit(self.pool,
               lambda progress=None: bombercat.card_scan_to_ram(devs[0], on_line=progress),
               want_progress=True,
               on_line=lambda l: self.console.wire("rx", l, "emu"),
               on_result=_ok,
               on_error=lambda m: self.notify.emit(f"CARDSCAN: {m}"))

    def _fill_card_editor(self, card) -> None:
        """Vuelca la tarjeta al Editor de tarjeta EMV de la pestaña Fuzzing (para
        que se llene solo al escanear). Best-effort: no rompe si el panel no está."""
        try:
            self.fuzz_panel._ed_populate(card)
        except Exception:  # noqa: BLE001
            pass

    def stop_ndef(self) -> None:
        """Detiene la emulación (NDEF o EMV) en curso (señala al worker STOP)."""
        self._emu_stop.set()
        self.notify.emit("Deteniendo emulación…")

    def _save_console_to_project(self, text: str) -> None:
        """Guarda el volcado de la consola en logs/ del proyecto activo."""
        proj = store.active_project()
        if not proj:
            self.notify.emit("No hay proyecto activo (créalo/actívalo en Proyectos).")
            return
        if not text.strip():
            self.notify.emit("La consola está vacía.")
            return
        from datetime import datetime
        name = f"consola-{datetime.now():%Y%m%d-%H%M%S}"
        dest = store.save_log(proj, name, text)
        self.notify.emit(f"Consola guardada en {dest}")

    def reboot_bombercat(self) -> None:
        """Reinicia el BomberCat (REBOOT). Detiene antes cualquier emulación para
        soltar el puerto; tras el reset hay que reconectar el lector."""
        from ..readers import bombercat
        self._emu_stop.set()
        devs = [d for d in registry.list_all_devices() if d.backend == "bombercat"]
        if not devs:
            self.notify.emit("No se detectó BomberCat.")
            return
        self.console.banner("REBOOT BomberCat — reconecta el lector tras el reinicio")

        def _done(out) -> None:
            self.console.wire("rx", f"# REBOOT → {out}", "emu")
            if self.reader_device and self.reader_device.backend == "bombercat":
                self._disconnect_after_reboot()
            self.notify.emit("BomberCat reiniciado. Reconecta el lector (pestaña Lectores).")

        submit(self.pool, lambda: bombercat.reboot(devs[0]),
               on_result=_done,
               on_error=lambda m: self.notify.emit(f"REBOOT: {m}"))

    def _disconnect_after_reboot(self) -> None:
        try:
            if self.reader and self.reader.close:
                self.reader.close()
        except Exception:
            pass
        self.reader = None
        self.reader_device = None
        self.card_atr = None
        self.reader_changed.emit()

    # -- escritura en tarjeta ----------------------------------------------
    def write_record(self, sfi: int, record: int, data: bytes) -> None:
        self.write_op("record", {"sfi": sfi, "record": record, "data": data})

    def write_op(self, op: str, params: dict) -> None:
        """Escritura **inteligente**: prueba la escritura directa y, si la tarjeta
        exige canal seguro (6982/6985), abre GlobalPlatform con el keyset elegido y
        reintenta — un solo paso. `params` puede traer `keyset` (nombre) y `enc`."""
        if not self._need_reader():
            return
        from ..core import cardwrite
        from ..core.gp import content
        from ..core.gp.scp import SEC_CENC, SEC_CMAC
        send = self.active_send()
        data = params["data"]
        ks = None
        ksname = params.get("keyset")
        if ksname:
            from ..project import store
            proj = store.active_project()
            ks = store.get_keyset(proj, ksname) if proj else None
        self.console.banner(f"{op.upper()} {to_hex(data)}"
                            + (f" · keyset {ksname}" if ksname else ""))

        def write_fn(s):
            if op == "record":
                return cardwrite.update_record(s, params["sfi"], params["record"], data)
            if op == "binary":
                return cardwrite.update_binary(s, params["offset"], data, sfi=params.get("sfi"))
            if op == "data":
                return cardwrite.put_data(s, params["tag"], data)
            if op == "append":
                return cardwrite.append_record(s, params["sfi"], data)
            raise ValueError(op)

        def _do():
            return content.smart_write(
                send, write_fn, keyset=ks,
                security_level=SEC_CENC if params.get("enc") else SEC_CMAC)

        def _ok(res):
            self.tools_panel.write.append_gp_lines(res.log)
            self.tools_panel.log_write(op, res.response)
            r = res.response
            tail = f" (canal seguro SCP{res.protocol})" if res.secured else ""
            self.notify.emit(f"{op.upper()} → SW {r.sw_hex} {cardwrite.write_status(r.sw)}{tail}")

        submit(self.pool, _do, on_result=_ok,
               on_error=lambda m: self.notify.emit(f"Escritura: {m}"))

    # -- GlobalPlatform: canal seguro + gestión de contenido ---------------
    def gp_op(self, action: str, keyset_name: str, *, enc: bool = False, **kw) -> None:
        if not self._need_reader():
            return
        from ..project import store
        proj = store.active_project()
        ks = store.get_keyset(proj, keyset_name) if proj else None
        if not ks:
            self.notify.emit(f"Keyset {keyset_name!r} no existe."); return
        send = self.active_send()
        self.console.banner(f"GP {action} (keyset {ks.name})")

        def _do():
            from ..core.gp import apdu as gpapdu
            from ..core.gp import cap as capmod
            from ..core.gp import content
            from ..core.gp.scp import SEC_CENC, SEC_CMAC
            chan = content.authenticate(send, ks, security_level=SEC_CENC if enc else SEC_CMAC)
            lines = [f"Canal seguro: SCP{chan.protocol} (keyset {ks.name})"]
            if action == "status":
                inv = content.list_all(chan)
                for key, label in (("isd", "ISD"), ("apps", "Apps/SD"),
                                   ("load_files", "Paquetes")):
                    lines.append(f"── {label} ──")
                    if not inv[key]:
                        lines.append("  (ninguno)")
                    for a in inv[key]:
                        lines.append(f"  {a.aid}  {a.lifecycle}  {a.privileges}")
                        lines += [f"      └ módulo {m}" for m in a.modules]
            elif action == "delete":
                content.delete(chan, from_hex(kw["aid"]), related=kw.get("related", True))
                lines.append(f"DELETE {kw['aid']} OK")
            elif action == "wipe":
                res = content.restore_virgin(
                    chan, keep_aids=kw.get("keep", ()),
                    delete_packages=kw.get("packages", False))
                lines += res.log
            elif action == "instantiate":
                content.install_instance(
                    chan, from_hex(kw["package"]), from_hex(kw["module"]),
                    from_hex(kw["instance"]),
                    make_selectable=not kw.get("no_selectable", False))
                lines.append(f"Instancia creada: {kw['instance']} "
                             f"(módulo {kw['module']})")
            elif action == "install":
                capf = capmod.parse_cap(kw["cap"])
                lines.append(f"CAP: paquete {capf.package_aid_hex}")
                res = content.install_cap(chan, capf, force=kw.get("force", False))
                lines += [f"  {s}: {v}" for s, v in res.steps]
                lines.append(f"Instalado: paquete {res.package_aid}"
                             + (f", instancia {res.instance_aid}" if res.instance_aid else ""))
            return lines

        submit(self.pool, _do,
               on_result=lambda lines: self.tools_panel.gp_log(lines),
               on_error=lambda m: self.tools_panel.gp_log([f"✗ GP: {m}"]))

    # -- ISO 8583: enviar a un host ----------------------------------------
    def send_iso8583(self, host: str, port: int, data: bytes, header: int) -> None:
        from ..payments import iso_host
        submit(self.pool,
               lambda: iso_host.send_message(host, port, data, header=header),
               on_result=lambda r: self.tools_panel.iso_response(r),
               on_error=lambda m: self.notify.emit(f"ISO 8583: {m}"))

    # -- Cobros: flujo de switch ISO 8583 ----------------------------------
    def run_switch_flow(self, kind: str, *, amount: int = 500, dry_run: bool = True,
                        sign_on: bool = True) -> None:
        from ..payments import EmvCard, SwitchConfig, switch
        proj = store.active_project()
        variables = ({v.name: v.value for v in store.load_project_variables(proj)}
                     if proj else {})
        cfg = SwitchConfig.from_vars(lambda k: variables.get(k))

        def _do():
            if kind == "signon":
                return switch.run_signon(cfg)
            if kind == "reversal":
                return switch.run_reversal(cfg, stan=variables.get("stan", "000001"),
                                           rrn=variables.get("rrn", ""),
                                           amount_cents=amount, dry_run=dry_run, sign_on=sign_on)
            card = EmvCard.from_dump(self.last_dump) if self.last_dump else None
            if card is None:
                raise RuntimeError("Necesitas una tarjeta (captura una en el Explorador).")
            return switch.run_purchase(cfg, card, amount, dry_run=dry_run, sign_on=sign_on)

        def _ok(res):
            if proj:
                try:
                    from datetime import datetime
                    tdir = proj.path / "transactions"; tdir.mkdir(parents=True, exist_ok=True)
                    (tdir / f"{datetime.now():%Y%m%d-%H%M%S}-{kind}.txt").write_text(res.summary())
                except Exception:
                    pass
            self.charges_panel.log_flow(kind, res)

        submit(self.pool, _do, on_result=_ok,
               on_error=lambda m: self.notify.emit(f"Switch: {m}"))

    # -- PoC: ejecutar un plugin del proyecto ------------------------------
    def run_poc(self, poc_id: str, *, dry_run: bool = True, allow_write: bool = False,
                capture_name: str | None = None) -> None:
        from .. import poc as pocmod
        from ..payments import EmvCard
        proj = store.active_project()
        if not proj:
            self.notify.emit("No hay proyecto activo.")
            return

        def _do():
            pocmod.clear(); pocmod.load_plugins(proj)
            p = pocmod.get(poc_id)
            if not p:
                raise RuntimeError(f"PoC {poc_id!r} no encontrado.")
            if capture_name:                     # tarjeta desde una captura guardada
                from ..session.model import CardDump
                path = proj.captures_dir / (capture_name if capture_name.endswith(".json")
                                            else capture_name + ".json")
                card = EmvCard.from_dump(CardDump.from_json(path.read_text()))
            else:
                card = EmvCard.from_dump(self.last_dump) if self.last_dump else None
            run_dir = pocmod.runner.run_dir_for(proj, p.meta.id)
            ctx = pocmod.make_context(proj, card=card, run_dir=run_dir,
                                      dry_run=dry_run, allow_write=allow_write)
            result = pocmod.run_poc(p, ctx)
            pocmod.save_result(ctx, p.meta, result)
            return p.meta, result, run_dir

        submit(self.pool, _do,
               on_result=lambda r: self.poc_panel.show_result(*r),
               on_error=lambda m: self.notify.emit(f"PoC: {m}"))

    # -- Intercept: aplicar reglas / activar -------------------------------
    def apply_intercept(self, text: str):
        from ..core import intercept
        rules, errors = intercept.parse_rules(text)
        self.intercept_rules = rules
        return rules, errors

    # -- BomberCat: compilar / subir firmware ------------------------------
    def compile_firmware(self, sketch_dir: str, *, upload: bool = False, port: str | None = None) -> None:
        from ..integrations import arduino as ard
        self.firmware_panel.log(f"→ {'compilar y subir' if upload else 'compilar'}: {sketch_dir}")

        def _do():
            if upload:
                return ard.upload_sketch(sketch_dir, port=port)
            return ard.compile_sketch(sketch_dir)

        submit(self.pool, _do,
               on_result=lambda r: self.firmware_panel.log_result(r),
               on_error=lambda m: self.notify.emit(f"Firmware: {m}"))

    def setup_usb_permissions(self) -> None:
        """Instala reglas udev + grupos para el BomberCat (via bombercat-tools
        setup-env, elevado con pkexec). Resuelve los fallos de permiso de
        picotool/serie sin tener que hacerlo a mano."""
        from ..integrations import bombercat_tools as bctools
        self.firmware_panel.log("→ configurando permisos USB (udev + grupos)… "
                                "acepta el diálogo de elevación si aparece.")

        def _do():
            return bctools.setup_env_gui()

        submit(self.pool, _do,
               on_result=lambda r: (self.firmware_panel.log_result(r),
                                    self.notify.emit("Permisos USB: revisa el log "
                                                     "(reconecta el BomberCat tras aplicar).")),
               on_error=lambda m: (self.firmware_panel.log(f"✗ {m}"),
                                   self.notify.emit(f"Permisos USB: {m}")))


def _harden_qt_env() -> None:
    """Evita SIGSEGV al arrancar en Linux: PySide6 trae su **propio** Qt, y
    cargar plugins del **sistema** (tema de plataforma KDE/gtk, estilo, portal)
    compilados contra otra build de Qt provoca un mismatch de ABI que revienta
    el proceso. Neutraliza las variables que fuerzan esos plugins del sistema.
    Opt-out con `EMVY_GUI_KEEP_QT_ENV=1` (si tu Qt del sistema coincide).
    """
    import os
    if not sys.platform.startswith("linux") or os.environ.get("EMVY_GUI_KEEP_QT_ENV"):
        return
    os.environ["QT_QPA_PLATFORMTHEME"] = ""        # no cargar tema del sistema (KDE/gtk3…)
    os.environ.pop("QT_STYLE_OVERRIDE", None)       # ni un estilo del sistema
    # Deja que Qt elija plataforma (wayland;xcb ya trae fallback a xcb); se puede
    # forzar con QT_QPA_PLATFORM=xcb si el compositor Wayland da problemas.


def run_gui(argv=None) -> int:
    _harden_qt_env()
    # PC/SC: activar `pcscd.socket` si hace falta (igual que hace `cli.main`),
    # porque la GUI empaquetada (AppImage/.exe) NO pasa por la CLI. El daemon
    # `pcscd` y el driver CCID son del SISTEMA (no se empaquetan); esto solo
    # arranca su socket. `ensure_started` nunca lanza; devuelve True solo si lo
    # activó este proceso, para pararlo al salir.
    from ..integrations import pcscd
    started_pcscd = pcscd.ensure_started()

    app = QApplication.instance() or QApplication(argv or sys.argv)
    app.setApplicationName("EMVy Controller")
    app.setStyle("Fusion")     # base estable; encima va nuestro QSS (tema oscuro pro)
    from .brand import brand_icon
    from .theme import ACCENT, apply_theme
    app.setWindowIcon(brand_icon("logo", ACCENT))
    apply_theme(app)
    win = MainWindow()
    win.show()
    try:
        return app.exec()
    finally:
        if started_pcscd:
            pcscd.stop()
