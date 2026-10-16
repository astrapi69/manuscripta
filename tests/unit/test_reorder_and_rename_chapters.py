# tests/test_reorder_and_rename_chapters.py
import json
import csv
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

# Importiere direkt aus deinem Script
from manuscripta.project.reorder import (
    load_mapping_file,
    parse_inline_map,
    update_header_and_anchor,
    _resolve_mapping,
    _two_phase_rename,
    autodetect_lang_by_header,
)

# ----------------------------
# Helpers
# ----------------------------


def write_chapter(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


ES_H1 = (
    "# ✦ Capítulo 11: Creatividad – La moneda renovable {#-chapter-11}\n\nContenido…\n"
)
DE_H1 = "# ✦ Kapitel 9: Mentale Klarheit – Der Kompass des Geistes {#-chapter-9}\n\nInhalt…\n"
EN_H1 = "# ✦ Chapter 7: Presence – The Lost Art of Being Rich Now {#-chapter-7}\n\nContent…\n"

# Header ohne Anchor (soll Fallback greifen)
ES_H1_NO_ANCHOR = "# ✦ Capítulo 16: Ideas – Semillas de riqueza mental\n\nContenido…\n"


# ----------------------------
# Mapping Loader Tests
# ----------------------------


def json_file(data):
    """A writer storing ``data`` as JSON."""
    return lambda path: path.write_text(json.dumps(data), encoding="utf-8")


def csv_file(*rows):
    """A writer storing ``rows`` as CSV."""

    def write(path):
        with path.open("w", newline="", encoding="utf-8") as fh:
            csv.writer(fh).writerows(rows)

    return write


def yaml_file(data):
    """A writer storing ``data`` as YAML."""

    def write(path):
        import yaml  # type: ignore

        path.write_text(yaml.safe_dump(data), encoding="utf-8")

    return write


# Each row: the mapping file's name, the writer filling it, the mapping loaded
LOAD_MAPPING_CASES = [
    pytest.param(
        "mapping.json",
        json_file({"11-chapter.md": "07-chapter.md", "14-chapter.md": "08-chapter.md"}),
        {"11-chapter.md": "07-chapter.md", "14-chapter.md": "08-chapter.md"},
        id="json-dict",
    ),
    pytest.param(
        "mapping.json",
        json_file([{"src": "16-chapter.md", "tgt": "09-chapter.md"}]),
        {"16-chapter.md": "09-chapter.md"},
        id="json-list",
    ),
    pytest.param(
        "mapping.csv",
        csv_file(["src", "tgt"], ["07-chapter.md", "10-chapter.md"]),
        {"07-chapter.md": "10-chapter.md"},
        id="csv-with-header",
    ),
    pytest.param(
        "mapping.csv",
        csv_file(["08-chapter.md", "14-chapter.md"]),
        {"08-chapter.md": "14-chapter.md"},
        id="csv-no-header",
    ),
    pytest.param(
        "mapping.yaml",
        yaml_file([{"src": "21-chapter.md", "tgt": "15-chapter.md"}]),
        {"21-chapter.md": "15-chapter.md"},
        id="yaml-list",
        marks=pytest.mark.skipif(
            not pytest.importorskip("yaml"), reason="PyYAML not installed"
        ),
    ),
]


@pytest.mark.parametrize("name, fill, expected", LOAD_MAPPING_CASES)
def test_load_mapping_file(name, fill, expected, tmp_path: Path):
    mf = tmp_path / name
    fill(mf)
    assert load_mapping_file(mf) == expected


# Each row: the src:tgt items, the mapping parsed, the ValueError message
# (None: the items parse)
PARSE_INLINE_MAP_CASES = [
    pytest.param(
        ["11-chapter.md:07-chapter.md", "14-chapter.md:08-chapter.md"],
        {"11-chapter.md": "07-chapter.md", "14-chapter.md": "08-chapter.md"},
        None,
        id="ok",
    ),
    pytest.param([" a : b "], {"a": "b"}, None, id="strips-whitespace"),
    pytest.param(["broken_entry_without_colon"], None, "Use 'src:tgt'", id="invalid"),
    pytest.param(["a:"], None, "Empty src/tgt", id="empty-target"),
    pytest.param([":b"], None, "Empty src/tgt", id="empty-source"),
]


@pytest.mark.parametrize("items, mapping, error", PARSE_INLINE_MAP_CASES)
def test_parse_inline_map(items, mapping, error):
    if error is None:
        assert parse_inline_map(items) == mapping
    else:
        with pytest.raises(ValueError, match=error):
            parse_inline_map(items)


# ----------------------------
# Resolve Mapping Tests
# ----------------------------


def test_resolve_mapping_merges_and_detects_collisions(tmp_path: Path):
    # File mapping
    mf = tmp_path / "mapping.json"
    mf.write_text(json.dumps({"11-chapter.md": "07-chapter.md"}), encoding="utf-8")

    # Inline extends / overrides
    mapping = _resolve_mapping(mf, ["14-chapter.md:08-chapter.md"])
    assert mapping["11-chapter.md"] == "07-chapter.md"
    assert mapping["14-chapter.md"] == "08-chapter.md"

    # Collision
    with pytest.raises(ValueError):
        _resolve_mapping(mf, ["XX.md:07-chapter.md"])  # two targets -> 07-chapter.md


# ----------------------------
# Header & Anchor Normalization
# ----------------------------

# Each row: the chapter's text, the new number, the language (None: autodetected
# from the header), the start of the H1 afterwards, the anchor it must carry
UPDATE_HEADER_CASES = [
    pytest.param(ES_H1, 7, "es", "# ✦ Capítulo 7:", "{#-chapter-7}", id="es"),
    pytest.param(DE_H1, 16, "de", "# ✦ Kapitel 16:", "{#-chapter-16}", id="de"),
    # No lang provided -> autodetect EN from header
    pytest.param(
        EN_H1, 10, None, "# ✦ Chapter 10:", "{#-chapter-10}", id="en-autodetect"
    ),
    # update should add anchor {#-chapter-9} and adjust number in H1
    pytest.param(
        ES_H1_NO_ANCHOR,
        9,
        "es",
        "# ✦ Capítulo 9:",
        "{#-chapter-9}",
        id="fallback-anchor-only",
    ),
]


@pytest.mark.parametrize("content, new_num, lang, start, anchor", UPDATE_HEADER_CASES)
def test_update_header_and_anchor(content, new_num, lang, start, anchor, tmp_path):
    f = tmp_path / "chapter.md"
    write_chapter(f, content)
    update_header_and_anchor(f, new_num, lang=lang, dry_run=False)
    out = f.read_text(encoding="utf-8")
    assert out.startswith(start), out
    assert anchor in out


# ----------------------------
# Two-Phase Rename
# ----------------------------


def test_two_phase_rename_and_header_update(tmp_path: Path):
    base = tmp_path / "manuscript" / "chapters"
    base.mkdir(parents=True, exist_ok=True)

    # Source files
    src_a = base / "11-chapter.md"
    src_b = base / "14-chapter.md"
    write_chapter(src_a, ES_H1)  # Capítulo 11
    write_chapter(src_b, ES_H1_NO_ANCHOR.replace("16", "14"))

    mapping = {
        "11-chapter.md": "07-chapter.md",
        "14-chapter.md": "08-chapter.md",
    }

    # Phase 1 + 2 (real run)
    _ = _two_phase_rename(base, mapping, dry_run=False)
    # Files should now be at targets
    tgt_a = base / "07-chapter.md"
    tgt_b = base / "08-chapter.md"
    assert tgt_a.exists(), "Target A missing"
    assert tgt_b.exists(), "Target B missing"

    # Update headers to match new numbers
    update_header_and_anchor(tgt_a, 7, lang="es", dry_run=False)
    update_header_and_anchor(tgt_b, 8, lang="es", dry_run=False)

    assert (base / "11-chapter.md").exists() is False
    out_a = tgt_a.read_text(encoding="utf-8")
    out_b = tgt_b.read_text(encoding="utf-8")
    assert out_a.startswith("# ✦ Capítulo 7:")
    assert "{#-chapter-7}" in out_a
    assert out_b.startswith("# ✦ Capítulo 8:")
    assert "{#-chapter-8}" in out_b


def test_two_phase_rename_dry_run(tmp_path: Path):
    base = tmp_path / "manuscript" / "chapters"
    base.mkdir(parents=True, exist_ok=True)

    src = base / "11-chapter.md"
    write_chapter(src, ES_H1)
    mapping = {"11-chapter.md": "07-chapter.md"}

    tmp_map = _two_phase_rename(base, mapping, dry_run=True)

    # In dry-run: no file changes should occur
    assert src.exists(), "Source should remain in dry-run"
    tgt = base / "07-chapter.md"
    assert not tgt.exists()

    # tmp_map still returns the intended paths (for logging), but nothing moved
    assert len(tmp_map) == 1
    (tmp_path_key, final_path) = list(tmp_map.items())[0]
    # tmp files not created on dry-run
    assert not tmp_path_key.exists()
    assert final_path.name == "07-chapter.md"


# ----------------------------
# Autodetect language
# ----------------------------

# Each row: a chapter's text and the language its header names (None: none)
AUTODETECT_LANG_CASES = [
    pytest.param(ES_H1, "es", id="es"),
    pytest.param(DE_H1, "de", id="de"),
    pytest.param(EN_H1, "en", id="en"),
    pytest.param("no matching header", None, id="no-matching-header"),
]


@pytest.mark.parametrize("text, lang", AUTODETECT_LANG_CASES)
def test_autodetect_lang(text, lang):
    assert autodetect_lang_by_header(text) == lang
