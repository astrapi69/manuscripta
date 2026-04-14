# tests/conftest.py
"""Shared fixtures and helpers for the PDF-generation test suite.

Markers:
    requires_pandoc:  pandoc binary must be present on PATH
    requires_latex:   xelatex binary must be present on PATH
    slow:             expensive test (visual diff or 50-chapter scale)
"""

from __future__ import annotations

import shutil
import struct
import subprocess
import zlib
from pathlib import Path

import pytest


# --------------------------------------------------------------------------
# Markers
# --------------------------------------------------------------------------


_LAYER_MARKERS = {"unit", "integration", "e2e", "e2e_wheel"}


def pytest_configure(config):
    config.addinivalue_line("markers", "unit: Layer-1 unit test (pure logic, no I/O)")
    config.addinivalue_line(
        "markers", "integration: Layer-2 integration test (real Pandoc, no LaTeX)"
    )
    config.addinivalue_line("markers", "e2e: Layer-3 end-to-end (Pandoc + LaTeX)")
    config.addinivalue_line(
        "markers", "e2e_wheel: Layer-4 wheel-install e2e (excluded from default run)"
    )
    config.addinivalue_line(
        "markers", "requires_pandoc: requires pandoc binary on PATH"
    )
    config.addinivalue_line(
        "markers", "requires_latex: requires xelatex binary on PATH"
    )
    config.addinivalue_line("markers", "slow: slow test (visual diff or scale)")


def _has(binary: str) -> bool:
    return shutil.which(binary) is not None


def pytest_collection_modifyitems(config, items):
    skip_pandoc = pytest.mark.skip(reason="pandoc binary not on PATH")
    skip_latex = pytest.mark.skip(reason="xelatex binary not on PATH")
    pandoc_ok = _has("pandoc")
    latex_ok = _has("xelatex")

    offenders = []
    for item in items:
        if "requires_pandoc" in item.keywords and not pandoc_ok:
            item.add_marker(skip_pandoc)
        if "requires_latex" in item.keywords and not latex_ok:
            item.add_marker(skip_latex)

        layers = _LAYER_MARKERS & {m.name for m in item.iter_markers()}
        if len(layers) != 1:
            offenders.append((item.nodeid, sorted(layers)))

    if offenders:
        msg = [
            "Every test must carry exactly one layer marker "
            f"({sorted(_LAYER_MARKERS)}). Offenders:"
        ]
        for nodeid, layers in offenders:
            msg.append(f"  {nodeid}: markers={layers}")
        raise pytest.UsageError("\n".join(msg))


# --------------------------------------------------------------------------
# PNG generator (avoids a Pillow dependency for tests)
# --------------------------------------------------------------------------


def _png_bytes(width: int = 8, height: int = 8, rgb: tuple[int, int, int] = (255, 0, 0)) -> bytes:
    """Return bytes of a tiny solid-color PNG."""
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    row = b"\x00" + bytes(rgb) * width
    raw = row * height
    idat = chunk(b"IDAT", zlib.compress(raw))
    iend = chunk(b"IEND", b"")
    return sig + ihdr + idat + iend


def write_png(path: Path, **kwargs) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_png_bytes(**kwargs))


# --------------------------------------------------------------------------
# Layout builder
# --------------------------------------------------------------------------


def _scaffold(root: Path, *, title: str = "Test Book", lang: str = "en") -> None:
    (root / "manuscript" / "chapters").mkdir(parents=True, exist_ok=True)
    (root / "manuscript" / "front-matter").mkdir(parents=True, exist_ok=True)
    (root / "manuscript" / "back-matter").mkdir(parents=True, exist_ok=True)
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "assets").mkdir(parents=True, exist_ok=True)
    (root / "config" / "metadata.yaml").write_text(
        f'title: "{title}"\nauthor: "Tester"\nlang: "{lang}"\n', encoding="utf-8"
    )


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


