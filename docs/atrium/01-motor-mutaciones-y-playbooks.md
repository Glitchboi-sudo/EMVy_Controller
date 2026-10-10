# 01 — Motor de mutaciones en vuelo y playbooks COMBO

**Prioridad: ALTA.** Es la feature más singular de atrium y la que mejor encaja en
EMVy: el propio `TODO.md` pide ampliar `core/cardfuzz` con "variantes de TTQ, PDOL
con longitudes inválidas, respuestas GPO fuera de rango" — que es exactamente lo que
este motor ya hace, pero además sobre el flujo en vivo.

## En atrium

Vive en `tmp/atrium/mutation_engine.py` (70KB) + `tmp/atrium/mutations.yaml`, dentro
del path de relay (terminal ⇄ motor ⇄ tarjeta). Cinco familias ortogonales de reglas
YAML, cada una con `enabled`/`comment` (razón de existir) y log JSONL
(`logs/mutations.jsonl` con original/mutado):

1. **PDOL mutations** — reescriben campos del GPO (`80 A8`) antes de llegar a la
   tarjeta: importe `9F02` (1 céntimo → umbral No-CVM), divisa `5F2A`, país `9F1A`,
   TTQ `9F66` (online-only, sin offline PIN).
2. **AFL mutations** (tag `94` en la respuesta GPO): `skip_signed` (vacia los
   registros firmados → derrota SDA/DDA), `truncate`, `remove_sfi`, `extend`.
3. **DOL mutations** (`8C` CDOL1 / `8D` CDOL2): `remove_field` (quitar `9F02`/`9F34`
   → criptograma sin binding de importe/CVM — el vector más interesante), `truncate`.
4. **Response TLV mutations**: modos `replace | delete | splice | xor | flip_bit |
   prepend | append`, limitables por `on_ins`.
5. **Injected commands**: APDUs extra hacia la tarjeta en `before_command`/
   `after_response` (GET DATA silenciosos de ATC `9F36`, PIN retry `9F17`, Log Format
   `9F4F`); las respuestas se loguean pero jamás se reenvían al terminal.

Detalles de ingeniería que vale la pena copiar: recarga en caliente (`reload()`),
runner standalone por stdin (probar mutaciones sin hardware), y en contactless una
mutación que alargue la respuesta >253 bytes se omite y se cuenta (no tumba el
enlace).

Los **playbooks COMBO** (`tmp/atrium/playbooks/COMBO-A…E.yaml`) son combinaciones
curadas, aplicables desde CLI y desde la web sin perder la config propia:

- **COMBO-A CVM-Bypass**: 1¢ + EUR + TTQ online-only + CVM list No-CVM + lecturas
  silenciosas ATC/PIN.
- **COMBO-B Offline-Auth-Defeat**: AFL `skip_signed` + AIP XOR 2100 (downgrade
  CDA/DDA→SDA).
- **COMBO-C PDOL/CDOL desync** (vector "novedoso" según su paper): PDOL 1¢ + quitar
  `9F02` de CDOL1 + IAC-Denial a cero.
- **COMBO-D**: AFL truncate a 1 entrada + borrar CDOL2.
- **COMBO-E**: ATC freeze + Last Online ATC + inyecciones silenciosas (replay/pre-play).

## En EMVy hoy

- `emvy/core/cardfuzz.py` muta **plantillas de terminal** (track magnético, registro
  EMV escrito en tarjeta reescribible, NDEF emulado) para probar terminales/POS.
  Es mutación estática de campo, no sobre un flujo vivo.
- `emvy/core/intercept.py` es el "Burp para EMV": DSL de reglas tag/valor + status
  words sobre un `Transceiver`, ya integrado en la pestaña **Intercept** — pero hoy
  solo aplica en sesiones propias, no sobre relay (el relay está diferido por
  hardware).
- Falta: mutación de la **tarjeta** (respuestas del lado tarjeta) para variar el
  comportamiento de la tarjeta que ve el terminal.

## Propuesta para EMVy

Nuevo módulo **puro** `emvy/core/mutations.py` (sin I/O, siguiendo la arquitectura
de EMVy), con las cinco familias como funciones sobre pares (comando, respuesta) y
config YAML compatible en espíritu con `mutations.yaml`. Tres aplicadores concretos,
del más barato al más caro:

1. **`emv-emulate --mutations <yaml|combo>`** — el aplicador inmediato y de mayor
   valor: hoy `bombercat emv-emulate` responde un flujo qVSDC fijo (perfilado de
   terminales). Alimentar el emulador con las familias 2–4 (AFL, CDOL, TLV de
   respuesta) convierte a EMVy en un **fuzzar de terminales mucho más profundo**:
   variar CVM list, AIP, AFL, CDOL1/2 y ver cómo reacciona el POS (¿pide PIN?
   ¿cae a SDA? ¿acepta el criptograma?). No requiere hardware nuevo — el BomberCat
   ya emula.
2. **Modo offline `emvy mutations run <combo> < captura.json`** — rejugar una
   captura de sesión por el motor (las capturas de `<proyecto>/captures/` ya son
   JSON) y ver el diff sin hardware. Base de tests: como `cardfuzz` hoy, cada
   mutación se valida contra los decodificadores propios.
3. **En el futuro relay** (cuando haya segundo extremo NFCGate, ver
   [doc 05](05-relay-mitm-y-hardware.md)) el mismo motor corre en el path —
   exactamente el diseño de atrium — y se le acoplan las reglas existentes de
   `core/intercept`.

CLI propuesta: `emvy mutations list|show <id>|run <combo> [--file captura]`,
playbooks COMPO en `emvy/data/playbooks/*.yaml` (traducidos, con el catálogo de
ataques ATTACK-1…11 de `card_intel.KNOWN_ATTACKS` como documentación de cada uno),
y editor/selector en la pestaña Fuzzing de GUI/TUI.

**Esfuerzo estimado:** motor + familia TLV + tests ≈ el tamaño de `cardfuzz.py`;
familias DOL/AFL ≈ 300–400 líneas más con el decoder TLV ya existente. Las
COMBOs son YAML puro.

**Por qué sí:** cierra exactamente el hueco que `TODO.md` reconoce ("ampliar
cardfuzz"), multiplica el valor del `emv-emulate` existente sin hardware extra, y
deja el motor listo para el relay. **Cuidado:** las mutaciones PDOL/ATC presuponen
un relay; en el emulador aplican las familias de respuesta (2–4) y las inyecciones
(5) se reducen a lecturas locales.
