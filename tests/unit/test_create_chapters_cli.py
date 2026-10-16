"""Unit tests for manuscripta.project.chapters beyond tests/test_create_chapters.py
(which covers create_chapter_files for the common cases): the pattern-to-regex
conversion, the detection of the next number, the fallback to the working
directory, the parser, main's exit statuses and log lines, and the __main__
guard."""

from __future__ import annotations

import logging
import re
import runpy
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

import manuscripta.project.chapters as ch
from manuscripta.project.chapters import (
    DEFAULT_PATTERN,
    _detect_next_start,
    _parse_args,
    _pattern_to_regex,
    create_chapter_files,
    main,
)

PROG = "create-chapters"
NO_PLACEHOLDER = (
    "Error: `--name-pattern` must include a '{num}' placeholder "
    "(e.g. '{num:02d}-chapter.md')."
)
FOREIGN_FIELD = (
    "Error: `--name-pattern` '{number}.md' cannot be formatted with num=1 "
    "(KeyError: 'number'); use a '{num}' placeholder (e.g. '{num:02d}-chapter.md')."
)


def chapters_of(root: Path) -> Path:
    """The directory create_chapter_files writes below the project root."""
    return root / "manuscript" / "chapters"


def seed(chapter_dir: Path, entries: list[str]) -> None:
    """Create the entries below chapter_dir; a trailing slash makes a directory."""
    chapter_dir.mkdir(parents=True)
    for entry in entries:
        if entry.endswith("/"):
            (chapter_dir / entry.rstrip("/")).mkdir()
        else:
            (chapter_dir / entry).touch()


def names_in(chapter_dir: Path) -> list[str] | None:
    """The sorted file names of chapter_dir, None when it does not exist."""
    if not chapter_dir.exists():
        return None
    return sorted(p.name for p in chapter_dir.iterdir())


# ---------------------------------------------------------------------------
# _pattern_to_regex
# ---------------------------------------------------------------------------
# Each row: a name pattern, the file names it matches with the number each
# captures, file names it rejects
PATTERN_REGEXES = [
    pytest.param(
        DEFAULT_PATTERN,
        {"01-chapter.md": 1, "7-chapter.md": 7, "123-chapter.md": 123},
        ["chapter.md", "01-chapter.md.bak", "x01-chapter.md", "01-chapter.mdx"],
        id="default-pattern-anchored-padding-not-enforced",
    ),
    pytest.param(
        "{num}-part.md",
        {"1-part.md": 1, "10-part.md": 10},
        ["-part.md", "a-part.md"],
        id="bare-placeholder-needs-digits",
    ),
    pytest.param(
        "chapter-{num:03d}.md",
        {"chapter-007.md": 7},
        ["chapter-.md", "007.md"],
        id="text-before-the-placeholder-is-kept",
    ),
    pytest.param(
        "{num}.scene.md",
        {"1.scene.md": 1},
        ["1xscene.md"],
        id="dots-are-literal",
    ),
]


@pytest.mark.parametrize("pattern, matches, rejects", PATTERN_REGEXES)
def test_pattern_to_regex(pattern, matches, rejects):
    rx = _pattern_to_regex(pattern)
    assert {name: int(rx.match(name).group("num")) for name in matches} == matches
    assert [name for name in rejects if rx.match(name)] == []


# Each row: a name pattern without the '{num}' or '{num:...}' token, which the
# conversion rejects (a '{num!r}' conversion formats but is no token)
PATTERNS_WITHOUT_TOKEN = [
    pytest.param("chapter.md", id="no-placeholder"),
    pytest.param("{num!r}.md", id="conversion-is-not-the-token"),
]


@pytest.mark.parametrize("pattern", PATTERNS_WITHOUT_TOKEN)
def test_pattern_to_regex_requires_the_token(pattern):
    with pytest.raises(ValueError, match="must contain a '{num}' placeholder"):
        _pattern_to_regex(pattern)