@pytest.fixture
def minimal_book_fixture(tmp_path: Path) -> Path:
    """Single chapter, single image."""
    _scaffold(tmp_path, title="Minimal Book")
    write_png(tmp_path / "assets" / "sample.png")
    (tmp_path / "manuscript" / "chapters" / "chapter1.md").write_text(
        "# Chapter One\n\nIntro paragraph.\n\n![sample](sample.png)\n",
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture
def multi_chapter_fixture(tmp_path: Path) -> Path:
    """Three chapters, one image each, image filenames distinct."""
    _scaffold(tmp_path, title="Multi-chapter Book")
    for i in range(1, 4):
        write_png(
            tmp_path / "assets" / f"figure{i}.png",
            rgb=(50 * i, 80, 200 - 50 * i),
        )
        (tmp_path / "manuscript" / "chapters" / f"chapter{i}.md").write_text(
            f"# Chapter {i}\n\nText for chapter {i}.\n\n![fig{i}](figure{i}.png)\n",
            encoding="utf-8",
        )
    return tmp_path


@pytest.fixture
def broken_image_fixture(tmp_path: Path) -> Path:
    """Markdown references an image that does not exist."""
    _scaffold(tmp_path, title="Broken Book")
    (tmp_path / "manuscript" / "chapters" / "chapter1.md").write_text(
        "# Chapter\n\nWords.\n\n![ghost](missing.png)\n",
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture
def mixed_image_fixture(tmp_path: Path) -> Path:
    """One present image, one missing image, in a single chapter."""
    _scaffold(tmp_path, title="Mixed Book")
    write_png(tmp_path / "assets" / "present.png")
    (tmp_path / "manuscript" / "chapters" / "chapter1.md").write_text(
        "# Chapter\n\n![ok](present.png)\n\n![bad](absent.png)\n",
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture
def nested_assets_fixture(tmp_path: Path) -> Path:
    """Images live under per-chapter subdirectories of assets/."""
    _scaffold(tmp_path, title="Nested Book")
    write_png(tmp_path / "assets" / "chapter1" / "figure1.png", rgb=(10, 200, 10))
    write_png(tmp_path / "assets" / "chapter2" / "figure2.png", rgb=(10, 10, 200))
    (tmp_path / "manuscript" / "chapters" / "chapter1.md").write_text(
        "# Ch1\n\n![](chapter1/figure1.png)\n", encoding="utf-8"
    )
    (tmp_path / "manuscript" / "chapters" / "chapter2.md").write_text(
        "# Ch2\n\n![](chapter2/figure2.png)\n", encoding="utf-8"
    )
    return tmp_path


@pytest.fixture
def absolute_path_fixture(tmp_path: Path) -> Path:
    """Markdown references an image via absolute path outside the project."""
    _scaffold(tmp_path, title="Absolute Path Book")
    external_dir = tmp_path / "external"
    external_dir.mkdir()
    image = external_dir / "external.png"
    write_png(image, rgb=(120, 200, 50))
    (tmp_path / "manuscript" / "chapters" / "chapter1.md").write_text(
        f"# Chapter\n\nWords.\n\n![ext]({image.resolve()})\n",
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture
def unicode_fixture(tmp_path: Path) -> Path:
    """Non-ASCII filenames and content (Greek, German, French)."""
    _scaffold(tmp_path, title="Λόγος und Élan", lang="de")
    img = tmp_path / "assets" / "Bücher.png"
    write_png(img, rgb=(40, 40, 220))
    md = tmp_path / "manuscript" / "chapters" / "Kapitel-α.md"
    md.write_text(
        "# Καλημέρα — Élan\n\n"
        "Über die Bedeutung der Bücher mit Λόγος und café au lait.\n\n"
        "![das Bild](Bücher.png)\n",
        encoding="utf-8",
    )
    return tmp_path


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _pdfimages_count(pdf_path: Path) -> int:
    """Return the number of embedded image streams in ``pdf_path``."""
    if shutil.which("pdfimages") is None:
        pytest.skip("pdfimages binary not on PATH")
    result = subprocess.run(
        ["pdfimages", "-list", str(pdf_path)],
        capture_output=True,
        text=True,
        check=True,
    )
    # Header is two lines (column titles + dashes), then one line per image.
    rows = [ln for ln in result.stdout.splitlines() if ln.strip()]
    if len(rows) < 2:
        return 0
    return max(0, len(rows) - 2)


def assert_pdf_has_images(pdf_path: Path, expected_count: int) -> None:
    """Assert ``pdf_path`` contains exactly ``expected_count`` image streams."""
    if not pdf_path.exists():
        raise AssertionError(f"PDF does not exist: {pdf_path}")
    actual = _pdfimages_count(pdf_path)
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


# Re-export helpers as fixtures so tests can declare them in their signatures
# (they're called directly in most cases — both styles are convenient).


@pytest.fixture
def assert_pdf_images():
    return assert_pdf_has_images


@pytest.fixture
def assert_pdf_text():
    return assert_pdf_contains_text


@pytest.fixture
def get_pdf_text():
    return pdf_text
