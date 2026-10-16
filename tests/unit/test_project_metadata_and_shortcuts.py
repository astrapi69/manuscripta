"""Unit tests for manuscripta.project.metadata and
manuscripta.project.shortcuts_init.

metadata.main() fills the {{PLACEHOLDER}} slots of config/metadata.yaml
from config/metadata_values.json (or built-in defaults) relative to the
working directory, then deletes the JSON. shortcuts_init dispatches two
interactive entry points by name; both are replaced by recorders here.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

import json
import sys

import manuscripta.project.metadata as metadata
import manuscripta.project.shortcuts_init as shortcuts

DEFAULT_FORMATS = "\n  - pdf\n  - epub\n  - mobi\n  - docx"


# ---------------------------------------------------------------------------
# metadata.main
# ---------------------------------------------------------------------------
# Each row: the metadata_values.json text (None: no file), the metadata.yaml
# template (None: no file), the metadata.yaml text afterwards (None: still
# no file), the lines printed, whether metadata_values.json is left behind
METADATA_CASES = [
    pytest.param(
        json.dumps(
            {
                "BOOK_TITLE": "Mind",
                "KEYWORDS": ["one", "two"],
                "KDP_ENABLED": True,
            }
        ),
        "title: {{BOOK_TITLE}}\nkeywords:{{KEYWORDS}}\nkdp: {{KDP_ENABLED}}\n",
        "title: Mind\nkeywords:\n  - one\n  - two\nkdp: true\n",
        [
            "✅ metadata.yaml has been updated with values from metadata_values.json.",
            "🗑️ metadata_values.json has been deleted.",
        ],
        False,
        id="json-values-fill-and-json-deleted",
    ),
    pytest.param(
        json.dumps({"KEYWORDS": "alpha, beta ,gamma"}),
        "keywords:{{KEYWORDS}}\n",
        "keywords:\n  - alpha\n  - beta\n  - gamma\n",
        [
            "✅ metadata.yaml has been updated with values from metadata_values.json.",
            "🗑️ metadata_values.json has been deleted.",
        ],
        False,
        id="comma-keywords-split-and-stripped",
    ),
    pytest.param(
        None,
        "title: {{BOOK_TITLE}}\nformats:{{OUTPUT_FORMATS}}\nkdp: {{KDP_ENABLED}}\n"
        "cover: '{{COVER_IMAGE}}'\nother: {{NOT_A_KEY}}\n",
        "title: Enter the title of your book\n"
        f"formats:{DEFAULT_FORMATS}\nkdp: false\ncover: ''\nother: {{{{NOT_A_KEY}}}}\n",
        ["✅ metadata.yaml has been updated with values from metadata_values.json."],
        False,
        id="no-json-uses-defaults-and-keeps-unknown-placeholders",
    ),
    pytest.param(
        json.dumps({"BOOK_TITLE": "Mind"}),
        None,
        None,
        [
            "❌ An error occurred: [Errno 2] No such file or directory: 'config/metadata.yaml'"
        ],
        True,
        id="missing-yaml-reported-and-json-kept",
    ),
    pytest.param(
        "{ not json",
        "title: {{BOOK_TITLE}}\n",
        "title: {{BOOK_TITLE}}\n",
        [
            "❌ An error occurred: Expecting property name enclosed in double quotes: line 1 column 3 (char 2)"
        ],
        True,
        id="invalid-json-reported-and-yaml-untouched",
    ),
]


@pytest.mark.parametrize(
    "json_text, template, result, printed, json_left", METADATA_CASES
)
def test_metadata_main(
    tmp_path, monkeypatch, capsys, json_text, template, result, printed, json_left
):
    monkeypatch.chdir(tmp_path)
    config = tmp_path / "config"
    config.mkdir()
    json_path = config / "metadata_values.json"
    yaml_path = config / "metadata.yaml"
    if json_text is not None:
        json_path.write_text(json_text, encoding="utf-8")
    if template is not None:
        yaml_path.write_text(template, encoding="utf-8")

    metadata.main()

    assert capsys.readouterr().out.splitlines() == printed
    assert (yaml_path.read_text(encoding="utf-8") if yaml_path.exists() else None) == (
        result
    )
    assert json_path.exists() is json_left


# ---------------------------------------------------------------------------
# shortcuts_init
# ---------------------------------------------------------------------------
@pytest.fixture
def capture_targets(monkeypatch):
    """Replace both entry points; return the names called in order."""
    called: list[str] = []
    monkeypatch.setattr(
        shortcuts, "init_book_project_main", lambda: called.append("init")
    )
    monkeypatch.setattr(
        shortcuts, "update_metadata_values_main", lambda: called.append("metadata")
    )
    return called


# Each row: the shortcut name, its wrapper, the entry point it reaches
SHORTCUTS = [
    pytest.param(
        "run_init_book_project",
        shortcuts.run_init_book_project,
        "init",
        id="run_init_book_project",
    ),
    pytest.param(
        "run_update_metadata_values",
        shortcuts.run_update_metadata_values,
        "metadata",
        id="run_update_metadata_values",
    ),
]


@pytest.mark.parametrize("name, wrapper, target", SHORTCUTS)
def test_wrapper_reaches_its_entry_point(capture_targets, name, wrapper, target):
    assert shortcuts.available_shortcuts[name] is wrapper
    wrapper()
    assert capture_targets == [target]


@pytest.mark.parametrize("name, wrapper, target", SHORTCUTS)
def test_main_dispatches_by_name(monkeypatch, capture_targets, name, wrapper, target):
    monkeypatch.setattr(sys, "argv", ["shortcuts", name])
    shortcuts.main()
    assert capture_targets == [target]


def test_main_without_task_prints_help_and_runs_nothing(
    monkeypatch, capture_targets, capsys
):
    monkeypatch.setattr(sys, "argv", ["shortcuts"])

    shortcuts.main()

    out = capsys.readouterr().out
    assert out.startswith(
        "usage: shortcuts [-h] [{run_init_book_project,run_update_metadata_values}]"
    )
    assert (
        "Available shortcuts:\n"
        "                          run_init_book_project\n"
        "                          run_update_metadata_values\n"
    ) in out
    assert out.endswith(
        "Run a shortcut like: poetry run shortcuts run_init_book_project\n"
    )
    assert capture_targets == []


# Each row: the argv after the program name, the exit code, the stream the
# message goes to and a fragment of it
EXITS = [
    pytest.param(["--help"], 0, "out", "📚 Book Project Shortcut Runner", id="help"),
    pytest.param(["bogus"], 2, "err", "invalid choice: 'bogus'", id="unknown-shortcut"),
]


@pytest.mark.parametrize("argv, code, stream, fragment", EXITS)
def test_main_exits(monkeypatch, capture_targets, capsys, argv, code, stream, fragment):
    monkeypatch.setattr(sys, "argv", ["shortcuts", *argv])

    with pytest.raises(SystemExit) as exc:
        shortcuts.main()

    assert exc.value.code == code
    assert fragment in getattr(capsys.readouterr(), stream)
    assert capture_targets == []
