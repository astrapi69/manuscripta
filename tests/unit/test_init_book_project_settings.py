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

import json
import logging
import re
import sys
from pathlib import Path

import yaml
import toml

import manuscripta.project.init as mod

APPENDIX = "manuscript/back-matter/appendix.md"
SETTINGS = mod.INIT_SETTINGS_FILE
TEMPLATE = "config/data/image_prompt_generation_template.json"
BAD_YAML = "directories: [a, b"

# A legacy export script with the two placeholders the run replaces
FULL_EXPORT_SCRIPT = """# legacy
OUTPUT_FILE = "book"                            # Base name for the output files #TODO replace with your data
f.write("title: 'CHANGE TO YOUR TITLE'\\nauthor: 'YOUR NAME'\\ndate: '2025'\\nlang: 'en'\\n") #TODO replace with your data
"""


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


def _read_error(path: Path) -> str:
    """What the OSError raised by reading ``path`` says."""
    try:
        path.read_text(encoding="utf-8")
    except OSError as exc:
        return str(exc)
    raise AssertionError(f"{path} is readable")


def _yaml_error(text: str) -> str:
    """What the YAMLError raised by parsing ``text`` says."""
    try:
        yaml.safe_load(text)
    except yaml.YAMLError as exc:
        return str(exc)
    raise AssertionError("the text parses")


def _lines(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records]


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
# from the defaults, the level and a builder (from base_dir) of the exact
# line logged: it names the file and quotes the error it hit
LOAD_SETTINGS_CASES = [
    pytest.param(
        lambda base: None,
        lambda d: d,
        (
            "INFO",
            lambda base: "No config/init-settings.yaml found, using built-in defaults.",
        ),
        id="absent-file-uses-defaults",
    ),
    pytest.param(
        _settings_as_directory,
        lambda d: d,
        (
            "WARNING",
            lambda base: f"Could not read {base / SETTINGS} "
            f"({_read_error(base / SETTINGS)}), falling back to defaults.",
        ),
        id="unreadable-file-falls-back",
    ),
    pytest.param(
        lambda base: _write_settings(base, BAD_YAML),
        lambda d: d,
        (
            "ERROR",
            lambda base: f"Failed to parse {base / SETTINGS} "
            f"({_yaml_error(BAD_YAML)}), falling back to defaults.",
        ),
        id="invalid-yaml-falls-back",
    ),
    pytest.param(
        lambda base: _write_settings(base, "- a\n- b\n"),
        lambda d: d,
        (
            "ERROR",
            lambda base: f"{base / SETTINGS} does not contain a YAML mapping "
            "(got list), falling back to defaults.",
        ),
        id="list-instead-of-mapping-falls-back",
    ),
    pytest.param(
        lambda base: _write_settings(base, ""),
        lambda d: d,
        (
            "ERROR",
            lambda base: f"{base / SETTINGS} does not contain a YAML mapping "
            "(got NoneType), falling back to defaults.",
        ),
        id="empty-file-falls-back",
    ),
    pytest.param(
        lambda base: _write_settings(base, "exclude:\n  - README.md\n"),
        lambda d: {
            "directories": d["directories"],
            "files": [f for f in d["files"] if f != "README.md"],
            "exclude": ["README.md"],
        },
        ("INFO", lambda base: f"Loaded project structure from {base / SETTINGS}"),
        id="mapping-is-resolved",
    ),
]


