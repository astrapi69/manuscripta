# tests/conftest.py
"""Shared pytest configuration for the manuscripta test suite.

Responsibilities:
  * Register the layer markers (``unit``, ``integration``, ``e2e``,
    ``e2e_wheel``) and the external-tool markers (``requires_pandoc``,
    ``requires_latex``, ``slow``).
  * Auto-skip tests whose external-tool requirement is not met.
  * **Enforce** that every collected test carries exactly one layer
    marker. See ``docs/TESTING.md`` §13.

Helpers and assertion utilities live under ``tests/helpers/``; they are
re-exported here so long-standing ``from conftest import ...`` imports
in existing test files keep working.
"""

from __future__ import annotations

import shutil

import pytest

from helpers.pdf import (  # noqa: F401  (re-export)
    assert_pdf_contains_text,
    assert_pdf_has_images,
    pdf_text,
    pdfimages_count as _pdfimages_count,
)
from helpers.png import write_png  # noqa: F401  (re-export)
from helpers.project import scaffold as _scaffold


# --------------------------------------------------------------------------
# Markers + auto-skip + layer enforcement
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
# Fixtures (thin wrappers around helpers/)
# --------------------------------------------------------------------------


@pytest.fixture
def minimal_book_fixture(tmp_path):
    """Single chapter, single image."""
    _scaffold(tmp_path, title="Minimal Book")
    write_png(tmp_path / "assets" / "sample.png")
    (tmp_path / "manuscript" / "chapters" / "chapter1.md").write_text(
        "# Chapter One\n\nIntro paragraph.\n\n![sample](sample.png)\n",
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture
def multi_chapter_fixture(tmp_path):
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
def broken_image_fixture(tmp_path):
    """Markdown references an image that does not exist."""
    _scaffold(tmp_path, title="Broken Book")
    (tmp_path / "manuscript" / "chapters" / "chapter1.md").write_text(
        "# Chapter\n\nWords.\n\n![ghost](missing.png)\n",
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture
def mixed_image_fixture(tmp_path):
    """One present image, one missing image, in a single chapter."""
    _scaffold(tmp_path, title="Mixed Book")
    write_png(tmp_path / "assets" / "present.png")
    (tmp_path / "manuscript" / "chapters" / "chapter1.md").write_text(
        "# Chapter\n\n![ok](present.png)\n\n![bad](absent.png)\n",
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture
def nested_assets_fixture(tmp_path):
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
def absolute_path_fixture(tmp_path):
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
def unicode_fixture(tmp_path):
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


# Helper-as-fixture wrappers — some tests declare these in their signatures.
@pytest.fixture
def assert_pdf_images():
    return assert_pdf_has_images


@pytest.fixture
def assert_pdf_text():
    return assert_pdf_contains_text


@pytest.fixture
def get_pdf_text():
    return pdf_text
