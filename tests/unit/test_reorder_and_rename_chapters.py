# tests/test_reorder_and_rename_chapters.py
import json
import csv
import locale
import re
import sys
from contextlib import contextmanager
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
    main,
)
import manuscripta.project.reorder as reorder

# ----------------------------
# Helpers
# ----------------------------


def write_chapter(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


@contextmanager
def c_locale(monkeypatch):
    """The C locale for the block: its codec is ASCII, so a file read or
    written with the locale default instead of UTF-8 cannot carry ✦ or an
    umlaut."""
    saved = locale.setlocale(locale.LC_ALL)
    monkeypatch.setenv("LC_ALL", "C")
    monkeypatch.setenv("LANG", "C")
    locale.setlocale(locale.LC_ALL, "C")
    try:
        yield
    finally:
        locale.setlocale(locale.LC_ALL, saved)


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


NEEDS_YAML = pytest.mark.skipif(not reorder._HAS_YAML, reason="PyYAML not installed")

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
    pytest.param(
        "mapping.yml",
        yaml_file({"01-chapter.md": "02-chapter.md"}),
        {"01-chapter.md": "02-chapter.md"},
        id="yaml-dict",
        marks=NEEDS_YAML,
    ),
    pytest.param(
        "mapping.csv",
        csv_file(["a.md", "b.md"], ["c.md", "d.md"]),
        {"a.md": "b.md", "c.md": "d.md"},
        id="csv-no-header-several-rows",
    ),
    pytest.param("mapping.csv", csv_file(), {}, id="csv-empty"),
    pytest.param(
        "mapping.json", json_file({1: 2}), {"1": "2"}, id="json-values-stringified"
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
    # The first colon separates src from tgt; a target keeps any later one
    pytest.param(
        ["11-chapter.md:07-chapter: Ideas.md"],
        {"11-chapter.md": "07-chapter: Ideas.md"},
        None,
        id="first-colon-splits-target-keeps-later-ones",
    ),
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
    # H1 without the language prefix: only the anchor's number is replaced
    pytest.param(
        "# Intro {#-chapter-3}\n\nTexto…\n",
        5,
        "es",
        "# Intro {#-chapter-5}",
        "{#-chapter-5}",
        id="anchor-only-when-h1-lacks-the-prefix",
    ),
    # Neither --lang nor a recognisable prefix: the anchor is still renumbered
    pytest.param(
        "# Intro {#-chapter-3}\n\nTexto…\n",
        5,
        None,
        "# Intro {#-chapter-5}",
        "{#-chapter-5}",
        id="anchor-only-without-lang-when-no-prefix-is-detected",
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
    # The language word is recognised whatever its case
    pytest.param("# ✦ CAPÍTULO 3: Ideas\n", "es", id="es-uppercase"),
    pytest.param("# ✦ kapitel 2: Klarheit\n", "de", id="de-lowercase"),
    pytest.param("# ✦ CHAPTER 1: One\n", "en", id="en-uppercase"),
]


@pytest.mark.parametrize("text, lang", AUTODETECT_LANG_CASES)
def test_autodetect_lang(text, lang):
    assert autodetect_lang_by_header(text) == lang


def text_file(text):
    """A writer storing ``text`` verbatim."""
    return lambda path: path.write_text(text, encoding="utf-8")


def no_file(path):
    """A writer storing nothing: the mapping file stays missing."""


# Each row: the mapping file's name, the writer filling it, the exception
# raised and its message
LOAD_MAPPING_ERRORS = [
    pytest.param(
        "mapping.json",
        no_file,
        FileNotFoundError,
        "Mapping file not found",
        id="missing-file",
    ),
    pytest.param(
        "mapping.json",
        json_file([{"src": "a.md"}]),
        ValueError,
        "JSON list items must have 'src' and 'tgt'",
        id="json-list-without-tgt",
    ),
    pytest.param(
        "mapping.json",
        json_file("a.md:b.md"),
        ValueError,
        "JSON mapping must be dict or list",
        id="json-scalar",
    ),
    pytest.param(
        "mapping.csv",
        csv_file(["src", "tgt"], ["a.md", ""]),
        ValueError,
        "CSV with header must have columns 'src' and 'tgt'",
        id="csv-header-row-without-tgt",
    ),
    pytest.param(
        "mapping.csv",
        csv_file(["a.md"]),
        ValueError,
        "CSV rows must have at least 2 columns",
        id="csv-first-row-one-column",
    ),
    pytest.param(
        "mapping.csv",
        csv_file(["a.md", "b.md"], ["c.md"]),
        ValueError,
        "CSV rows must have at least 2 columns",
        id="csv-later-row-one-column",
    ),
    pytest.param(
        "mapping.yaml",
        yaml_file([{"tgt": "b.md"}]),
        ValueError,
        "YAML list items must have 'src' and 'tgt'",
        id="yaml-list-without-src",
        marks=NEEDS_YAML,
    ),
    pytest.param(
        "mapping.yaml",
        yaml_file("a.md"),
        ValueError,
        "YAML mapping must be dict or list",
        id="yaml-scalar",
        marks=NEEDS_YAML,
    ),
    pytest.param(
        "mapping.txt",
        text_file("a.md:b.md"),
        ValueError,
        "Unsupported mapping file format: .txt",
        id="unsupported-extension",
    ),
]


@pytest.mark.parametrize("name, fill, error, message", LOAD_MAPPING_ERRORS)
def test_load_mapping_file_errors(name, fill, error, message, tmp_path: Path):
    mf = tmp_path / name
    fill(mf)
    with pytest.raises(error, match=message):
        load_mapping_file(mf)


def test_load_mapping_file_yaml_without_pyyaml(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(reorder, "_HAS_YAML", False)
    mf = tmp_path / "mapping.yaml"
    mf.write_text("a.md: b.md\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="PyYAML not installed"):
        load_mapping_file(mf)


# Each row: the chapter's text, the new number, the language (None:
# autodetected), the exact text written, the "[OK]" line printed
UPDATE_HEADER_WRITES = [
    pytest.param(
        ES_H1,
        7,
        "es",
        "# ✦ Capítulo 7: Creatividad – La moneda renovable {#-chapter-7}\n\nContenido…\n",
        "[OK] chapter.md: header/anchor -> chapter 7 (lang=es)\n",
        id="es-renumbered-trailing-newline-kept",
    ),
    pytest.param(
        "# ✦ Chapter 3: Rich Now\nBody\n",
        4,
        None,
        "# ✦ Chapter 4: Rich Now {#-chapter-4}\nBody\n",
        "[OK] chapter.md: header/anchor -> chapter 4 (lang=en)\n",
        id="en-autodetected-anchor-added",
    ),
    pytest.param(
        "# Title only\n\nBody\n",
        2,
        "de",
        "# Title only\n\nBody\n",
        "[OK] chapter.md: header/anchor -> chapter 2 (lang=de)\n",
        id="no-pattern-no-anchor-leaves-h1",
    ),
    pytest.param(
        "# ✦ Kapitel 1: Klarheit",
        2,
        "de",
        "# ✦ Kapitel 2: Klarheit {#-chapter-2}",
        "[OK] chapter.md: header/anchor -> chapter 2 (lang=de)\n",
        id="without-trailing-newline-none-added",
    ),
    pytest.param(
        "# ✦ Kapitel 1: Leer {#-chapter-1}\n\n\n",
        3,
        "de",
        "# ✦ Kapitel 3: Leer {#-chapter-3}\n\n\n",
        "[OK] chapter.md: header/anchor -> chapter 3 (lang=de)\n",
        id="trailing-blank-lines-kept",
    ),
    # The prefix is recognised whatever its case and rewritten canonically
    pytest.param(
        "# ✦ KAPITEL 1: Klarheit\n",
        2,
        None,
        "# ✦ Kapitel 2: Klarheit {#-chapter-2}\n",
        "[OK] chapter.md: header/anchor -> chapter 2 (lang=de)\n",
        id="uppercase-prefix-detected-and-rewritten-canonically",
    ),
]


@pytest.mark.parametrize("content, new_num, lang, written, line", UPDATE_HEADER_WRITES)
def test_update_header_writes_exact_text(
    content, new_num, lang, written, line, tmp_path, capsys
):
    f = tmp_path / "chapter.md"
    write_chapter(f, content)
    update_header_and_anchor(f, new_num, lang=lang, dry_run=False)
    assert f.read_text(encoding="utf-8") == written
    assert capsys.readouterr().out == line


# Each row: the chapter's text, the new number, the language (None:
# autodetected), the "[DRY]" line printed ("": nothing, the header already fits)
UPDATE_HEADER_DRY_RUNS = [
    pytest.param(
        ES_H1,
        7,
        "es",
        "[DRY] Would update header/anchor -> chapter 7 in chapter.md (lang=es)\n",
        id="es-renumbered",
    ),
    pytest.param(
        EN_H1,
        2,
        None,
        "[DRY] Would update header/anchor -> chapter 2 in chapter.md (lang=en)\n",
        id="en-autodetected",
    ),
    pytest.param(
        "# ✦ Kapitel 9: Klarheit {#-chapter-9}\n\nInhalt…\n",
        9,
        "de",
        "",
        id="already-normalized-prints-nothing",
    ),
    pytest.param(
        "# ✦ Kapitel 9: Klarheit {#-chapter-9}",
        9,
        "de",
        "",
        id="already-normalized-without-trailing-newline-prints-nothing",
    ),
]


@pytest.mark.parametrize("content, new_num, lang, line", UPDATE_HEADER_DRY_RUNS)
def test_update_header_dry_run(content, new_num, lang, line, tmp_path, capsys):
    f = tmp_path / "chapter.md"
    write_chapter(f, content)
    update_header_and_anchor(f, new_num, lang=lang, dry_run=True)
    assert f.read_text(encoding="utf-8") == content
    assert capsys.readouterr().out == line


def test_update_header_rejects_unknown_language(tmp_path: Path):
    f = tmp_path / "chapter.md"
    write_chapter(f, ES_H1)
    with pytest.raises(
        ValueError, match="Unsupported language 'fr'. Use one of: es, de, en"
    ):
        update_header_and_anchor(f, 1, lang="fr", dry_run=False)
    assert f.read_text(encoding="utf-8") == ES_H1


def test_update_header_leaves_empty_file_alone(tmp_path: Path, capsys):
    f = tmp_path / "chapter.md"
    write_chapter(f, "")
    update_header_and_anchor(f, 3, lang="de", dry_run=False)
    assert f.read_text(encoding="utf-8") == ""
    assert capsys.readouterr().out == ""


def test_update_header_reads_and_writes_utf8_under_c_locale(tmp_path, monkeypatch):
    """The chapter is read and written as UTF-8 whatever the locale: under
    LC_ALL=C the locale codec is ASCII and cannot carry ✦ or the umlauts."""
    f = tmp_path / "chapter.md"
    f.write_bytes("# ✦ Kapitel 1: Grüße\n\nBär…\n".encode("utf-8"))
    with c_locale(monkeypatch):
        update_header_and_anchor(f, 2, lang=None, dry_run=False)
    assert f.read_bytes() == "# ✦ Kapitel 2: Grüße {#-chapter-2}\n\nBär…\n".encode(
        "utf-8"
    )


# Each row: a mapping file's name and the writer filling it with the entry
# Grüße.md -> Bär.md, spelled in UTF-8 (not escaped to ASCII)
UTF8_MAPPING_FILES = [
    pytest.param(
        "mapping.json",
        text_file(json.dumps({"Grüße.md": "Bär.md"}, ensure_ascii=False)),
        id="json",
    ),
    pytest.param("mapping.csv", csv_file(["Grüße.md", "Bär.md"]), id="csv"),
    pytest.param(
        "mapping.yaml", text_file("Grüße.md: Bär.md\n"), id="yaml", marks=NEEDS_YAML
    ),
]


@pytest.mark.parametrize("name, fill", UTF8_MAPPING_FILES)
def test_load_mapping_file_reads_utf8_under_c_locale(name, fill, tmp_path, monkeypatch):
    """A mapping file is read as UTF-8 whatever the locale: under LC_ALL=C
    the locale codec is ASCII and cannot carry the umlauts in the names."""
    mf = tmp_path / name
    fill(mf)
    with c_locale(monkeypatch):
        assert load_mapping_file(mf) == {"Grüße.md": "Bär.md"}


def test_resolve_mapping_requires_a_mapping():
    with pytest.raises(ValueError, match="No mapping provided"):
        _resolve_mapping(None, [])


def test_two_phase_rename_skips_missing_sources(tmp_path: Path, capsys):
    write_chapter(tmp_path / "11-chapter.md", ES_H1)
    mapping = {"99-chapter.md": "05-chapter.md", "11-chapter.md": "07-chapter.md"}
    tmp_map = _two_phase_rename(tmp_path, mapping, dry_run=False)
    assert tmp_map == {tmp_path / "11-chapter.md.tmpmove": tmp_path / "07-chapter.md"}
    assert sorted(p.name for p in tmp_path.iterdir()) == ["07-chapter.md"]
    missing = tmp_path / "99-chapter.md"
    assert capsys.readouterr().out == f"[WARN] Source not found (skipping): {missing}\n"


# ----------------------------
# Command line
# ----------------------------

ES_H1_14 = ES_H1_NO_ANCHOR.replace("16", "14")
DONE = "[DONE] Reorder/rename + header/anchor normalization complete."


def head_of_text(text: str) -> str:
    """The first line of a chapter's text."""
    return text.splitlines()[0]


def head_of(path: Path):
    """The first line of a chapter (None: the file is not UTF-8)."""
    try:
        return path.read_text(encoding="utf-8").splitlines()[0]
    except UnicodeDecodeError:
        return None


# Each row: the chapter files (name -> text; bytes: written raw), the arguments
# after the program name ({base}: the chapters dir manuscript/chapters below
# the working directory, {map}: a JSON mapping file 11-chapter.md ->
# 07-chapter.md), the exit code, the chapters afterwards (path below the
# chapters dir -> first line; None: not UTF-8), the stdout lines, the stderr
MAIN_RUNS = [
    pytest.param(
        {},
        ["--base-dir", "{base}/missing"],
        1,
        {},
        [],
        "[ERROR] Base dir not found: {base}/missing\n",
        id="base-dir-missing",
    ),
    pytest.param(
        {"11-chapter.md": ES_H1},
        ["--base-dir", "{base}"],
        1,
        {"11-chapter.md": head_of_text(ES_H1)},
        [],
        "[ERROR] No mapping provided. Use --map-file and/or --map 'src:tgt'.\n",
        id="no-mapping",
    ),
    pytest.param(
        {"11-chapter.md": ES_H1},
        ["--base-dir", "{base}", "--map", "nocolon"],
        1,
        {"11-chapter.md": head_of_text(ES_H1)},
        [],
        "[ERROR] Invalid mapping 'nocolon'. Use 'src:tgt'.\n",
        id="invalid-inline-map",
    ),
    pytest.param(
        {"11-chapter.md": ES_H1, "14-chapter.md": ES_H1_14},
        [
            "--base-dir",
            "{base}",
            "--lang",
            "es",
            "--map",
            "11-chapter.md:07-chapter.md",
            "--map",
            "14-chapter.md:08-chapter.md",
        ],
        0,
        {
            "07-chapter.md": "# ✦ Capítulo 7: Creatividad – La moneda renovable {#-chapter-7}",
            "08-chapter.md": "# ✦ Capítulo 8: Ideas – Semillas de riqueza mental {#-chapter-8}",
        },
        [
            "[OK] 07-chapter.md: header/anchor -> chapter 7 (lang=es)",
            "[OK] 08-chapter.md: header/anchor -> chapter 8 (lang=es)",
            DONE,
        ],
        "",
        id="inline-map-renames-and-renumbers",
    ),
    pytest.param(
        {"11-chapter.md": ES_H1},
        ["--base-dir", "{base}", "--map-file", "{map}", "--dry-run"],
        0,
        {"11-chapter.md": head_of_text(ES_H1)},
        [
            "[DRY] Would rename: 11-chapter.md -> 11-chapter.md.tmpmove",
            "[DRY] Would finalize: 11-chapter.md.tmpmove -> 07-chapter.md",
            "[DRY] Would update header/anchor -> chapter 7 in 11-chapter.md (lang=es)",
            DONE + " (dry-run)",
        ],
        "",
        id="map-file-dry-run-moves-nothing-and-previews-the-header",
    ),
    pytest.param(
        {"11-chapter.md": ES_H1},
        ["--base-dir", "{base}", "--map", "11-chapter.md:intro.md"],
        0,
        {"intro.md": head_of_text(ES_H1)},
        ["[WARN] Could not infer chapter number from filename: intro.md", DONE],
        "",
        id="target-without-number-keeps-header",
    ),
    pytest.param(
        {"11-chapter.md": ES_H1},
        [
            "--base-dir",
            "{base}",
            "--lang",
            "es",
            "--map",
            "99-chapter.md:05-chapter.md",
            "--map",
            "11-chapter.md:07-chapter.md",
        ],
        0,
        {
            "07-chapter.md": "# ✦ Capítulo 7: Creatividad – La moneda renovable {#-chapter-7}",
        },
        [
            "[WARN] Source not found (skipping): {base}/99-chapter.md",
            "[OK] 07-chapter.md: header/anchor -> chapter 7 (lang=es)",
            DONE,
        ],
        "",
        id="missing-source-skipped",
    ),
    pytest.param(
        {"11-chapter.md": b"\xff\xfe"},
        ["--base-dir", "{base}", "--map", "11-chapter.md:07-chapter.md"],
        0,
        {"07-chapter.md": None},
        [
            "[WARN] Header/anchor update failed for 07-chapter.md: "
            "'utf-8' codec can't decode byte 0xff in position 0: invalid start byte",
            DONE,
        ],
        "",
        id="undecodable-chapter-renamed-but-warned",
    ),
    # Without --base-dir the chapters are looked for in manuscript/chapters
    pytest.param(
        {"11-chapter.md": ES_H1},
        ["--map", "11-chapter.md:07-chapter.md"],
        0,
        {
            "07-chapter.md": "# ✦ Capítulo 7: Creatividad – La moneda renovable {#-chapter-7}",
        },
        ["[OK] 07-chapter.md: header/anchor -> chapter 7 (lang=es)", DONE],
        "",
        id="base-dir-defaults-to-manuscript-chapters",
    ),
    # Two sources mapped onto one target: a configuration error, nothing moves
    pytest.param(
        {"11-chapter.md": ES_H1, "14-chapter.md": ES_H1_14},
        [
            "--base-dir",
            "{base}",
            "--map",
            "11-chapter.md:07-chapter.md",
            "--map",
            "14-chapter.md:07-chapter.md",
        ],
        1,
        {"11-chapter.md": head_of_text(ES_H1), "14-chapter.md": head_of_text(ES_H1_14)},
        [],
        "[ERROR] Target filename collision in mapping. Make targets unique.\n",
        id="colliding-targets-are-a-configuration-error",
    ),
    # A target may name directories that do not exist yet, at any depth
    pytest.param(
        {"11-chapter.md": ES_H1},
        [
            "--base-dir",
            "{base}",
            "--map",
            "11-chapter.md:part-2/chapters/07-chapter.md",
        ],
        0,
        {
            "part-2/chapters/07-chapter.md": "# ✦ Capítulo 7: Creatividad – La moneda renovable {#-chapter-7}",
        },
        ["[OK] 07-chapter.md: header/anchor -> chapter 7 (lang=es)", DONE],
        "",
        id="target-directories-are-created",
    ),
    # A target without a chapter number skips only that chapter
    pytest.param(
        {"11-chapter.md": ES_H1, "14-chapter.md": ES_H1_14},
        [
            "--base-dir",
            "{base}",
            "--map",
            "11-chapter.md:intro.md",
            "--map",
            "14-chapter.md:08-chapter.md",
        ],
        0,
        {
            "intro.md": head_of_text(ES_H1),
            "08-chapter.md": "# ✦ Capítulo 8: Ideas – Semillas de riqueza mental {#-chapter-8}",
        },
        [
            "[WARN] Could not infer chapter number from filename: intro.md",
            "[OK] 08-chapter.md: header/anchor -> chapter 8 (lang=es)",
            DONE,
        ],
        "",
        id="target-without-number-skips-only-that-chapter",
    ),
    # --lang forces the pattern instead of auto-detecting it per file: an H1
    # in another language does not match it and gets only its anchor renumbered
    pytest.param(
        {"11-chapter.md": EN_H1},
        [
            "--base-dir",
            "{base}",
            "--lang",
            "es",
            "--map",
            "11-chapter.md:08-chapter.md",
        ],
        0,
        {
            "08-chapter.md": "# ✦ Chapter 7: Presence – The Lost Art of Being Rich Now {#-chapter-8}",
        },
        ["[OK] 08-chapter.md: header/anchor -> chapter 8 (lang=es)", DONE],
        "",
        id="lang-forces-the-pattern-instead-of-auto-detecting",
    ),
]


def chapters_dir(tmp_path: Path, monkeypatch) -> Path:
    """The chapters dir manuscript/chapters below the working directory."""
    base = tmp_path / "manuscript" / "chapters"
    base.mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    return base


@pytest.mark.parametrize("files, args, code, heads, lines, err", MAIN_RUNS)
def test_main(files, args, code, heads, lines, err, tmp_path, monkeypatch, capsys):
    base = chapters_dir(tmp_path, monkeypatch)
    for name, content in files.items():
        raw = content if isinstance(content, bytes) else content.encode("utf-8")
        (base / name).write_bytes(raw)
    map_file = tmp_path / "mapping.json"
    map_file.write_text(
        json.dumps({"11-chapter.md": "07-chapter.md"}), encoding="utf-8"
    )

    def fill(s: str) -> str:
        return s.replace("{base}", str(base)).replace("{map}", str(map_file))

    monkeypatch.setattr(sys, "argv", ["reorder-chapters", *map(fill, args)])
    assert main() == code
    out, stderr = capsys.readouterr()
    assert out.splitlines() == [fill(line) for line in lines]
    assert stderr == fill(err)
    assert {
        p.relative_to(base).as_posix(): head_of(p)
        for p in base.rglob("*")
        if p.is_file()
    } == heads


# Each row: the arguments after the program name ({base}: the chapters dir
# holding 11-chapter.md), the option argparse's usage error names; the parser
# rejects the run (exit status 2) before anything is renamed
MAIN_USAGE_ERRORS = [
    pytest.param(
        [
            "--base-dir",
            "{base}",
            "--lang",
            "fr",
            "--map",
            "11-chapter.md:07-chapter.md",
        ],
        "--lang",
        id="unknown-language-is-rejected-by-the-parser",
    ),
]


@pytest.mark.parametrize("args, option", MAIN_USAGE_ERRORS)
def test_main_usage_errors(args, option, tmp_path, monkeypatch, capsys):
    base = chapters_dir(tmp_path, monkeypatch)
    write_chapter(base / "11-chapter.md", ES_H1)
    argv = [a.replace("{base}", str(base)) for a in args]
    monkeypatch.setattr(sys, "argv", ["reorder-chapters", *argv])
    with pytest.raises(SystemExit) as exit_info:
        main()
    assert exit_info.value.code == 2
    assert option in capsys.readouterr().err
    assert sorted(p.name for p in base.iterdir()) == ["11-chapter.md"]


def help_output(monkeypatch, capsys) -> str:
    """The --help page, rendered wide enough that no entry wraps."""
    monkeypatch.setenv("COLUMNS", "200")
    monkeypatch.setattr(sys, "argv", ["reorder-chapters", "--help"])
    with pytest.raises(SystemExit) as exit_info:
        main()
    assert exit_info.value.code == 0
    return capsys.readouterr().out


def option_help_text(help_out: str, flag: str) -> str:
    """The help text argparse attached to the listing entry of ``flag`` (""
    when the entry carries none)."""
    sections = re.split(
        r"^(?:positional arguments|options):$", help_out, maxsplit=1, flags=re.M
    )
    lines = sections[1].splitlines()
    for i, line in enumerate(lines):
        entry = line.strip()
        if re.match(re.escape(flag) + r"(?=[\s,]|$)", entry):
            parts = re.split(r"\s{2,}", entry, maxsplit=1)
            if len(parts) > 1:
                return parts[1]
            # a wide invocation pushes its text onto a deeper-indented line;
            # without text the next line is the next entry, indented alike
            following = lines[i + 1] if i + 1 < len(lines) else ""
            deeper = indentation(following) > indentation(line)
            return following.strip() if deeper else ""
    raise AssertionError(f"{flag} is not listed")


def indentation(line: str) -> int:
    return len(line) - len(line.lstrip())


# Each row: an option whose --help entry must carry some help text; what the
# text says is not asserted (TESTING.md §14.8.1)
OPTIONS_WITH_HELP = [
    pytest.param("--base-dir", id="base-dir"),
    pytest.param("--map-file", id="map-file"),
    pytest.param("--map", id="map"),
    pytest.param("--lang", id="lang"),
    pytest.param("--dry-run", id="dry-run"),
]


@pytest.mark.parametrize("flag", OPTIONS_WITH_HELP)
def test_every_option_has_help_text(flag, monkeypatch, capsys):
    assert option_help_text(help_output(monkeypatch, capsys), flag) != ""


def test_help_has_a_description_paragraph(monkeypatch, capsys):
    out = help_output(monkeypatch, capsys)
    paragraphs = [p.strip() for p in out.split("\n\n") if p.strip()]
    assert not paragraphs[1].startswith(("positional arguments:", "options:"))