@pytest.mark.parametrize("prepare, expected, logged", LOAD_SETTINGS_CASES)
def test_load_init_settings(tmp_path, caplog, prepare, expected, logged):
    caplog.set_level(logging.INFO, logger="manuscripta.init")
    prepare(tmp_path)

    assert mod.load_init_settings(tmp_path) == expected(_defaults())

    level, line = logged
    assert [
        r.levelname for r in caplog.records if r.getMessage() == line(tmp_path)
    ] == [level]


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
    pytest.param(
        {"files": "README.md"},
        lambda d: {**d, "files": []},
        [
            "WARNING:'files' should be a list, got str. Ignoring.",
            "Using custom files list (0 entries).",
        ],
        id="scalar-files-yields-empty-list",
    ),
    pytest.param(
        {"include_directories": "assets/audio"},
        lambda d: d,
        ["WARNING:'include_directories' should be a list, got str. Ignoring."],
        id="scalar-include-directories-ignored",
    ),
    pytest.param(
        {"include_files": 3},
        lambda d: d,
        ["WARNING:'include_files' should be a list, got int. Ignoring."],
        id="number-include-files-ignored",
    ),
    pytest.param(
        {"exclude": {"output": True}},
        lambda d: d,
        ["WARNING:'exclude' should be a list, got dict. Ignoring."],
        id="mapping-exclude-ignored",
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
# write_default_init_settings
# ---------------------------------------------------------------------------
def test_write_default_init_settings_creates_config_and_logs(tmp_path, caplog):
    """The defaults land in base_dir/config/init-settings.yaml, config/ (and
    whatever is missing above it) is created on the way, the write is logged
    and the returned path is the file written."""
    caplog.set_level(logging.INFO, logger="manuscripta.init")
    base = tmp_path / "new-project"

    path = mod.write_default_init_settings(base)

    assert path == base / SETTINGS
    assert yaml.safe_load(path.read_text(encoding="utf-8")) == {
        "directories": mod._DEFAULT_DIRECTORIES,
        "files": mod._DEFAULT_FILES,
    }
    assert _lines(caplog) == [f"Created default {path}"]


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
# (created, existed) stats fields it fills, the lines logged (one per entry)
CREATE_CASES = [
    pytest.param(
        mod.create_directories,
        ["a", "b/c"],
        [],
        ("dirs_created", "dirs_existed"),
        ["Created directory: a", "Created directory: b/c"],
        id="directories-all-new",
    ),
    pytest.param(
        mod.create_directories,
        ["a", "b/c"],
        ["a"],
        ("dirs_created", "dirs_existed"),
        ["Directory already exists: a", "Created directory: b/c"],
        id="directories-one-exists",
    ),
    pytest.param(
        mod.create_files,
        ["a.md", "b/c.md"],
        [],
        ("files_created", "files_existed"),
        ["Created file: a.md", "Created file: b/c.md"],
        id="files-all-new-with-parents",
    ),
    pytest.param(
        mod.create_files,
        ["a.md", "b/c/d.md"],
        [],
        ("files_created", "files_existed"),
        ["Created file: a.md", "Created file: b/c/d.md"],
        id="files-missing-parents-created-all-the-way-down",
    ),
    pytest.param(
        mod.create_files,
        ["a.md", "b/c.md"],
        ["b/c.md"],
        ("files_created", "files_existed"),
        ["Created file: a.md", "File already exists: b/c.md"],
        id="files-one-exists",
    ),
]


@pytest.mark.parametrize("creator, entries, existing, fields, logged", CREATE_CASES)
def test_create_entries(tmp_path, caplog, creator, entries, existing, fields, logged):
    caplog.set_level(logging.INFO, logger="manuscripta.init")
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
    assert _lines(caplog) == logged


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
        if kind == "missing":
            continue
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
# Each row: the items as (entry, kind) with kind "dir", "file" or "missing"
# (not on disk), the answer typed, the entries left on disk afterwards, the
# lines printed after the listing, the lines logged
CLEAN_DECISIONS = [
    pytest.param(
        [("d", "dir"), ("f.md", "file")],
        "y",
        [],
        ["  Deleted: d", "  Deleted: f.md"],
        ["Deleted directory: d", "Deleted file: f.md"],
        id="yes-deletes-both-kinds",
    ),
    pytest.param(
        [("d", "dir")],
        "  Y ",
        [],
        ["  Deleted: d"],
        ["Deleted directory: d"],
        id="answer-is-stripped-and-lowercased",
    ),
    pytest.param(
        [("d", "dir"), ("f.md", "file")],
        "n",
        ["d", "f.md"],
        ["Skipped. No items deleted."],
        [],
        id="no-keeps-everything",
    ),
    pytest.param(
        [("f.md", "file")],
        "",
        ["f.md"],
        ["Skipped. No items deleted."],
        [],
        id="enter-defaults-to-no",
    ),
    pytest.param(
        [("d", "dir"), ("gone", "missing"), ("f.md", "file")],
        "y",
        [],
        ["  Deleted: d", "  Deleted: f.md"],
        [
            "Excluded item not on disk: gone",
            "Deleted directory: d",
            "Deleted file: f.md",
        ],
        id="missing-item-reported-not-listed-not-deleted",
    ),
    pytest.param(
        [("gone.md", "missing"), ("d", "dir")],
        "n",
        ["d"],
        ["Skipped. No items deleted."],
        ["Excluded item not on disk: gone.md"],
        id="missing-item-reported-before-no",
    ),
]


@pytest.mark.parametrize("items, answer, left, printed, logged", CLEAN_DECISIONS)
def test_clean_excluded(
    tmp_path, capsys, caplog, answers, items, answer, left, printed, logged
):
    caplog.set_level(logging.INFO, logger="manuscripta.init")
    _place(tmp_path, items)
    queue, prompts = answers
    queue.append(answer)
    names = [entry for entry, _ in items]

    mod.clean_excluded(tmp_path, names)

    lines = capsys.readouterr().out.splitlines()
    missing = [
        f"  Missing (nothing to delete): {entry}"
        for entry, kind in items
        if kind == "missing"
    ]
    listing = ["The following excluded items still exist on disk:"] + [
        f"  - {entry} ({kind})" for entry, kind in items if kind != "missing"
    ]
    assert lines == [""] + missing + listing + printed
    assert prompts == ["\nDelete these items? [y/N]: "]
    assert [e for e in names if (tmp_path / e).exists()] == left
    assert _lines(caplog) == logged


def test_clean_excluded_with_nothing_asks_nothing(tmp_path, capsys, answers):
    mod.clean_excluded(tmp_path, [])
    assert capsys.readouterr().out == ""
    assert answers[1] == []


def test_clean_excluded_with_only_missing_items_asks_nothing(tmp_path, capsys, answers):
    mod.clean_excluded(tmp_path, ["gone", "sub/gone.md"])
    assert capsys.readouterr().out.splitlines() == [
        "",
        "  Missing (nothing to delete): gone",
        "  Missing (nothing to delete): sub/gone.md",
    ]
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
    assert [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR] == [
        "Failed to delete locked: device busy"
    ]
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
    assert _lines(caplog) == [logged]


# ---------------------------------------------------------------------------
# run_init_book_project
# ---------------------------------------------------------------------------
def _run(base: Path, clean: bool = False, **overrides):
    arguments = dict(
        project_name="book",
        project_description="About it",
        book_title="Title",
        author_name="Author",
        base_dir=base,
        clean=clean,
    )
    mod.run_init_book_project(**{**arguments, **overrides})


def _place_legacy_files(base: Path, script: str = FULL_EXPORT_SCRIPT) -> None:
    """A pyproject.toml and an export script for the run to update."""
    (base / "scripts").mkdir()
    (base / "scripts" / "full_export_book.py").write_text(script, encoding="utf-8")
    (base / "pyproject.toml").write_text(
        toml.dumps({"project": {"name": "old", "description": "old"}}),
        encoding="utf-8",
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


def test_run_init_keeps_an_existing_readme_and_template(tmp_path):
    """The generated README.md and image-prompt template are written once:
    a run never overwrites either when it is already on disk."""
    readme = tmp_path / "README.md"
    readme.write_text("mine\n", encoding="utf-8")
    template = tmp_path / TEMPLATE
    template.parent.mkdir(parents=True)
    template.write_text("{}", encoding="utf-8")

    _run(tmp_path)

    assert readme.read_text(encoding="utf-8") == "mine\n"
    assert template.read_text(encoding="utf-8") == "{}"


def test_run_init_writes_a_template_that_describes_the_scaffold(tmp_path):
    """The image-prompt template is pretty-printed JSON with its documented
    sections; its paths point into the directories the same run created,
    its two prompt-file and figures entries agree with each other ("Keep
    prompt-file mapping stable") and its cover is the one metadata.yaml
    names."""
    _run(tmp_path)

    text = (tmp_path / TEMPLATE).read_text(encoding="utf-8")
    template = json.loads(text)
    assert len(text.splitlines()) > 1
    assert set(template) == {
        "project_name",
        "description",
        "author",
        "language",
        "structure",
        "output_formats",
        "image_generation",
        "tasks",
        "notes",
    }
    structure, generation = template["structure"], template["image_generation"]
    assert set(structure) == {
        "source_format",
        "chapter_path",
        "assets_path",
        "cover_file",
        "image_prompt_file",
    }
    assert set(generation) == {"engine", "prompt_file", "target_path", "style"}
    assert template["tasks"]
    assert all(set(task) == {"name", "description"} for task in template["tasks"])
    assert (tmp_path / structure["chapter_path"]).is_dir()
    assert (tmp_path / structure["assets_path"]).is_dir()
    assert (tmp_path / structure["cover_file"]).parent.is_dir()
    assert (tmp_path / structure["image_prompt_file"]).parent.is_dir()
    assert generation["prompt_file"] == structure["image_prompt_file"]
    assert generation["target_path"] == structure["assets_path"]
    metadata = yaml.safe_load(
        (tmp_path / "config" / "metadata.yaml").read_text(encoding="utf-8")
    )
    assert structure["cover_file"] == metadata["cover_image"]


def test_run_init_carries_the_given_metadata_into_every_file_and_logs_it(
    tmp_path, caplog
):
    """Title, author, description, year and language reach metadata.yaml and
    the legacy export script; the legacy metadata_values.json goes away;
    each of these edits is logged."""
    caplog.set_level(logging.INFO, logger="manuscripta.init")
    _place_legacy_files(tmp_path)
    legacy = tmp_path / "config" / "metadata_values.json"
    legacy.parent.mkdir()
    legacy.write_text("{}", encoding="utf-8")

    _run(tmp_path, year="2031", lang="de")

    metadata = yaml.safe_load(
        (tmp_path / "config" / "metadata.yaml").read_text(encoding="utf-8")
    )
    assert {
        key: metadata[key]
        for key in ("title", "author", "description", "date", "language")
    } == {
        "title": "Title",
        "author": "Author",
        "description": "About it",
        "date": "2031",
        "language": "de",
    }
    script = (tmp_path / "scripts" / "full_export_book.py").read_text(encoding="utf-8")
    assert "title: 'Title'\\nauthor: 'Author'\\ndate: '2031'\\nlang: 'de'" in script
    assert "#TODO" not in script
    assert not legacy.exists()
    logged = _lines(caplog)
    for line in (
        "Removed legacy file: config/metadata_values.json",
        "Updated pyproject.toml with name='book'.",
        "Updated full_export_book.py with metadata.",
    ):
        assert line in logged


def test_run_init_reads_and_writes_utf8_under_c_locale(tmp_path, monkeypatch):
    """Every file the run reads or writes is UTF-8 whatever the locale: under
    LC_ALL=C the locale codec is ASCII and cannot carry the umlauts in the
    settings file, the export script, the title, the author and the
    description."""
    import locale

    saved = locale.setlocale(locale.LC_ALL)
    monkeypatch.setenv("LC_ALL", "C")
    monkeypatch.setenv("LANG", "C")
    locale.setlocale(locale.LC_ALL, "C")
    try:
        _write_settings(tmp_path, "include_files:\n  - Grüße.md\n")
        _place_legacy_files(tmp_path, "# Grüße\n" + FULL_EXPORT_SCRIPT)

        _run(tmp_path, project_description="Über Bären", book_title="Grüße")

        assert (tmp_path / "Grüße.md").exists()
        metadata = (tmp_path / "config" / "metadata.yaml").read_bytes().decode("utf-8")
        assert yaml.safe_load(metadata)["title"] == "Grüße"
        pyproject = (tmp_path / "pyproject.toml").read_bytes().decode("utf-8")
        assert toml.loads(pyproject)["project"]["description"] == "Über Bären"
        script = (tmp_path / "scripts" / "full_export_book.py").read_bytes()
        assert "title: 'Grüße'" in script.decode("utf-8")
    finally:
        locale.setlocale(locale.LC_ALL, saved)


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


def _help_output(monkeypatch, capsys) -> str:
    """The --help page, rendered wide enough that no entry wraps."""
    monkeypatch.setenv("COLUMNS", "200")
    monkeypatch.setattr(sys, "argv", ["init-bp", "--help"])
    with pytest.raises(SystemExit) as exc:
        mod.main()
    assert exc.value.code == 0
    return capsys.readouterr().out


def test_help_has_a_description_paragraph_and_help_text_for_clean(
    monkeypatch, answers, capsys
):
    """Presence, not wording (TESTING.md §14.8.1): --help carries a
    description paragraph between the usage block and the options, and the
    --clean entry carries help text."""
    out = _help_output(monkeypatch, capsys)

    usage, _, rest = out.partition("\n\n")
    assert usage.startswith("usage:")
    description, _, options = rest.partition("\n\n")
    assert description.strip() and not description.startswith("options:")
    assert re.search(r"^\s*--clean\s{2,}\S", options, re.MULTILINE)
    assert answers[1] == []


def test_main_shows_every_action_to_the_operator_tagged_with_its_level(
    tmp_path, monkeypatch, answers, capsys
):
    """The CLI configures INFO-level logging to stderr, so the actions the
    module docstring promises to log reach the operator, each line tagged
    with its level. basicConfig is a no-op while pytest's own handlers sit
    on the root logger, hence the cleared handler list."""
    root = logging.getLogger()
    saved_level = root.level
    monkeypatch.setattr(root, "handlers", [])
    monkeypatch.setattr(mod, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["init-bp"])
    answers[0].extend(["my-book", "About it", "Title", "Author", "", ""])

    try:
        mod.main()
    finally:
        root.setLevel(saved_level)

    err = capsys.readouterr().err.splitlines()
    assert any(re.fullmatch(r"INFO\b.*Created directory: config", line) for line in err)
    assert (tmp_path / "config" / "metadata.yaml").exists()
