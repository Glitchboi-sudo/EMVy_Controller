# 06 — Agente LLM y dashboard web

**Prioridad: MEDIA–BAJA (agente, opcional) / NO PORTAR (dashboard).** Dos features
visibles de atrium que en EMVy requieren juicio: una es interesante pero opcional;
la otra ya está resuelta por otra vía.

## En atrium

**Agente LLM** — `llm_provider.py` + `emv_agent.py` (57KB):
- Capa provider-agnostic con tool-calling: `anthropic` (SDK), `openai`, y `local`
  (cualquier servidor OpenAI-compatible — Ollama, LM Studio, vLLM, llama.cpp,
  OpenRouter, Groq — vía HTTP stdlib; consulta `/models` para llenar el dropdown
  de la UI). Detección por env (`ATRIUM_LLM_PROVIDER` → `ANTHROPIC_API_KEY` →
  `OPENAI_API_KEY` → `ATRIUM_LLM_BASE_URL`) y mensaje de error claro si el modelo
  no soporta tool-calling.
- Orquestador interactivo/no-interactivo con **11 tools**:
  `fingerprint_card`, `load_card_intel`, `record_attack_result`, `list_known_cards`,
  `configure_mutations`, `start_relay_session`/`stop_relay_session`, 
  `read_mutation_log`, `query_mutation_outcomes`, `list_session_logs`,
  `read_session_log`.
- System prompt embebido con el catálogo ATTACK-1…11 y COMBOs con condiciones de
  disparo: el agente planea, ejecuta, registra outcome y reconsulta la intel DB.
  Flags: `--task/--task-file/--non-interactive`. Eventos por WebSocket para el
  chat en vivo de la UI.
- Todo es **opcional**: la suite funciona completa sin API key.

**Dashboard web** — `api/` (FastAPI + pydantic, token auth obligatorio si bind ≠
loopback, protección anti DNS-rebinding por `Host` header, routers de sesión/readers/
nfc/fingerprint/mutations/intel/agent/playbooks/logs/config/proxy/outcomes/host) +
`web/` (SPA sin build step: home con pipeline de 6 etapas, Live Trace con diff de
mutaciones, perfil en tiles, editor YAML de mutaciones, chat del agente, intel,
playbooks, logs, ISO 8583). Modelo de seguridad del plano de control fijado por
tests (AST que prohíbe subprocess en el server, path-traversal safe, etc.).

## En EMVy hoy

- No hay agente LLM ni API web. El análogo funcional del agente hoy es el
  **framework de PoCs** (`emvy/poc/`): plugins Python con `PocContext`, evidencia
  automática, IDE integrado en TUI/GUI.
- Las UIs ya son dos: TUI (Textual) y GUI (PySide6), con paridad de pestañas,
  i18n es/en/pt y paletas. Una tercera interfaz es mantenimiento, no capacidad.

## Propuesta para EMVy

**Agente: 🟡 opcional, pero si se hace, así:**
- `emvy agent` (extra `[agent]`, dependencias opcionales), provider-agnostic
  copiando el diseño de `llm_provider.py` (la parte local-via-stdlib es la más
  atractiva: sin SDKs, funciona con Ollama/LM Studio de laboratorio).
- Tools sobre lo que EMVy ya tendría tras los docs 01–03: `fingerprint`,
  `intel load/record/recommend`, `mutations configure`, `poc run`, `log list/read`.
  Es decir: **el agente se construye después y encima** del motor de mutaciones y la
  intel DB, no antes. Sin esas piezas, el agente no tiene nada útil que orquestar.
- Modo no-interactivo (`--task-file`) para integrarlo a corridas de engagement.
- Dejar claro en docs que es opcional y offline-friendly (modelo local).

**Dashboard web: ❌ no portar.** Justificación: EMVy ya invirtió en TUI+GUI con
paridad; atrium invirtió en web porque su UI principal es el navegador. Son apuestas
distintas y EMVy no gana duplicando. **Sí reutilizar ideas sueltas:**
- El **Live Trace** con diff original/mutado de atrium: la consola en vivo de EMVy
  podría marcar visualmente los pares tocados por reglas de Intercept/mutaciones
  (barato dentro de las UIs existentes).
- El **editor YAML de mutaciones** con validación: entraría como panel dentro de
  Fuzzing/Intercept (GUI/TUI ya tienen editores con este patrón).
- El **pipeline visual de 6 etapas** con badges de estado de la home de atrium: la
  pestaña Inicio de EMVy ya es un "centro de operaciones"; análogo conceptual.

**Modelo de seguridad del plano de control** (token, anti-rebinding, tests AST):
aplicable **solo si** algún día se expone API (p.ej. para el agente remoto). Hoy es
solución a un problema que EMVy no tiene; anotarlo como referencia.

**Esfuerzo estimado:** agente ≈ 800–1000 líneas sobre llm_provider + tools; la mitad
son tests y prompts. No empezar antes de tener docs 01–02.

**Por qué (no):** el agente es un multiplicador, no una base — sin mutaciones/intel
que orquestar es chat vacío. Y el dashboard resuelve un problema (UI única
compartida) que en EMVy ya está resuelto dos veces.
