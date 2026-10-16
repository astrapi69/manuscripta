"""Unit tests for manuscripta.project.chapters beyond tests/test_create_chapters.py
(which covers create_chapter_files for the common cases): the pattern-to-regex
conversion, the detection of the next number, the fallback to the working
directory, the parser, main's exit statuses and log lines, and the __main__
guard."""

from __future__ import annotations

import logging
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


def test_pattern_with_an_incomplete_placeholder_fails_at_detection(tmp_path):
    # "{number}" passes the "{num" check but is no placeholder; without a
    # start the detection of the next number is where it is rejected.
    with pytest.raises(ValueError, match="must contain a '{num}' placeholder"):
        create_chapter_files(tmp_path, total=1, start=None, name_pattern="{number}.md")


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
