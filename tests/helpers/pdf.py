"""PDF assertion helpers wrapping ``pdfimages`` and ``pdftotext``.

Each helper skips (does not fail) when the underlying binary is absent,
with a named-tool reason. That pattern is required by the project's test
conventions — see ``docs/TESTING.md`` §6.5.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


def pdfimages_count(pdf_path: Path) -> int:
    """Return the number of embedded image streams in ``pdf_path``."""
    if shutil.which("pdfimages") is None:
        pytest.skip("pdfimages binary not on PATH")
    result = subprocess.run(
        ["pdfimages", "-list", str(pdf_path)],
        capture_output=True,
        text=True,
        check=True,
    )
    rows = [ln for ln in result.stdout.splitlines() if ln.strip()]
    if len(rows) < 2:
        return 0
    return max(0, len(rows) - 2)


def assert_pdf_has_images(pdf_path: Path, expected_count: int) -> None:
    """Assert ``pdf_path`` contains exactly ``expected_count`` image streams."""
    if not pdf_path.exists():
        raise AssertionError(f"PDF does not exist: {pdf_path}")
    actual = pdfimages_count(pdf_path)
    assert actual == expected_count, (
        f"Expected {expected_count} embedded image(s) in {pdf_path}, "
        f"got {actual}.\nRun: pdfimages -list {pdf_path}"
    )


def assert_pdf_contains_text(pdf_path: Path, text: str) -> None:
    """Assert that ``text`` appears in the PDF's extracted text."""
    if shutil.which("pdftotext") is None:
        pytest.skip("pdftotext binary not on PATH")
    if not pdf_path.exists():
        raise AssertionError(f"PDF does not exist: {pdf_path}")
    result = subprocess.run(
        ["pdftotext", "-layout", str(pdf_path), "-"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert text in result.stdout, (
        f"Expected substring {text!r} in PDF text. First 500 chars:\n"
        f"{result.stdout[:500]}"
    )


def pdf_text(pdf_path: Path) -> str:
    """Return the full extracted text of ``pdf_path``."""
    if shutil.which("pdftotext") is None:
        pytest.skip("pdftotext binary not on PATH")
    result = subprocess.run(
        ["pdftotext", "-layout", str(pdf_path), "-"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout
