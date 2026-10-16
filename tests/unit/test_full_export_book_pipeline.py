# tests/test_full_export_book_pipeline.py
"""
Tests for the full export pipeline order, skip-images flag, and language resolution.
Adapted from the original script-copying approach to use the installed library directly.
"""
import sys
from pathlib import Path
import pytest

pytestmark = pytest.mark.unit

import manuscripta.export.book as feb


@pytest.fixture()
def temp_project(tmp_path: Path):
    """Create a self-contained project layout."""
    project = tmp_path
    (project / "manuscript" / "chapters").mkdir(parents=True)
    (project / "manuscript" / "front-matter").mkdir(parents=True)
    (project / "manuscript" / "back-matter").mkdir(parents=True)
    (project / "assets" / "img").mkdir(parents=True)
    (project / "config").mkdir(parents=True)
    (project / "output").mkdir(parents=True)

    (project / "pyproject.toml").write_text(
        '[tool.poetry]\nname = "write-book-template"\n', encoding="utf-8"
    )
    (project / "config" / "metadata.yaml").write_text(
        "title: T\nlanguage: de\n", encoding="utf-8"
    )
    (project / "manuscript" / "chapters" / "01.md").write_text(
        "# Ch1\n\n![c](assets_image.png)\n", encoding="utf-8"
    )
    (project / "assets" / "img" / "cover.png").write_text("png", encoding="utf-8")

    return project


@pytest.fixture()
def wired_module(temp_project: Path, monkeypatch):
    """Patch feb module-level paths to point at the temp project."""
    monkeypatch.chdir(temp_project)
    monkeypatch.setattr(feb, "BOOK_DIR", "./manuscript")
    monkeypatch.setattr(feb, "OUTPUT_DIR", "./output")
    monkeypatch.setattr(feb, "BACKUP_DIR", "./output_backup")
    monkeypatch.setattr(feb, "LOG_FILE", "export.log")
    monkeypatch.setattr(feb, "METADATA_FILE", Path("config") / "metadata.yaml")
    monkeypatch.setattr(
        feb, "EXPORT_SETTINGS_FILE", Path("config") / "export-settings.yaml"
    )
    monkeypatch.setattr(feb, "TOC_FILE", Path("manuscript") / "front-matter" / "toc.md")
    return feb


# Each row: the arguments after "--format markdown --extension md" and the
# convert scripts main() runs, in order, as (module, argument)
CONVERT_SCRIPT_CASES = [
    pytest.param(
        [],
        [
            ("to_absolute", None),
            ("img_tags", "--to-absolute"),
            ("to_relative", None),
            ("img_tags", "--to-relative"),
        ],
        id="runs-convert-scripts-in-correct-order",
    ),
    pytest.param(["--skip-images"], [], id="skip-images-flag-skips-pre-and-post"),
]


@pytest.mark.parametrize("extra, expected", CONVERT_SCRIPT_CASES)
def test_pipeline_convert_scripts(
    extra, expected, wired_module, temp_project, monkeypatch
):
    feb = wired_module
    calls = []

    def fake_run_script(module_path, arg=None, **kwargs):
        calls.append((module_path.split(".")[-1], arg))

    compile_calls = []

    def fake_compile_book(*args, **kwargs):
        compile_calls.append((args, kwargs))

    monkeypatch.setattr(feb, "run_script", fake_run_script)
    monkeypatch.setattr(feb, "compile_book", fake_compile_book)

    argv = [sys.argv[0], "--format", "markdown", "--extension", "md", *extra]
    monkeypatch.setattr(sys, "argv", argv)

    feb.main()

    assert compile_calls, "compile_book() was not called"
    assert calls == expected


# Each row: the arguments after "--format markdown --extension md" and the
# language compile_book receives (metadata.yaml says "de")
LANGUAGE_CASES = [
    pytest.param(["--lang", "en"], "en", id="cli-overrides-metadata"),
    pytest.param([], "de", id="uses-metadata-when-cli-missing"),
]


@pytest.mark.parametrize("extra, lang", LANGUAGE_CASES)
def test_language_resolution(extra, lang, wired_module, temp_project, monkeypatch):
    feb = wired_module
    seen = {}

    def capture_compile(*args, **kwargs):
        seen["lang"] = args[5] if len(args) > 5 else kwargs.get("lang")

    monkeypatch.setattr(feb, "compile_book", capture_compile)
    monkeypatch.setattr(feb, "run_script", lambda *a, **k: None)

    argv = [sys.argv[0], "--format", "markdown", "--extension", "md", *extra]
    monkeypatch.setattr(sys, "argv", argv)

    feb.main()
    assert seen.get("lang") == lang


def test_run_script_bubbles_up_subprocess_errors(wired_module, monkeypatch):
    feb = wired_module
    import subprocess as _sub

    def fake_run(*args, **kwargs):
        raise _sub.CalledProcessError(returncode=1, cmd="python3 -m some.module")

    monkeypatch.setattr(_sub, "run", fake_run)

    with pytest.raises(Exception):
        feb.run_script("manuscripta.paths.to_absolute")
