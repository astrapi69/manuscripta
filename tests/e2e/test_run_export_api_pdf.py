"""Full-PDF e2e check split out of test_run_export_api.py.

The rest of the public-API tests live under tests/unit/, where they can
run without pandoc / xelatex. This single test requires the full
toolchain and asserts that an image reference in the fixture markdown
ends up embedded in the produced PDF when run_export is invoked from a
cwd outside the project.
"""

from __future__ import annotations

import shutil
import struct
import subprocess
import zlib
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e

from manuscripta.export import book as book_mod


def _write_png(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    raw = b"\x00\xff\x00\x00"
    idat = chunk(b"IDAT", zlib.compress(raw))
    iend = chunk(b"IEND", b"")
    path.write_bytes(sig + ihdr + idat + iend)


def _make_consumer_project(root: Path, image_ref: str = "images/pic.png") -> Path:
    (root / "manuscript" / "chapters").mkdir(parents=True)
    (root / "config").mkdir()
    (root / "assets" / "images").mkdir(parents=True)
    (root / "config" / "metadata.yaml").write_text(
        'title: "Fixture Book"\nauthor: "Tester"\nlang: "en"\n', encoding="utf-8"
    )
    (root / "manuscript" / "chapters" / "ch01.md").write_text(
        f"# Chapter One\n\nHello world.\n\n![pic]({image_ref})\n", encoding="utf-8"
    )
    _write_png(root / "assets" / image_ref)
    return root


def _has(tool: str) -> bool:
    return shutil.which(tool) is not None


@pytest.mark.requires_pandoc
@pytest.mark.requires_latex
@pytest.mark.skipif(not _has("pdfimages"), reason="pdfimages binary not on PATH")
def test_image_is_embedded_in_pdf_when_called_from_outside_repo(tmp_path, monkeypatch):
    project = tmp_path / "book"
    _make_consumer_project(project)
    monkeypatch.chdir(tmp_path)  # invoke from OUTSIDE the project

    book_mod.run_export(
        project,
        formats="pdf",
        strict_images=True,
        skip_images=True,
    )

    pdf = project / "output" / "book_ebook.pdf"
    if not pdf.exists():
        candidates = list((project / "output").glob("*.pdf"))
        assert candidates, "No PDF produced"
        pdf = candidates[0]

    result = subprocess.run(
        ["pdfimages", "-list", str(pdf)],
        capture_output=True,
        text=True,
        check=True,
    )
    lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
    assert len(lines) >= 3, f"pdfimages -list did not show an embedded image:\n{result.stdout}"
