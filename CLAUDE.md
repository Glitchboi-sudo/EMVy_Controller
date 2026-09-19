# EMVyController — guía del proyecto y wiki de la herramienta

> **Qué es**: una suite **funcional** en Python para **pruebas de seguridad autorizadas
> sobre tarjetas bancarias**. Controla múltiples lectores (chip EMV vía PC/SC, NFC/contactless
> y banda magnética), organiza el trabajo en **proyectos**, gestiona **variables de entorno**
> (perfil de terminal EMV + variables libres) y ofrece una **TUI rica** (Textual) más una
> **CLI** para scripting.
>
> **Uso previsto**: pentest/laboratorio/CTF con tarjetas **propias o de laboratorio**. La
> herramienta **lee y explora**; los valores de terminal son de laboratorio y no generan
> transacciones válidas. No usar contra tarjetas ajenas ni para fraude.

Este archivo es a la vez las **instrucciones para trabajar en el repo** y la **wiki** de la
herramienta. Manténlo actualizado cuando cambie la arquitectura.

---

## 1. Arquitectura (por capas, de dentro hacia afuera)

El principio rector es **programación funcional**: un **núcleo puro** sin IO ni estado global, y
los **efectos en los bordes** (lectores, disco, terminal). La lógica se escribe como **funciones
reutilizables** que reciben sus dependencias como argumentos.

```
emvy/
├── core/        ── PURO (sin IO): calculable y testeable sin tarjeta ni lector
│   ├── hexutil.py   to_hex/from_hex/hexdump/ascii_printable/ascii_only/chunk
│   ├── apdu.py      APDU/Response/TraceEvent, status words, constructores, make_transceiver()
│   ├── tlv.py       BER-TLV parse()/encode() (inversos), DOL parse/build, interpretación
│   ├── tags.py      diccionario de tags EMV + tag_fmt/tag_name/is_constructed
│   ├── aids.py      AIDs/RIDs conocidos, nombres PSE/PPSE, rid_scheme()
│   ├── atr.py       describe_atr()
│   ├── track.py     pistas de banda magnética (Track 1/2/3) + Track2 EMV (tag 57)
│   ├── emv.py       flujo EMV sobre un `send`: discover/select/GPO/AFL/records/GET DATA
│   ├── rawscan.py   escaneo CRUDO (cualquier ISO 7816): SELECT por RID parcial + AIDs, READ RECORD, GET DATA, READ BINARY; read_type4_ndef() lee un tag NFC Forum Type 4 (NDEF) siguiendo la spec (SELECT AID→CC→fichero NDEF)
│   ├── ndef.py      NDEF puro: parse_records() (Texto/URI/MIME…), find_ndef_tlv() (TLV 0x03 en CC/fichero NDEF), summarize()
│   ├── cardwrite.py ESCRITURA en tarjeta: UPDATE RECORD/BINARY, PUT DATA, APPEND RECORD + write_status() + write_hint() (pista accionable en llano por SW)
│   ├── cardfuzz.py  plantillas para PROBAR terminales/POS: pistas mutadas (magspoof) + registros EMV mutados (para escribir) + personalize_record() (registro '70' amistoso PAN/caducidad/titular→5A/57/5F24/5F20, base de la personalización rápida de Escritura) + TEST_RECORD
│   ├── emvbits.py   decodificadores de bits: AIP/AUC/TTQ (Flag name/is_set)
│   ├── cvm.py       CVM List (8E) → reglas + notas de riesgo (No CVM/PIN claro/firma)
│   ├── oda.py       ODA: inventario, claves débiles y recuperación/verificación RSA del cert. del emisor
│   ├── analyze.py   assess(tlvs) → informe combinado (AIP/CVM/ODA) + hallazgos + summary()
│   ├── intercept.py motor de reglas MITM (reescribe tag/valor, set-sw) + intercepting(send,rules)
│   ├── search.py    Blob/Hit + búsqueda de flags/regex
│   └── gp/          GlobalPlatform (extra [gp]=pycryptodome): keyset (modelo Keyset), crypto (SCP02 3DES / SCP03 AES: derivación, criptogramas, KDF, retail-MAC, ICV), apdu (comandos GP), scp (Secure Channel sobre Transceiver + wrap C-MAC/C-ENC, autodetección), cap (parseo CAP→Load File Data Block), content (authenticate/get_status [AppInfo.modules = AIDs de módulos instanciables, tag 84]/list_modules/delete/**restore_virgin** [deja la tarjeta 'virgen': borra instancias que no sean ISD/SD/keep_aids; opcional delete_packages]/install_cap [carga+instancia un CAP EMV abierto] + **install_instance** [instancia un módulo YA cargado: INSTALL [for install] — "inicializar" la tarjeta sin cargar código] + **smart_write**: escritura inteligente — prueba la escritura directa y, si la tarjeta exige canal seguro [SW 6982/6985], abre GP con un keyset y reintenta la escritura envuelta; devuelve `SmartWriteResult` con log del proceso). Escribir/gestionar JavaCards
├── readers/     ── EFECTOS: transporte hacia el hardware (aísla pyscard/nfcpy/evdev/pyserial)
│   ├── types.py     Transceiver, OpenReader, DeviceInfo, Capability, ReaderError, WireEvent (traza de transporte de bajo nivel)
│   ├── registry.py  descubrimiento unificado + open_device(on_event,on_wire) + resolve()
│   ├── pcsc.py      backend PC/SC (chip contacto + contactless PC/SC)
│   ├── nfc.py       backend NFC (nfcpy/PN532), degradación elegante
│   ├── msr.py       backend banda magnética (evdev HID / pyserial), degradación elegante
│   └── bombercat.py backend BomberCat (serie): EMV-JSON, passthrough APDU (on_wire = líneas serie crudas), magspoof, relay
├── payments/    ── PURO: helpers de pago reutilizables (base de los PoCs)
│   ├── emvcard.py   EmvCard (from_bombercat_json/from_dump) — modelo normalizado
│   ├── iso8583.py   codec ISO 8583 (build/parse) + translate() + emv_icc() (campo 55) + pin_block_iso0()
│   ├── iso_host.py  cliente TCP (efecto): envía un mensaje ISO 8583 a un host (prefijo de longitud)
│   └── cryptogram.py análisis ATC/ARQC/UN (replay/reuso) sobre capturas
├── session/     ── captura de tarjeta sobre `send`
│   ├── model.py     CardDump serializable (JSON) + app_to_dict/fci_hex + from_bombercat()
│   └── capture.py   capture_card()/capture_reader()/find_flags()
├── project/     ── proyectos + variables de entorno (persistencia)
│   ├── model.py     Project (captures/pocs/poc_runs/logs dirs), Variable (frozen)
│   ├── store.py     CRUD proyectos + activo + capturas + import_capture + poc_runs + save_log/list_logs (logs/) + export/import (.zip)
│   ├── env.py       CRUD puro de variables + encoders EMV + alias + IO
│   └── profiles.py  perfiles de terminal preconfigurados (kiosk/atendido/ATM) aplicables en un paso
├── poc/         ── framework de PoCs (runner + plugins del proyecto; sin PoCs integrados)
│   ├── model.py     Severity/Status/Finding/PocResult/PocMeta/PocContext
│   ├── registry.py  @poc(...) + load_plugins(project) desde <proyecto>/pocs/*.py
│   ├── runner.py    make_context()/run_poc()/save_result() (+ evidencias)
│   ├── http.py      PocHttp (urllib) con evidencia, solo-lectura y dry-run
│   └── scaffold.py  plantilla para 'poc new'
├── tui/         ── interfaz TUI (Textual)
│   ├── app.py       EmvyApp: pestañas, estado de sesión, workers de hardware/PoC
│   ├── screens/     dashboard, projects, variables, readers, explorer, tools(console+flags+iso8583+write), charges(Cobros), pocs, intercept, firmware(BomberCat), fuzz
│   └── widgets/     tlvtree (árbol TLV), common (StatusBar), copyable (CopyableDataTable: Ctrl+C copia la fila)
├── gui/         ── interfaz GUI de escritorio (PySide6/Qt) — frontend nativo alternativo a la TUI
│   ├── app.py       MainWindow: estado de sesión + orquestación de hardware por señales Qt; run_gui()
│   ├── worker.py    submit()/Worker(QRunnable): operaciones de hardware fuera del hilo GUI, con progreso por señales (mantiene vivos los workers en `_ACTIVE` + `setAutoDelete(False)`: si no, el pool los auto-borra y las señales `result`/`error` en cola se pierden)
│   └── panels/      dashboard, projects, variables, readers, explorer (árbol TLV + inspector), tools (Flags/ISO8583/Escritura), charges (Cobros), poc, intercept, firmware (**ADR-001: un Tab por firmware BomberCat** — `DevicePanel` control-plane [estado/flasheo/permisos USB/compilar propio, posee el puerto serie único] + gated por capacidad `TagsPanel`/`ReadersPanel`/`MagspoofPanel`/`MifarePanel`/`RelayPanel`; `BaseFirmwarePanel` centraliza gating+pill de estado+log; orquestados vía `integrations.bombercat_tools` [subprocess al venv del vendor]), fuzz (emulación: Fuente decide NFC-NDEF [plantilla/tarjeta-de-prueba/captura] o EMV [perfilar terminal]), console (consola cruda: TX/RX completo + Exportar/Guardar en proyecto)
├── cli.py       ── CLI (argparse) sobre todo lo anterior; main() aplica settings al arrancar
├── config.py    ── rutas XDG (datos/config); data_home() honra override de ajustes/EMVY_DATA_HOME; repo_root() = sys._MEIPASS al empaquetar (PyInstaller)
├── settings.py  ── PREFERENCIAS globales (tema/idioma/carpeta de datos) → <config>/settings.json; apply() empuja data_dir a config y idioma a i18n
├── palettes.py  ── PALETAS de color con nombre (EMVy, Tokyo Night, Gruvbox, Nord, Catppuccin, Dracula, Solarized, Gruvbox Light) — un solo set de tokens viste GUI (QSS) y TUI (Theme)
├── i18n.py      ── i18n mínimo t(key): catálogos es/en/pt (fallback es→en→clave); despliegue INCREMENTAL (nav/pestañas/botones/Ajustes migrados)
└── term.py      ── color ANSI para la CLI (presentación)
```

