# tests/test_full_export_book_pipeline.py
"""
Tests for the full export pipeline order, skip-images flag, and language resolution.
Adapted from the original script-copying approach to use the installed library directly.
"""
import sys
from pathlib import Path
import pytest

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


def test_pipeline_runs_convert_scripts_in_correct_order(
    wired_module, temp_project, monkeypatch, capsys
):
    feb = wired_module
    calls = []

    def fake_run_script(module_path, arg=None):
        calls.append((module_path.split(".")[-1], arg))

    compile_calls = []

    def fake_compile_book(*args, **kwargs):
        compile_calls.append((args, kwargs))

    monkeypatch.setattr(feb, "run_script", fake_run_script)
    monkeypatch.setattr(feb, "compile_book", fake_compile_book)

    argv = [sys.argv[0], "--format", "markdown", "--extension", "md"]
    monkeypatch.setattr(sys, "argv", argv)

    feb.main()

    assert compile_calls, "compile_book() was not called"
    expected = [
        ("to_absolute", None),
        ("img_tags", "--to-absolute"),
        ("to_relative", None),
        ("img_tags", "--to-relative"),
    ]
    filtered = [c for c in calls if c[0] in ("to_absolute", "to_relative", "img_tags")]
    assert (
        filtered == expected
    ), f"Call order mismatch.\nExpected: {expected}\nGot:      {filtered}"


def test_skip_images_flag_skips_pre_and_post(wired_module, temp_project, monkeypatch):
    feb = wired_module
    calls = []

    def fake_run_script(module_path, arg=None):
        calls.append((module_path.split(".")[-1], arg))

    monkeypatch.setattr(feb, "run_script", fake_run_script)
    monkeypatch.setattr(feb, "compile_book", lambda *a, **k: None)

    argv = [sys.argv[0], "--format", "markdown", "--extension", "md", "--skip-images"]
    monkeypatch.setattr(sys, "argv", argv)

    feb.main()

    assert not calls, "convert scripts should not run when --skip-images is set"


def test_language_resolution_cli_overrides_metadata(
    wired_module, temp_project, monkeypatch
):
    feb = wired_module
    seen = {}

    def capture_compile(*args, **kwargs):
        seen["lang"] = args[5] if len(args) > 5 else kwargs.get("lang")

    monkeypatch.setattr(feb, "compile_book", capture_compile)
    monkeypatch.setattr(feb, "run_script", lambda *a, **k: None)

    argv = [sys.argv[0], "--format", "markdown", "--extension", "md", "--lang", "en"]
    monkeypatch.setattr(sys, "argv", argv)

    feb.main()
    assert seen.get("lang") == "en", "CLI --lang should override metadata.yaml language"


def test_language_resolution_uses_metadata_when_cli_missing(
    wired_module, temp_project, monkeypatch
):
    feb = wired_module
    seen = {}

    def capture_compile(*args, **kwargs):
        seen["lang"] = args[5] if len(args) > 5 else kwargs.get("lang")

    monkeypatch.setattr(feb, "compile_book", capture_compile)
    monkeypatch.setattr(feb, "run_script", lambda *a, **k: None)

    argv = [sys.argv[0], "--format", "markdown", "--extension", "md"]
    monkeypatch.setattr(sys, "argv", argv)

    feb.main()
    assert (
        seen.get("lang") == "de"
    ), "Should use language from metadata.yaml when CLI --lang not provided"


def test_run_script_bubbles_up_subprocess_errors(wired_module, monkeypatch):
    feb = wired_module
    import subprocess as _sub

    def fake_run(*args, **kwargs):
        raise _sub.CalledProcessError(returncode=1, cmd="python3 -m some.module")

    monkeypatch.setattr(_sub, "run", fake_run)

    with pytest.raises(Exception):
        feb.run_script("manuscripta.paths.to_absolute")
