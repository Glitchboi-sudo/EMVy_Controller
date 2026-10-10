# 02 — Fingerprinting normalizado e inteligencia cross-session

**Prioridad: ALTA.** Hoy EMVy analiza tarjetas pero no "recuerda" nada entre
sesiones; en un engagement real (varias tarjetas de laboratorio, varios días) la
pregunta "¿a esta tarjeta ya le probé el COMBO-C y qué pasó?" no tiene respuesta.

## En atrium

Dos piezas complementarias:

**`tmp/atrium/card_fingerprint.py` (54KB)** — `CardFingerprinter`:
- Enumeración de AIDs vía PSE/PPSE (fallback a lista de 12 AIDs).
- Mapa completo del AFL y **brute-force off-AFL de SFI 1–10** (`--brute-sfi`).
- Decode de PDOL/CDOL, flags AIP (SDA/DDA/CDA/CVM…), CVM list completa (método +
  condición + continue-if-fail), capacidades cripto (tamaños de clave RSA del
  certificado, CA key index, `9F08`, `9F6E`).
- ATC + PIN retry vía GET DATA, service code desde Track 2, inventario plano de
  tags.
- **Hash SHA-256 del perfil normalizado = identidad estable** de la tarjeta
  (reconocerla entre sesiones aunque cambien datos volátiles como ATC).
- Salida JSON (`--output`) + resumen a color. API Python y CLI.

**`tmp/atrium/card_intel.py` (29KB)** — SQLite WAL en `logs/card_intel.db`:
- Tabla `cards`: perfil por hash, first/last seen, times_seen, AIDs, AIP,
  PDOL/CDOL, CVM rules, pin_retry, ATC first/last, notas.
- Tabla `attacks`: historial de ataques con snapshot de config, resultado
  (`success|partial|failed|blocked|error`) y mutaciones disparadas.
- **`_recommend()`**: recomendador top-5 (ataques parciales → no probados que casan
  con el perfil → prerrequisitos de combos → orden canónico). Es el feedback del
  pipeline de ataque: marca resultados y la siguiente corrida te dice qué intentar.
- `get_cross_card_patterns()`: patrones de SW por tarjeta **y cross-card**
  (¿todas las del mismo emisor mueren igual ante el ATTACK-7?).
- CLI: `list / intel <prefix> / note`; la API web permite marcar filas del Live
  Trace como interesantes (feedback ⑥→⑤).

El catálogo `KNOWN_ATTACKS` (ATTACK-1…11) documenta cada técnica con condiciones de
disparo — la misma lista que usa el agente LLM.

## En EMVy hoy

- `emvy dump` / `emvy analyze` ya extraen casi todo lo que compone el perfil
  (AIP/AUC, CVM list con notas de riesgo, ODA con verificación RSA del certificado,
  hallazgos combinados) — pero el resultado es un informe **para humanos**, por
  sesión, sin identidad estable.
- Los proyectos persisten capturas (`<proyecto>/captures/*.json`), variables,
  keysets, logs… pero **no hay base de conocimiento de tarjetas ni de resultados**.
- El framework de PoCs guarda evidencia por corrida, sin cruzar por tarjeta.

## Propuesta para EMVy

1. **`emvy fingerprint [-o perfil.json]`** (CLI + API en `emvy/core/fingerprint.py`):
   perfil normalizado construido sobre lo que `dump`/`analyze` ya producen + hash
   SHA-256 estable. Es principalmente "empaquetar" lo existente, no re-hacerlo.
2. **`emvy intel …`** con store SQLite **dentro del proyecto activo**
   (`<proyecto>/intel.db`, coherente con el modelo projects/engagements de EMVy —
   a diferencia de atrium, donde la DB es global):
   - `emvy intel list` — tarjetas vistas en el proyecto (hash, veces, última vez).
   - `emvy intel show <hash>` — perfil + historial de outcomes.
   - `emvy intel note <hash> "texto"`.
   - `emvy intel record <hash> --attack combo-c --result partial --notes "..."` —
     o automático desde PoC runs (`ctx.finding()` ya existe: unificar criterios).
   - `emvy intel recommend <hash>` — recomendador top-N (ATTACK-1…11/COMBOs del
     [doc 01](01-motor-mutaciones-y-playbooks.md) vs perfil y outcomes).
3. UI: tarjeta "identidad" en el Explorador (hash + veces vista), panel Intel en
   GUI/TUI (lista, historial, recomendaciones).
4. Sinergia con el **generador de reportes** (pendiente en `TODO.md`): la tabla de
   outcomes por tarjeta es contenido natural del informe de engagement.

**Esfuerzo estimado:** fingerprint ≈ 200–300 líneas sobre lo existente; intel DB +
recomendador ≈ el tamaño de `store.py`. Todo puro + SQLite, cero dependencias nuevas.

**Por qué sí:** convierte sesiones sueltas en conocimiento acumulado del engagement,
da criterio de cobertura ("¿qué no he probado?") y habilita el reporte final. Es la
feature que más diferencia un "kit de comandos" de una "suite de pentest".