**Ajustes globales / Preferencias** (`emvy/settings.py` + pestaña **Ajustes** en GUI y TUI): tema de color
(paletas de `palettes.py`, aplicables **en vivo** — la GUI reconstruye el QSS, la TUI cambia el `Theme`
registrado), **idioma** (es/en/pt vía `i18n.t`; se aplica del todo al reiniciar, en vivo las pestañas/nav) y
**carpeta de datos** (redirige proyectos/capturas/variables a otra ruta — solo datos nuevos, no mueve los
existentes; vía `config.set_data_home`). Persisten en `<config>/settings.json`; `settings.apply(load())` corre
al arrancar CLI/GUI/TUI. Añadir un tema = una entrada en `palettes.PALETTES`; migrar más textos a i18n = usar
`i18n.t("clave")` y añadir la clave al catálogo. Las etiquetas de pestaña/nav usan **ids estables**
(`_tab_specs`/`_NAV_GROUPS` por id) desacoplados del texto traducible.

**Empaquetado / distribución** (`packaging/`, ver `packaging/README.md`): binarios **de la GUI** con
PyInstaller (`EMVyController.spec`, entry `emvy_gui.py`). **AppImage** (Linux) vía Docker Ubuntu 22.04 +
appimagetool (`Dockerfile.appimage`, `build-appimage.sh` → `dist/EMVy_Controller-<ver>-beta-x86_64.AppImage`);
**.exe** (Windows) con la misma spec en Windows/CI, o best-effort con Wine (`Dockerfile.windows`). Incluye
`firmware/` (código + `.uf2` flasheable, vía `config.repo_root()`); **NO** empaqueta proyectos/capturas
(viven en XDG `~/.local/share/emvy`) ni `engagements/` (excluidos por `.dockerignore`). La versión
(`emvy.__version__`=0.6.0, `__release__`="BETA") se muestra en el título de la ventana y en Inicio.

`emvyctl.py` (raíz) es un shim → `emvy.cli:main`. Entry point: `emvyctl = "emvy.cli:main"`.

### La abstracción clave: `Transceiver`
`Transceiver = Callable[[APDU | bytes], Response]`. **Toda** la lógica EMV de `core.emv` recibe
una función `send`, no un objeto con estado. Esto:
- desacopla la lógica EMV del backend de lector (PC/SC, NFC… dan el mismo `send`);
- la hace testeable con un `send` falso (ver `tests/fakecard.py`).

`core.apdu.make_transceiver(transmit, on_event=None)` compone un `transmit` de bajo nivel
(`bytes -> (data, sw1, sw2)`, que aporta cada backend) en un `Transceiver` de alto nivel que
resuelve solo los `61xx` (GET RESPONSE) y `6Cxx` (Le). Lo comparten PC/SC y NFC.

### Un lector abierto es un registro de funciones
`OpenReader` (frozen) agrupa callables `transceive` / `atr` / `read_swipe` / `close` — composición
en vez de herencia. Los campos que no aplican al tipo de lector quedan en `None` (p.ej. un lector
de banda magnética no tiene `transceive`; uno de chip no tiene `read_swipe`).

---

## 2. Modelo de proyectos y variables

Un **proyecto** es un espacio de trabajo persistente en
`~/.local/share/emvy/projects/<nombre>/`:
- `project.json` — manifest (nombre, descripción, creado, lector preferido).
- `variables.json` — lista de variables de entorno.
- `captures/*.json` — volcados de tarjeta.

El **proyecto activo** se guarda en `~/.config/emvy/state.json` (respeta `XDG_*`).

Una **variable** (`project.model.Variable`) es de dos clases:
- `kind="terminal"`: parámetro del **perfil de terminal EMV**, mapeado a un tag. El conjunto de
  variables terminal se convierte en un `TerminalProfile` (`dict[tag_hex, bytes]`) vía
  `env.to_terminal_profile()`, que alimenta la construcción de **DOL** (PDOL/CDOL/DDOL) en el GPO.
- `kind="user"`: par clave-valor libre (objetivos, notas, secretos, plantillas).

**Alias amistosos** (`env.ALIASES`): `amount`→9F02, `country`→9F1A, `currency`→5F2A, `tvr`→95,
`txn_date`→9A, `txn_type`→9C, `unpredictable_number`/`un`→9F37, `ttq`→9F66, `merchant_name`→9F4E,
`terminal_caps`→9F33, etc. Se puede usar el alias o el tag hex directamente.

**Codificación de valores** (`env.encode_value`): para tags de texto (`an`/`ans`) el valor es
**texto ASCII**; para el resto (`n`/`b`/`cn`) el valor es **hex**. `env.default_variables()` siembra
el perfil por defecto desde `core.emv.default_terminal_profile()`.

---

## 3. Lectores y hardware

`readers.registry` es el **único punto** que usan CLI y TUI:
- `available_backends() -> {backend: bool}`
- `list_all_devices() -> [DeviceInfo]` (une PC/SC+NFC+MSR, salta los no disponibles)
- `open_device(DeviceInfo, *, protocol, timeout) -> OpenReader`
- `resolve(spec) -> DeviceInfo` (por índice, nombre, backend o id)

**Degradación elegante**: si falta la dependencia (`nfcpy`, `evdev`, `pyserial`) o el hardware,
ese backend simplemente no aporta dispositivos y `open()` lanza `ReaderError` con instrucciones.

| Backend | Dep      | Cubre                                   | Notas |
|---------|----------|-----------------------------------------|-------|
| pcsc    | pyscard  | chip de contacto + contactless PC/SC    | requiere `pcscd` + driver `ccid` |
| nfc     | nfcpy    | NFC/ISO-DEP (EMV contactless, Type 4)   | PN532/PN533, ACR122 (libnfc), RC-S380 |
| msr     | evdev / pyserial | banda magnética (HID teclado / serie) | parsea el swipe con `core.track` |
| bombercat | pyserial | EMV contactless (NFC), passthrough APDU, magspoof, relay | Electronic Cats RP2040; ver §9 |

EMV contactless habla APDUs sobre ISO-DEP, así que **el mismo `core.emv` funciona** por PC/SC o por
NFC sin cambios.

### Requisitos del sistema (Arch Linux)
```sh
sudo pacman -S ccid                      # driver CCID (chip de contacto)
lsusb | grep -i reader                   # verifica el lector (p.ej. Alcor AU9540)
```

**`pcscd.socket` se gestiona solo** (`emvy/integrations/pcscd.py`): `emvy.cli.main()` lo activa al
arrancar (CLI o TUI, cualquier comando) y lo apaga al salir — **solo si fue él quien lo activó** (si
ya estaba activo por otra razón, no lo toca al salir). Usa `systemctl start/stop` directo (sin
`sudo`): en sistemas con polkit, un usuario de sesión activa suele poder gestionar esta unidad sin
contraseña; si no es el caso, falla en silencio y no rompe nada — arráncalo a mano como antes
(`sudo systemctl start pcscd.socket`).

---

## 4. Instalación y entorno

- **Python 3.10+** (probado en 3.14). Entorno con `uv`.
```sh
uv venv .venv
uv pip install --python .venv -e '.[dev,tui]'   # + [nfc] y/o [msr] según hardware
```
Dependencias por grupo (`pyproject.toml`): runtime `pyscard`; extras `tui=textual`,
`gui=PySide6`, `nfc=nfcpy`, `msr=pyserial+evdev`, `dev=pytest`.

---

## 5. Uso

