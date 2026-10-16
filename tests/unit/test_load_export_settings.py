# tests/test_load_export_settings.py
"""Tests for load_export_settings() and get_section_order_from_settings()."""
import json
import pytest

pytestmark = pytest.mark.unit

from manuscripta.export.book import (
    load_export_settings,
    get_section_order_from_settings,
)


@pytest.fixture()
def settings_file(tmp_path):
    """Create a temporary export-settings.json and return its path."""
    data = {
        "formats": {
            "markdown": "gfm",
            "pdf": "pdf",
            "epub": "epub",
        },
        "toc_depth": 3,
        "epub_skip_toc_files": ["front-matter/toc.md"],
        "section_order": {
            "default": ["chapters", "back-matter/epilogue.md"],
            "ebook": None,
            "paperback": ["front-matter/toc-print.md", "chapters"],
            "hardcover": None,
            "audiobook": ["front-matter/preface.md", "chapters"],
        },
    }
    path = tmp_path / "export-settings.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


# --- load_export_settings ---------------------------------------------------

# Each row: a key of the settings file above, the value loaded for it
LOADED_SETTINGS = [
    pytest.param("toc_depth", 3, id="reads-json"),
    pytest.param(
        "formats",
        {"markdown": "gfm", "pdf": "pdf", "epub": "epub"},
        id="returns-formats",
    ),
    pytest.param(
        "epub_skip_toc_files", ["front-matter/toc.md"], id="returns-epub-skip"
    ),
]


@pytest.mark.parametrize("key, expected", LOADED_SETTINGS)
def test_load_export_settings_reads_json(settings_file, key, expected):
    result = load_export_settings(settings_file)
    assert result[key] == expected


def test_load_export_settings_missing_file_returns_empty(tmp_path):
    result = load_export_settings(tmp_path / "nonexistent.json")
    assert result == {}


# --- get_section_order_from_settings -----------------------------------------

# Each row: the book type, the order the settings file above yields for it
# (None: no order, the caller uses its built-in one)
SECTION_ORDER_CASES = [
    pytest.param("default", ["chapters", "back-matter/epilogue.md"], id="default"),
    # ebook is null in the test fixture -> should fall back to 'default' key.
    pytest.param(
        "ebook",
        ["chapters", "back-matter/epilogue.md"],
        id="ebook-falls-back-to-default",
    ),
    pytest.param(
        "paperback", ["front-matter/toc-print.md", "chapters"], id="paperback-explicit"
    ),
    # hardcover is null -> should fall back to 'paperback' key.
    pytest.param(
        "hardcover",
        ["front-matter/toc-print.md", "chapters"],
        id="hardcover-falls-back-to-paperback",
    ),
    pytest.param(
        "audiobook", ["front-matter/preface.md", "chapters"], id="audiobook-explicit"
    ),
    # An unknown book type with no key should return None (caller uses built-in).
    pytest.param("comic", None, id="unknown-type-returns-none"),
]


@pytest.mark.parametrize("book_type, expected", SECTION_ORDER_CASES)
def test_get_section_order(settings_file, book_type, expected):
    settings = load_export_settings(settings_file)
    order = get_section_order_from_settings(settings, book_type)
    if expected is None:
        assert order is None
    else:
        assert order == expected


# Each row: settings without a section_order, the book type asked for
NO_SECTION_ORDER_CASES = [
    # Empty settings dict should return None.
    pytest.param({}, "ebook", id="empty-settings-returns-none"),
    # Settings with other keys but no section_order should return None.
    pytest.param(
        {"formats": {"pdf": "pdf"}, "toc_depth": 2}, "ebook", id="no-section-order-key"
    ),
]


@pytest.mark.parametrize("settings, book_type", NO_SECTION_ORDER_CASES)
def test_get_section_order_without_section_order(settings, book_type):
    order = get_section_order_from_settings(settings, book_type)
    assert order is None
