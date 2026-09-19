"""Paneles BomberCat (GUI) — **un Tab de nivel superior por firmware** (ADR-001).

La placa corre **una** imagen a la vez; cada firmware oficial es un modo/herramienta
distinto, así que cada uno es su propio panel (Tab), no un sub-tab de un panel único:

* **DevicePanel** (*Dispositivo*) — control-plane común, **siempre habilitado**: estado de
  la placa (firmware + capacidades vía `bombercat status`), identificar (LED), permisos USB
  (udev), flasheo de imágenes `.uf2` **oficiales** (`bombercat flash`) y, como sección "dev",
  compilar/subir el firmware propio de `firmware/` con arduino-cli. Es el **único** panel que
  posee el puerto serie compartido y el que flashea.
* **TagsPanel** / **ReadersPanel** / **MagspoofPanel** / **MifarePanel** / **RelayPanel** —
  paneles **gated** por capacidad (`tags`/`readers`/`magspoof`/`mifare`/`relay`): arrancan
  deshabilitados y `set_status()` los habilita solo si la placa corre el firmware que aporta
  esa capacidad; si no, cada uno ofrece **flashear su imagen** en su propia cabecera (una
  "pill" de estado en vivo + botón contextual), sin obligar a saltar al panel Dispositivo.

`BaseFirmwarePanel` centraliza el gating (`set_status` → pill + `setEnabled(cap in caps)`), el
acceso al **puerto único** (`port()` → `DevicePanel`) y el `log`/`log_result`. Todo el trabajo
de hardware pasa por métodos de `MainWindow` (worker en `QThreadPool`); los paneles solo mueven
widgets y señales.

**Requiere bombercat-tools >= v1.3.0** (los subcomandos `status`/`identify`/`tags mifare`/
`magspoof`/`relay`). El submódulo de este repo está clavado a v1.2.0.0; súbelo para operar
hardware real (ver `emvy/integrations/bombercat_tools.py`).
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QFrame, QGroupBox, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QSpinBox,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ...integrations import arduino as ard

_MONO = QFont("monospace"); _MONO.setStyleHint(QFont.Monospace)


def _set_prop(w: QWidget, name: str, value) -> None:
    """Fija una propiedad dinámica y re-aplica el QSS (necesario para que el
    selector `QLabel[prop="..."]` del tema surta efecto al cambiar en vivo)."""
    w.setProperty(name, value)
    w.style().unpolish(w); w.style().polish(w)


class BaseFirmwarePanel(QWidget):
    """Base común de los paneles de firmware: gating por capacidad, puerto serie
    compartido, cabecera con pill de estado y log. Los paneles gated declaran su
    `capability`; el control-plane deja `capability = None` (siempre habilitado)."""

    #: capacidad que habilita el panel (`None` = control-plane, siempre activo).
    capability: str | None = None
    #: imagen oficial a flashear para habilitar este firmware.
    needs_image: str = ""
    #: título e intro mostrados en la cabecera.
    title: str = ""
    intro: str = ""

    def __init__(self, win) -> None:
        super().__init__()
        self.win = win
        self.caps: list[str] = []
        self._log = QPlainTextEdit(readOnly=True)
        self._log.setFont(_MONO)
        self._log.setMaximumBlockCount(4000)
        # Estructura: [cabecera SIEMPRE activa] · [cuerpo gated] · [log].
        # El cuerpo (self.body) es lo que se deshabilita cuando falta la
        # capacidad; la cabecera (pill + botón «Flashear») queda activa para
        # que el usuario pueda habilitar el panel flasheando su imagen — si se
        # deshabilitara todo el panel, ese botón quedaría inutilizable (en Qt un
        # hijo de un widget deshabilitado no se puede reactivar).
        self._outer = QVBoxLayout(self)
        self._outer.addWidget(self._header())
        self._body = QWidget()
        self.body = QVBoxLayout(self._body)
        self.body.setContentsMargins(0, 0, 0, 0)
        self._outer.addWidget(self._body, 1)
        self._outer.addWidget(self._log, 1)
        if self.capability is not None:
            self._body.setEnabled(False)  # gated hasta que llegue el status

    # -- puerto serie único (vive en el DevicePanel; los demás lo leen) -----
    def port(self) -> str | None:
        return self.win.firmware_port()

    # -- gating por capacidad ----------------------------------------------
    def set_status(self, st: dict) -> None:
        """Actualiza capacidades, pill de estado y (si es gated) habilitación."""
        self.caps = list(st.get("capabilities", []))
        if self.capability is not None:
            active = self.capability in self.caps
            self._body.setEnabled(active)
            self._update_pill(active)
        self.on_status(st)

    def on_status(self, st: dict) -> None:
        """Hook para subclases (p.ej. el DevicePanel pinta la cabecera)."""

    def _update_pill(self, active: bool) -> None:
        if not hasattr(self, "_pill"):
            return
        if active:
            self._pill.setText("● activo")
            _set_prop(self._pill, "pill", "on")
            self._flash_btn.setVisible(False)
        else:
            self._pill.setText(f"○ requiere {self.needs_image}")
            _set_prop(self._pill, "pill", "off")
            self._flash_btn.setVisible(True)

    # -- log ----------------------------------------------------------------
    def log(self, text: str) -> None:
        self._log.appendPlainText(text)

    def log_result(self, res) -> None:
        rc = getattr(res, "returncode", "?")
        out = (getattr(res, "stdout", "") or "")[-2000:]
        err = (getattr(res, "stderr", "") or "")[-800:]
        self._log.appendPlainText(f"── returncode {rc} ──")
        if out:
            self._log.appendPlainText(out)
        if err:
            self._log.appendPlainText(err)

    # -- helpers de UI compartidos -----------------------------------------
    @staticmethod
    def _hint(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setProperty("hint", "true")          # → color tenue del tema (theme.py)
        return lbl

    @staticmethod
    def _h2(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setProperty("h2", "true")
        return lbl

    def _header(self) -> QWidget:
        """Cabecera común: título + intro y, para paneles gated, una pill de estado
        (activo / requiere flashear) con botón de flasheo contextual a la derecha."""
        box = QWidget()
        v = QVBoxLayout(box); v.setContentsMargins(0, 0, 0, 0)
        top = QHBoxLayout()
        top.addWidget(self._h2(self.title))
        top.addStretch(1)
        if self.capability is not None:
            self._pill = QLabel("○ deshabilitado")
            _set_prop(self._pill, "pill", "off")
            self._flash_btn = QPushButton(f"Flashear {self.needs_image}")
            self._flash_btn.setToolTip(
                f"Flashea la imagen «{self.needs_image}» para habilitar esta función.")
            self._flash_btn.clicked.connect(
                lambda: self.win.flash_image(self.needs_image, port=self.port()))
            top.addWidget(self._pill)
            top.addWidget(self._flash_btn)
        v.addLayout(top)
        if self.intro:
            v.addWidget(self._hint(self.intro))
        return box

    def _kv_table(self, headers=("Campo", "Valor")) -> QTableWidget:
        """Tabla de 2 columnas (las claves del JSON varían por firmware)."""
        t = QTableWidget(0, 2)
        t.setHorizontalHeaderLabels(list(headers))
        t.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        t.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        t.setSelectionBehavior(QAbstractItemView.SelectRows)
        t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        t.verticalHeader().setVisible(False)
        return t

    @staticmethod
    def _fill_kv(table: QTableWidget, data: dict) -> None:
        rows = list(data.items())
        table.setRowCount(len(rows))
        for i, (k, v) in enumerate(rows):
            table.setItem(i, 0, QTableWidgetItem(str(k)))
            table.setItem(i, 1, QTableWidgetItem("—" if v is None else str(v)))


class DevicePanel(BaseFirmwarePanel):
    """Control-plane común (siempre habilitado): estado + flasheo + firmware propio.
    Posee el **puerto serie único** que el resto de paneles lee vía `MainWindow`."""

    capability = None
    title = "Dispositivo"
    intro = ("Estado y flasheo de la placa BomberCat. Corre UNA imagen a la vez: "
             "refresca el estado para ver cuál y sus capacidades — se habilitan los "
             "paneles de firmware correspondientes.")

    def __init__(self, win) -> None:
        super().__init__(win)
        self._port = QLineEdit()
        self._port.setPlaceholderText("puerto (opcional, p.ej. /dev/ttyACM0)")
        self._port.setFixedWidth(260)
        prow = QHBoxLayout()
        prow.addWidget(QLabel("Puerto"))
        prow.addWidget(self._port)
        prow.addStretch(1)

        self.body.addLayout(prow)
        self.body.addWidget(self._build_device_group())
        self.body.addWidget(self._build_flash_group())
        self.body.addStretch(1)
        self.reload()

    def port(self) -> str | None:
        return self._port.text().strip() or None

    def _build_device_group(self) -> QGroupBox:
        box = QGroupBox("Estado de la placa")
        v = QVBoxLayout(box)

        # cabecera: nombre de firmware prominente + pill de detección
        self._l_name = QLabel("—")
        f = self._l_name.font(); f.setPointSize(f.pointSize() + 3); f.setBold(True)
        self._l_name.setFont(f)
        self._l_name.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._det_pill = QLabel("sin refrescar")
        _set_prop(self._det_pill, "pill", "off")
        hrow = QHBoxLayout()
        hrow.addWidget(self._l_name)
        hrow.addStretch(1)
        hrow.addWidget(self._det_pill)
        v.addLayout(hrow)

        self._l_ver = QLabel("—")
        self._l_caps = QLabel("—"); self._l_caps.setWordWrap(True)
        for title, lbl in (("Versión", self._l_ver), ("Capacidades", self._l_caps)):
            lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
            r = QHBoxLayout()
            t = QLabel(title); t.setFixedWidth(96); t.setProperty("hint", "true")
            r.addWidget(t); r.addWidget(lbl, 1)
            v.addLayout(r)

        refresh = QPushButton("Refrescar estado"); refresh.setProperty("accent", True)
        refresh.clicked.connect(lambda: self.win.refresh_device())
        ident = QPushButton("Identificar (LED)")
        ident.setToolTip("Parpadea el LED de la placa para localizarla.")
        ident.clicked.connect(lambda: self.win.identify_device())
        udev = QPushButton("Permisos USB (udev)…")
        udev.setToolTip("Instala reglas udev + grupos (dialout/plugdev) para subir sin "
                        "sudo.\nRequiere pkexec (pedirá contraseña de administrador).")
        udev.clicked.connect(lambda: self.win.setup_usb_permissions())
        btns = QHBoxLayout()
        btns.addWidget(refresh); btns.addWidget(ident); btns.addWidget(udev)
        btns.addStretch(1)
        v.addLayout(btns)
        return box

    def _build_flash_group(self) -> QGroupBox:
        box = QGroupBox("Flashear")
        lay = QVBoxLayout(box)

        # Imágenes oficiales (bombercat flash)
        lay.addWidget(self._h2("Imágenes oficiales (bombercat-tools)"))
        self._image = QComboBox(); self._image.setMinimumWidth(220)
        rel_img = QPushButton("Recargar lista"); rel_img.clicked.connect(self.reload_images)
        flash = QPushButton("Flashear imagen"); flash.setProperty("accent", True)
        flash.clicked.connect(self._do_flash)
        orow = QHBoxLayout()
        orow.addWidget(QLabel("Imagen")); orow.addWidget(self._image, 1)
        orow.addWidget(rel_img); orow.addWidget(flash)
        lay.addLayout(orow)
        lay.addWidget(self._hint("Flashear reescribe toda la imagen y BORRA la config "
                                 "guardada (WiFi/relay de NFCGate). Se pedirá confirmación."))

        sep = QFrame(); sep.setFrameShape(QFrame.HLine); lay.addWidget(sep)

        # Firmware propio (dev) — arduino-cli / picotool
        lay.addWidget(self._h2("Firmware propio (dev)"))
        self._sketch = QComboBox()
        comp = QPushButton("Compilar"); comp.clicked.connect(lambda: self._go(False))
        upl = QPushButton("Compilar y subir"); upl.clicked.connect(lambda: self._go(True))
        rel = QPushButton("Recargar"); rel.clicked.connect(self.reload)
        drow = QHBoxLayout()
        drow.addWidget(QLabel("Sketch")); drow.addWidget(self._sketch, 1)
        drow.addWidget(comp); drow.addWidget(upl); drow.addWidget(rel)
        lay.addLayout(drow)
        return box

    def on_status(self, st: dict) -> None:
        self._l_name.setText(st.get("name") or "—")
        self._l_ver.setText(st.get("version") or "—")
        self._l_caps.setText(", ".join(self.caps) or "—")
        detected = (st.get("detected") or "").strip().lower() in ("yes", "sí", "si", "true", "1")
        self._det_pill.setText("detectada" if detected else (st.get("detected") or "no detectada"))
        _set_prop(self._det_pill, "pill", "on" if detected else "off")

    def reload(self) -> None:
        """Recarga los sketches locales (sección dev). No toca el venv del vendor."""
        self._sketch.clear()
        if not ard.arduino_cli_available():
            self._log.appendPlainText("arduino-cli no disponible (instálalo para compilar/subir).")
        try:
            for p in ard.list_sketches():
                self._sketch.addItem(p.name, str(p))
        except Exception as e:  # noqa: BLE001
            self._log.appendPlainText(f"No se pudieron listar sketches: {e}")
        if self._sketch.count() == 0:
            self._sketch.addItem("(sin sketches en firmware/)", "")

    def reload_images(self) -> None:
        """Recarga las imágenes oficiales (arranca el venv del vendor la primera
        vez → va por worker en `MainWindow`)."""
        self.win.reload_flash_images()

    def set_images(self, names: list[str]) -> None:
        cur = self._image.currentData()
        self._image.clear()
        for n in names:
            self._image.addItem(n, n)
        if not names:
            self._image.addItem("(sin imágenes)", "")
        if cur:
            i = self._image.findData(cur)
            if i >= 0:
                self._image.setCurrentIndex(i)

    def _do_flash(self) -> None:
        name = self._image.currentData()
        if not name:
            self.win.notify.emit("No hay imagen seleccionada.")
            return
        self.win.flash_image(name, port=self.port())

    def _go(self, upload: bool) -> None:
        sketch = self._sketch.currentData()
        if not sketch:
            self.win.notify.emit("No hay sketch seleccionado.")
            return
        self.win.compile_firmware(sketch, upload=upload, port=self.port())


class TagsPanel(BaseFirmwarePanel):
    """DetectTags (gated:tags): lee un tag NFC y muestra UID/tech/protocolo/modelo."""

    capability = "tags"; needs_image = "DetectTags"
    title = "Tags"
    intro = ("Lee un tag NFC (DetectTags): espera a que se acerque una tarjeta y "
             "muestra UID, tecnología, protocolo y modelo resuelto host-side.")

    def __init__(self, win) -> None:
        super().__init__(win)
        self._timeout = QSpinBox(); self._timeout.setRange(1, 120); self._timeout.setValue(15)
        self._timeout.setSuffix(" s")
        read = QPushButton("Leer tag"); read.setProperty("accent", True)
        read.clicked.connect(lambda: self.win.tags_read(self._timeout.value()))
        row = QHBoxLayout()
        row.addWidget(QLabel("Timeout")); row.addWidget(self._timeout)
        row.addWidget(read); row.addStretch(1)

        self._table = self._kv_table()
        self.body.addLayout(row)
        self.body.addWidget(self._table, 1)

    def show_tag(self, data) -> None:
        if isinstance(data, list):
            data = data[0] if data else {}
        self._fill_kv(self._table, data or {})


class ReadersPanel(BaseFirmwarePanel):
    """DetectReaders (gated:readers): detecta un lector/POS y su primer APDU."""

    capability = "readers"; needs_image = "DetectReaders"
    title = "Readers"
    intro = ("Detecta un lector/POS (DetectReaders): espera a que un terminal consulte "
             "la placa y muestra su primer APDU (p.ej. SELECT PPSE).")

    def __init__(self, win) -> None:
        super().__init__(win)
        self._timeout = QSpinBox(); self._timeout.setRange(1, 120); self._timeout.setValue(15)
        self._timeout.setSuffix(" s")
        read = QPushButton("Detectar lector"); read.setProperty("accent", True)
        read.clicked.connect(lambda: self.win.readers_read(self._timeout.value()))
        row = QHBoxLayout()
        row.addWidget(QLabel("Timeout")); row.addWidget(self._timeout)
        row.addWidget(read); row.addStretch(1)

        self._table = self._kv_table()
        self.body.addLayout(row)
        self.body.addWidget(self._table, 1)

    def show_reader(self, data) -> None:
        if isinstance(data, list):
            data = data[0] if data else {}
        self._fill_kv(self._table, data or {})


class MagspoofPanel(BaseFirmwarePanel):
    """magspoof (gated:magspoof): inspecciona/reproduce banda magnética + store."""

    capability = "magspoof"; needs_image = "magspoof"
    title = "Magspoof"
    intro = ("Emulación de banda magnética (magspoof): inspecciona la tarjeta activa, "
             "reprodúcela (swipe), gestiona el store y emula Visa por NFC contactless.")

    def __init__(self, win) -> None:
        super().__init__(win)
        # -- tarjeta activa --
        show = QPushButton("Mostrar"); show.clicked.connect(lambda: self.win.magspoof_show())
        play = QPushButton("Reproducir"); play.setProperty("accent", True)
        play.clicked.connect(lambda: self.win.magspoof_play())
        nfc = QPushButton("Emular Visa (NFC)"); nfc.clicked.connect(lambda: self.win.magspoof_nfc_visa())
        arow = QHBoxLayout()
        arow.addWidget(show); arow.addWidget(play); arow.addWidget(nfc); arow.addStretch(1)
        self._table = self._kv_table()
        active = QGroupBox("Tarjeta activa")
        al = QVBoxLayout(active); al.addLayout(arow); al.addWidget(self._table, 1)

        # -- store persistente --
        lst = QPushButton("Listar"); lst.clicked.connect(lambda: self.win.magspoof_card_list())
        self._card_name = QComboBox(); self._card_name.setEditable(True); self._card_name.setMinimumWidth(160)
        sel = QPushButton("Seleccionar")
        sel.clicked.connect(lambda: self.win.magspoof_card_select(self._card_name.currentText().strip()))
        srow = QHBoxLayout()
        srow.addWidget(lst); srow.addWidget(QLabel("Tarjeta")); srow.addWidget(self._card_name)
        srow.addWidget(sel); srow.addStretch(1)

        self._cards_table = self._kv_table(("Tarjeta", "Datos"))
        self._add_name = QLineEdit(); self._add_name.setPlaceholderText("nombre"); self._add_name.setFixedWidth(120)
        self._add_t1 = QLineEdit(); self._add_t1.setPlaceholderText("Track 1 (%B…?)")
        self._add_t2 = QLineEdit(); self._add_t2.setPlaceholderText("Track 2 (;…?)")
        add = QPushButton("Agregar")
        add.clicked.connect(lambda: self.win.magspoof_card_add(
            self._add_name.text().strip(), self._add_t1.text().strip(), self._add_t2.text().strip()))
        frow = QHBoxLayout()
        frow.addWidget(QLabel("Nombre")); frow.addWidget(self._add_name)
        frow.addWidget(self._add_t1, 1); frow.addWidget(self._add_t2, 1); frow.addWidget(add)

        store = QGroupBox("Tarjetas guardadas")
        sl = QVBoxLayout(store); sl.addLayout(srow); sl.addWidget(self._cards_table, 1); sl.addLayout(frow)

        self.body.addWidget(active, 1)
        self.body.addWidget(store, 1)

    def show_magspoof(self, data) -> None:
        if isinstance(data, list):
            data = data[0] if data else {}
        data = data or {}
        flat = {k: v for k, v in data.items() if k != "analysis"}
        for k, v in (data.get("analysis") or {}).items():
            flat[f"analysis.{k}"] = v
        self._fill_kv(self._table, flat)

    def show_cards(self, cards) -> None:
        cards = cards if isinstance(cards, list) else [cards] if cards else []
        self._cards_table.setRowCount(len(cards))
        names: list[str] = []
        for i, c in enumerate(cards):
            name = str(c.get("name", "")) if isinstance(c, dict) else str(c)
            names.append(name)
            rest = ({k: v for k, v in c.items() if k != "name"} if isinstance(c, dict) else {})
            self._cards_table.setItem(i, 0, QTableWidgetItem(name))
            self._cards_table.setItem(i, 1, QTableWidgetItem(", ".join(f"{k}={v}" for k, v in rest.items())))
        cur = self._card_name.currentText()
        self._card_name.clear()
        self._card_name.addItems([n for n in names if n])
        if cur:
            self._card_name.setEditText(cur)


class MifarePanel(BaseFirmwarePanel):
    """MifareClassic (gated:mifare): recuperación de claves + volcado/restauración.

    Flujo en tres pasos con ficheros intermedios en `<proyecto>/artifacts/`:
    **Claves** (diccionario) → **Recuperar+Volcar** (check → keyfile → dump → JSON)
    → **Restaurar** (escribe un dump de vuelta). El dump es un JSON de tarjeta Mifare
    (uid + bloques por sector), NO un CardDump EMV: se guarda como artefacto."""

    capability = "mifare"; needs_image = "MifareClassic"
    title = "Mifare"
    intro = ("Mifare Classic: acerca una tarjeta y el firmware abre la sesión solo. "
             "«Recuperar y volcar» prueba el diccionario de claves contra cada sector, "
             "guarda las recuperadas y vuelca la tarjeta a un JSON en artifacts/. "
             "«Restaurar» escribe un dump de vuelta a una tarjeta reescribible.")

    def __init__(self, win) -> None:
        super().__init__(win)
        self.body.addWidget(self._build_dump_group())
        self.body.addWidget(self._build_restore_group(), 1)

    def _build_dump_group(self) -> QGroupBox:
        box = QGroupBox("Recuperar claves y volcar")
        v = QVBoxLayout(box)
        self._sectors = QSpinBox(); self._sectors.setRange(1, 40); self._sectors.setValue(16)
        self._sectors.setToolTip("16 = tarjeta de 1K; 40 = 4K.")
        keys = QPushButton("Ver claves por defecto"); keys.clicked.connect(lambda: self.win.mifare_keys())
        dump = QPushButton("Recuperar y volcar"); dump.setProperty("accent", True)
        dump.setToolTip("check → recupera las claves de cada sector → dump → JSON en "
                        "artifacts/. Requiere un proyecto activo.")
        dump.clicked.connect(lambda: self.win.mifare_dump(self._sectors.value()))
        row = QHBoxLayout()
        row.addWidget(QLabel("Sectores")); row.addWidget(self._sectors)
        row.addWidget(keys); row.addWidget(dump); row.addStretch(1)
        v.addLayout(row)
        self._keys_table = self._kv_table(("Clave", "Valor"))
        v.addWidget(self._keys_table)
        self._dump_table = self._kv_table()
        v.addWidget(self._dump_table)
        return box

    def _build_restore_group(self) -> QGroupBox:
        box = QGroupBox("Restaurar")
        v = QVBoxLayout(box)
        self._dumps = QComboBox(); self._dumps.setMinimumWidth(220)
        rel = QPushButton("Recargar dumps"); rel.clicked.connect(self.reload_dumps)
        restore = QPushButton("Restaurar a la tarjeta")
        restore.setToolTip("Escribe el dump seleccionado de vuelta a una tarjeta Mifare "
                           "reescribible. No reescribe el bloque 0 (UID).")
        restore.clicked.connect(self._do_restore)
        row = QHBoxLayout()
        row.addWidget(QLabel("Dump")); row.addWidget(self._dumps, 1)
        row.addWidget(rel); row.addWidget(restore)
        v.addLayout(row)
        v.addWidget(self._hint("Los dumps son los JSON de artifacts/ generados por «Recuperar "
                               "y volcar». Restaurar sobrescribe bloques de datos y trailers."))
        return box

    def show_keys(self, keys) -> None:
        keys = keys if isinstance(keys, list) else [keys] if keys else []
        self._keys_table.setRowCount(len(keys))
        for i, k in enumerate(keys):
            name = str(k.get("name", "")) if isinstance(k, dict) else str(k)
            val = str(k.get("key", "")) if isinstance(k, dict) else ""
            self._keys_table.setItem(i, 0, QTableWidgetItem(name))
            self._keys_table.setItem(i, 1, QTableWidgetItem(val))

    def show_dump(self, data) -> None:
        if isinstance(data, list):
            data = data[0] if data else {}
        data = data or {}
        sectors = data.get("sectors") or data.get("sector_results") or []
        summary = {"uid": data.get("uid"),
                   "sectores": len(sectors) if isinstance(sectors, (list, dict)) else sectors}
        self._fill_kv(self._dump_table, summary)

    def set_dumps(self, names: list[str]) -> None:
        cur = self._dumps.currentData()
        self._dumps.clear()
        for n in names:
            self._dumps.addItem(n, n)
        if not names:
            self._dumps.addItem("(sin dumps en artifacts/)", "")
        if cur:
            i = self._dumps.findData(cur)
            if i >= 0:
                self._dumps.setCurrentIndex(i)

    def reload_dumps(self) -> None:
        self.win.mifare_reload_dumps()

    def _do_restore(self) -> None:
        name = self._dumps.currentData()
        if not name:
            self.win.notify.emit("Mifare: no hay dump seleccionado.")
            return
        self.win.mifare_restore(name)


class RelayPanel(BaseFirmwarePanel):
    """NFCGate (gated:relay): configura/arranca el relay APDU sobre WiFi/TCP contra
    un `nfcgate-server`, y captura los APDUs relayados a `.pcap`.

    Control-plane: no habla APDUs por serie (los relaya el firmware sobre WiFi entre
    dos peers); aquí solo se configura, arranca/detiene y se observa el estado — más
    la captura, que sí toca la serie. Necesita DOS placas NFCGate (rol reader/card)."""

    capability = "relay"; needs_image = "NFCGate"
    title = "Relay NFCGate"
    intro = ("Relaya APDUs entre un lector y una tarjeta a través de un nfcgate-server. "
             "Necesita DOS placas NFCGate (una «reader», otra «card») contra el mismo "
             "servidor y sesión. Control-plane: sin tráfico APDU por serie salvo al capturar.")

    def __init__(self, win) -> None:
        super().__init__(win)
        self.body.addWidget(self._build_config_group())
        self.body.addWidget(self._build_run_group())
        self.body.addWidget(self._build_capture_group())

    def _build_config_group(self) -> QGroupBox:
        box = QGroupBox("Configuración (persistida en flash)")
        v = QVBoxLayout(box)
        self._ssid = QLineEdit(); self._ssid.setPlaceholderText("SSID")
        self._password = QLineEdit(); self._password.setPlaceholderText("contraseña (vacío = red abierta)")
        self._password.setEchoMode(QLineEdit.Password)
        self._wifi_save = QCheckBox("Guardar"); self._wifi_save.setChecked(True)
        wifi_btn = QPushButton("Aplicar WiFi"); wifi_btn.clicked.connect(self._do_config_wifi)
        wrow = QHBoxLayout()
        wrow.addWidget(QLabel("WiFi")); wrow.addWidget(self._ssid, 1); wrow.addWidget(self._password, 1)
        wrow.addWidget(self._wifi_save); wrow.addWidget(wifi_btn)
        v.addLayout(wrow)

        self._server = QLineEdit(); self._server.setPlaceholderText("nfcgate-server: host[:puerto]")
        self._session = QSpinBox(); self._session.setRange(1, 255); self._session.setValue(1)
        self._role = QComboBox()
        self._role.addItem("reader (lee una tarjeta física)", "reader")
        self._role.addItem("card (la emula a un terminal)", "card")
        self._nfcgate_save = QCheckBox("Guardar"); self._nfcgate_save.setChecked(True)
        nfc_btn = QPushButton("Aplicar NFCGate"); nfc_btn.clicked.connect(self._do_config_nfcgate)
        nrow = QHBoxLayout()
        nrow.addWidget(QLabel("Servidor")); nrow.addWidget(self._server, 1)
        nrow.addWidget(QLabel("Sesión")); nrow.addWidget(self._session)
        nrow.addWidget(self._role); nrow.addWidget(self._nfcgate_save); nrow.addWidget(nfc_btn)
        v.addLayout(nrow)

        show = QPushButton("Ver configuración"); show.clicked.connect(lambda: self.win.relay_config_show())
        srow = QHBoxLayout(); srow.addWidget(show); srow.addStretch(1)
        v.addLayout(srow)
        self._config_table = self._kv_table()
        v.addWidget(self._config_table)
        return box

    def _build_run_group(self) -> QGroupBox:
        box = QGroupBox("Relay")
        v = QVBoxLayout(box)
        run = QPushButton("Iniciar"); run.setProperty("accent", True)
        run.setToolTip("Asocia WiFi, conecta al servidor y arranca la sesión. Puede tardar "
                       "hasta ~45 s en llegar a 'relaying'.")
        run.clicked.connect(lambda: self.win.relay_run())
        stop = QPushButton("Detener"); stop.clicked.connect(lambda: self.win.relay_stop())
        status = QPushButton("Actualizar estado"); status.clicked.connect(lambda: self.win.relay_status())
        row = QHBoxLayout()
        row.addWidget(run); row.addWidget(stop); row.addWidget(status); row.addStretch(1)
        v.addLayout(row)
        self._status_table = self._kv_table()
        v.addWidget(self._status_table)
        return box

    def _build_capture_group(self) -> QGroupBox:
        box = QGroupBox("Capturar APDUs relayados (pcap)")
        v = QVBoxLayout(box)
        self._duration = QSpinBox(); self._duration.setRange(5, 600); self._duration.setValue(30)
        self._duration.setSuffix(" s")
        cap = QPushButton("Capturar a artifacts/")
        cap.setToolTip("Arma el tap, escribe un .pcap en el proyecto activo durante la "
                       "duración indicada y lo desarma. El relay debe estar corriendo.")
        cap.clicked.connect(lambda: self.win.relay_capture(self._duration.value()))
        row = QHBoxLayout()
        row.addWidget(QLabel("Duración")); row.addWidget(self._duration); row.addWidget(cap)
        row.addStretch(1)
        v.addLayout(row)
        v.addWidget(self._hint("El comando del vendor captura sin límite (hasta Ctrl-C); aquí "
                               "se acota a la duración y siempre se desarma el tap al terminar."))
        return box

    def show_config(self, data: dict) -> None:
        self._fill_kv(self._config_table, data or {})

    def show_status(self, data: dict) -> None:
        self._fill_kv(self._status_table, data or {})

    def _do_config_wifi(self) -> None:
        ssid = self._ssid.text().strip()
        if not ssid:
            self.win.notify.emit("Relay: indica el SSID.")
            return
        self.win.relay_config_wifi(ssid, self._password.text(), save=self._wifi_save.isChecked())

    def _do_config_nfcgate(self) -> None:
        server = self._server.text().strip()
        if not server:
            self.win.notify.emit("Relay: indica el nfcgate-server (host[:puerto]).")
            return
        self.win.relay_config_nfcgate(server, self._session.value(), self._role.currentData(),
                                      save=self._nfcgate_save.isChecked())


# Compat: el nombre histórico apunta al panel de control-plane (posee el puerto,
# compila el firmware propio y flashea) — así el código que referencia
# `FirmwarePanel`/`firmware_panel` sigue funcionando.
FirmwarePanel = DevicePanel

#: Orden de los paneles de firmware (id de pestaña → clase) para el wiring de app.py.
FIRMWARE_PANELS = (
    ("device", DevicePanel),
    ("tags", TagsPanel),
    ("readers", ReadersPanel),
    ("magspoof", MagspoofPanel),
    ("mifare", MifarePanel),
    ("relay", RelayPanel),
)
