"""Unit tests for the configurable parts of manuscripta.project.init.

tests/unit/test_init_book_project.py checks the generated metadata and the
edits to pyproject.toml and full_export_book.py. This module covers the
init-settings.yaml loading and resolution, the stats and summary, the
excluded-items check with its interactive clean-up, and the CLI entry
point. ``input()`` is replaced by a queue of answers, nothing is read
from the terminal.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

import logging
import sys
from pathlib import Path

import yaml
import toml

import manuscripta.project.init as mod

APPENDIX = "manuscript/back-matter/appendix.md"
SETTINGS = mod.INIT_SETTINGS_FILE


def _defaults() -> dict:
    return mod._build_default_init_settings()


def _write_settings(base: Path, text: str) -> Path:
    path = base / SETTINGS
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _settings_as_directory(base: Path) -> Path:
    """A directory where the settings file is expected: exists, unreadable."""
    path = base / SETTINGS
    path.mkdir(parents=True)
    return path


@pytest.fixture
def answers(monkeypatch):
    """Replace input() with a queue; returns (queue, prompts shown)."""
    queue: list[str] = []
    prompts: list[str] = []

    def fake_input(prompt=""):
        prompts.append(prompt)
        if not queue:
            raise AssertionError("input() called with no answer queued")
        return queue.pop(0)

    monkeypatch.setattr("builtins.input", fake_input)
    return queue, prompts


# ---------------------------------------------------------------------------
# load_init_settings
# ---------------------------------------------------------------------------
# Each row: a builder preparing base_dir, a builder of the settings expected
# from the defaults, the level and fragment of the line logged
LOAD_SETTINGS_CASES = [
    pytest.param(
        lambda base: None,
        lambda d: d,
        ("INFO", "No config/init-settings.yaml found, using built-in defaults."),
        id="absent-file-uses-defaults",
    ),
    pytest.param(
        _settings_as_directory,
        lambda d: d,
        ("WARNING", "Could not read"),
        id="unreadable-file-falls-back",
    ),
    pytest.param(
        lambda base: _write_settings(base, "directories: [a, b"),
        lambda d: d,
        ("ERROR", "Failed to parse"),
        id="invalid-yaml-falls-back",
    ),
    pytest.param(
        lambda base: _write_settings(base, "- a\n- b\n"),
        lambda d: d,
        ("ERROR", "does not contain a YAML mapping (got list)"),
        id="list-instead-of-mapping-falls-back",
    ),
    pytest.param(
        lambda base: _write_settings(base, ""),
        lambda d: d,
        ("ERROR", "does not contain a YAML mapping (got NoneType)"),
        id="empty-file-falls-back",
    ),
    pytest.param(
        lambda base: _write_settings(base, "exclude:\n  - README.md\n"),
        lambda d: {
            "directories": d["directories"],
            "files": [f for f in d["files"] if f != "README.md"],
            "exclude": ["README.md"],
        },
        ("INFO", "Loaded project structure from"),
        id="mapping-is-resolved",
    ),
]


@pytest.mark.parametrize("prepare, expected, logged", LOAD_SETTINGS_CASES)
def test_load_init_settings(tmp_path, caplog, prepare, expected, logged):
    caplog.set_level(logging.INFO, logger="manuscripta.init")
    prepare(tmp_path)

    assert mod.load_init_settings(tmp_path) == expected(_defaults())

    level, fragment = logged
    assert [r.levelname for r in caplog.records if fragment in r.getMessage()] == [
        level
    ]


# ---------------------------------------------------------------------------
# _resolve_settings
# ---------------------------------------------------------------------------
# Each row: the parsed init-settings mapping, a builder of the result from
# the defaults, the lines logged in order (prefix "WARNING:" for warnings)
RESOLVE_CASES = [
    pytest.param(
        {},
        lambda d: d,
        [],
        id="empty-mapping-keeps-defaults",
    ),
    pytest.param(
        {"directories": ["src", "docs"]},
        lambda d: {**d, "directories": ["src", "docs"]},
        ["Using custom directories list (2 entries)."],
        id="directories-replace-defaults",
    ),
    pytest.param(
        {"files": ["README.md"]},
        lambda d: {**d, "files": ["README.md"]},
        ["Using custom files list (1 entries)."],
        id="files-replace-defaults",
    ),
    pytest.param(
        {"directories": None, "files": None},
        lambda d: d,
        [],
        id="null-lists-keep-defaults",
    ),
    pytest.param(
        {"include_directories": ["assets/audio", "config"]},
        lambda d: {**d, "directories": d["directories"] + ["assets/audio"]},
        ["  + directory: assets/audio"],
        id="include-directories-appends-new-only",
    ),
    pytest.param(
        {"include_files": ["manuscript/chapters/03-chapter.md", "LICENSE"]},
        lambda d: {**d, "files": d["files"] + ["manuscript/chapters/03-chapter.md"]},
        ["  + file: manuscript/chapters/03-chapter.md"],
        id="include-files-appends-new-only",
    ),
    pytest.param(
        {"exclude": ["output", APPENDIX]},
        lambda d: {
            "directories": [x for x in d["directories"] if x != "output"],
            "files": [x for x in d["files"] if x != APPENDIX],
            "exclude": ["output", APPENDIX],
        },
        ["Excluded 1 directories and 1 files."],
        id="exclude-removes-both-kinds",
    ),
    pytest.param(
        {"exclude": ["nothing/here"]},
        lambda d: {**d, "exclude": ["nothing/here"]},
        [],
        id="exclude-without-match-is-kept-silently",
    ),
    pytest.param(
        {"directories": ["a", "b"], "include_directories": ["c"], "exclude": ["a"]},
        lambda d: {**d, "directories": ["b", "c"], "exclude": ["a"]},
        [
            "Using custom directories list (2 entries).",
            "  + directory: c",
            "Excluded 1 directories and 0 files.",
        ],
        id="custom-then-include-then-exclude",
    ),
    pytest.param(
        {"directories": "manuscript"},
        lambda d: {**d, "directories": []},
        [
            "WARNING:'directories' should be a list, got str. Ignoring.",
            "Using custom directories list (0 entries).",
        ],
        id="scalar-directories-yields-empty-list",
    ),
    pytest.param(
        {"include_files": [1, 2.5]},
        lambda d: {**d, "files": d["files"] + ["1", "2.5"]},
        ["  + file: 1", "  + file: 2.5"],
        id="entries-coerced-to-strings",
    ),
]


@pytest.mark.parametrize("data, expected, logged", RESOLVE_CASES)
def test_resolve_settings(caplog, data, expected, logged):
    caplog.set_level(logging.INFO, logger="manuscripta.init")

    assert mod._resolve_settings(data, _defaults()) == expected(_defaults())

    assert [
        ("WARNING:" if r.levelno >= logging.WARNING else "") + r.getMessage()
        for r in caplog.records
    ] == logged


# Each row: the YAML value, the list it becomes, whether a warning names it
AS_LIST_CASES = [
    pytest.param(None, [], False, id="none-is-empty"),
    pytest.param(["a", 1, None], ["a", "1", "None"], False, id="list-stringified"),
    pytest.param("a", [], True, id="string-ignored"),
    pytest.param({"a": 1}, [], True, id="mapping-ignored"),
    pytest.param(3, [], True, id="number-ignored"),
]


@pytest.mark.parametrize("value, result, warned", AS_LIST_CASES)
def test_as_list(caplog, value, result, warned):
    caplog.set_level(logging.WARNING, logger="manuscripta.init")
    assert mod._as_list(value, "exclude") == result
    assert (
        f"'exclude' should be a list, got {type(value).__name__}. Ignoring."
        in caplog.text
    ) is warned


# ---------------------------------------------------------------------------
# InitStats.log_summary
# ---------------------------------------------------------------------------
# Each row: the stats fields set, the lines logged
SUMMARY_CASES = [
    pytest.param(
        {},
        ["Summary: 0 created (0 dirs, 0 files), 0 already existed."],
        id="nothing-done",
    ),
    pytest.param(
        {
            "dirs_created": ["a", "b"],
            "files_created": ["c"],
            "dirs_existed": ["d"],
            "files_existed": ["e", "f", "g"],
        },
        ["Summary: 3 created (2 dirs, 1 files), 4 already existed."],
        id="counts-add-up",
    ),
    pytest.param(
        {"excluded_exist_on_disk": ["x", "y/z"]},
        [
            "Summary: 0 created (0 dirs, 0 files), 0 already existed.",
            "2 excluded items still exist on disk. Run with --clean to remove them.",
            "  excluded but present: x",
            "  excluded but present: y/z",
        ],
        id="excluded-items-warned",
    ),
]


@pytest.mark.parametrize("fields, logged", SUMMARY_CASES)
def test_log_summary(caplog, fields, logged):
    caplog.set_level(logging.INFO, logger="manuscripta.init")
    mod.InitStats(**fields).log_summary()
    assert [r.getMessage() for r in caplog.records] == logged


# ---------------------------------------------------------------------------
# create_directories / create_files / check_excluded_on_disk
# ---------------------------------------------------------------------------
# Each row: the creator, the entries, the entries already on disk, the
# (created, existed) stats fields it fills
CREATE_CASES = [
    pytest.param(
        mod.create_directories,
        ["a", "b/c"],
        [],
        ("dirs_created", "dirs_existed"),
        id="directories-all-new",
    ),
    pytest.param(
        mod.create_directories,
        ["a", "b/c"],
        ["a"],
        ("dirs_created", "dirs_existed"),
        id="directories-one-exists",
    ),
    pytest.param(
        mod.create_files,
        ["a.md", "b/c.md"],
        [],
        ("files_created", "files_existed"),
        id="files-all-new-with-parents",
    ),
    pytest.param(
        mod.create_files,
        ["a.md", "b/c.md"],
        ["b/c.md"],
        ("files_created", "files_existed"),
        id="files-one-exists",
    ),
]


@pytest.mark.parametrize("creator, entries, existing, fields", CREATE_CASES)
def test_create_entries(tmp_path, creator, entries, existing, fields):
    for entry in existing:
        path = tmp_path / entry
        if creator is mod.create_directories:
            path.mkdir(parents=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("keep", encoding="utf-8")
    stats = mod.InitStats()

    creator(tmp_path, entries, stats)

    created, existed = fields
    assert getattr(stats, created) == [e for e in entries if e not in existing]
    assert getattr(stats, existed) == existing
    assert all((tmp_path / e).exists() for e in entries)
    for entry in existing:
        if creator is mod.create_files:
            assert (tmp_path / entry).read_text(encoding="utf-8") == "keep"


# Each row: the excluded entries, the ones present on disk as (entry, kind),
# the entries recorded as present
CHECK_EXCLUDED_CASES = [
    pytest.param(["a", "b.md"], [], [], id="none-present"),
    pytest.param(["a", "b.md"], [("b.md", "file")], ["b.md"], id="file-present"),
    pytest.param(["a", "b.md"], [("a", "dir")], ["a"], id="directory-present"),
    pytest.param(
        ["a", "gone", "b.md"],
        [("a", "dir"), ("b.md", "file")],
        ["a", "b.md"],
        id="present-ones-in-order",
    ),
]


def _place(base: Path, present: list[tuple[str, str]]):
    for entry, kind in present:
        path = base / entry
        if kind == "dir":
            path.mkdir(parents=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("x", encoding="utf-8")


@pytest.mark.parametrize("exclude, present, recorded", CHECK_EXCLUDED_CASES)
def test_check_excluded_on_disk(tmp_path, exclude, present, recorded):
    _place(tmp_path, present)
    stats = mod.InitStats()

    mod.check_excluded_on_disk(tmp_path, exclude, stats)

    assert stats.excluded_exist_on_disk == recorded


# ---------------------------------------------------------------------------
# clean_excluded
# ---------------------------------------------------------------------------
# Each row: the items present on disk as (entry, kind), the answer typed,
# the entries left on disk afterwards, the lines printed after the listing
CLEAN_DECISIONS = [
    pytest.param(
        [("d", "dir"), ("f.md", "file")],
        "y",
        [],
        ["  Deleted: d", "  Deleted: f.md"],
        id="yes-deletes-both-kinds",
    ),
    pytest.param(
        [("d", "dir")],
        "  Y ",
        [],
        ["  Deleted: d"],
        id="answer-is-stripped-and-lowercased",
    ),
    pytest.param(
        [("d", "dir"), ("f.md", "file")],
        "n",
        ["d", "f.md"],
        ["Skipped. No items deleted."],
        id="no-keeps-everything",
    ),
    pytest.param(
        [("f.md", "file")],
        "",
        ["f.md"],
        ["Skipped. No items deleted."],
        id="enter-defaults-to-no",
    ),
]


@pytest.mark.parametrize("present, answer, left, printed", CLEAN_DECISIONS)
def test_clean_excluded(tmp_path, capsys, answers, present, answer, left, printed):
    _place(tmp_path, present)
    queue, prompts = answers
    queue.append(answer)
    items = [entry for entry, _ in present]

    mod.clean_excluded(tmp_path, items)

    lines = capsys.readouterr().out.splitlines()
    listing = ["The following excluded items still exist on disk:"] + [
        f"  - {entry} ({kind})" for entry, kind in present
    ]
    assert lines == [""] + listing + printed
    assert prompts == ["\nDelete these items? [y/N]: "]
    assert [e for e in items if (tmp_path / e).exists()] == left


def test_clean_excluded_with_nothing_asks_nothing(tmp_path, capsys, answers):
    mod.clean_excluded(tmp_path, [])
    assert capsys.readouterr().out == ""
    assert answers[1] == []


def test_clean_excluded_reports_a_failed_deletion(
    tmp_path, capsys, caplog, answers, monkeypatch
):
    caplog.set_level(logging.INFO, logger="manuscripta.init")
    _place(tmp_path, [("locked", "dir"), ("f.md", "file")])
    answers[0].append("y")

    def refuse(path):
        raise OSError("device busy")

    monkeypatch.setattr(mod.shutil, "rmtree", refuse)

    mod.clean_excluded(tmp_path, ["locked", "f.md"])

    out = capsys.readouterr().out
    assert "  Error deleting locked: device busy" in out
    assert "  Deleted: f.md" in out
    assert "Failed to delete locked: device busy" in caplog.text
    assert (tmp_path / "locked").is_dir()
    assert not (tmp_path / "f.md").exists()


# ---------------------------------------------------------------------------
# update_pyproject
# ---------------------------------------------------------------------------
# Each row: the pyproject.toml mapping (None: no file), the mapping afterwards
# (None: still no file), the line logged
PYPROJECT_CASES = [
    pytest.param(
        None,
        None,
        "pyproject.toml not found, skipping update.",
        id="missing-file-skipped",
    ),
    pytest.param(
        {"project": {"name": "old", "description": "old"}},
        {"project": {"name": "new-book", "description": "About it"}},
        "Updated pyproject.toml with name='new-book'.",
        id="pep-621-section",
    ),
    pytest.param(
        {"tool": {"poetry": {"name": "old", "version": "0.1.0"}}},
        {"tool": {"poetry": {"name": "new-book", "version": "0.1.0"}}},
        "Updated pyproject.toml with name='new-book'.",
        id="poetry-without-description-gets-none",
    ),
    pytest.param(
        {
            "project": {"name": "old", "description": "old"},
            "tool": {"poetry": {"name": "old", "description": "old"}},
        },
        {
            "project": {"name": "new-book", "description": "About it"},
            "tool": {"poetry": {"name": "new-book", "description": "About it"}},
        },
        "Updated pyproject.toml with name='new-book'.",
        id="both-sections",
    ),
]


@pytest.mark.parametrize("before, after, logged", PYPROJECT_CASES)
def test_update_pyproject(tmp_path, caplog, before, after, logged):
    caplog.set_level(logging.INFO, logger="manuscripta.init")
    path = tmp_path / "pyproject.toml"
    if before is not None:
        path.write_text(toml.dumps(before), encoding="utf-8")

    mod.update_pyproject("new-book", "About it", tmp_path)

    assert (toml.load(path) if path.exists() else None) == after
    assert logged in caplog.text


# ---------------------------------------------------------------------------
# run_init_book_project
# ---------------------------------------------------------------------------
def _run(base: Path, clean: bool = False):
    mod.run_init_book_project(
        project_name="book",
        project_description="About it",
        book_title="Title",
        author_name="Author",
        base_dir=base,
        clean=clean,
    )


def test_first_run_writes_default_settings_and_a_second_run_creates_nothing(
    tmp_path, capsys
):
    _run(tmp_path)
    first = capsys.readouterr().out

    written = yaml.safe_load((tmp_path / SETTINGS).read_text(encoding="utf-8"))
    assert written == {
        "directories": mod._DEFAULT_DIRECTORIES,
        "files": mod._DEFAULT_FILES,
    }
    n_dirs, n_files = len(mod._DEFAULT_DIRECTORIES), len(mod._DEFAULT_FILES)
    assert (
        f"Done: {n_dirs} dirs created, {n_files} files created, 0 already existed."
        in first
    )
    assert "excluded item(s)" not in first

    _run(tmp_path)
    second = capsys.readouterr().out
    assert (
        f"Done: 0 dirs created, 0 files created, {n_dirs + n_files} already existed."
        in second
    )


def test_readme_excluded_from_files_is_still_written_with_content(tmp_path):
    """README.md in the file list is only touched; taken out of the list it
    is written by write_readme instead."""
    _write_settings(tmp_path, "exclude:\n  - README.md\n")

    _run(tmp_path)

    assert (tmp_path / "README.md").read_text(encoding="utf-8") == (
        "# Book Project\nThis is the book project structure.\n"
    )
    assert (tmp_path / "manuscript" / "chapters" / "01-chapter.md").read_text(
        encoding="utf-8"
    ) == ""


# Each row: the clean argument, the answers queued, whether the excluded
# appendix is still on disk afterwards, the line printed about it
RUN_INIT_CLEAN_DECISIONS = [
    pytest.param(
        False,
        [],
        True,
        "1 excluded item(s) still exist on disk. Run with --clean to remove them.",
        id="without-clean-only-reports",
    ),
    pytest.param(True, ["y"], False, "  Deleted: " + APPENDIX, id="clean-and-yes"),
    pytest.param(True, ["n"], True, "Skipped. No items deleted.", id="clean-and-no"),
]


@pytest.mark.parametrize("clean, queued, remains, printed", RUN_INIT_CLEAN_DECISIONS)
def test_run_init_handles_excluded_items_on_disk(
    tmp_path, capsys, answers, clean, queued, remains, printed
):
    _write_settings(tmp_path, f"exclude:\n  - {APPENDIX}\n")
    appendix = tmp_path / APPENDIX
    appendix.parent.mkdir(parents=True)
    appendix.write_text("old", encoding="utf-8")
    answers[0].extend(queued)

    _run(tmp_path, clean=clean)

    out = capsys.readouterr().out
    assert printed in out
    assert (f"  - {APPENDIX} (file)" in out) is clean
    assert appendix.exists() is remains
    assert answers[0] == []


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
PROMPTS = [
    "Enter your project name (e.g., 'ai-for-everyone'): ",
    "Enter a short description of your project: ",
    "Enter your book title: ",
    "Enter the author's name: ",
    "Enter publication year [2025]: ",
    "Enter language code [en]: ",
]

# Each row: the argv after the program name, the six answers typed, the
# keyword arguments run_init_book_project receives
MAIN_CASES = [
    pytest.param(
        [],
        ["  my-book ", "About it", " Title", "Author ", "2026", "de"],
        {
            "project_name": "my-book",
            "project_description": "About it",
            "book_title": "Title",
            "author_name": "Author",
            "year": "2026",
            "lang": "de",
            "clean": False,
        },
        id="answers-stripped",
    ),
    pytest.param(
        ["--clean"],
        ["my-book", "About it", "Title", "Author", "  ", ""],
        {
            "project_name": "my-book",
            "project_description": "About it",
            "book_title": "Title",
            "author_name": "Author",
            "year": "2025",
            "lang": "en",
            "clean": True,
        },
        id="clean-flag-and-defaults",
    ),
]


@pytest.mark.parametrize("argv, typed, expected", MAIN_CASES)
def test_main(monkeypatch, answers, argv, typed, expected):
    received: list[dict] = []
    monkeypatch.setattr(mod, "run_init_book_project", lambda **kw: received.append(kw))
    monkeypatch.setattr(sys, "argv", ["init-bp", *argv])
    answers[0].extend(typed)

    mod.main()

    assert received == [{**expected, "base_dir": mod.PROJECT_ROOT}]
    assert answers[1] == PROMPTS


def test_main_rejects_unknown_option(monkeypatch, answers, capsys):
    monkeypatch.setattr(sys, "argv", ["init-bp", "--bogus"])
    with pytest.raises(SystemExit) as exc:
        mod.main()
    assert exc.value.code == 2
    assert "unrecognized arguments: --bogus" in capsys.readouterr().err
    assert answers[1] == []
