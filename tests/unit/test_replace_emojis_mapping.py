"""Unit tests for the mapping side of manuscripta.markdown.emojis: the bundled
EMOJI_MAP as the default, loading EMOJI_MAP from a --map module and
validate_mapping."""

from __future__ import annotations

import sys

import pytest

pytestmark = pytest.mark.unit

import manuscripta.markdown.emojis as repl
from manuscripta.data.emoji_map import EMOJI_MAP

MAP_MODULE = "manuscripta.data.emoji_map"


# ---------------------------------------------------------------------------
# the default mapping
# ---------------------------------------------------------------------------


def test_without_a_module_the_bundled_map_is_loaded_as_a_copy():
    mapping = repl.load_mapping_from_module(None)
    assert mapping == EMOJI_MAP
    assert mapping is not EMOJI_MAP
    mapping["🧪"] = "test tube"
    assert "🧪" not in EMOJI_MAP


def test_default_map_is_empty_when_the_bundled_module_cannot_be_imported(monkeypatch):
    monkeypatch.setitem(sys.modules, MAP_MODULE, None)
    assert repl._load_default_map() == {}


def test_without_any_mapping_loading_fails(monkeypatch):
    monkeypatch.setitem(sys.modules, MAP_MODULE, None)
    with pytest.raises(RuntimeError, match="No emoji mapping available"):
        repl.load_mapping_from_module(None)


# ---------------------------------------------------------------------------
# load_mapping_from_module
# ---------------------------------------------------------------------------
# Each row: the text of the --map module and the mapping loaded from it
MAP_MODULES = [
    pytest.param("EMOJI_MAP = {'🔥': '+++'}", {"🔥": "+++"}, id="dict-literal"),
    pytest.param(
        "EMOJI_MAP = dict([('📈', 'up')])\nHELPER = 1",
        {"📈": "up"},
        id="other-names-are-ignored",
    ),
    pytest.param(
        "class M(dict):\n    pass\nEMOJI_MAP = M({'🔥': '+'})",
        {"🔥": "+"},
        id="dict-subclass-is-copied-to-a-plain-dict",
    ),
]


@pytest.mark.parametrize("text, mapping", MAP_MODULES)
def test_load_mapping_from_module(text, mapping, tmp_path):
    module = tmp_path / "map.py"
    module.write_text(text, encoding="utf-8")
    loaded = repl.load_mapping_from_module(module)
    assert loaded == mapping
    assert type(loaded) is dict


# Each row: the name and text of the --map module (None: the file is missing),
# the exception raised, the text its message carries
MAP_MODULE_REJECTS = [
    pytest.param(
        "map.txt",
        "EMOJI_MAP = {}",
        RuntimeError,
        "Cannot import map module from",
        id="unknown-suffix-has-no-loader",
    ),
    pytest.param(
        "map.py",
        "OTHER = {}",
        RuntimeError,
        "does not define EMOJI_MAP",
        id="module-without-emoji-map",
    ),
    pytest.param(
        "map.py",
        "EMOJI_MAP = [('🔥', '+')]",
        RuntimeError,
        "EMOJI_MAP must be a dict[str, str]",
        id="emoji-map-not-a-dict",
    ),
    pytest.param("map.py", None, FileNotFoundError, "map.py", id="missing-module-file"),
]


@pytest.mark.parametrize("name, text, error, message", MAP_MODULE_REJECTS)
def test_load_mapping_from_module_rejects(name, text, error, message, tmp_path):
    module = tmp_path / name
    if text is not None:
        module.write_text(text, encoding="utf-8")
    with pytest.raises(error) as exc:
        repl.load_mapping_from_module(module)
    assert message in str(exc.value)


# ---------------------------------------------------------------------------
# validate_mapping
# ---------------------------------------------------------------------------
# Each row: a mapping, whether it is valid, the message
MAPPING_VERDICTS = [
    pytest.param({"🔥": "+"}, True, "", id="plain-pair"),
    pytest.param({"🔥": ""}, True, "", id="empty-replacement-deletes-the-emoji"),
    pytest.param({}, False, "Mapping is empty.", id="empty-mapping"),
    pytest.param({"🔥": 1}, False, "All keys/values must be strings.", id="int-value"),
    pytest.param({1: "x"}, False, "All keys/values must be strings.", id="int-key"),
    pytest.param({"": "x"}, False, "Empty string emoji key detected.", id="empty-key"),
]


@pytest.mark.parametrize("mapping, ok, message", MAPPING_VERDICTS)
def test_validate_mapping(mapping, ok, message):
    assert repl.validate_mapping(mapping) == (ok, message)
