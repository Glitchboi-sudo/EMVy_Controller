"""Panel explorador: captura la tarjeta y muestra apps/registros como árbol TLV.

Cada nodo con valor lleva datos estructurados (tag / valor hex / ASCII) para:
  - **copiar** el valor (hex o ASCII) al portapapeles;
  - **asignarlo a una variable** del proyecto (existente o nueva), en hex o ASCII,
    con la codificación correcta según el tag destino;
  - **guardar la captura** completa en el proyecto activo.
"""
from __future__ import annotations

from datetime import datetime

from textual import on
from textual.actions import SkipAction
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import (
    Button, Checkbox, Collapsible, Input, Label, Select, Static, Tree,
)

from ...core import tlv
from ...core.hexutil import from_hex
from ...project import env as envmod
from ...project import store
from ..widgets.copyable import CopyableDataTable, has_text_selection
from ..widgets.tlvtree import add_tlvs, ascii_of
from .console import ConsoleScreen
from .intelrecs import IntelRecsScreen


def _hexdata(tag, hexstr, suggest=None):
    try:
        ascii_ = ascii_of(from_hex(hexstr))
    except ValueError:
        ascii_ = ""
    return {"tag": tag, "value": hexstr, "ascii": ascii_, "is_hex": True,
            "suggest": suggest or tag}


def _textdata(text, suggest):
    return {"tag": None, "value": str(text), "ascii": str(text), "is_hex": False,
            "suggest": suggest}


