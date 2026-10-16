"""Unit tests for manuscripta.config.loader: load_yaml and the two settings
loaders with their default files, which are resolved against the current
working directory (the book repository root)."""

from __future__ import annotations

import locale
from contextlib import contextmanager
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

from manuscripta.config.loader import (
    CONFIG_DIR,
    EXPORT_SETTINGS_FILE,
    VOICE_SETTINGS_FILE,
    load_export_settings,
    load_voice_settings,
    load_yaml,
)


@contextmanager
def c_locale(monkeypatch):
    """LC_ALL=C for the block: the locale codec is ASCII and can carry no
    non-ASCII text, so a read that relies on it fails."""
    saved = locale.setlocale(locale.LC_ALL)
    monkeypatch.setenv("LC_ALL", "C")
    monkeypatch.setenv("LANG", "C")
    locale.setlocale(locale.LC_ALL, "C")
    try:
        yield
    finally:
        locale.setlocale(locale.LC_ALL, saved)


# ---------------------------------------------------------------------------
# load_yaml
# ---------------------------------------------------------------------------
# Each row: the text of a YAML file and the dict load_yaml returns for it
YAML_DOCUMENTS = [
    pytest.param(
        "formats:\n  pdf: pdf\ntoc_depth: 3\n",
        {"formats": {"pdf": "pdf"}, "toc_depth": 3},
        id="nested-mapping",
    ),
    pytest.param("voices: [de, en]\n", {"voices": ["de", "en"]}, id="flow-sequence"),
    pytest.param("---\nlang: de\n", {"lang": "de"}, id="document-marker"),
    pytest.param("title: Λόγος und Élan\n", {"title": "Λόγος und Élan"}, id="utf-8"),
    pytest.param("", {}, id="empty-file-is-an-empty-dict"),
    pytest.param("# only a comment\n", {}, id="comment-only-file-is-an-empty-dict"),
]


@pytest.mark.parametrize("text, loaded", YAML_DOCUMENTS)
def test_load_yaml(text, loaded, tmp_path):
    path = tmp_path / "settings.yaml"
    path.write_text(text, encoding="utf-8")
    assert load_yaml(path) == loaded


# Each row: the text of a YAML file whose top-level node is no mapping, the
# type name load_yaml's ValueError reports
NON_MAPPING_DOCUMENTS = [
    pytest.param("- a\n- b\n", "list", id="sequence"),
    pytest.param("[]\n", "list", id="empty-sequence"),
    pytest.param("just text\n", "str", id="scalar-string"),
    pytest.param("42\n", "int", id="scalar-number"),
]


@pytest.mark.parametrize("text, kind", NON_MAPPING_DOCUMENTS)
def test_load_yaml_rejects_a_non_mapping_document(text, kind, tmp_path):
    path = tmp_path / "settings.yaml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError) as exc:
        load_yaml(path)
    assert str(exc.value) == (
        f"{path}: the top-level YAML node must be a mapping, not {kind}"
    )


def test_load_yaml_is_safe_and_rejects_python_tags(tmp_path):
    path = tmp_path / "settings.yaml"
    path.write_text("cmd: !!python/object/apply:os.system ['true']\n", encoding="utf-8")
    with pytest.raises(yaml.constructor.ConstructorError):
        load_yaml(path)


def test_load_yaml_requires_the_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_yaml(tmp_path / "missing.yaml")


def test_load_yaml_reads_utf8_under_c_locale(tmp_path, monkeypatch):
    """The file is read as UTF-8 whatever the locale: under LC_ALL=C the
    locale codec is ASCII and cannot carry the umlauts."""
    path = tmp_path / "settings.yaml"
    path.write_bytes("title: Grüße\n".encode("utf-8"))
    with c_locale(monkeypatch):
        assert load_yaml(path) == {"title": "Grüße"}


# ---------------------------------------------------------------------------
# load_export_settings / load_voice_settings
# ---------------------------------------------------------------------------
# Each row: a settings loader, the module constant naming its default file,
# the name of that file below config/
LOADERS = [
    pytest.param(
        load_export_settings, EXPORT_SETTINGS_FILE, "export-settings.yaml", id="export"
    ),
    pytest.param(
        load_voice_settings, VOICE_SETTINGS_FILE, "voice-settings.yaml", id="voice"
    ),
]


@pytest.mark.parametrize("loader, default, name", LOADERS)
def test_default_file_is_relative_to_config_dir(loader, default, name):
    assert CONFIG_DIR == Path("config")
    assert default == CONFIG_DIR / name
    assert not default.is_absolute()


@pytest.mark.parametrize("loader, default, name", LOADERS)
def test_loader_reads_the_given_path(loader, default, name, tmp_path):
    path = tmp_path / "custom.yaml"
    path.write_text("engine: piper\nrate: 1.5\n", encoding="utf-8")
    assert loader(path) == {"engine": "piper", "rate": 1.5}


@pytest.mark.parametrize("loader, default, name", LOADERS)
def test_loader_returns_an_empty_dict_for_a_missing_path(
    loader, default, name, tmp_path
):
    assert loader(tmp_path / "missing.yaml") == {}


@pytest.mark.parametrize("loader, default, name", LOADERS)
def test_loader_reads_its_default_file_below_cwd(
    loader, default, name, tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / name).write_text("lang: de\n", encoding="utf-8")
    assert loader() == {"lang": "de"}


@pytest.mark.parametrize("loader, default, name", LOADERS)
def test_loader_returns_an_empty_dict_without_its_default_file(
    loader, default, name, tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    assert loader() == {}
