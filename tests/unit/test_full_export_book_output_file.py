import pytest

pytestmark = pytest.mark.unit

import sys
import io
import subprocess
from manuscripta.export import book as full_export_book


def run_main_with_args(
    monkeypatch,
    args,
    tmp_path,
    pyproject_content=None,
    preset_output=None,
    stub_project_name=None,
):
    """
    Helper to run full_export_book.main() with controlled environment.
    - monkeypatch: pytest fixture
    - args: CLI args to simulate
    - tmp_path: temporary directory
    - pyproject_content: optional TOML content to write
    - preset_output: optional pre-set OUTPUT_FILE
    - stub_project_name: if set, bypasses real pyproject parsing
    """

    # Fake pyproject.toml if content provided
    if pyproject_content:
        (tmp_path / "pyproject.toml").write_text(pyproject_content, encoding="utf-8")
    # Satisfy v0.8.0 source_dir layout contract (cwd-based CLI default).
    (tmp_path / "manuscript").mkdir(exist_ok=True)
    (tmp_path / "config").mkdir(exist_ok=True)
    (tmp_path / "assets").mkdir(exist_ok=True)
    monkeypatch.chdir(tmp_path)

    # Reset OUTPUT_FILE
    full_export_book.OUTPUT_FILE = preset_output

    # Stub external calls so we don’t run real scripts
    monkeypatch.setattr(
        full_export_book,
        "run_script",
        lambda *a, **k: print(f"MOCK run_script {a} {k}"),
    )

    class _CP:
        returncode = 0

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _CP())

    # Stub project name resolution if desired
    if stub_project_name is not None:
        monkeypatch.setattr(
            full_export_book,
            "get_project_name_from_pyproject",
            lambda *a, **k: stub_project_name,
        )

    # Capture stdout
    old_stdout = sys.stdout
    sys.stdout = io.StringIO()
    base_args = ["--skip-images"]  # avoid preprocessing noise
    monkeypatch.setattr(sys, "argv", ["full_export_book.py"] + base_args + args)

    try:
        full_export_book.main()
        return sys.stdout.getvalue()
    finally:
        sys.stdout = old_stdout


# Each row: the arguments after --skip-images, a preset OUTPUT_FILE, the
# stubbed project name and the output name main() prints
OUTPUT_FILE_CASES = [
    pytest.param(
        ["--output-file", "custom"], None, "ignored", "custom_ebook", id="explicit"
    ),
    # Here we bypass TOML parsing and directly control return value
    pytest.param([], None, "demo-book", "demo-book_ebook", id="from-pyproject"),
    pytest.param([], "presetname", "ignored", "presetname_ebook", id="preset"),
    pytest.param(
        ["--book-type", "paperback"],
        None,
        "demo-book",
        "demo-book_paperback",
        id="book-type",
    ),
    pytest.param(
        ["--book-type", "hardcover"],
        None,
        "demo-book",
        "demo-book_hardcover",
        id="book-type-hardcover",
    ),
    # Simulate parsing error fallback
    pytest.param([], None, "book", "book_ebook", id="broken-pyproject"),
]


@pytest.mark.parametrize(
    "args, preset_output, stub_project_name, expected", OUTPUT_FILE_CASES
)
def test_output_file(
    args, preset_output, stub_project_name, expected, monkeypatch, tmp_path
):
    out = run_main_with_args(
        monkeypatch,
        args,
        tmp_path,
        preset_output=preset_output,
        stub_project_name=stub_project_name,
    )
    assert expected in out
