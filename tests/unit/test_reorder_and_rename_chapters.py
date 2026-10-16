# tests/test_reorder_and_rename_chapters.py
import json
import csv
import sys
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
# after the program name ({base}: the chapters dir, {map}: a JSON mapping file
# 11-chapter.md -> 07-chapter.md), the exit code, the chapters afterwards
# (name -> first line; None: not UTF-8), the stdout lines, the stderr
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
]


@pytest.mark.parametrize("files, args, code, heads, lines, err", MAIN_RUNS)
def test_main(files, args, code, heads, lines, err, tmp_path, monkeypatch, capsys):
    base = tmp_path / "chapters"
    base.mkdir()
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
    assert {p.name: head_of(p) for p in base.iterdir()} == heads
