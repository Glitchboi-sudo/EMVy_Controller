"""i18n mínimo y sin dependencias: `t(key)` sobre catálogos por idioma.

Idiomas: `es` (por defecto, el original), `en`, `pt`. El despliegue es
**incremental**: las superficies migradas usan `t("clave")`; lo que aún no está
migrado queda en español. Si falta una clave en el idioma activo, cae al español
y, en último término, a la propia clave (nunca rompe la UI).

Uso:
    from emvy import i18n
    i18n.set_language("en")
    i18n.t("nav.readers")            -> "Readers"
    i18n.t("common.saved", name=x)   -> "Guardado {name}" formateado
"""
from __future__ import annotations

LANGUAGES = [("es", "Español"), ("en", "English"), ("pt", "Português")]

_LANG = "es"

# Catálogo: clave -> {idioma: texto}. El español es la fuente (siempre presente).
_CATALOG: dict[str, dict[str, str]] = {
    # -- navegación / pestañas principales --------------------------------
    "nav.home":       {"es": "Inicio",       "en": "Home",        "pt": "Início"},
    "nav.projects":   {"es": "Proyectos",    "en": "Projects",    "pt": "Projetos"},
    "nav.variables":  {"es": "Variables",    "en": "Variables",   "pt": "Variáveis"},
    "nav.readers":    {"es": "Lectores",     "en": "Readers",     "pt": "Leitores"},
    "nav.explorer":   {"es": "Explorador",   "en": "Explorer",    "pt": "Explorador"},
    "nav.tools":      {"es": "Herramientas", "en": "Tools",       "pt": "Ferramentas"},
    "nav.charges":    {"es": "Cobros",       "en": "Charges",     "pt": "Cobranças"},
    "nav.poc":        {"es": "PoC",          "en": "PoC",         "pt": "PoC"},
    "nav.intercept":  {"es": "Intercept",    "en": "Intercept",   "pt": "Intercept"},
    "nav.firmware":   {"es": "BomberCat",    "en": "BomberCat",   "pt": "BomberCat"},
    "nav.fuzzing":    {"es": "Fuzzing",      "en": "Fuzzing",     "pt": "Fuzzing"},
    "nav.settings":   {"es": "Ajustes",      "en": "Settings",    "pt": "Ajustes"},
    # -- grupos de la barra lateral (GUI) ---------------------------------
    "group.session":  {"es": "SESIÓN",     "en": "SESSION",    "pt": "SESSÃO"},
    "group.card":     {"es": "TARJETA",    "en": "CARD",       "pt": "CARTÃO"},
    "group.ops":      {"es": "OPERACIONES","en": "OPERATIONS", "pt": "OPERAÇÕES"},
    "group.hardware": {"es": "HARDWARE",   "en": "HARDWARE",   "pt": "HARDWARE"},
    "group.settings": {"es": "AJUSTES",    "en": "SETTINGS",   "pt": "AJUSTES"},
    # -- botones / acciones comunes ---------------------------------------
    "common.save":     {"es": "Guardar",   "en": "Save",     "pt": "Salvar"},
    "common.cancel":   {"es": "Cancelar",  "en": "Cancel",   "pt": "Cancelar"},
    "common.apply":    {"es": "Aplicar",   "en": "Apply",    "pt": "Aplicar"},
    "common.refresh":  {"es": "Refrescar", "en": "Refresh",  "pt": "Atualizar"},
    "common.browse":   {"es": "Examinar…", "en": "Browse…",  "pt": "Procurar…"},
    "common.reset":    {"es": "Restablecer","en": "Reset",   "pt": "Restaurar"},
    # -- pantalla de Ajustes ----------------------------------------------
    "settings.title":       {"es": "Ajustes", "en": "Settings", "pt": "Ajustes"},
    "settings.subtitle":    {"es": "Preferencias globales del programa (tema, idioma y datos).",
                             "en": "Global program preferences (theme, language and data).",
                             "pt": "Preferências globais do programa (tema, idioma e dados)."},
    "settings.theme":       {"es": "Tema de color", "en": "Color theme", "pt": "Tema de cor"},
    "settings.language":    {"es": "Idioma", "en": "Language", "pt": "Idioma"},
    "settings.data_dir":    {"es": "Carpeta de datos", "en": "Data folder", "pt": "Pasta de dados"},
    "settings.data_hint":   {"es": "Dónde se guardan proyectos, capturas y variables. "
                                   "Vacío = ubicación por defecto. Solo redirige los datos "
                                   "nuevos (los existentes no se mueven).",
                             "en": "Where projects, captures and variables are stored. "
                                   "Empty = default location. Only redirects new data "
                                   "(existing data is not moved).",
                             "pt": "Onde projetos, capturas e variáveis são salvos. "
                                   "Vazio = local padrão. Só redireciona dados novos "
                                   "(os existentes não são movidos)."},
    "settings.saved":       {"es": "Ajustes guardados.", "en": "Settings saved.", "pt": "Ajustes salvos."},
    "settings.lang_restart":{"es": "El idioma se aplicará por completo al reiniciar.",
                             "en": "Language fully applies after a restart.",
                             "pt": "O idioma será aplicado por completo ao reiniciar."},
    "settings.current_data":{"es": "Actual: {path}", "en": "Current: {path}", "pt": "Atual: {path}"},
}


_LANG_CODES = {code for code, _ in LANGUAGES}


def set_language(lang: str) -> None:
    global _LANG
    _LANG = lang if lang in _LANG_CODES else "es"


def language() -> str:
    return _LANG


def t(key: str, **kwargs) -> str:
    """Traduce `key` al idioma activo (fallback: es → en → la propia clave)."""
    entry = _CATALOG.get(key)
    if entry is None:
        return key
    text = entry.get(_LANG) or entry.get("es") or entry.get("en") or key
    return text.format(**kwargs) if kwargs else text