# ---------------------------------------------------------------------------
# _ensure_valid_pattern (through create_chapter_files)
# ---------------------------------------------------------------------------
# Each row: a name pattern create_chapter_files rejects up front (with or
# without a start, nothing is created), the error text
REJECTED_PATTERNS = [
    pytest.param(
        "chapter.md",
        "`--name-pattern` must include a '{num}' placeholder",
        id="no-placeholder",
    ),
    pytest.param(
        "{{num}}.md",
        "`--name-pattern` must include a '{num}' placeholder",
        id="escaped-braces-are-no-placeholder",
    ),
    pytest.param(
        "{number}.md",
        "`--name-pattern` '{number}.md' cannot be formatted with num=1 "
        "(KeyError: 'number')",
        id="foreign-field",
    ),
    pytest.param(
        "{}.md",
        "`--name-pattern` '{}.md' cannot be formatted with num=1 (IndexError:",
        id="positional-field",
    ),
    pytest.param(
        "{num:zz}.md",
        "`--name-pattern` '{num:zz}.md' cannot be formatted with num=1 (ValueError:",
        id="bad-format-spec",
    ),
    pytest.param(
        "{num}-{.md",
        "`--name-pattern` '{num}-{.md' cannot be formatted with num=1 (ValueError:",
        id="unbalanced-brace",
    ),
]


@pytest.mark.parametrize("pattern, text", REJECTED_PATTERNS)
@pytest.mark.parametrize("start", [1, None], ids=["with-start", "without-start"])
def test_rejected_patterns(pattern, text, start, tmp_path):
    with pytest.raises(ValueError) as exc:
        create_chapter_files(tmp_path, total=1, start=start, name_pattern=pattern)
    assert str(exc.value).startswith(text)
    assert names_in(chapters_of(tmp_path)) is None


# ---------------------------------------------------------------------------
# _detect_next_start
# ---------------------------------------------------------------------------
# Each row: the entries seeded in manuscript/chapters (a trailing slash marks
# a directory; None: the directory itself is missing), the number the next
# file gets for the default pattern
NEXT_STARTS = [
    pytest.param(None, 1, id="missing-directory-starts-at-1"),
    pytest.param([], 1, id="empty-directory-starts-at-1"),
    pytest.param(["01-chapter.md", "02-chapter.md"], 3, id="continues-after-highest"),
    pytest.param(["01-chapter.md", "07-chapter.md"], 8, id="gaps-are-not-filled"),
    pytest.param(
        ["02-chapter.md", "05-chapter.md/"],
        3,
        id="a-directory-with-a-matching-name-is-ignored",
    ),
    pytest.param(["7-chapter.md"], 8, id="unpadded-numbers-count"),
    pytest.param(["01-scene.md", "README.md"], 1, id="other-names-are-ignored"),
]


@pytest.mark.parametrize("entries, start", NEXT_STARTS)
def test_detect_next_start(entries, start, tmp_path):
    chapter_dir = chapters_of(tmp_path)
    if entries is not None:
        seed(chapter_dir, entries)
    assert _detect_next_start(chapter_dir, DEFAULT_PATTERN) == start


# ---------------------------------------------------------------------------
# create_chapter_files over an existing chapter directory
# ---------------------------------------------------------------------------
# Each row: the files already in manuscript/chapters (name -> text), the
# start, the total, the names created (returned), the directory afterwards
# (name -> text). The documented errors are the three ValueErrors, so an
# existing directory or file is none, and a chapter's text is never destroyed
EXISTING_DIRECTORY_RUNS = [
    pytest.param(
        {"01-chapter.md": "", "02-chapter.md": ""},
        None,
        2,
        ["03-chapter.md", "04-chapter.md"],
        {
            "01-chapter.md": "",
            "02-chapter.md": "",
            "03-chapter.md": "",
            "04-chapter.md": "",
        },
        id="continues-after-the-existing-files",
    ),
    pytest.param(
        {"01-chapter.md": "# Keep me\n"},
        1,
        2,
        ["01-chapter.md", "02-chapter.md"],
        {"01-chapter.md": "# Keep me\n", "02-chapter.md": ""},
        id="an-explicit-start-over-an-existing-file-keeps-its-text",
    ),
]


@pytest.mark.parametrize(
    "existing, start, total, created, after", EXISTING_DIRECTORY_RUNS
)
def test_create_chapter_files_in_an_existing_directory(
    existing, start, total, created, after, tmp_path
):
    chapter_dir = chapters_of(tmp_path)
    chapter_dir.mkdir(parents=True)
    for name, text in existing.items():
        (chapter_dir / name).write_text(text, encoding="utf-8")
    paths = create_chapter_files(tmp_path, total=total, start=start)
    assert [p.name for p in paths] == created
    assert {
        p.name: p.read_text(encoding="utf-8") for p in chapter_dir.iterdir()
    } == after