### GUI de escritorio (PySide6/Qt)
```sh
uv pip install --python .venv 'emvyctl[gui]'   # o: PySide6
./emvyctl.py gui      # o: emvy gui
```
Frontend **nativo** alternativo a la TUI (para quien prefiere ventana de escritorio). Reutiliza el
mismo núcleo puro; `emvy/gui/`. **Paridad de pestañas con la TUI**: **Inicio** (estado + proyectos
recientes + acciones rápidas), **Proyectos**, **Variables** (+perfiles), **Lectores**, **Explorador**
(capturar → árbol TLV con inspector: copiar hex/ASCII, asignar a variable, guardar captura),
**Herramientas** (sub-tabs Flags · ISO 8583 · **Escritura**: UX **guiada por intención** —una barra de
**canal seguro** (keyset + C-ENC) compartida arriba, con hint que dice si se autenticará sola; luego dos
pestañas (GUI `QTabWidget`, TUI `TabbedContent`) + un log común abajo—: **«Personalizar»** (amistoso, por
defecto) con **preset** (Visa/Mastercard/Amex de prueba / Personalizado) que rellena PAN/caducidad/titular/
cód.servicio, **vista previa en vivo** del registro EMV (resumen PAN/Cad/Titular + Track2 + hex, via
`cardfuzz.personalize_record`), y botones «Datos de prueba», «Copiar hex», «Editar en Avanzado→» (lleva el
hex a la otra pestaña) y **«Escribir en la tarjeta»** (CTA); y **«Avanzado»** con dos grupos: **Escritura
directa (APDU)** (op + **campos contextuales** según el op) y **GlobalPlatform · inicializar/gestionar la
tarjeta** (probar auth · Ver contenido/GET STATUS —lista los **módulos instanciables** de cada paquete— ·
**Instalar CAP EMV** [`install_cap`] · **Instanciar applet cargado** [paquete/módulo/instancia →
`install_instance`, INSTALL [for install] de un módulo ya LOADED] · DELETE · **Restaurar (virgen)**
[`restore_virgin`: borra instancias, conserva ISD/SD/fábrica]). Toda escritura es **inteligente**: prueba
directo y, si la tarjeta pide canal seguro (6982/6985), **autentica sola por GlobalPlatform** con el keyset y
reintenta (`content.smart_write`). Flujo de una tarjeta en blanco: (restaurar→virgen) → instalar/instanciar un
applet EMV → seleccionable → personalizar en «Personalizar». **Ojo**: solo funciona con applets que soporten
perso por UPDATE RECORD (p.ej. un CAP EMV abierto); los Visa/EMV licenciados de fábrica suelen rechazar
UPDATE RECORD/PUT DATA (6D00) y exigir perso propietaria (STORE DATA/DGI). El log añade una **pista accionable** por SW vía
`cardwrite.write_hint()`),
**Cobros** (switch ISO 8583), **PoC**
(runner del proyecto), **Intercept** (reglas MITM; `active_send` las envuelve al activar), **BomberCat**
(compilar/subir firmware con arduino-cli) y **Fuzzing** (banda/EMV/NDEF + emulación). En el carril de
emulación un **único botón "Emular"** decide **NFC o EMV según la Fuente**: `NFC · plantilla NDEF (fuzz)`,
`NFC · tarjeta de prueba (NDEF)`, `NFC · captura (NDEF)` → emula un tag NDEF a un lector; `EMV · tarjeta
de pago (perfilar terminal)` → emula una tarjeta EMV a un terminal — con el selector de captura elige
presentar los **datos reales** de una captura o la Visa de prueba fija (ver §9). Además un **Editor de
tarjeta EMV** (`FuzzPanel._card_editor`): carga una tarjeta (escanear→memoria, escanear→RAM del BomberCat,
o una captura guardada), muestra los campos **editables** (PAN, caducidad, cód. servicio, AID, titular,
Track2), regenera el Track2 desde PAN/caducidad/servicio (`core.track.build_track2_emv`, inverso de
`parse_track2_emv`) y emula la tarjeta **editada** (`emit_emv(card)` → `EMUEMV:` con los datos nuevos).
Botones
**Detener**/**Reboot** compartidos. Un **dock inferior "Consola cruda"** siempre visible muestra **todo lo
que se envía y se recibe en crudo** (APDU completo + status word, y el transporte serie del BomberCat) vía
las señales `apdu_event`/`wire_event`, permite enviar un APDU a mano, y **exportar** todo el volcado a un
archivo (**Exportar…**) o **guardar en el proyecto** (**Guardar en proyecto** → `<proy>/logs/` vía
`store.save_log`). Las
operaciones de hardware corren en un `QThreadPool` (`gui/worker.py`) para no congelar la ventana; el
resultado/traza vuelve por señales Qt. Verificable headless con `QT_QPA_PLATFORM=offscreen` +
`QWidget.grab()` (ver `tests/test_gui.py`). **Navegación por barra lateral** (`MainWindow._build_sidebar`):
un `QListWidget#nav` agrupado (SESIÓN/TARJETA/OPERACIONES/HARDWARE) con iconos SVG conduce un `QTabWidget`
con la barra de pestañas oculta (`self.tabs` sigue siendo la API; `_nav_to_tab` mapea fila→pestaña) — más
limpio que 11 pestañas arriba. La pestaña **PoC** es ahora un **IDE integrado** (`panels/poc.py`, paridad
con la TUI): explorador de `pocs/*.py`, editor de código con **resaltado Python** (`_PyHighlighter`), crear
desde plantilla, Guardar/Eliminar, y **Ejecutar al vuelo** eligiendo la fuente de la tarjeta (sesión o
captura guardada) con dry-run/allow-write (`run_poc(capture_name=…)`), panel de referencia de `ctx` y salida.

**UX (limpieza contextual)**: la **consola cruda** (dock inferior) solo se muestra en las pestañas con
tráfico de hardware (`MainWindow._CONSOLE_TABS`: Lectores/Explorador/Herramientas/Cobros/PoC/Intercept/
BomberCat/Fuzzing) y se **oculta** en Inicio/Proyectos/Variables (vía `currentChanged`→`_on_tab_changed`).
La pestaña **Inicio** es un **centro de operaciones**: tarjetas de estado (proyecto/lector/tarjeta),
"siguiente paso" como **botón de acción** contextual, **capturas del proyecto** (doble clic → abre en el
Explorador), lista de proyectos (doble clic → activar) y accesos rápidos. La pestaña **Fuzzing** agrupa sus
herramientas en **sub-pestañas** (Editor de tarjeta · Emulación NFC/EMV · Registro EMV · Banda magnética)
para no apilar todo — los widgets/IDs no cambian. **Iconografía SVG** (estilo Lucide, sin emojis) vía
`emvy/gui/icons.py::icon(name, color, size)` (renderiza SVG inline → `QIcon` con `QtSvg`, sin ficheros):
iconos en las 11 pestañas principales (`MainWindow._apply_tab_icons`) y en los CTAs (Emular/Detener/Reboot,
accesos rápidos de Inicio). En la **TUI** el "siguiente paso" del Inicio es también un **botón de acción**
(`#dash-next-btn` → `build_model().next_action`) además del atajo de teclado.

**Gotcha Linux (SIGSEGV al arrancar)**: PySide6 trae su **propio** Qt; si el sistema fuerza plugins de
tema/estilo de plataforma (`QT_QPA_PLATFORMTHEME=kde|gtk3`, `QT_STYLE_OVERRIDE=…`) compilados contra
otra build de Qt, cargarlos en el Qt embebido revienta el proceso (mismatch de ABI — típico en
KDE/GNOME/Arch). `gui.app.run_gui` lo neutraliza antes de crear la `QApplication` (`_harden_qt_env`:
vacía `QT_QPA_PLATFORMTHEME`, quita `QT_STYLE_OVERRIDE`, usa el estilo **Fusion** propio de Qt).
Opt-out: `EMVY_GUI_KEEP_QT_ENV=1`. Si el compositor Wayland aún da problemas, forzar
`QT_QPA_PLATFORM=xcb` (usa XWayland).

### TUI (interfaz principal)
```sh
./emvyctl.py tui      # o: emvy tui
```
Pestañas: **Inicio** (centro de operaciones: estado proyecto · lector · tarjeta · captura, siguiente
acción sugerida, **proyectos recientes** clicables — incluye engagements —, crear proyecto inline y
**acciones rápidas**; `dashboard.build_model()` es puro/testeable) · **Proyectos** (crear/activar/borrar)
· **Variables** (CRUD perfil terminal + libres; **perfiles preconfigurados** —kiosk sin CVM, POS
atendido, contacto genérico, ATM— aplicables en un paso) · **Lectores** (descubrir/conectar) · **Explorador**
(layout de **dos paneles**: a la izquierda el **árbol TLV** (panel bordeado, ocupa la mayor parte); a la
derecha un **inspector** (`VerticalScroll`) que agrupa las acciones contextuales en secciones —NODO
SELECCIONADO (detalle tag/valor/ascii + copiar hex/ASCII/tag=val), ASIGNAR A VARIABLE, GUARDAR CAPTURA—;
barra de acciones arriba y consola en vivo colapsable al pie. Solo dos botones de captura, agrupados
aparte de Analizar/Limpiar: **Capturar tarjeta** —siempre
`mode="auto"`: prueba EMV y si no hay apps cae solo a NFC genérico, sin pedir de antemano qué tipo de
tarjeta es— y **Dump crudo**, que se adapta al **backend del lector conectado** (`reader_device.backend`):
con BomberCat usa `mode="nfc"` (se salta el barrido ciego READ RECORD/GET DATA — cientos de intercambios
EMV-específicos que además hacen perder el campo NFC, de rango milimétrico, a mitad de barrido — y va
directo a NDEF Type 4 + AIDs); con lectores de contacto (más estables) hace el barrido crudo completo.
Si la captura por BomberCat vuelve vacía, avisa que probablemente se perdió el contacto a media lectura
en vez de mostrar un "0 apps" mudo. Al capturar, si el tag es **NFC Forum Type 4** con NDEF, sus
registros decodificados (Texto/URI) aparecen en un subárbol "NDEF (interesante)"
(`core.rawscan.read_type4_ndef` + `core.ndef`); **Dump crudo** también puede mostrar contenido como app
`RAW` (`core.rawscan`); **Analizar** añade un subárbol de seguridad AIP/CVM/ODA + hallazgos;
**guardar la captura en el proyecto** con un nombre; y al seleccionar un nodo,
copiar su valor **en hex o ASCII** al portapapeles o **asignarlo a una variable** del proyecto
—terminal o libre, hex o ASCII—, con la codificación correcta según el tag; y un `Collapsible`
**"Consola en vivo (APDU + transporte del lector)"** (`ConsoleScreen`, colapsado por defecto) con envío
manual de un APDU + **dos niveles de traza en vivo**: (1) **APDU** —cada intercambio de CUALQUIER
pestaña (captura, PoC, escritura…) parseado con su status word, vía el `on_event` de
`registry.open_device()` (`ConsoleScreen.live_log()`)— y (2) **transporte** —la línea cruda por debajo
del APDU vía `on_wire`: hoy las líneas serie del BomberCat (`PING`/`WAIT`/`READY:`/`ERR:NOCARD`/
`APDU:<hex>`/`RESP:<hex>`/`# debug`), con estilo ⇢/⇠ distinto (`ConsoleScreen.wire_log()`)— más banners
de conexión/desconexión. Así se ve **literalmente qué manda y qué responde** el hardware: el handshake,
la detección de tarjeta (clave para depurar lecturas NFC inestables) y el framing. Para lectores sin
capa de transporte propia (PC/SC, NFC) el `TraceEvent` de APDU ya es el comando que mandan al chip
—incluido GET RESPONSE/Le-retry—, así que no emiten `on_wire`. Vive en el Explorador y no en Consola
porque es justo ahí donde se está capturando) ·
**Consola** (agrupa en sub-pestañas: **Flags** sobre la última captura · **ISO 8583** constructor +
traducción + envío TCP · **Escritura** en tarjeta) · **Cobros** (flujo de switch de primer nivel: crear cobro → sign-on 0800 → 0200 con
F55/ARQC → seguir F39 → reverso; config por variables del proyecto; evidencia en `<proy>/transactions/`)
· **PoC** · **Intercept** (MITM: reglas que reescriben tag/valor y fuerzan SW; al activarse todo el
tráfico de la sesión pasa por ellas) · **BomberCat** (gestiona y **flashea firmware**: lista 📦 release (bombercat-tools) + ⬇ descargados de
**fuentes alternas** (GitHub `owner/repo` o URL `.uf2` → agregar/descargar/limpiar) + 🛠 tu firmware
compilado; **compila** los sketches de `firmware/` con arduino-cli (Compilar / Compilar y subir);
lista dispositivos y prepara el venv) · **Fuzzing** (plantillas para probar terminales/POS reales —
banda magnética mutada vía magspoof + registro EMV mutado para escribir en tarjeta de prueba—,
editables antes de disparar; ver §9.1). La barra principal es `TabbedContent#main-tabs`; `ToolsScreen`
(`#screen-tools`) hospeda las sub-herramientas (ids `#screen-flags/-iso8583/-write`; `#screen-console`
vive ahora en el Explorador). Atajos: `p v l e b o i m u` (pestañas; `e`=Explorador —incluye la
consola APDU—, `m`=BomberCat, `u`=Fuzzing) y `f 8 w` (Consola → Flags/ISO/Escritura), `r` refrescar,
`q` salir, **`?` abre el modal de Ayuda** (`HelpScreen`, `screens/help.py`) con todos los atajos
agrupados + el flujo de pentest sugerido. El **footer** solo muestra los esenciales (`q`/`?`/`r`); el
resto de bindings están activos pero `show=False` (antes se desbordaba con 14). Las operaciones de
hardware/red/subprocess corren en hilos (`@work(thread=True)`) para no congelar la UI.

**Tema visual profesional** (compartido GUI+TUI): paleta oscura "slate/OLED + run green" — fondo pizarra
`#0F172A`, paneles `#1B2336`, acento verde `#22C55E`, texto `#F8FAFC`, aviso ámbar, error rojo; tipografía
sans moderna (IBM Plex Sans/Inter/…) + monoespaciada (JetBrains Mono/…). La **GUI** lo aplica vía un QSS
global (`emvy/gui/theme.py::apply_theme(app)`, llamado en `run_gui`) que estiliza todos los widgets
(pestañas, botones, inputs, tablas, group boxes, dock, scrollbars…); botones CTA con `setProperty("accent",
True)`. La **TUI** registra un `textual.theme.Theme` (`EMVY_THEME` en `tui/app.py`, `self.theme="emvy"` en
`on_mount`) que recolorea los tokens `$primary/$accent/$panel/$surface…`. Verificable con capturas headless
(GUI: `QWidget.grab()`; TUI: `App.save_screenshot()` SVG → `rsvg-convert` PNG).

**Sistema visual compartido** (CSS en `EmvyApp.CSS`): clases `.title` (título de pantalla, subrayado
acento), `.subtitle` (descripción tenue), `.section` (etiqueta de sección), `.actions` (barra de
botones compacta) y `.row` (input+botones). Todas las pantallas las usan para verse coherentes;
Explorador/Inicio/Fuzzing/Lectores/Proyectos/Variables además llevan subtítulo + barra de acciones y
paneles bordeados (`border: round $primary`, foco en `$accent`).

**Copiar al portapapeles (toda la TUI)**: `Ctrl+C` copia, y **no** sale (para salir: `q`). En widgets
de texto (`Static`/`Label`/`RichLog`/`Input` — paneles del dashboard, consola en vivo, ISO 8583, flags,
ATR…) funciona la **selección de texto nativa de Textual**: arrastra con el ratón para seleccionar y
`Ctrl+C` copia (OSC 52; requiere terminal con OSC 52 habilitado). `Tree` y `DataTable` no soportan esa
selección (su render por líneas no expone texto extraíble, de ahí `ALLOW_SELECT=False`), así que ofrecen
copia **explícita** del elemento resaltado: el **árbol del Explorador** copia el valor del nodo resaltado
(`ExplorerScreen.action_copy_node`) y toda `DataTable` es una `CopyableDataTable` que copia la fila
resaltada (`emvy/tui/widgets/copyable.py`). Ambas ceden (`SkipAction`) al `Ctrl+C` estándar cuando hay
una selección de texto activa. `App.copy_to_clipboard()` (Textual) hace el trabajo — vía OSC 52, funciona
también por SSH.

### CLI (scripting)
```sh
# Lectores / tarjeta
./emvyctl.py readers                       # lista lectores de todos los backends
./emvyctl.py -r 0 atr                       # ATR del lector 0
./emvyctl.py discover                       # apps EMV (PPSE/PSE/bruteforce)
./emvyctl.py select A0000000041010          # SELECT + GPO + registros
./emvyctl.py info                           # resumen legible + búsqueda de flags
./emvyctl.py analyze                         # análisis de seguridad EMV (AIP/AUC/CVM/ODA)
./emvyctl.py analyze --file card.json --ca-modulus <hex>  # + verifica cert. del emisor
./emvyctl.py dump -o card.json              # volcado completo a JSON
./emvyctl.py dump --raw -o card.json        # + escaneo CRUDO (lee cualquier ISO 7816; auto si no hay app EMV)
./emvyctl.py dump --mode nfc                # tag NFC genérico (no de pago): NDEF Type 4 + crudo, sin EMV
./emvyctl.py dump --mode emv                # solo EMV; no cae a crudo aunque no halle apps
./emvyctl.py dump --save captura1           # guardar como captura en el proyecto activo
./emvyctl.py dump --save cap1 --project lab # guardar en OTRO proyecto (nombre o ruta)
# Elegir dónde: TUI → Proyectos (campo 'ruta' para proyecto XDG o en ruta), Explorador
# (destino: proyecto activo / otro proyecto / archivo). CLI: dump -o <ruta> · --project <n|ruta>
./emvyctl.py getdata 9F36                    # un GET DATA
./emvyctl.py write record 1 1 <hex>          # ESCRIBE: UPDATE RECORD (sfi rec hex) — modifica la tarjeta
./emvyctl.py write data 9F36 <hex>           # PUT DATA · write binary <offset> <hex> [--sfi N] · write append <sfi> <hex>
./emvyctl.py fuzz track list                 # plantillas de banda (probar terminales/POS)
./emvyctl.py fuzz track send bad-luhn        # dispara por BomberCat magspoof
./emvyctl.py fuzz card write no-cvm 1 1      # escribe un registro EMV mutado en tarjeta de prueba
./emvyctl.py fuzz ndef list                  # plantillas NDEF (emular tag NFC)
./emvyctl.py fuzz ndef emit invalid-tnf      # emula un tag NDEF mutado vía BomberCat (NFC)
./emvyctl.py apdu 00A404000E325041592E5359532E4444463031
./emvyctl.py flags --file card.json          # buscar flags en un dump (offline)
./emvyctl.py search 'flag\{[^}]+\}'          # regex propio
./emvyctl.py shell                           # shell interactivo

# Banda magnética
./emvyctl.py track '%B476173...^DOE/JOHN^2512...?;476173...=2512...?'
./emvyctl.py -r msr track --read             # leer del lector MSR

# ISO 8583 (traducción SEND/RCV)
./emvyctl.py iso8583 0200722004...            # traduce un mensaje crudo (hex)
echo 0210302000... | ./emvyctl.py iso -       # desde stdin (alias 'iso')

# Proyectos y variables
./emvyctl.py project new lab --desc "pentest lab"
./emvyctl.py project list | use <n> | rm <n> | show
./emvyctl.py project export lab -o ./backups  # empaqueta el proyecto a .zip
./emvyctl.py project import lab.zip --name lab2 --use  # importa (con Zip Slip check)
./emvyctl.py var set amount 000000001500     # alias terminal (hex)
./emvyctl.py var set merchant_name "ACME"     # tag an/ans (texto)
./emvyctl.py var set target "BancoX" --user   # variable libre
./emvyctl.py var list | get <n> | rm <n>      # (alias: `env`)
./emvyctl.py var profiles                     # perfiles de terminal preconfigurados
./emvyctl.py var apply contactless-kiosk      # aplica uno en un paso (terminal_type/ttq/txn_type)
```
Selección de lector: `-r <índice|nombre|backend|id>`. El **perfil de terminal** para el GPO sale
del **proyecto activo** (o del por defecto si no hay ninguno).

### Como librería
```python
from emvy.readers import registry
from emvy.core import emv
from emvy.session import capture_card, find_flags

dev = registry.list_all_devices()[0]
with registry.open_device(dev) as r:
    dump = capture_card(r.transceive, atr=r.atr(), reader=r.device.name)
    for hit in find_flags(dump):
        print(hit.match, "->", hit.source)
```

---

## 6. Convenciones de código (IMPORTANTE al contribuir)

- **Funcional primero**: el núcleo (`core/`) es puro; nada de IO ni estado global ahí. Las funciones
  reciben sus dependencias (p.ej. `send: Transceiver`, `profile`, rutas) como argumentos.
- **Inmutabilidad**: `Application`, `Record`, `Variable`, `Project`, `DeviceInfo`, `OpenReader` son
  `@dataclass(frozen=True)`. Para "modificar" usa `dataclasses.replace` y **devuelve** una copia; no
  mutes en sitio.
- **Efectos en los bordes**: el IO de hardware vive en `readers/`; el de disco en `project/store` y
  `session`; la presentación (color/Textual) en `term.py`/`tui/`. No metas `print`/color en `core/`.
- **Reutiliza**: antes de escribir, busca en `core.hexutil`, `core.tlv`, `core.apdu`, `env`. P.ej.
  serializa TLV con `tlv.encode` (no reconstruyas bytes a mano).
- **Estilo**: PEP 8, type hints, `snake_case`/`PascalCase`/`UPPER_CASE`, f-strings, `pathlib`,
  docstrings en funciones públicas. Comentarios y docstrings en **español** (consistencia). Los **textos de
  usuario** están en español por defecto pero migrando a **i18n** (`i18n.t("clave")`, catálogos es/en/pt): al
  tocar una superficie, envuelve sus cadenas con `t()` y añade la clave al catálogo (despliegue incremental).
- **Textual**: no nombres métodos de widget como `_render`/`render` (colisionan con la API interna);
  usa nombres propios (`_render_hits`, `show_dump`…). El hardware va en `@work(thread=True)` +
  `call_from_thread` para actualizar la UI.

---

## 7. Pruebas y verificación

```sh
.venv/bin/python -m pytest tests/ -q     # suite offline (sin hardware)
```
- `tests/fakecard.py` — tarjeta Mastercard **simulada** (un `Transceiver` falso). Base para probar
  todo el flujo EMV sin hardware.
- `tests/test_core.py` — TLV parse/encode roundtrip, DOL, APDU, `make_transceiver` (61/6C), ATR,
  AID, track, búsqueda de flags.
- `tests/test_emv_flow.py` — discover/select/GPO/AFL, PDOL desde perfil, cardholder, inmutabilidad,
  captura + flags.
- `tests/test_project.py` — env CRUD/encoders y ciclo de vida de proyectos (con `XDG_*` en `tmp`).
- `tests/test_payments.py` — EmvCard, ISO 8583 roundtrip + F55, análisis de criptograma.
- `tests/test_bombercat.py` — backend BomberCat con `tests/fakeserial.py` (serial falso).
- `tests/test_poc.py` — framework de PoCs (plugins, runner, HTTP dry-run/solo-lectura).

**Al cambiar algo con superficie de ejecución**, además de los tests:
- núcleo/flujo → añade/ajusta un test con `fakecard`;
- serie/BomberCat → usa `tests/fakeserial.py` (emula el firmware: PING/WAIT/APDU/JSON);
- TUI → prueba de humo headless con `App.run_test()` (Textual Pilot);
- hardware real (solo PC/SC disponible aquí): `pcscd` activo + `./emvyctl.py readers/atr/info/dump`.

---

## 8. Estado y notas

- Único hardware disponible en el entorno de desarrollo: lector de **contacto PC/SC Alcor AU9540**.
  NFC, MSR y BomberCat están implementados como backends que se activan al conectar el hardware.
- Compatibilidad de dumps: el JSON de `CardDump` mantiene el esquema
  `{atr, atr_info, reader, applications[], blobs[]}`.

---

## 9. BomberCat (Electronic Cats)

Integración por USB serie (`emvy/readers/bombercat.py`), cuatro modos según el firmware:

- **EMV reader (JSON)** — firmware `firmware/bombercat_emv_reader/`: lee EMV
  contactless por NFC y emite `JSON_START`/`<json>`/`JSON_END` @115200.
  `emvy bombercat read [--save nombre]` → captura (`session.from_bombercat` → `CardDump`).
- **Passthrough APDU** — el mismo firmware con el parche de passthrough (comandos `PING`,
  `WAIT`, `APDU:<hex>`→`RESP:<hex>`, `RELEASE`). **Conectar es instantáneo** (`open()` solo hace `PING`,
  no espera tarjeta): la detección de tarjeta (`WAIT`) es **perezosa**, en el primer APDU (p.ej. al
  capturar), así "Conectar" no falla con `ERR:NOCARD` cuando aún no hay tarjeta puesta. Si el APDU
  devuelve `ERR` (tarjeta retirada), se re-detecta en el siguiente. **Captura lean en contactless**:
  al capturar por BomberCat (GUI/TUI), la captura usa flujo EMV **mínimo** (`brute/sweep/get_data=False`
  → PPSE→SELECT→GPO→AFL, ~15 APDUs) en vez del barrido exhaustivo (bruteforce de ~40 AIDs + barrido
  ciego de registros/GET DATA = cientos de APDUs): sobre NFC de rango milimétrico sostenido a mano, un
  barrido largo pierde la tarjeta a media lectura → `ERR:TXFAIL`. Los lectores de contacto (estables)
  mantienen el barrido completo. Expone el BomberCat como lector `transceive`:
  `emvy -r bombercat discover|apdu|info` o `emvy bombercat apdu <hex>` funcionan con todo `core.emv`.
  **Interacción directa con el firmware** (mismo `Transceiver` que cualquier lector — lo prueba
  `tests/test_bombercat.py` con serial falso): `emvy bombercat dump [--raw] [--save nombre]`
  (volcado completo), `emvy bombercat write record|binary|data|append ...` (**escribe** en la
  tarjeta a través del firmware) y `emvy bombercat analyze` (AIP/CVM/ODA). Aceptan `--port` para
  fijar el puerto serie.
  **Gotcha de firmware (root-cause, 2026-09-06)**: `nfc.isTagDetected()` (librería
  `Electroniccats_PN7150`) es **de flanco, no de nivel** — reporta "llegó una
  notificación NCI nueva" una sola vez, no "hay tarjeta activa ahora". El
  handler `WAIT` la consume al detectar; si el handler `APDU:` volviera a
  llamarla para confirmar tarjeta antes de cada envío (como hacía antes),
  casi siempre daría `false` aunque la tarjeta siga físicamente presente →
  `ERR:NOCARD` espurio en el **primer** APDU tras un `WAIT` exitoso. Fix en
  `EMVyBomberCat.ino`: una bandera de estado `gPassthroughActive` que `WAIT`
  fija al detectar y `APDU:` solo **lee** (nunca vuelve a preguntarle al
  hardware) — mismo patrón que ya usa `runEmvFlowOnce` internamente (jamás
  re-llama `isTagDetected()` entre APDUs de un mismo flujo). Se limpia en
  `RELEASE` y si `readerTagCmd()` falla (se asume tarjeta retirada). Además,
  `WAIT` re-arma el discovery (`nfc.reset()`) **periódicamente** dentro de su
  ventana de espera (no solo una vez al entrar): el ciclo de poll/anticolisión
  del PN7150 puede tardar varios segundos en generar una notificación nueva
  tras un `TAG`/`APDU` previo, así que un solo `reset()` al principio corre el
  riesgo de una carrera con la única lectura corta que le sigue.
- **Panel web (todas las funciones)** — el AP WiFi `EMVyBomberCat` (clave `bombercat`,
  http://192.168.4.1) expone además de la lectura EMV los **endpoints** de las capacidades nuevas, con
  botones en el dashboard: `GET /tag` (lee UID de cualquier tag → JSON proto/tech/uid), `GET /nfcinfo`
  (diagnóstico: chip vivo + versión), `GET /emu?hex=<ndef>` (arranca la emulación NDEF persistente y
  responde enseguida; se detiene por serie con `STOP`) y `GET /mag?t1=&t2=` (magspoof). Helper `qparam()`
  decodifica los query params (%XX/+). Reusan la misma lógica que los comandos serie, así que **todo el
  firmware es accesible desde la web**, no solo por serie.
- **Diagnóstico NFC** — comando serie `NFCINFO` (firmware EMVyBomberCat): reconecta al PN7150,
  reporta su versión de firmware (`NFCINFO: fwver=<n> (chip vivo)`) y re-arma el discovery. Sirve para
  aislar fallos de "no detecta tarjeta": si devuelve una versión, el chip y la comunicación I2C/NCI
  están sanos y el problema es **RF** (tarjeta no contactless / fuera de rango / antena), no el
  firmware. `connectNCI()` ya se ejecuta al arrancar, así que si `PING` responde, el chip está vivo.
- **Magspoof / banda** — firmware oficial @9600: `emvy bombercat magspoof --track2 ...`.
- **Emulación NDEF (NFC) — observable y cancelable** — firmware `EMVyBomberCat`, comando `EMU:<hex>`:
  el BomberCat se hace pasar por un **tag NFC Forum Type 4** sirviendo `<hex>` como mensaje NDEF
  (posiblemente malformado, para fuzzear lectores/POS/teléfonos). **NO** usa el bucle opaco
  `isReaderDetected()`/`sendMessage()` de la librería (bloqueo de ~30 s, sin visibilidad): en su lugar el
  firmware **bombea él mismo** el card-emulation loop desde `loop()` con las primitivas públicas
  `cardModeReceive()`/`cardModeSend()` + la máquina de estados `T4T_NDEF_EMU_Next()` (exportada por la
  lib). Dos ventajas clave:
    1. **Visibilidad**: reporta por serie CADA APDU del lector — `EMU:RX SELECT-APP/SELECT-CC/
       SELECT-NDEF`, `EMU:RX READ off=<n> len=<n>` (qué "sector"/offset lee), `EMU:RX WRITE ...`, la
       respuesta `EMU:TX <hex>` y `EMU:MSG-SENT n=<k>` al entregar un mensaje completo. Así se ve
       exactamente qué está haciendo el lector.
    2. **Cancelable**: `EMU:` arranca y vuelve enseguida (no bloquea); se detiene en cualquier momento
       con `STOP`/`RELEASE`, mandando otro `EMU:` (reinicia), con `REBOOT`, o por el auto-stop de
       seguridad `EMU_MAX_MS` (180 s). Al parar restaura modo lector (`setReaderWriterMode()`+
       `startDiscovery`). Reporta `EMU:START len=<n>` … `EMU:DONE sent=<k> reason=<...>`.
  `setContent()` sirve los bytes crudos (para un hex sin `addRecord`, `updateHeaderFlags()` es no-op →
  el payload malformado se presenta tal cual). Backend: `bombercat.ndef_emulate(device, ndef_hex,
  timeout=None, on_line=..., stop=...)` (manda `STOP` cuando `stop()` es True o vence `timeout`).
  UI: pestaña **Fuzzing** (TUI/GUI) con botones **Detener** y **Reboot**; el log colorea RX/TX/MSG-SENT.
  Emulación EMV **como tag NDEF** no aplica aquí; para perfilar terminales EMV ver el punto siguiente.
- **Emulación de TARJETA EMV (perfilar/fuzzear terminales)** — firmware `EMVyBomberCat`, comando
  `EMUEMV`: reusa el mismo motor pumped (`gEmuMode=1`) pero, en vez de la máquina T4T, responde el flujo
  EMV contactless de un **terminal de pago** con datos canned para que **avance y revele su config**:
  `SELECT PPSE → FCI` (anuncia un AID), `SELECT AID` (acepta **cualquiera**, echa el AID + un **PDOL**),
  `GPO → 77 qVSDC` (Visa contactless: el criptograma va DENTRO del GPO —AIP=1800 [CVM+TRM, SIN SDA/DDA/CDA:
  anunciar DDA hacía que el kernel esperara la firma fDDA 9F4B que no podemos generar → abortaba "tarjeta
  ilegible"; sin auth offline el terminal salta la ODA y va a online con el ARQC], AFL=08010100, 57 track2,
  5F34, 9F10 IAD, 9F26 AC-dummy, 9F27 CID=ARQC, 9F36 ATC que incrementa por GPO, 9F6C CTQ=2840,
  9F6E FFI=20700000— vía `emvBuildGpoResp`; devolver solo `80` AIP+AFL hacía que el kernel Visa reintentara
  en bucle por falta de criptograma. El AFL hace que el terminal ADEMÁS lea el registro → más traza),
  `READ RECORD` (registro con track2/PAN/CDOL1/CVM), `GENERATE AC` (criptograma
  **dummy**). Lo potente es que **decodifica y reporta lo que manda el terminal**: `EMU:RX SELECT-PPSE`,
  `EMU:RX SELECT-AID <hex> (ESQUEMA)` (Visa/MC/Amex/…) y el **PDOL del GPO troceado** (`  PDOL
  TTQ(9F66)=… Monto(9F02)=… Pais(9F1A)=… Divisa(5F2A)=… UN(9F37)=… TipoTerm(9F35)=…`) + el CDOL1 del
  GENERATE AC. **Sin cripto real** (no hay clave del emisor → no aprueba el pago): el objetivo es extraer
  el perfil/configuración del terminal, no completar una transacción. Descubierto porque al emular NDEF
  a un POS real, éste pedía PPSE + AID de pago (no NDEF) y recibía `6A82` en bucle — este modo lo hace
  avanzar. Los TLV canned se validan con `core.tlv` en los tests. Backend: `bombercat.emv_emulate(device,
  card=None, from_ram=False, timeout=None, on_line=, stop=)`; CLI `emvy bombercat emv-emulate
  [--card cap.json] [--ram]`; en la pestaña Fuzzing (GUI) la Fuente `EMV · tarjeta de pago` (ver más abajo).
  **Escanear → RAM → reemular**: `CARDSCAN` (firmware) lee una tarjeta por NFC y la guarda en la **RAM del
  firmware** (`EMU:SCANNED`); `EMUEMV:RAM` la reemula — flujo on-device sin PC ni archivos, hasta reiniciar.
  Backend `bombercat.card_scan_to_ram(device)` + `emv_emulate(from_ram=True)`; CLI `emvy bombercat cardscan`.
  La GUI además guarda una tarjeta escaneada en la **RAM de la app** (`MainWindow._scanned_card`, botón
  Escanear→memoria) usable como fuente EMV — funciona con cualquier lector (contacto Alcor incluido), no
  solo el NFC del BomberCat.
  **Inyección de datos reales de una captura**: `EMUEMV:<aid>|<pan>|<exp>|<track2>` (hex; campos vacíos =
  default) hace que el firmware anuncie ese AID en el PPSE y sirva ese PAN/expiry/track2 en el registro —
  presenta al terminal la tarjeta **capturada** en vez de la Visa de prueba. `emv_emulate(card=<EmvCard>)`
  codifica los campos (`_emv_card_params`: PAN→BCD tag 5A, expiry YYMM→YYMMDD tag 5F24, track2 = tag 57
  tal cual); el firmware confirma con `EMU:CARD aid=.. pan=.. exp=.. t2=..`. El PPSE y el registro se
  construyen dinámicamente (`emvBuildPpseFci`/`emvBuildRecord`, longitud larga `81 XX` si el registro
  pasa de 127 B). **Validado en hardware**: arranque/parada (`EMU:START mode=emv` → `STOP` → `EMU:DONE`) e
  inyección de captura (`EMU:CARD aid=7 pan=8 exp=3 t2=19`); el flujo completo con un terminal real
  acercado queda por confirmar in situ. (NDEF y EMV comparten Detener/Reboot y el auto-stop de 180 s.)
- **Reinicio del MCU** — comando serie `REBOOT` (alias `RESET`): reinicia el RP2040 vía
  `NVIC_SystemReset()` para salir de un estado atascado (p.ej. emulación colgada) sin desconectar la
  placa. El USB CDC se re-enumera, así que **hay que reconectar** el lector después. Backend:
  `bombercat.reboot(device)` (reintenta abrir el puerto si está ocupado); CLI `emvy bombercat reboot`;
  botón **Reboot** en la pestaña Fuzzing (suelta el lector conectado tras el reset).
- **Relay NFC** — `emvy bombercat cmd <linea>` (el relay completo usa el coordinador MQTT
  `scripts/cordinator.py` del repo upstream `ElectronicCats/BomberCat`).

**Firmware**: el passthrough vive en `firmware/bombercat_emv_reader/` y en el firmware unificado
`firmware/EMVyBomberCat/` (helper `hexDecode` + dispatch en `handleSerialCmd`; AP WiFi `EMVyBomberCat`
clave `bombercat`, panel web con branding "parte de EMVy Controller"). Es **aditivo** (no altera
SCAN/HTTP). Compila con `arduino-cli` (`./build.sh`, o desde la TUI — pestaña **BomberCat**, ver
§12); **sube por picotool** (`arduino-cli upload` / `build.sh upload`, **no** por `.uf2`; el flasheo
`.uf2` de bombercat-tools es solo para las imágenes **oficiales** prebuilt). Luego validar con
`emvy -r bombercat discover` o `emvy bombercat dump`.

## 9.1 Fuzzing de terminales/TPV/POS (`emvy/core/cardfuzz.py`, puro)

No prueba tarjetas: prueba **cómo reacciona un lector/POS real** ante datos de
tarjeta fuera de lo normal. Genera **plantillas** (base + mutaciones) de:

- **Banda magnética** (`track_templates()`): Track1/Track2 válidas + mutaciones
  (`bad-luhn`, `expired`, `service-code-chip-required`, `truncated-pan`,
  `oversized-pan`, `missing-separator`, `no-end-sentinel`, `non-numeric-pan`,
  `oversized-discretionary`). Se disparan por **BomberCat magspoof**
  (`bombercat.magspoof_emit`). No calcula LRC/paridad física (eso lo resuelve
  el firmware al modular la señal); las mutaciones son a nivel de campo.
- **Registro EMV** (`emv_templates()`): registro `70` (5A/57/5F24/5F20/82/8E)
  válido + mutaciones (`no-cvm` fuerza "sin CVM requerido", `weak-aip` fuerza
  solo-SDA, `oversized-pan`, `missing-pan`, `bad-track2`, `expired`). Cada
  mutación se verifica contra los propios decodificadores del proyecto
  (`core.cvm`/`core.emvbits`) en los tests, no a ciegas. Se escriben en una
  tarjeta de prueba reescribible vía `core.cardwrite.update_record` (cualquier
  lector — PCSC o BomberCat passthrough).
- **NDEF** (`ndef_templates()`): mensaje NDEF válido (URI de referencia) +
  mutaciones (`oversized-record`, `bad-type-length`, `truncated`, `invalid-tnf`,
  `no-me-flag`, `huge-uri`, `long-format-mismatch`, `empty`, `multi-record`).
  Se construyen con `core.ndef` (builders `uri_record`/`text_record`/
  `build_record`, inversos de `parse_records`) y se **emulan como un tag NFC
  Type 4** vía `bombercat.ndef_emulate` (comando `EMU:` del firmware). Es el
  equivalente NFC de magspoof: en vez de una banda mutada, presenta un tag NDEF
  fuera de norma para ver cómo lo parsea un lector/POS/teléfono. La emulación es
  **observable** (el firmware reporta cada APDU del lector: qué app/fichero
  selecciona y qué offset lee) y **cancelable** (botón **Detener** en la pestaña
  Fuzzing, o `STOP`); el botón **Reboot** reinicia la placa si algo se atasca
  (ver §9, "Emulación NDEF observable" y "Reinicio del MCU").

Las plantillas aceptan overrides (`pan`/`name`/`expiry`/`service_code` para
banda/EMV; `url`/`text` para NDEF) y el valor generado es **editable antes de
disparar** ("en caliente"), tanto en la TUI (pestaña **Fuzzing**, atajo `u`,
tres carriles) como copiando/editando el hex en la CLI.

CLI: `emvy fuzz track list|show <id>|send <id> [--port] [--pan] [--name]
[--expiry] [--service-code]` (banda, vía BomberCat) · `emvy fuzz card
list|show <id>|write <id> <sfi> <registro> [-r <lector>] [--pan] [--name]
[--expiry]` (registro EMV, cualquier lector) · `emvy fuzz ndef list|show <id>|
emit <id> [--port] [--url] [--text]` (NDEF, emula tag NFC vía BomberCat).

## 10. Helpers de pago (`emvy/payments/`, puro)

- `EmvCard` — modelo normalizado de tarjeta/transacción (`from_bombercat_json`, `from_dump`).
- `iso8583` — codec genérico `build/parse` (bitmap, DEs) + `emv_icc()` para el **campo 55** (TLV EMV
  desde un `EmvCard`, usando `core.tlv`). Sin objetivos hardcodeados; a nivel de bytes.
  También un **traductor humano**: `translate(raw)` / `describe_mti(mti)` decodifican MTI
  (versión/clase/función/origen + dirección **envío/recepción**) y cada DE (monto, divisa,
  processing/response code, track 2, y **campo 55 expandido como TLV EMV**). Puro; el color se
  inyecta como callable. CLI: `emvy iso8583 <hex>` (alias `iso`; `-` lee de stdin).
- `cryptogram` — análisis de un conjunto de capturas: ATC duplicado/hueco, ARQC/UN reutilizado →
  indicios de **replay**. Base del caso `mock_card_ATC*.json`.
- `switch` — **flujo genérico de switch/adquirente ISO 8583** (efecto): `SwitchConfig` (host/puerto/
  TLS/TPDU/framing + perfil de terminal; `from_vars(get)` lo arma desde variables del proyecto) y
  `run_signon()/run_purchase()/run_reversal()`. Modela un flujo de switch real pero **sin objetivos
  hardcodeados**: cada proyecto apunta al suyo por configuración. `iso_host` es el cliente
  TCP simple; `switch` añade sign-on 0800, TPDU, TLS y el parseo de F39 (`iso8583.response_meaning`).

## 11. Framework de PoCs (`emvy/poc/`)

**Runner + plugins** (sin PoCs integrados). Los PoCs viven en `<proyecto>/pocs/*.py` y se registran con
`@poc(...)`; el resultado y las evidencias se guardan en `<proyecto>/poc_runs/<ts>-<id>/`.

```python
from emvy.poc import poc, Severity, Status
from emvy.payments import cryptogram

@poc(id="atc-replay", title="Análisis ATC/ARQC", category="emv",
     severity=Severity.HIGH, authorization="Prueba autorizada — cliente X")
def run(ctx):
    rep = cryptogram.analyze([ctx.card])          # ctx.card = EmvCard (de --card)
    ctx.save_evidence("report.txt", rep.summary())
    return ctx.result(Status.VULNERABLE if rep.replay_risk else Status.INFO, rep.summary())
```

**PoCs genéricos (plantillas)**: `emvy.poc.templates` trae PoCs reutilizables para **cualquier
proyecto/switch**, configurables por variables (switch_host, switch_port, switch_tls, tpdu,
terminal_id, merchant_id, mcc, currency, country, amount…): `iso8583-signon` (0800), `iso8583-purchase`
(0200→0210 con F55/ARQC real, respeta dry-run) e `iso8583-reversal` (0400→0410). Se materializan con
`emvy poc new <id> --template <nombre>` (o `poc templates` para listarlas; Select en la TUI). Usan
`payments.switch`. `poc run --card` acepta tanto un CardDump como un JSON de BomberCat.

CLI: `emvy poc new <id> [--template <t>]` · `emvy poc templates` · `emvy poc list` · `emvy poc run <id>
[--card cap.json] [--var k=v] [--dry-run] [--allow-write]` · `emvy poc runs|show`. También en la TUI (pestaña **PoC**, atajo `o`):
**ejecutar** eligiendo la fuente de la tarjeta (sesión / captura guardada / **lector en vivo** /
ninguna), con **dry-run** y **allow-write**; y un **IDE integrado** para crear/editar/eliminar los
`<proyecto>/pocs/*.py` (editor Python + panel de referencia con la API de `ctx`, las variables del
proyecto y el lector conectado). Cada run va a su propio `poc_runs/<ts>-<id>[-n]` (sin colisión).

`PocContext` da: `ctx.var(name)`/`ctx.require(name)` (variables del proyecto), `ctx.card` (EmvCard),
`ctx.http()` (cliente con **evidencia automática**, **solo-lectura** salvo `--allow-write`/`allow=`, y
`--dry-run`), `ctx.save_evidence()`, `ctx.finding()`/`ctx.result()`. Los PoCs específicos de cada
engagement viven en `engagements/<cliente>/pocs/` (ver §13), **no** en el core.

**Proyectos en ruta** (para engagements versionados en el repo): además de los proyectos XDG
(`~/.local/share/emvy/projects/<nombre>`), un proyecto puede vivir en cualquier carpeta con
`project.json`. `emvy project use ./ruta` (o `export EMVY_PROJECT=/ruta`) lo activa;
`store.open_project_path()/create_project_at()` lo gestionan. Prioridad del activo:
`EMVY_PROJECT` > `active_path` > nombre XDG.

**Descubrimiento de engagements**: `emvy project list` (y la pestaña Proyectos de la TUI) además de
los XDG muestran los proyectos en ruta encontrados bajo las **raíces de engagements**
(`config.engagements_dirs()`: `<repo>/engagements`, `./engagements`, y las de `EMVY_ENGAGEMENTS`,
separadas por `os.pathsep`). Así un engagement en `engagements/<cliente>/` aparece en la lista sin
tener que activarlo antes; se activa por ruta (`set_active_path`) y no se borra desde la TUI.
`store.list_path_projects()` implementa la búsqueda.

---

## 12. bombercat-tools (framework oficial) + firmware unificado

**bombercat-tools** (Electronic Cats, v1.2.0.0) es el framework oficial que controla el BomberCat y
flashea firmwares `.uf2` prebuilt (release `ElectronicCats/bombercat-firmware`, v1.2.0.0: NFCGate,
DetectTags, DetectReaders, magspoof, WiFiWebServer…). Está como **submódulo git** en
`vendor/bombercat-tools/` (`git submodule update --init`; `.gitmodules`), fijado al commit
`c636721` (v1.2.0.0 + `setup-env`, aún sin tag: es HEAD de `feature/packaging`/PR#3 — re-pinear a un
tag cuando lo publiquen). Usa su **propio venv aislado** en `vendor/bombercat-tools/.venv` (deps con
pines propios, no el venv de EMVy). CI lo inicializa con `submodules: recursive`.

> **Operar firmwares oficiales (rama `Test`) requiere el vendor en v1.3.0.** Los paneles GUI
> `TagsPanel`/`ReadersPanel`/`MagspoofPanel`/`MifarePanel`/`RelayPanel` (ADR-001) y sus helpers
> del orquestador (`status_json`/`identify`/`tags mifare`/`magspoof`/`relay`/`capture`) usan
> subcomandos que **aparecen en v1.3.0** del framework. El submódulo sigue clavado a v1.2.0.0; para
> operar hardware real, sube el pin (`git -C vendor/bombercat-tools checkout v1.3.0 && git submodule
> update`). Los helpers **degradan limpio** (`BombercatToolsError`) si el subcomando no existe, y los
> tests los cubren offline (monkeypatch de `run_capture`/`run_json`), así que la suite pasa sin bumpear.

- **Adaptador**: `emvy/integrations/bombercat_tools.py` lo maneja por **subprocess** —
  `locate()`/`ensure_venv()` (bootstrap perezoso), `run_passthrough()`, `run_json()` (extrae JSON de
  la salida rica), helpers `devices()/status()/fw_list()/flash()/tags_read()/readers_read()`, y
  `setup_env_passthrough()`/`setup_env_gui()` (permisos USB: reglas udev `99-bombercat.rules` +
  grupos `dialout`/`plugdev`, Linux; la variante GUI eleva con `pkexec`). `_env()` fija
  `BOMBERCAT_AUTO_FLASH=never` para que `tags`/`readers` no cuelguen en un prompt de auto-flash
  invisible al invocarse por subprocess. CLI `emvy bombercat setup-env`; botón "Permisos USB"/
  "Configurar permisos USB" en el panel BomberCat (TUI/GUI).
  Para la **TUI** (que no hereda stdout) hay variantes que **capturan**: `fw_list_names()` (parsea la
  tabla de `flash --list`), `flash_capture()`, `devices_text()`, `status_text()` — las usa la pestaña
  **BomberCat**. Ruta configurable con `EMVY_BOMBERCAT_TOOLS`.
- **Fuentes alternas** (`emvy/integrations/firmware_sources.py`): agrega fuentes GitHub (`owner/repo`,
  toma los `.uf2` del último release vía API) o URL directa; descarga a `<data>/firmware_cache/` y
  limpia. Persistencia en `<config>/firmware_sources.json`. **Compilación propia**
  (`emvy/integrations/arduino.py`): `list_sketches()` (carpetas de `firmware/` con `.ino`) +
  `compile_sketch()` (usa el `build.sh` del sketch o `arduino-cli compile --output-dir build`) +
  `upload_sketch()`. **Importante**: el FQBN `bombercat` sube por **picotool**
  (`bombercat.upload.tool=picotool` en `boards.txt`, reset a 1200-bps + carga directa del
  `.elf`/`.bin`), confirmado compilando de verdad (`arduino-cli compile` no genera `.uf2` para esta
  placa). El botón **"Compilar y subir (picotool)"** de la TUI usa `upload_sketch()`, **no** el
  flasher `.uf2` de bombercat-tools (ese es solo para las imágenes oficiales prebuilt).
  **Validado en hardware real** (2026-09-05, BomberCat genuino): compila limpio (152 823 bytes);
  `arduino-cli upload`/picotool falla en Linux sin una **regla udev** para `idVendor=2e8a` ("try sudo
  or check your permissions") — el touch-reset a 1200-bps sí funciona, pero el acceso USB crudo
  posterior no. Fix de una vez: `echo 'SUBSYSTEM=="usb", ATTRS{idVendor}=="2e8a", MODE="0666"' | sudo
  tee /etc/udev/rules.d/99-pico.rules && sudo udevadm control --reload-rules --trigger`. Alternativa
  sin permisos (la que sí funcionó aquí): convertir el `.elf` a `.uf2` con el `elf2uf2` del paquete de
  la placa (`~/.arduino15/packages/electroniccats/tools/rp2040tools/*/elf2uf2`) y copiarlo a la unidad
  `RPI-RP2` montada. Tras flashear, `PING`→`PONG` y el AP `EMVyBomberCat` quedó visible por WiFi
  (confirma el rebranding en hardware real).
  **Bug de identificación USB conocido en `electroniccats:mbed_rp2040` v2.0.0** (la única versión
  publicada — no hay fix aguas arriba): el variant `BOMBERCAT` (`pins_arduino.h` línea 65-66,
  `boards.txt` línea 16) deja **hardcodeado** `BOARD_VENDORID=0x2341 BOARD_PRODUCTID=0x005e
  BOARD_NAME="Nano RP2040 Connect"` y `-DARDUINO_NANO_RP2040_CONNECT` (leftover de copiar el variant
  del Nano RP2040 Connect), aunque `boards.txt` sí declara el VID correcto de BomberCat
  (`vid.0=0x1209 pid.0=0x005e`, pid.codes). Efecto: un BomberCat **genuino** enumera por USB como
  `2341:005e Arduino SA Nano RP2040 Connect` y `arduino-cli board list`/`emvy readers` lo etiquetan
  así — **puramente cosmético**, no indica placa incorrecta. La tabla de pines (`variant.cpp`) es la
  MISMA del Nano RP2040 Connect, pero **IRQ=11/VEN=13 para el PN7150 son correctos**: coinciden
  exactamente con el ejemplo oficial `Electronic_Cats_PN7150/examples/DetectTags/DetectTags.ino`.
  Parche opcional (fuera del repo, en el paquete global de Arduino, se revierte con
  `arduino-cli core update`): editar
  `~/.arduino15/packages/electroniccats/hardware/mbed_rp2040/2.0.0/variants/BOMBERCAT/pins_arduino.h`
  (líneas 65-66) a `BOARD_VENDORID 0x1209`, `BOARD_PRODUCTID 0x005e`, `BOARD_NAME "BomberCat"`, y en
  `boards.txt` línea 16 quitar `-DARDUINO_NANO_RP2040_CONNECT`.
- **CLI** (grupo `bombercat`, además de los verbos serie propios `read/apdu/monitor/magspoof/cmd`):
  `emvy bombercat setup` (prepara venv) · `tools -- <args>` (passthrough) ·
  `fw list|flash <NOMBRE>` (UF2 oficial) · `devices|status|tags|readers|relay`.
- **Flasheo**: `emvy bombercat fw flash <NOMBRE>` baja el `.uf2` y lo escribe por UF2 (reset 1200-bps
  → unidad `RPI-RP2`; si el board no entra solo, doble-tap RESET). UF2 es recuperable vía BOOTSEL.

**Firmware unificado "navaja suiza"** — `firmware/EMVyBomberCat/` (sketch multi-archivo):
base = lector EMV + passthrough (de `bombercat_emv_reader.ino`) + `modes_tags.ino` (UID) +
`modes_mag.ino` (magspoof). Dispatcher serie: `SCAN` (EMV→JSON), `PING/WAIT/APDU:/RELEASE`
(passthrough), `TAG` (UID), `MAG:<t1>|<t2>` (banda). **Compila** limpio para
`electroniccats:mbed_rp2040:bombercat` (`build.sh`); requiere core *Electronic Cats mbed RP2040* +
libs *Electronic Cats PN7150* / *WiFiNINA* / *ArduinoJson*. NFC/magspoof necesitan el hardware real
del BomberCat (PN7150 + bobina); en un Nano RP2040 Connect (sin PN7150) el firmware compila y
flashea pero se detiene en la init de periféricos — usar un BomberCat real para operar.

Nota de entorno (corregida 2026-09-05): el hardware conectado **es un BomberCat genuino** — el USB
lo identifica como `2341:005E Arduino SA Nano RP2040 Connect` / `rp2040:rp2040:arduino_nano_connect`
por el **bug de packaging descrito arriba** (VID/nombre hardcodeados del Nano RP2040 Connect en el
variant `BOMBERCAT`), no porque el hardware sea otro. No usar el VID/PID reportado como señal de
qué placa está conectada.

---

## 13. Layout del repo y engagements

La **herramienta** es genérica y vive en el repo; los **engagements** (datos/objetivos de cliente)
viven en carpetas-proyecto aparte:

```
EMVyController/
├── emvy/                el paquete (herramienta) — genérico, sin objetivos de cliente
├── firmware/            firmware BomberCat (EMVyBomberCat, bombercat_emv_reader, I2CDiscover)
├── vendor/              terceros vendorizados (bombercat-tools)
├── tests/               suite offline
└── engagements/         proyectos EMVy por cliente (versionables, NO se comparten con la herramienta)
    └── <cliente>/       project.json, variables, captures, pocs, tools, artifacts
```

**Engagements** (`engagements/<cliente>/`): cada uno es un proyecto EMVy en ruta (`project.json`).
Actívalo con `emvy project use ./engagements/<cliente>` (o `EMVY_PROJECT=…`). Contiene lo específico
del cliente: `captures/`, `pocs/` (plugins `@poc`, incluidos wrappers de ejecutables propios que
corren bajo `emvy poc run` y guardan su salida como evidencia respetando `--dry-run`), `tools/`,
`artifacts/`. **Regla**: nada específico de cliente entra en `emvy/` ni `firmware/`; va a
`engagements/<cliente>/`. La herramienta es genérica y **no debe mencionar clientes**; para PoCs de
pago reutilizables usa `payments.switch` + las plantillas `emvy poc new <id> --template iso8583-*`.
