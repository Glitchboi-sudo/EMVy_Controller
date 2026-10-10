"""Motor de mutaciones EMV sobre pares (comando, respuesta), en estilo puro.

Semántica adaptada del motor de mutaciones de atrium (relay orientado a
estado global y síncrono) a la arquitectura funcional de EMVy: cada función
recibe lo que necesita como argumento y devuelve copias, sin I/O ni estado
global. Las cinco familias ortogonales de reglas son:

1. **PDOL** (`pdol`): reescriben campos del GPO (CLA=80 INS=A8) antes de que
   llegue a la tarjeta — importe `9F02` (1 céntimo → umbral No-CVM), divisa
   `5F2A`, país `9F1A`, TTQ `9F66`. El layout del PDOL lo aporta quien llama
   (el último FCI visto, tag 9F38) o la propia config (`pdol_dol`).
2. **AFL** (`afl`): mutan el tag `94` de la respuesta GPO — `skip_signed`
   (contador de autenticación offline a 0 en cada entrada → derrota SDA/DDA),
   `truncate` (deja N entradas), `remove_sfi <n>`, `extend` (duplica/añade
   entradas). Basado en `emv.parse_afl`.
3. **DOL** (`dol`): mutan CDOL1 (`8C`) / CDOL2 (`8D`) en los registros —
   `remove_field` (quitar `9F02`/`9F34` → criptograma sin binding de
   importe/CVM), `truncate` (acortar a N campos). Basado en `tlv.parse_dol`.
4. **TLV de respuesta** (`response`): modos `replace | delete | splice | xor |
   flip_bit | prepend | append` sobre tags de las respuestas, limitables por
   `on_ins` (INS hex). Reescritura TLV recursiva (mismo recorrido que
   `intercept.set_tag_in`).
5. **Comandos inyectados** (`injections`): APDUs extra hacia la tarjeta en
   `before_command`/`after_response` (GET DATA silenciosos de ATC `9F36`,
   reintentos PIN `9F17`, Log Format `9F4F`). Sus respuestas se registran en
   las notas pero **jamás se reenvían al terminal**.

La config es un conjunto de dataclasses `frozen` construidas desde dicts con
`MutationConfig.from_dict(d)` (con `to_dict()` inverso); cada regla lleva
`enabled`/`comment`, al estilo del `mutations.yaml` de atrium pero en Python
puro. No se usa YAML ni ninguna dependencia nueva.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from . import tlv
from .apdu import APDU, Response, Transceiver
from .emv import parse_afl
from .hexutil import from_hex, to_hex
from .intercept import Exchange, to_apdu

# Modos válidos por familia (se validan en `from_dict`).
RESPONSE_MODES = ("replace", "delete", "splice", "xor", "flip_bit", "prepend", "append")
AFL_MODES = ("skip_signed", "truncate", "remove_sfi", "extend")
DOL_MODES = ("remove_field", "truncate")
INJECTION_WHEN = ("before_command", "after_response")

INS_GET_PROCESSING_OPTIONS = 0xA8
INS_SELECT = 0xA4

# Un DOL es una lista de (tag_hex, longitud); se comparte con tlv.parse_dol.
DOLLayout = list[tuple[str, int]]


# ---------------------------------------------------------------------------
# Reglas (dataclasses frozen)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class PDOLMutation:
    """Reescritura de un campo del PDOL dentro del comando GPO (80 A8)."""

    tag: str                 # tag a reescribir (p.ej. "9F02")
    value: bytes             # nuevo valor (se ajusta a la longitud declarada)
    enabled: bool = True
    comment: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "PDOLMutation":
        return cls(tag=str(d["tag"]).upper(),
                   value=from_hex(d.get("value", "")),
                   enabled=bool(d.get("enabled", True)),
                   comment=str(d.get("comment", "")))

    def to_dict(self) -> dict:
        return {"tag": self.tag, "value": to_hex(self.value),
                "enabled": self.enabled, "comment": self.comment}


@dataclass(frozen=True)
class AFLMutation:
    """Mutación del AFL (tag 94) de la respuesta GPO."""

    mode: str                        # skip_signed | truncate | remove_sfi | extend
    truncate_to: int = 1             # para truncate
    target_sfi: int = 0              # para remove_sfi
    extra_entries: tuple[dict, ...] = ()   # para extend: [{sfi,first,last,offline}]
    enabled: bool = True
    comment: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "AFLMutation":
        mode = str(d["mode"]).lower()
        if mode not in AFL_MODES:
            raise ValueError(f"modo AFL desconocido: {mode!r}")
        return cls(mode=mode,
                   truncate_to=int(d.get("truncate_to", 1)),
                   target_sfi=int(d.get("target_sfi", 0)),
                   extra_entries=tuple(dict(e) for e in d.get("extra_entries", ())),
                   enabled=bool(d.get("enabled", True)),
                   comment=str(d.get("comment", "")))

    def to_dict(self) -> dict:
        d: dict = {"mode": self.mode, "enabled": self.enabled, "comment": self.comment}
        if self.mode == "truncate":
            d["truncate_to"] = self.truncate_to
        if self.mode == "remove_sfi":
            d["target_sfi"] = self.target_sfi
        if self.mode == "extend":
            d["extra_entries"] = [dict(e) for e in self.extra_entries]
        return d


@dataclass(frozen=True)
class DOLMutation:
    """Mutación de un DOL (CDOL1=8C / CDOL2=8D) en las respuestas de registro."""

    target_tag: str              # "8C" | "8D"
    mode: str                    # remove_field | truncate
    field_tag: str = ""          # para remove_field
    truncate_to: int = 0         # para truncate
    enabled: bool = True
    comment: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "DOLMutation":
        mode = str(d["mode"]).lower()
        if mode not in DOL_MODES:
            raise ValueError(f"modo DOL desconocido: {mode!r}")
        return cls(target_tag=str(d["target_tag"]).upper(), mode=mode,
                   field_tag=str(d.get("field_tag", "")).upper(),
                   truncate_to=int(d.get("truncate_to", 0)),
                   enabled=bool(d.get("enabled", True)),
                   comment=str(d.get("comment", "")))

    def to_dict(self) -> dict:
        d: dict = {"target_tag": self.target_tag, "mode": self.mode,
                   "enabled": self.enabled, "comment": self.comment}
        if self.mode == "remove_field":
            d["field_tag"] = self.field_tag
        if self.mode == "truncate":
            d["truncate_to"] = self.truncate_to
        return d


@dataclass(frozen=True)
class ResponseMutation:
    """Mutación TLV sobre las respuestas, limitable por INS (`on_ins`)."""

    tag: str                     # tag a mutar (recursivo dentro de templates)
    mode: str                    # replace | delete | splice | xor | flip_bit | prepend | append
    value: bytes = b""           # valor/máscara/payload según el modo
    offset: int = 0              # para splice: posición dentro del valor
    bit_position: int = 0        # para flip_bit: 0 = MSB del valor completo
    on_ins: tuple[str, ...] = ()     # INS hex (p.ej. ("CA",)); vacío = todos
    enabled: bool = True
    comment: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "ResponseMutation":
        mode = str(d["mode"]).lower()
        if mode not in RESPONSE_MODES:
            raise ValueError(f"modo de respuesta desconocido: {mode!r}")
        return cls(tag=str(d["tag"]).upper(), mode=mode,
                   value=from_hex(d.get("value", "")),
                   offset=int(d.get("offset", 0)),
                   bit_position=int(d.get("bit_position", 0)),
                   on_ins=tuple(str(i).upper() for i in d.get("on_ins", ())),
                   enabled=bool(d.get("enabled", True)),
                   comment=str(d.get("comment", "")))

    def to_dict(self) -> dict:
        return {"tag": self.tag, "mode": self.mode, "value": to_hex(self.value),
                "offset": self.offset, "bit_position": self.bit_position,
                "on_ins": list(self.on_ins), "enabled": self.enabled,
                "comment": self.comment}


@dataclass(frozen=True)
class InjectedCommand:
    """APDU extra hacia la tarjeta; la respuesta se anota pero nunca se reenvía."""

    trigger_ins: str             # INS hex que dispara la inyección (p.ej. "AE")
    when: str                    # before_command | after_response
    apdu: bytes                  # APDU crudo a inyectar
    repeat: bool = False         # False = dispara una sola vez por sesión
    enabled: bool = True
    comment: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "InjectedCommand":
        when = str(d["when"]).lower()
        if when not in INJECTION_WHEN:
            raise ValueError(f"momento de inyección desconocido: {when!r}")
        return cls(trigger_ins=str(d["trigger_ins"]).upper(), when=when,
                   apdu=from_hex(d["apdu"]),
                   repeat=bool(d.get("repeat", False)),
                   enabled=bool(d.get("enabled", True)),
                   comment=str(d.get("comment", "")))

    def to_dict(self) -> dict:
        return {"trigger_ins": self.trigger_ins, "when": self.when,
                "apdu": to_hex(self.apdu), "repeat": self.repeat,
                "enabled": self.enabled, "comment": self.comment}


@dataclass(frozen=True)
class MutationConfig:
    """Configuración completa del motor: cinco familias de reglas + layout PDOL.

    `pdol_dol` es el layout esperado del PDOL (lista de (tag, longitud)) para
    cuando no hay FCI previo que lo aporte; el `mutating()` lo aprende de las
    respuestas SELECT (tag 9F38) y lo pasa a `apply_command`.
    """

    enabled: bool = True
    pdol: tuple[PDOLMutation, ...] = ()
    afl: tuple[AFLMutation, ...] = ()
    dol: tuple[DOLMutation, ...] = ()
    response: tuple[ResponseMutation, ...] = ()
    injections: tuple[InjectedCommand, ...] = ()
    pdol_dol: tuple[tuple[str, int], ...] = ()

    @classmethod
    def from_dict(cls, d: dict | None) -> "MutationConfig":
        """Construye la config desde un dict. Acepta también los nombres de
        claves del `mutations.yaml` de atrium (pdol_mutations, afl_mutations,
        dol_mutations, response_mutations, injected_commands)."""
        d = d or {}
        pdol = tuple(PDOLMutation.from_dict(x)
                     for x in d.get("pdol", d.get("pdol_mutations", ())))
        afl = tuple(AFLMutation.from_dict(x)
                    for x in d.get("afl", d.get("afl_mutations", ())))
        dol = tuple(DOLMutation.from_dict(x)
                    for x in d.get("dol", d.get("dol_mutations", ())))
        resp = tuple(ResponseMutation.from_dict(x)
                     for x in d.get("response", d.get("response_mutations", ())))
        inj = tuple(InjectedCommand.from_dict(x)
                    for x in d.get("injections", d.get("injected_commands", ())))
        pdol_dol = tuple((str(t).upper(), int(n)) for t, n in d.get("pdol_dol", ()))
        return cls(enabled=bool(d.get("enabled", True)), pdol=pdol, afl=afl,
                   dol=dol, response=resp, injections=inj, pdol_dol=pdol_dol)

    def to_dict(self) -> dict:
        return {"enabled": self.enabled,
                "pdol": [m.to_dict() for m in self.pdol],
                "afl": [m.to_dict() for m in self.afl],
                "dol": [m.to_dict() for m in self.dol],
                "response": [m.to_dict() for m in self.response],
                "injections": [m.to_dict() for m in self.injections],
                "pdol_dol": [[t, n] for t, n in self.pdol_dol]}


# ---------------------------------------------------------------------------
# Familia 1: mutaciones PDOL (comando GPO)
# ---------------------------------------------------------------------------
def _split_gpo_fields(data: bytes, pdol: DOLLayout) -> dict[str, bytes] | None:
    """Divide el valor del template `83` del GPO en campos según el PDOL.
    Devuelve {tag: bytes} o None si el layout no encaja."""
    parsed = tlv.parse(data)
    t83 = parsed.find("83")
    if t83 is None or not t83.value:
        return None
    fields: dict[str, bytes] = {}
    pos = 0
    for tag, length in pdol:
        end = pos + length
        if end > len(t83.value):
            return None
        fields[tag] = t83.value[pos:end]
        pos = end
    return fields


def _rebuild_gpo_data(data: bytes, fields: dict[str, bytes], pdol: DOLLayout) -> bytes:
    """Reconstruye el campo de datos del GPO: nuevo `83` con los campos en
    orden PDOL (recreando los bytes con `tlv.build_dol`, que rellena/pad a la
    longitud declarada) y el resto de TLVs del comando igual."""
    new_value = tlv.build_dol(list(pdol), fields)
    out = tlv.TLVList()
    for t in tlv.parse(data):
        if t.tag == "83":
            out.append(tlv.tlv("83", new_value))
        else:
            out.append(t)
    return tlv.encode(out)


def apply_command(apdu: APDU, config: MutationConfig,
                  pdol: DOLLayout | None = None) -> tuple[APDU, list[str]]:
    """Aplica la familia PDOL al comando. Solo actúa sobre el GPO (INS A8) y
    si hay layout PDOL (el del argumento o el de la config). Devuelve
    (apdu, notas)."""
    notes: list[str] = []
    if not config.enabled or apdu.ins != INS_GET_PROCESSING_OPTIONS or not config.pdol:
        return apdu, notes
    layout = list(pdol if pdol is not None else config.pdol_dol)
    if not layout:
        return apdu, notes
    fields = _split_gpo_fields(apdu.data, layout)
    if fields is None:
        return apdu, notes
    changed = False
    for m in config.pdol:
        if not m.enabled or m.tag not in fields:
            continue
        declared = next((n for t, n in layout if t == m.tag), len(m.value))
        new_val = m.value[:declared].ljust(declared, b"\x00")
        notes.append(f"cmd PDOL {m.tag} {to_hex(fields[m.tag])}→{to_hex(new_val)}")
        fields[m.tag] = new_val
        changed = True
    if not changed:
        return apdu, notes
    return replace(apdu, data=_rebuild_gpo_data(apdu.data, fields, layout)), notes


# ---------------------------------------------------------------------------
# Familia 2: mutaciones AFL (tag 94 en la respuesta GPO)
# ---------------------------------------------------------------------------
def _apply_afl_spec(entries: list[tuple[int, int, int, int]],
                    spec: AFLMutation) -> list[tuple[int, int, int, int]]:
    """Aplica una regla AFL sobre entradas (sfi, first, last, offline_auth)."""
    if spec.mode == "skip_signed":
        return [(s, f, l, 0) for s, f, l, _ in entries]
    if spec.mode == "truncate":
        return entries[:max(1, spec.truncate_to)]
    if spec.mode == "remove_sfi":
        return [e for e in entries if e[0] != spec.target_sfi]
    if spec.mode == "extend":  # añade entradas extra (fuzz de errores del terminal)
        extra = [(int(e.get("sfi", 1)), int(e.get("first", 1)),
                  int(e.get("last", 1)), int(e.get("offline", 0)))
                 for e in spec.extra_entries]
        return entries + extra
    return entries


def mutate_afl(afl: bytes, specs) -> tuple[bytes, list[str]]:
    """Aplica las reglas AFL habilitadas sobre los bytes crudos del tag 94.
    Devuelve (nuevos_bytes, notas) usando `emv.parse_afl` para el roundtrip."""
    notes: list[str] = []
    entries = parse_afl(afl)
    if not entries:
        return afl, notes
    for spec in specs:
        if not spec.enabled:
            continue
        original = bytes(b for e in entries for b in (e[0] << 3, e[1], e[2], e[3]))
        new_entries = _apply_afl_spec(entries, spec)
        new_bytes = bytes(b for e in new_entries for b in (e[0] << 3, e[1], e[2], e[3]))
        notes.append(f"resp AFL {spec.mode} 94 {to_hex(original)}→{to_hex(new_bytes)}")
        entries = new_entries
    if not notes:
        return afl, notes
    final = bytes(b for e in entries for b in (e[0] << 3, e[1], e[2], e[3]))
    return final, notes


# ---------------------------------------------------------------------------
# Familia 3: mutaciones DOL (8C CDOL1 / 8D CDOL2)
# ---------------------------------------------------------------------------
def _encode_dol(entries: list[tuple[str, int]]) -> bytes:
    """Codifica entradas de DOL como puros pares tag+longitud (sin valores),
    que es la codificación real de un DOL (no TLV)."""
    return b"".join(from_hex(t) + bytes([n]) for t, n in entries)


def mutate_dol(value: bytes, specs) -> tuple[bytes, list[str]]:
    """Aplica reglas DOL sobre el valor crudo de un tag 8C/8D (usa
    `tlv.parse_dol` para el roundtrip). Devuelve (nuevos_bytes, notas)."""
    notes: list[str] = []
    entries = tlv.parse_dol(value)
    if not entries:
        return value, notes
    for spec in specs:
        if not spec.enabled:
            continue
        if spec.mode == "remove_field":
            new_entries = [e for e in entries if e[0] != spec.field_tag]
            desc = f"remove_field {spec.field_tag}"
        else:  # truncate
            new_entries = entries[:max(0, spec.truncate_to)]
            desc = f"truncate {spec.truncate_to}"
        notes.append(f"resp DOL {spec.target_tag} {desc} "
                     f"{to_hex(_encode_dol(entries))}→{to_hex(_encode_dol(new_entries))}")
        entries = new_entries
    if not notes:
        return value, notes
    return _encode_dol(entries), notes


# ---------------------------------------------------------------------------
# Familia 4: mutaciones TLV de respuesta
# ---------------------------------------------------------------------------
def _compute_new_value(spec: ResponseMutation, original: bytes) -> bytes | None:
    """Calcula el nuevo valor según el modo; None = borrar el tag.
    Semántica de atrium: `splice` conserva la longitud (un splice que
    cambiara el tamaño desplazaría todos los bytes posteriores); `xor` aplica
    la máscara sobre `min(len)`; `flip_bit` cuenta 0 = MSB del valor entero."""
    mode = spec.mode
    if mode == "delete":
        return None
    if mode == "replace":
        return bytes(spec.value)
    if mode == "prepend":
        return bytes(spec.value) + original
    if mode == "append":
        return original + bytes(spec.value)
    if mode == "splice":
        patch = bytes(spec.value)
        if not patch:
            return original
        if spec.offset < 0 or spec.offset + len(patch) > len(original):
            raise ValueError(
                f"splice de {len(patch)} byte(s) en offset {spec.offset} excede "
                f"un valor de {len(original)} bytes; usa 'replace' para cambiar "
                f"la longitud o 'append' para extenderlo")
        result = bytearray(original)
        result[spec.offset:spec.offset + len(patch)] = patch
        return bytes(result)
    if mode == "xor":
        mask = bytes(spec.value)
        result = bytearray(original)
        for i in range(min(len(result), len(mask))):
            result[i] ^= mask[i]
        return bytes(result)
    if mode == "flip_bit":
        if not original:
            return original
        result = bytearray(original)
        byte_idx = spec.bit_position // 8
        bit_idx = 7 - (spec.bit_position % 8)  # MSB-first dentro del byte
        if byte_idx < len(result):
            result[byte_idx] ^= 1 << bit_idx
        return bytes(result)
    raise ValueError(f"modo desconocido: {mode!r}")


def _apply_resp_spec(tlvs: tlv.TLVList, spec: ResponseMutation,
                     notes: list[str]) -> tlv.TLVList:
    """Recorrido TLV recursivo (mismo estilo que `intercept.set_tag_in`):
    aplica `spec` a cada nodo con el tag buscado; los borrados se omiten."""
    out = tlv.TLVList()
    for t in tlvs:
        if t.tag == spec.tag:
            original = tlv.encode(t.children) if t.children else bytes(t.value)
            new_value = _compute_new_value(spec, original)
            notes.append(f"resp TLV {spec.mode} {t.tag} "
                         f"{to_hex(original)}→"
                         f"{to_hex(new_value) if new_value is not None else '(borrado)'}")
            if new_value is None:
                continue  # delete: se omite el nodo
            out.append(tlv.tlv(t.tag, new_value))
        elif t.children:
            out.append(tlv.TLV(t.tag, b"", list(_apply_resp_spec(t.children, spec, notes)),
                               constructed=True))
        else:
            out.append(t)
    return out


def apply_response(resp: Response, ins: int | None,
                   config: MutationConfig) -> tuple[Response, list[str]]:
    """Aplica las familias de respuesta (AFL, DOL y TLV) sobre los datos de
    `resp`. `ins` (int o None) filtra las reglas `on_ins` y decora las notas.
    Devuelve (respuesta, notas)."""
    notes: list[str] = []
    if not config.enabled or not resp.data:
        return resp, notes
    ins_hex = f"{ins:02X}" if ins is not None else ""
    parsed = tlv.parse(resp.data)

    # Familia 2: AFL (tag 94 donde aparezca; en la práctica, respuesta GPO).
    afl_specs = [m for m in config.afl if m.enabled]
    if afl_specs:
        def _walk_afl(tlvs: tlv.TLVList) -> tlv.TLVList:
            out = tlv.TLVList()
            for t in tlvs:
                if t.tag == "94" and t.value:
                    new_val, n = mutate_afl(t.value, afl_specs)
                    notes.extend(n)
                    out.append(tlv.tlv("94", new_val))
                elif t.children:
                    out.append(tlv.TLV(t.tag, b"", list(_walk_afl(t.children)),
                                       constructed=True))
                else:
                    out.append(t)
            return out
        parsed = _walk_afl(parsed)

    # Familia 3: DOL (8C/8D en los registros).
    dol_specs = [m for m in config.dol if m.enabled]
    if dol_specs:
        spec_map: dict[str, list[DOLMutation]] = {}
        for m in dol_specs:
            spec_map.setdefault(m.target_tag, []).append(m)

        def _walk_dol(tlvs: tlv.TLVList) -> tlv.TLVList:
            out = tlv.TLVList()
            for t in tlvs:
                if t.tag in spec_map and t.value:
                    new_val, n = mutate_dol(t.value, spec_map[t.tag])
                    notes.extend(n)
                    out.append(tlv.tlv(t.tag, new_val))
                elif t.children:
                    out.append(tlv.TLV(t.tag, b"", list(_walk_dol(t.children)),
                                       constructed=True))
                else:
                    out.append(t)
            return out
        parsed = _walk_dol(parsed)

    # Familia 4: TLV de respuesta (en orden; cada una opera sobre la anterior).
    for spec in config.response:
        if not spec.enabled:
            continue
        if spec.on_ins and (ins is None or ins_hex not in spec.on_ins):
            continue
        parsed = _apply_resp_spec(parsed, spec, notes)

    if not notes:
        return resp, notes
    return Response(tlv.encode(parsed), resp.sw1, resp.sw2), notes


# ---------------------------------------------------------------------------
# Middleware de Transceiver (familias 1–4 en el path + inyecciones 5)
# ---------------------------------------------------------------------------
def _update_pdol_from_response(resp: Response) -> DOLLayout | None:
    """Extrae el PDOL (tag 9F38) de una respuesta SELECT para las mutaciones
    GPO posteriores. Devuelve el layout o None si no hay 9F38."""
    if not resp.data:
        return None
    t = tlv.parse(resp.data).find("9F38")
    if t is None or not t.value:
        return None
    return tlv.parse_dol(t.value)


def _run_injections(send: Transceiver, config: MutationConfig, ins: int,
                    when: str, fired: set[int],
                    notes: list[str]) -> list[tuple[APDU, Response]]:
    """Dispara las inyecciones habilitadas para (ins, when). Las respuestas se
    registran en `notes` y se devuelven para el evento, pero NUNCA se reenvían
    al terminal. Las de `repeat=False` solo disparan una vez por wrapper."""
    exchanges: list[tuple[APDU, Response]] = []
    for idx, inj in enumerate(config.injections):
        if not inj.enabled or inj.when != when:
            continue
        if inj.trigger_ins != f"{ins:02X}":
            continue
        if not inj.repeat and idx in fired:
            continue
        fired.add(idx)
        cmd = to_apdu(inj.apdu)
        resp: Response | None = None
        try:
            resp = send(cmd)
            result = f"SW {resp.sw_hex}" + (f" data {to_hex(resp.data)}" if resp.data else "")
        except Exception as exc:  # la inyección no tumba el intercambio
            result = f"ERROR {exc}"
        notes.append(f"inject {inj.apdu.hex().upper()} ({when} {inj.trigger_ins}) "
                     f"→ {result}")
        exchanges.append((cmd, resp))
    return exchanges


def mutating(send: Transceiver, config: MutationConfig,
             on_event=None) -> Transceiver:
    """Envuelve un `Transceiver` con el motor de mutaciones (mismo contrato
    que `intercept.intercepting`): aplica las familias 1–4 al comando y a la
    respuesta, ejecuta las inyecciones (5) registrando sus respuestas en las
    notas (jamás reenviadas) y emite un `intercept.Exchange` por intercambio.

    Mantiene el estado mínimo de sesión en el closure: el último PDOL visto
    (tag 9F38 de los FCI) para la familia PDOL, y el conjunto de inyecciones
    ya disparadas (las de `repeat=False` solo una vez)."""
    last_pdol: DOLLayout = list(config.pdol_dol)
    fired: set[int] = set()

    def transceiver(command) -> Response:
        cmd_before = to_apdu(command)
        notes: list[str] = []

        # Inyecciones previas al comando (nunca reenvían su respuesta).
        _run_injections(send, config, cmd_before.ins, "before_command", fired, notes)

        cmd_after, cnotes = apply_command(cmd_before, config, pdol=last_pdol)
        notes.extend(cnotes)

        resp_before = send(cmd_after)
        new_pdol = _update_pdol_from_response(resp_before)
        if new_pdol is not None:
            last_pdol[:] = new_pdol

        try:
            resp_after, rnotes = apply_response(resp_before, cmd_after.ins, config)
        except ValueError as exc:
            # una reg mal formada (p.ej. splice fuera de rango) no tumba el
            # intercambio en vivo: se anota y la respuesta pasa sin mutar.
            resp_after, rnotes = resp_before, [f"error de mutación: {exc}"]
        notes.extend(rnotes)

        # Inyecciones tras la respuesta (p.ej. lectura silenciosa de ATC).
        _run_injections(send, config, cmd_after.ins, "after_response", fired, notes)

        if on_event:
            on_event(Exchange(cmd_before, cmd_after, resp_before, resp_after, notes))
        return resp_after

    return transceiver


# ---------------------------------------------------------------------------
# Modo offline: vista previa sobre una captura
# ---------------------------------------------------------------------------
def _fmt_change(label: str, original: bytes, mutated: bytes) -> str:
    return f"{label}: {to_hex(original) or '(vacío)'} → {to_hex(mutated) or '(vacío)'}"


def preview_dump(dump, config: MutationConfig) -> list[str]:
    """Aplica las familias de RESPUESTA (2 AFL, 3 DOL, 4 TLV) sobre los TLVs
    de una captura (`session.model.CardDump`) y devuelve líneas diff legibles
    "original → mutado". Es la base del modo offline de la CLI y de la UI.
    Requiere captura real: no inventa tarjeta ninguna."""
    from ..session.model import tlvs_from_dump  # import perezoso: session -> core

    lines: list[str] = []
    app, _ = tlvs_from_dump(dump)
    if app is None:
        return ["(la captura no tiene aplicaciones: nada que mutar)"]

    # Familia 2: AFL tal cual lo guardó la captura.
    afl_hex = app.get("afl")
    if afl_hex and config.afl:
        _, notes = mutate_afl(from_hex(afl_hex), config.afl)
        for n in notes:
            lines.append(n)

    # Familias 3 y 4 sobre cada fuente de TLVs de la app. Cada fuente conserva
    # el INS real del que provino para que los filtros `on_ins` sean fieles:
    # registros = READ RECORD (B2), get_data = GET DATA (CA), AIP = GPO (A8).
    sources: list[tuple[str, bytes, int | None]] = []
    for rec in app.get("records", []):
        try:
            sources.append((f"registro SFI {rec['sfi']} nº {rec['record']}",
                            from_hex(rec["hex"]), 0xB2))
        except Exception:
            continue
    for tag, hx in (app.get("get_data") or {}).items():
        try:
            sources.append((f"GET DATA {tag}", tlv.encode([tlv.tlv(tag, from_hex(hx))]),
                            0xCA))
        except Exception:
            continue
    if app.get("aip"):
        try:
            sources.append(("AIP", tlv.encode([tlv.tlv("82", from_hex(app["aip"]))]), 0xA8))
        except Exception:
            pass

    for label, data, ins in sources:
        original = data
        mutated, notes = apply_response(Response(data, 0x90, 0x00), ins, config)
        if notes:
            lines.append(f"{label}")
            for n in notes:
                lines.append(f"  {n}")
            lines.append(f"  {_fmt_change('datos', original, mutated.data)}")
    if not lines:
        lines.append("(sin cambios: la config no aplica sobre esta captura)")
    return lines


def planned_injections(config: MutationConfig) -> list[str]:
    """Lista legible de las inyecciones que dispararía la config (modo
    offline/preview: se muestran como «planificadas», sin ejecutar)."""
    out: list[str] = []
    for inj in config.injections:
        if not inj.enabled:
            continue
        when = "antes" if inj.when == "before_command" else "después"
        out.append(f"inyección planificada {when} de INS {inj.trigger_ins}: "
                   f"{inj.apdu.hex().upper()}"
                   + (f" — {inj.comment}" if inj.comment else ""))
    return out