# ---------------------------------------------------------------------------
# the project directory
# ---------------------------------------------------------------------------
# Each row: a project_dir that falls back to the current working directory
CWD_FALLBACKS = [
    pytest.param(None, id="none"),
    pytest.param("", id="empty"),
    pytest.param("   ", id="blank"),
]


@pytest.mark.parametrize("project_dir", CWD_FALLBACKS)
def test_project_dir_falls_back_to_cwd(project_dir, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    created = create_chapter_files(project_dir, total=1, start=1)
    assert created == [chapters_of(tmp_path) / "01-chapter.md"]
    assert created[0].is_file()


# ---------------------------------------------------------------------------
# _parse_args
# ---------------------------------------------------------------------------
# Each row: the arguments after --total 1, the attribute, its parsed value
PARSER_VALUES = [
    pytest.param([], "total", 1, id="total"),
    pytest.param([], "project_dir", "", id="project-dir-default"),
    pytest.param([], "start", None, id="start-default"),
    pytest.param([], "name_pattern", DEFAULT_PATTERN, id="name-pattern-default"),
    pytest.param([], "dry_run", False, id="dry-run-default"),
    pytest.param(["--project-dir", "book"], "project_dir", "book", id="project-dir"),
    pytest.param(["--start", "4"], "start", 4, id="start"),
    pytest.param(
        ["--name-pattern", "{num}-x.md"], "name_pattern", "{num}-x.md", id="pattern"
    ),
    pytest.param(["--dry-run"], "dry_run", True, id="dry-run"),
]


@pytest.mark.parametrize("tail, attr, value", PARSER_VALUES)
def test_parser_values(tail, attr, value):
    assert getattr(_parse_args(["--total", "1", *tail]), attr) == value


# Each row: the arguments and the text of the usage error (exit status 2)
PARSER_REJECTS = [
    pytest.param([], "the following arguments are required: --total", id="no-total"),
    pytest.param(["--total", "two"], "invalid int value", id="total-not-an-int"),
    pytest.param(["--total", "1", "--start", "x"], "invalid int value", id="start"),
]


@pytest.mark.parametrize("argv, text", PARSER_REJECTS)
def test_parser_rejects(argv, text, capsys):
    with pytest.raises(SystemExit) as exc:
        _parse_args(argv)
    assert exc.value.code == 2
    assert text in capsys.readouterr().err


def help_output(monkeypatch, capsys) -> str:
    """The --help page, rendered wide enough that no entry wraps."""
    monkeypatch.setenv("COLUMNS", "200")
    with pytest.raises(SystemExit) as exc:
        _parse_args(["--help"])
    assert exc.value.code == 0
    return capsys.readouterr().out


def option_help_text(help_out: str, flag: str) -> str:
    """The help text argparse attached to the listing entry of ``flag`` (""
    when the entry carries none); an entry too long for its column carries
    the text on the indented line below."""
    lines = help_out.split("options:\n", 1)[1].splitlines()
    for line, below in zip(lines, lines[1:] + [""]):
        entry = line.strip()
        if entry != flag and not entry.startswith(flag + " "):
            continue
        parts = re.split(r"\s{2,}", entry, maxsplit=1)
        if len(parts) > 1:
            return parts[1]
        return below.strip() if below.startswith(" " * 20) else ""
    raise AssertionError(f"{flag} is not listed")


# Each row: an option whose --help entry must carry some help text; what the
# text says is not asserted (TESTING.md §14.8.1: presence, not wording)
OPTIONS_WITH_HELP = [
    pytest.param("--project-dir", id="project-dir"),
    pytest.param("--total", id="total"),
    pytest.param("--start", id="start"),
    pytest.param("--name-pattern", id="name-pattern"),
    pytest.param("--dry-run", id="dry-run"),
]


@pytest.mark.parametrize("flag", OPTIONS_WITH_HELP)
def test_every_option_has_help_text(flag, monkeypatch, capsys):
    assert option_help_text(help_output(monkeypatch, capsys), flag) != ""


def test_help_has_a_description_paragraph(monkeypatch, capsys):
    out = help_output(monkeypatch, capsys)
    paragraphs = [p.strip() for p in out.split("\n\n") if p.strip()]
    assert not paragraphs[1].startswith(("positional arguments:", "options:"))


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
# Each row: the arguments after --project-dir <root>, the exit status, the
# files of manuscript/chapters afterwards (None: the directory is not
# created), the lines logged (DIR stands for that directory)
MAIN_RUNS = [
    pytest.param(
        ["--total", "2"],
        0,
        ["01-chapter.md", "02-chapter.md"],
        ["✓ Created: DIR/01-chapter.md", "✓ Created: DIR/02-chapter.md"],
        id="creates-the-files",
    ),
    pytest.param(
        ["--total", "1", "--start", "7", "--name-pattern", "{num:03d}_scene.md"],
        0,
        ["007_scene.md"],
        ["✓ Created: DIR/007_scene.md"],
        id="start-and-pattern-are-forwarded",
    ),
    pytest.param(
        ["--total", "2", "--dry-run"],
        0,
        None,
        [
            "[dry-run] Would create: DIR/01-chapter.md",
            "[dry-run] Would create: DIR/02-chapter.md",
        ],
        id="dry-run-plans-only",
    ),
    pytest.param(
        ["--total", "0"],
        2,
        None,
        ["Error: `total` must be >= 1."],
        id="total-below-1-exits-2",
    ),
    pytest.param(
        ["--total", "1", "--start", "0"],
        2,
        None,
        ["Error: `start` must be >= 1 when provided."],
        id="start-below-1-exits-2",
    ),
    pytest.param(
        ["--total", "1", "--name-pattern", "chapter.md"],
        2,
        None,
        [NO_PLACEHOLDER],
        id="pattern-without-placeholder-exits-2",
    ),
    pytest.param(
        ["--total", "1", "--start", "1", "--name-pattern", "{number}.md"],
        2,
        None,
        [FOREIGN_FIELD],
        id="pattern-with-a-foreign-field-exits-2",
    ),
    # '{num!r}' formats (so the pattern is accepted up front) but is no
    # '{num}' token, which the detection of the next number rejects
    pytest.param(
        ["--total", "1", "--dry-run", "--name-pattern", "{num!r}.md"],
        2,
        None,
        ["Error: Pattern must contain a '{num}' placeholder."],
        id="pattern-that-formats-without-the-token-exits-2-at-detection",
    ),
]


@pytest.mark.parametrize("tail, code, files, logged", MAIN_RUNS)
def test_main(tail, code, files, logged, tmp_path, caplog):
    chapter_dir = chapters_of(tmp_path)
    caplog.set_level(logging.INFO)
    assert main(["--project-dir", str(tmp_path), *tail]) == code
    assert names_in(chapter_dir) == files
    assert caplog.messages == [line.replace("DIR", str(chapter_dir)) for line in logged]


def test_main_without_argv_reads_sys_argv(tmp_path, monkeypatch):
    monkeypatch.setattr(
        sys, "argv", [PROG, "--project-dir", str(tmp_path), "--total", "1"]
    )
    assert main() == 0
    assert names_in(chapters_of(tmp_path)) == ["01-chapter.md"]


# ---------------------------------------------------------------------------
# the __main__ guard
# ---------------------------------------------------------------------------
# Each row: the arguments after --project-dir <root>, the exit status of the
# script run as __main__, the files of manuscript/chapters afterwards
MAIN_GUARD_EXITS = [
    pytest.param(["--total", "1"], 0, ["01-chapter.md"], id="creates-and-exits-0"),
    pytest.param(["--total", "0"], 2, None, id="invalid-total-exits-2"),
]


@pytest.mark.parametrize("tail, code, files", MAIN_GUARD_EXITS)
def test_script_run_as_main(tail, code, files, tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "argv", [PROG, "--project-dir", str(tmp_path), *tail])
    with pytest.raises(SystemExit) as exc:
        runpy.run_path(ch.__file__, run_name="__main__")
    assert exc.value.code == code
    assert names_in(chapters_of(tmp_path)) == files