class ExplorerScreen(Vertical):
    """Explorador de tarjeta en dos paneles: el **árbol TLV** ocupa la mayor
    parte a la izquierda; un **inspector** a la derecha agrupa las acciones
    contextuales (nodo seleccionado → copiar/asignar, y guardar la captura).
    La consola en vivo va, colapsable, al pie."""

    # Ctrl+C copia el nodo resaltado del árbol (los `Tree` no permiten
    # selección de texto con el ratón). Si hay una selección de texto en la
    # pantalla, se cede al Ctrl+C estándar (copia la selección).
    BINDINGS = [Binding("ctrl+c", "copy_node", "Copiar nodo", show=False)]

    DEFAULT_CSS = """
    ExplorerScreen { padding: 0 1; }
    ExplorerScreen .exp-sub { color: $text-muted; padding: 0 0 1 0; }

    /* Barra de acciones superior (captura / análisis) */
    ExplorerScreen #exp-actions { height: auto; padding: 0 0 1 0; }
    ExplorerScreen #exp-actions Button { margin: 0 1 0 0; min-width: 14; }

    /* Zona principal: árbol (2fr) + inspector (1fr) */
    ExplorerScreen #exp-main { height: 1fr; }
    ExplorerScreen #exp_tree {
        width: 2fr; height: 100%; margin: 0 1 0 0;
        border: round $primary; padding: 0 1; background: $panel 40%;
    }
    ExplorerScreen #exp_tree:focus { border: round $accent; }
    ExplorerScreen #exp_sidebar {
        width: 1fr; height: 100%; min-width: 32;
        border: round $primary; padding: 0 1;
    }

    /* Etiquetas de sección del inspector */
    ExplorerScreen .exp-label {
        text-style: bold; color: $accent; padding: 1 0 0 0;
    }
    ExplorerScreen .exp-label-first { text-style: bold; color: $accent; }
    ExplorerScreen #exp_detail { height: auto; padding: 0 0 1 0; }

    /* Filas dentro del inspector: inputs a lo ancho, botones compactos */
    ExplorerScreen .exp-inrow { height: auto; padding: 0 0 1 0; }
    ExplorerScreen .exp-inrow Input { width: 1fr; }
    ExplorerScreen .exp-inrow Button { margin: 0 0 0 1; min-width: 6; }
    ExplorerScreen .exp-copyrow { height: auto; }
    ExplorerScreen .exp-copyrow Button { margin: 0 1 0 0; min-width: 6; }
    ExplorerScreen .exp-copyhint { color: $text-muted; padding: 0 0 1 0; }
    ExplorerScreen .exp-chkrow { height: auto; }
    ExplorerScreen .exp-chkrow Checkbox { width: auto; margin: 0 2 0 0; }

    /* Sección INTEL: tabla compacta + botón de recomendaciones */
    ExplorerScreen #exp_intel_table { height: auto; max-height: 10; }
    ExplorerScreen .exp-intelrow { height: auto; padding: 1 0 0 0; }
    ExplorerScreen .exp-intelrow Button { min-width: 16; }

    /* Consola embebida al pie */
    ExplorerScreen #exp_console_box { height: auto; margin: 1 0 0 0; }
    ExplorerScreen #screen-console { height: auto; }
    ExplorerScreen #screen-console RichLog { height: 10; }
    """

    def compose(self):
        yield Label("Explorador de tarjeta", classes="title")
        yield Static("Captura una tarjeta, inspecciona su árbol TLV y exporta lo que "
                     "encuentres.", classes="exp-sub")

        with Horizontal(id="exp-actions"):
            yield Button("● Capturar", id="exp_capture", variant="success")
            yield Button("◐ Dump crudo", id="exp_raw", variant="warning")
            yield Button("🔒 Analizar", id="exp_analyze", variant="primary")
            yield Button("Limpiar", id="exp_clear")

        with Horizontal(id="exp-main"):
            yield Tree("tarjeta", id="exp_tree")
            with VerticalScroll(id="exp_sidebar"):
                yield Static("IDENTIDAD DE TARJETA", classes="exp-label-first")
                yield Static("[dim]Sin captura.[/]", id="exp_identity")

                yield Static("NODO SELECCIONADO", classes="exp-label")
                yield Label("[dim]Selecciona un nodo del árbol para copiar o "
                            "asignar su valor.[/]", id="exp_detail")
                with Horizontal(classes="exp-copyrow"):
                    yield Button("Hex", id="exp_copy")
                    yield Button("ASCII", id="exp_copyascii")
                    yield Button("tag=val", id="exp_copytv")
                yield Static("[dim]Ctrl+C copia el nodo. En consola/paneles: "
                             "arrastra para seleccionar y Ctrl+C.[/]",
                             classes="exp-copyhint")

                yield Static("ASIGNAR A VARIABLE", classes="exp-label")
                with Horizontal(classes="exp-inrow"):
                    yield Input(placeholder="destino (tag/alias/nombre; vacío = sugerido)",
                                id="exp_varname")
                    yield Button("→", id="exp_assign", variant="success")
                with Horizontal(classes="exp-chkrow"):
                    yield Checkbox("libre", id="exp_varuser")
                    yield Checkbox("ASCII", id="exp_varascii")

                yield Static("GUARDAR CAPTURA", classes="exp-label")
                yield Select([("→ proyecto activo", "active")], value="active",
                             allow_blank=False, id="exp_dest")
                with Horizontal(classes="exp-inrow"):
                    yield Input(placeholder="nombre (o ruta .json si destino=archivo)",
                                id="exp_savename")
                    yield Button("Guardar", id="exp_save", variant="warning")

                yield Static("INTEL", classes="exp-label")
                yield CopyableDataTable(id="exp_intel_table")
                with Horizontal(classes="exp-intelrow"):
                    yield Button("Recomendaciones", id="exp_intel_recs")

        with Collapsible(title="Consola en vivo (APDU + transporte del lector)",
                         collapsed=True, id="exp_console_box"):
            yield ConsoleScreen(id="screen-console")

    def on_mount(self):
        self._sel: dict | None = None
        self._profile = None          # CardProfile de la última captura mostrada
        tree = self.query_one("#exp_tree", Tree)
        tree.border_title = "Árbol TLV"
        tree.show_root = True
        try:
            self.query_one("#exp_sidebar").border_title = "Inspector"
        except Exception:
            pass
        table = self.query_one("#exp_intel_table", CopyableDataTable)
        table.add_columns("hash", "esquema", "veces", "última")
        table.border_title = "Tarjetas del proyecto"
        self._empty_tree()
        self.reload()

    def _empty_tree(self):
        """Estado vacío del árbol: un marcador amable en vez de un nodo pelón."""
        tree = self.query_one("#exp_tree", Tree)
        tree.reset("tarjeta")
        tree.root.add_leaf("[dim]Sin captura — pulsa «Capturar» o «Dump crudo».[/]")
        tree.root.expand()

    def reload(self):
        """Repuebla los destinos de guardado (proyectos + archivo) y la tabla INTEL."""
        opts = [("→ proyecto activo", "active")]
        for p in store.list_projects():
            opts.append((f"→ proyecto: {p.name}", f"proj:{p.name}"))
        for p in store.list_path_projects():
            opts.append((f"→ ruta: {p.name}", f"path:{p.path}"))
        opts.append(("→ archivo (el campo es la ruta)", "file"))
        try:
            self.query_one("#exp_dest", Select).set_options(opts)
        except Exception:
            pass
        self._reload_intel_table()

    # -- intel: identidad de tarjeta + tabla del proyecto --------------------
    def _reload_intel_table(self):
        """Tarjetas conocidas del proyecto en la tabla INTEL (defensivo: la DB
        es local y pequeña; ante cualquier error se muestra un mensaje honesto)."""
        table = self.query_one("#exp_intel_table", CopyableDataTable)
        table.clear()
        proj = store.active_project()
        if not proj:
            return
        try:
            from ...project.inteldb import IntelDB
            with IntelDB(proj) as db:
                rows = db.list_cards()
        except Exception:
            return
        for r in rows:
            table.add_row(r.hash[:12], r.profile.scheme or "?",
                          str(r.times_seen),
                          datetime.fromtimestamp(r.last_seen).strftime("%Y-%m-%d"))

    def _update_identity(self, dump):
        """Calcula el fingerprint de la captura y lo muestra en el inspector;
        con proyecto activo registra la tarjeta (vista N veces) en la intel DB."""
        from ...core import fingerprint
        label = self.query_one("#exp_identity", Static)
        try:
            profile = fingerprint.profile_from_dump(dump)
        except Exception:
            profile = None
        self._profile = profile
        if profile is None:
            label.update("[dim]Captura sin datos de aplicación: sin identidad.[/]")
            return
        proj = store.active_project()
        if not proj:
            label.update(f"[b cyan]{profile.hash[:16]}[/]…\n"
                         "[dim]Sin proyecto activo: no se consulta la intel DB.[/]")
            return
        try:
            from ...project.inteldb import IntelDB
            with IntelDB(proj) as db:
                row = db.upsert_card(profile)
        except Exception:
            label.update(f"[b cyan]{profile.hash[:16]}[/]…\n"
                         "[dim]No se pudo consultar la intel DB.[/]")
            return
        veces = "vez" if row.times_seen == 1 else "veces"
        nota = f"\n[dim]{row.notes[:64]}[/]" if row.notes else ""
        label.update(f"[b cyan]{profile.hash[:16]}[/]…  "
                     f"[green]{profile.scheme or '?'}[/]\n"
                     f"Vista {row.times_seen} {veces} en el proyecto · "
                     f"última {datetime.fromtimestamp(row.last_seen):%Y-%m-%d %H:%M}{nota}")
        self._reload_intel_table()

    @on(Button.Pressed, "#exp_intel_recs")
    def _intel_recs(self):
        """Abre el modal de recomendaciones para el hash mostrado (si hay)."""
        if self._profile is None:
            self.app.notify("Captura una tarjeta primero (la identidad da el hash).",
                            severity="warning")
            return
        proj = store.active_project()
        if not proj:
            self.app.notify("Sin proyecto activo: no hay intel DB que consultar.",
                            severity="warning")
            return
        try:
            from ...project.inteldb import IntelDB
            with IntelDB(proj) as db:
                recs = db.recommend_for(self._profile.hash)
        except Exception as e:
            self.app.notify(f"No se pudieron calcular recomendaciones: {e}",
                            severity="error")
            return
        self.app.push_screen(IntelRecsScreen(self._profile.hash[:16], recs))

    # -- captura ------------------------------------------------------------
    # "Capturar tarjeta" siempre prueba EMV y, si no hay apps, cae a NFC
    # genérico (mode="auto") — sin pedirle al usuario que elija de antemano.
    @on(Button.Pressed, "#exp_capture")
    def _capture(self):
        self.app.capture_card_ui(mode="auto")

    # "Dump crudo" se adapta al lector conectado: con BomberCat usa el modo
    # NFC genérico (se salta el barrido ciego READ RECORD/GET DATA, que son
    # cientos de intercambios EMV-específicos) porque el rango de contacto
    # NFC es de milímetros y una tarjeta sostenida a mano se sale del campo
    # a mitad de un barrido largo; con otros lectores (contacto, más estable)
    # se mantiene el barrido crudo completo.
    @on(Button.Pressed, "#exp_raw")
    def _raw(self):
        backend = getattr(getattr(self.app, "reader_device", None), "backend", None)
        if backend == "bombercat":
            self.app.notify("Dump crudo (NFC genérico): sostén la tarjeta firme y cerca…")
            self.app.capture_card_ui(mode="nfc")
        else:
            self.app.notify("Dump crudo: leyendo lo que haya en la tarjeta…")
            self.app.capture_card_ui(raw=True)

    @on(Button.Pressed, "#exp_analyze")
    def _analyze(self):
        from ...core import analyze
        from ...session.model import tlvs_from_dump
        dump = getattr(self.app, "last_dump", None)
        if dump is None:
            self.app.notify("No hay captura para analizar (captura primero).",
                            severity="warning")
            return
        app, tlvs = tlvs_from_dump(dump)
        if not tlvs:
            self.app.notify("La captura no tiene datos de aplicación.", severity="warning")
            return
        a = analyze.assess(tlvs)
        tree = self.query_one("#exp_tree", Tree)
        node = tree.root.add("[b yellow]🔒 ANÁLISIS DE SEGURIDAD[/]")
        caps = node.add("[b]Capacidades / CVM / ODA[/]")
        for line in a.summary().splitlines():
            caps.add_leaf(line)
        if a.findings:
            fnode = node.add(f"[b red]Hallazgos ({len(a.findings)})[/]")
            for f in a.findings:
                fnode.add_leaf(f"[yellow]! {f}[/]")
        node.expand()
        self.app.notify(f"Análisis: {len(a.findings)} hallazgo(s).")

    @on(Button.Pressed, "#exp_clear")
    def _clear(self):
        self._empty_tree()
        self._sel = None
        self._profile = None
        self.query_one("#exp_identity", Static).update("[dim]Sin captura.[/]")
        self.query_one("#exp_detail", Label).update(
            "[dim]Selecciona un nodo del árbol para copiar o asignar su valor.[/]")

    # -- guardar la captura en el proyecto ---------------------------------
    def _resolve_project(self, dest: str):
        if dest == "active":
            return store.active_project()
        if dest.startswith("proj:"):
            return store.open_project(dest[5:])
        if dest.startswith("path:"):
            return store.open_project_path(dest[5:])
        return None

    @on(Button.Pressed, "#exp_save")
    @on(Input.Submitted, "#exp_savename")
    def _save(self, _event=None):
        dump = getattr(self.app, "last_dump", None)
        if dump is None:
            self.app.notify("No hay captura que guardar (captura una tarjeta primero).",
                            severity="warning")
            return
        dest = self.query_one("#exp_dest", Select).value
        name = self.query_one("#exp_savename", Input).value.strip()
        ts = f"captura-{datetime.now():%Y%m%d-%H%M%S}"
        try:
            if dest == "file":                                   # guardar en un archivo
                from pathlib import Path
                if not name:
                    self.app.notify("Indica la ruta del archivo .json.", severity="warning")
                    return
                path = Path(name).expanduser()
                if path.is_dir() or path.suffix == "":
                    path = path / f"{ts}.json"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(dump.to_json())
                where = str(path)
            else:                                                # guardar en un proyecto
                proj = self._resolve_project(dest)
                if not proj:
                    self.app.notify("Sin proyecto destino (crea/activa uno).", severity="warning")
                    return
                saved = store.save_capture(proj, name or ts, dump.to_json())
                where = f"{proj.name}/{saved.name}"
        except Exception as e:
            self.app.notify(f"No se pudo guardar: {e}", severity="error")
            return
        self.query_one("#exp_savename", Input).value = ""
        self.app.refresh_ui()
        self.app.notify(f"Captura guardada → {where}")

    # -- selección: refleja el nodo activo (hex + ASCII) -------------------
    @on(Tree.NodeHighlighted, "#exp_tree")
    def _highlight(self, event):
        data = event.node.data
        self._sel = data if isinstance(data, dict) else None
        detail = self.query_one("#exp_detail", Label)
        if not self._sel:
            detail.update("[dim]nodo sin valor asignable[/]")
            return
        tag = self._sel.get("tag")
        ascii_ = self._sel.get("ascii") or ""
        val = self._sel["value"]
        val_show = val if len(val) <= 72 else val[:72] + "…"
        lines = [f"[dim]tag[/]    [b cyan]{tag or '—'}[/]",
                 f"[dim]valor[/]  [yellow]{val_show}[/]"]
        if ascii_:
            lines.append(f'[dim]ascii[/]  [green]"{ascii_}"[/]')
        sug = self._sel.get("suggest")
        if sug:
            lines.append(f"[dim]→ sugerido: {sug}[/]")
        detail.update("\n".join(lines))

    # -- copiar al portapapeles --------------------------------------------
    def action_copy_node(self) -> None:
        """Ctrl+C dentro del Explorador: copia el valor del nodo resaltado.
        Cede (SkipAction) a la copia de selección de texto estándar cuando el
        usuario tiene una selección activa, o cuando no hay nodo con valor."""
        if has_text_selection(self):
            raise SkipAction()
        if not self._sel:
            raise SkipAction()
        self._to_clipboard(self._sel["value"])

    @on(Button.Pressed, "#exp_copy")
    def _copy_value(self):
        if self._require_sel():
            self._to_clipboard(self._sel["value"])

    @on(Button.Pressed, "#exp_copyascii")
    def _copy_ascii(self):
        if not self._require_sel():
            return
        ascii_ = self._sel.get("ascii")
        if not ascii_:
            self.app.notify("Este valor no tiene ASCII imprimible.", severity="warning")
            return
        self._to_clipboard(ascii_)

    @on(Button.Pressed, "#exp_copytv")
    def _copy_tagvalue(self):
        if self._require_sel():
            tag = self._sel.get("tag") or "?"
            self._to_clipboard(f"{tag}={self._sel['value']}")

    def _to_clipboard(self, text: str):
        try:
            self.app.copy_to_clipboard(text)
        except Exception:
            pass
        shown = text if len(text) <= 48 else text[:48] + "…"
        self.app.notify(f"Copiado: {shown}")

    # -- asignar a variable de entorno (hex o ASCII) -----------------------
    @on(Button.Pressed, "#exp_assign")
    @on(Input.Submitted, "#exp_varname")
    def _assign(self, _event=None):
        if not self._require_sel():
            return
        proj = store.active_project()
        if not proj:
            self.app.notify("No hay proyecto activo (pestaña Proyectos).", severity="warning")
            return
        name = (self.query_one("#exp_varname", Input).value.strip()
                or self._sel.get("suggest") or "")
        if not name:
            self.app.notify("Indica un nombre de variable.", severity="warning")
            return
        force_user = self.query_one("#exp_varuser", Checkbox).value

        # ¿asignar el ASCII en vez del hex?
        if self.query_one("#exp_varascii", Checkbox).value and self._sel.get("ascii"):
            value, is_hex = self._sel["ascii"], False
        else:
            value, is_hex = self._sel["value"], self._sel.get("is_hex", True)

        # Destino terminal si el nombre mapea a un tag; codifica acorde.
        tag = None if force_user else envmod.resolve_tag(name)
        try:
            if tag is not None and is_hex:
                value_str = envmod.decode_value(tag, from_hex(value))
            elif tag is not None and not is_hex and not envmod.is_text_tag(tag):
                tag, value_str = None, value      # texto hacia tag numérico -> user
            else:
                value_str = value
            kind = "terminal" if tag is not None else "user"
            variables = store.load_project_variables(proj)
            variables = envmod.set_var(variables, name, value_str, kind=kind)
            store.save_project_variables(proj, variables)
        except Exception as e:
            self.app.notify(f"No se pudo asignar: {e}", severity="error")
            return
        self.query_one("#exp_varname", Input).value = ""
        self.app.refresh_ui()
        self.app.notify(f"{name} = {value_str}  → guardado ({kind}).")

    def _require_sel(self) -> bool:
        if self._sel:
            return True
        self.app.notify("Selecciona un nodo con valor en el árbol.", severity="warning")
        return False

    # -- poblado desde el hilo principal (lo llama la app) ------------------
    def show_dump(self, dump):
        self._update_identity(dump)
        tree = self.query_one("#exp_tree", Tree)
        n = len(dump.applications)
        tree.reset(f"[b]tarjeta[/]  [dim]{n} app{'s' if n != 1 else ''} · "
                   f"{len(dump.blobs)} blobs[/]")
        blobs = {b["source"]: b["hex"] for b in dump.blobs}
        for app in dump.applications:
            aid = app["aid"]
            label = app.get("label", "")
            meta = " · ".join(x for x in (label, app.get("source", "")) if x)
            node = tree.root.add(
                f"[b cyan]{aid}[/]  [b]{app['scheme']}[/]"
                + (f"  [dim]{meta}[/]" if meta else ""),
                data=_hexdata("4F", aid))
            ch = app.get("cardholder") or {}
            if ch:
                info = node.add("[b]Titular[/]")
                for k, v in ch.items():
                    info.add_leaf(f"[green]{k}[/][dim]:[/] {v}", data=_textdata(v, k))
            if app.get("aip"):
                node.add_leaf(f"AIP [dim]=[/] [yellow]{app['aip']}[/]",
                              data=_hexdata("82", app["aip"]))
            if app.get("afl"):
                node.add_leaf(f"AFL [dim]=[/] [yellow]{app['afl']}[/]",
                              data=_hexdata("94", app["afl"]))
            ndef_records = app.get("ndef_records") or []
            if ndef_records:
                nnode = node.add(f"[b green]★ NDEF[/] [dim]({len(ndef_records)})[/]")
                for line in ndef_records:
                    nnode.add_leaf(f"[green]{line}[/]", data=_textdata(line, "ndef"))
            fci_hex = blobs.get(f"{aid}:FCI")
            if fci_hex:
                fnode = node.add("[b]FCI[/]")
                add_tlvs(fnode, tlv.parse(from_hex(fci_hex)))
            records = app.get("records", [])
            for rec in records:
                rnode = node.add(f"[b]SFI {rec['sfi']}[/] [dim]·[/] REC {rec['record']}")
                add_tlvs(rnode, tlv.parse(from_hex(rec["hex"])))
            gd = app.get("get_data") or {}
            if gd:
                gnode = node.add(f"[b]GET DATA[/] [dim]({len(gd)})[/]")
                for tg, hx in gd.items():
                    short = hx if len(hx) <= 40 else hx[:40] + "…"
                    leaf = gnode.add(f"[cyan]{tg}[/][dim]:[/] [yellow]{short}[/]",
                                     data=_hexdata(tg, hx))
                    try:  # si el valor es TLV (p.ej. una FCI de SELECT), muéstralo como árbol
                        parsed = tlv.parse(from_hex(hx))
                        if parsed and any(t.constructed for t in parsed):
                            add_tlvs(leaf, parsed)
                    except Exception:
                        pass
        tree.root.expand()
