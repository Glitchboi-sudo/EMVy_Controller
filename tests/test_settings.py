"""Ajustes globales: palettes, i18n, settings (persistencia) y el override del
directorio de datos en config."""
import pytest


@pytest.fixture
def xdg(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.delenv("EMVY_DATA_HOME", raising=False)
    from emvy import config
    config.set_data_home(None)                  # limpia override entre tests
    return tmp_path


# --- palettes --------------------------------------------------------------
def test_all_palettes_have_all_tokens():
    from emvy import palettes
    assert palettes.DEFAULT in palettes.PALETTES
    for name, pal in palettes.PALETTES.items():
        assert palettes.is_valid(pal), name
        assert pal["accent"].startswith("#") and "label" in pal


def test_palette_get_falls_back_to_default():
    from emvy import palettes
    # get() devuelve una copia derivada (con tokens derivados), no la definición
    # cruda; un nombre inexistente cae a la de por defecto (misma por valor).
    assert palettes.get("no-existe") == palettes.get(palettes.DEFAULT)
    assert [n for n, _ in palettes.names()][0] == palettes.DEFAULT


def test_palette_get_fills_derived_tokens():
    from emvy import palettes
    for name, _ in palettes.names():
        pal = palettes.get(name)
        for tok in palettes._DERIVED:
            assert tok in pal, (name, tok)


# --- i18n ------------------------------------------------------------------
def test_i18n_translates_and_falls_back():
    from emvy import i18n
    i18n.set_language("en")
    assert i18n.t("nav.readers") == "Readers"
    i18n.set_language("pt")
    assert i18n.t("nav.readers") == "Leitores"
    i18n.set_language("zz")                      # inválido → es
    assert i18n.language() == "es"
    assert i18n.t("nav.readers") == "Lectores"
    assert i18n.t("clave.inexistente") == "clave.inexistente"   # fallback a la clave
    i18n.set_language("es")


def test_i18n_format_kwargs():
    from emvy import i18n
    i18n.set_language("en")
    assert i18n.t("settings.current_data", path="/x") == "Current: /x"
    i18n.set_language("es")


# --- settings + override de datos ------------------------------------------
def test_settings_roundtrip_and_normalize(xdg):
    from emvy import settings
    s = settings.Settings(theme="dracula", language="pt", data_dir="/tmp/x")
    settings.save(s)
    loaded = settings.load()
    assert (loaded.theme, loaded.language, loaded.data_dir) == ("dracula", "pt", "/tmp/x")
    # valores inválidos → normalizados a por defecto
    bad = settings.Settings(theme="nope", language="xx").normalized()
    assert bad.theme == "emvy" and bad.language == "es"


def test_settings_load_default_when_missing(xdg):
    from emvy import settings
    assert settings.load() == settings.Settings()   # sin fichero → por defecto


def test_apply_redirects_data_home(xdg, tmp_path):
    from emvy import config, i18n, settings
    custom = tmp_path / "mydata"
    settings.apply(settings.Settings(data_dir=str(custom), language="en"))
    assert config.data_home() == custom
    assert config.projects_dir() == custom / "projects"
    assert i18n.language() == "en"
    settings.apply(settings.Settings())             # limpia → vuelve a XDG
    assert config.data_home() == tmp_path / "data" / "emvy"
    i18n.set_language("es")


def test_env_data_home_override(xdg, tmp_path, monkeypatch):
    from emvy import config
    monkeypatch.setenv("EMVY_DATA_HOME", str(tmp_path / "envdata"))
    assert config.data_home() == tmp_path / "envdata"     # env por encima de XDG
