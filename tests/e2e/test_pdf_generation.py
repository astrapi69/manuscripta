"""End-to-end PDF-generation tests for the v0.8.0 manuscripta library API.

Markers:
    requires_pandoc — skipped if pandoc is not on PATH
    requires_latex  — skipped if xelatex is not on PATH
    slow            — opt-out via ``-m "not slow"`` for fast iteration

The fast suite runs in well under 30 s on a developer laptop; the full
suite, including ``slow`` tests, should run in under two minutes.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e

from manuscripta import (
    ManuscriptaError,
    ManuscriptaImageError,
    ManuscriptaLayoutError,
    ManuscriptaPandocError,
)
from manuscripta.export import book as book_mod
from manuscripta.export.book import run_export

from conftest import (  # type: ignore[import-not-found]
    assert_pdf_contains_text,
    assert_pdf_has_images,
    pdf_text,
    write_png,
)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _build_pdf(source_dir: Path, **kwargs) -> Path:
    """Run a PDF export and return the path of the produced PDF."""
    out = source_dir / "output" / "book.pdf"
    run_export(
        source_dir,
        formats="pdf",
        output_path=out,
        skip_images=True,  # don't run path-rewrite helpers in tests
        no_type_suffix=True,
        output_file="book",
        **kwargs,
    )
    return out


# Placements: each takes the fixture root and tmp_path and returns the
# source dir to export and the cwd to run from.


def _in_place(project: Path, tmp_path: Path) -> tuple[Path, Path]:
    """Export the fixture where it lies, from its parent directory."""
    return project, project.parent


def _from_inside(project: Path, tmp_path: Path) -> tuple[Path, Path]:
    """Export the fixture where it lies, from inside the project."""
    return project, tmp_path


def _from_elsewhere(project: Path, tmp_path: Path) -> tuple[Path, Path]:
    """Export the fixture from an unrelated directory under tmp_path."""
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    return project, elsewhere


def _copied_into_spaced_dir(project: Path, tmp_path: Path) -> tuple[Path, Path]:
    """Export a copy of the fixture whose path carries spaces and parens."""
    target = tmp_path / "My Book (Draft)"
    shutil.copytree(project, target)
    return target, tmp_path


def _behind_symlink(project: Path, tmp_path: Path) -> tuple[Path, Path]:
    """Export the fixture through a symlink to it."""
    link = tmp_path / "linked-book"
    link.symlink_to(project)
    return link, tmp_path


# --------------------------------------------------------------------------
# Happy-path builds: the images embed and the text survives
# --------------------------------------------------------------------------


# Each row: the conftest fixture to build, its placement (see above), the
# image count pdfimages must report, the texts pdftotext must show (a tuple
# lists the spellings font fallback may produce)
HAPPY_PATH_BUILDS = [
    pytest.param(
        "minimal_book_fixture",
        _in_place,
        1,
        ["Chapter One"],
        id="single-chapter-single-image-embeds",
    ),
    pytest.param(
        "multi_chapter_fixture",
        _in_place,
        3,
        [],
        id="multi-chapter-all-images-embedded",
    ),
    # Original-bug regression: run_export called with source_dir from
    # a different cwd.
    pytest.param(
        "minimal_book_fixture",
        _from_elsewhere,
        1,
        [],
        id="called-from-different-cwd-with-source-dir",
    ),
    pytest.param(
        "nested_assets_fixture", _in_place, 2, [], id="nested-asset-dirs-resolve"
    ),
    pytest.param(
        "absolute_path_fixture", _in_place, 1, [], id="absolute-path-image-embeds"
    ),
    pytest.param(
        "unicode_fixture",
        _in_place,
        1,
        ["Καλημέρα", ("Élan", "Elan"), "Bücher"],
        id="unicode-in-paths-and-content",
    ),
    pytest.param(
        "minimal_book_fixture",
        _copied_into_spaced_dir,
        1,
        [],
        id="source-dir-with-spaces-in-path",
    ),
    pytest.param(
        "minimal_book_fixture", _behind_symlink, 1, [], id="source-dir-as-symlink"
    ),
]


@pytest.mark.requires_pandoc
@pytest.mark.requires_latex
@pytest.mark.parametrize("fixture, place, images, texts", HAPPY_PATH_BUILDS)
def test_pdf_build_embeds_images(
    fixture, place, images, texts, request, tmp_path, monkeypatch
):
    source_dir, cwd = place(request.getfixturevalue(fixture), tmp_path)
    monkeypatch.chdir(cwd)
    pdf = _build_pdf(source_dir)
    assert pdf.exists()
    assert_pdf_has_images(pdf, images)
    for spellings in texts:
        if isinstance(spellings, str):
            assert_pdf_contains_text(pdf, spellings)
        else:  # font fallbacks may strip accents
            text = pdf_text(pdf)
            assert any(s in text for s in spellings), f"None of {spellings} in PDF"


@pytest.mark.requires_pandoc
@pytest.mark.requires_latex
def test_chapter_order_preserved(multi_chapter_fixture, monkeypatch):
    monkeypatch.chdir(multi_chapter_fixture.parent)
    pdf = _build_pdf(multi_chapter_fixture)
    text = pdf_text(pdf)
    pos = [text.find(f"Chapter {i}") for i in range(1, 4)]
    assert all(p > -1 for p in pos), f"Missing chapter heading: positions={pos}"
    assert pos == sorted(pos), f"Chapters out of order: positions={pos}"


@pytest.mark.slow
@pytest.mark.requires_pandoc
@pytest.mark.requires_latex
def test_image_actually_visible_not_just_embedded(minimal_book_fixture, monkeypatch):
    """Render the PDF to PPM and verify the page contains non-background pixels.

    Catches "embedded XObject but never drawn" regressions. We can't pixel-diff
    against a golden file (LaTeX/font version drift) so we use a coarse colour
    heuristic: the fixture PNG is solid red, so the rendered page must contain
    at least one strongly-red pixel.
    """
    if shutil.which("pdftoppm") is None:
        pytest.skip("pdftoppm not on PATH")
    monkeypatch.chdir(minimal_book_fixture.parent)
    pdf = _build_pdf(minimal_book_fixture)
    out_prefix = minimal_book_fixture / "render"
    subprocess.run(
        ["pdftoppm", "-r", "72", "-png", str(pdf), str(out_prefix)],
        check=True,
    )
    page_pngs = sorted(minimal_book_fixture.glob("render-*.png"))
    assert page_pngs, "pdftoppm produced no pages"

    # Re-render to PPM (raw RGB) so we can scan for a strongly-red pixel.
    ppm_prefix = minimal_book_fixture / "render-ppm"
    subprocess.run(
        ["pdftoppm", "-r", "72", str(pdf), str(ppm_prefix)],
        check=True,
    )
    ppm_files = sorted(minimal_book_fixture.glob("render-ppm-*.ppm"))
    assert ppm_files, "pdftoppm produced no PPM"
    data = ppm_files[0].read_bytes()
    # P6 header: "P6\n<w> <h>\n255\n" then raw RGB triplets.
    header_end = 0
    newlines = 0
    while newlines < 3 and header_end < len(data):
        if data[header_end : header_end + 1] == b"\n":
            newlines += 1
        header_end += 1
    pixels = data[header_end:]
    # Look for any strongly-red pixel (R high, G/B low).
    found_red = False
    for i in range(0, len(pixels) - 2, 3):
        r, g, b = pixels[i], pixels[i + 1], pixels[i + 2]
        if r > 200 and g < 80 and b < 80:
            found_red = True
            break
    assert (
        found_red
    ), "Embedded image was not rendered (no red pixel found in rasterised page)"


# --------------------------------------------------------------------------
# Original-bug regression tests: the library API and its Pandoc argv
# --------------------------------------------------------------------------


def test_called_without_source_dir_raises_typeerror():
    with pytest.raises(TypeError):
        run_export()  # type: ignore[call-arg]


def test_pandoc_resource_path_is_absolute(minimal_book_fixture, monkeypatch):
    captured: dict[str, list[str]] = {}

    def fake_run(cmd, **kwargs):
        if cmd and cmd[0] == "pandoc":
            captured["argv"] = list(cmd)

        # Return a sentinel "successful" pandoc call.
        class _CP:
            stdout = ""
            stderr = ""

        return _CP()

    monkeypatch.setattr(book_mod.subprocess, "run", fake_run)
    monkeypatch.setattr(book_mod, "validate_pdf", lambda *a, **k: None)
    monkeypatch.chdir(minimal_book_fixture.parent)
    _build_pdf(minimal_book_fixture)

    argv = captured.get("argv")
    assert argv, "pandoc was never invoked"
    rp = next(a for a in argv if a.startswith("--resource-path="))
    value = rp.split("=", 1)[1]
    first = value.split(os.pathsep)[0]
    assert os.path.isabs(first), f"--resource-path must be absolute, got: {first}"
    assert (
        Path(first) == (minimal_book_fixture / "assets").resolve()
    ), f"--resource-path[0] should be source_dir/assets; got {first}"
    assert "./assets" not in argv, "Found legacy relative './assets' in argv"


def test_pandoc_invoked_with_no_chdir(minimal_book_fixture, monkeypatch):
    def trip(_path):
        raise AssertionError(f"library called os.chdir({_path!r})")

    monkeypatch.setattr(os, "chdir", trip)

    # Stub subprocess.run so we don't actually run pandoc (which is fine here;
    # the assertion is about library behavior, not pandoc execution).
    class _CP:
        stdout = ""
        stderr = ""

    monkeypatch.setattr(book_mod.subprocess, "run", lambda *a, **k: _CP())
    monkeypatch.setattr(book_mod, "validate_pdf", lambda *a, **k: None)

    _build_pdf(minimal_book_fixture)


# --------------------------------------------------------------------------
# strict_images contract
# --------------------------------------------------------------------------


# Each row: the conftest fixture to build, its placement, the output path
# relative to the source dir, the paths ManuscriptaImageError.unresolved must
# list (the message names each of them). Every row builds with
# strict_images=True and must leave no PDF behind.
STRICT_IMAGE_FAILURES = [
    pytest.param(
        "broken_image_fixture",
        _in_place,
        "output/book.pdf",
        ["missing.png"],
        id="strict-images-true-raises-on-missing",
    ),
    pytest.param(
        "mixed_image_fixture",
        _in_place,
        "output/book.pdf",
        ["absent.png"],
        id="mixed-images-strict-lists-only-missing",
    ),
    # Pandoc's own resource warning is what the message must surface.
    pytest.param(
        "broken_image_fixture",
        _in_place,
        "output/book.pdf",
        ["missing.png"],
        id="pandoc-warnings-surfaced-when-strict",
    ),
    pytest.param(
        "broken_image_fixture",
        _from_inside,
        "out/book.pdf",
        ["missing.png"],
        id="failed-build-does-not-leave-partial-pdf",
    ),
]


@pytest.mark.requires_pandoc
@pytest.mark.requires_latex
@pytest.mark.parametrize("fixture, place, out, unresolved", STRICT_IMAGE_FAILURES)
def test_strict_images_missing_raises_and_leaves_no_pdf(
    fixture, place, out, unresolved, request, tmp_path, monkeypatch
):
    source_dir, cwd = place(request.getfixturevalue(fixture), tmp_path)
    monkeypatch.chdir(cwd)
    out = source_dir / out
    with pytest.raises(ManuscriptaImageError) as excinfo:
        run_export(
            source_dir,
            formats="pdf",
            output_path=out,
            skip_images=True,
            no_type_suffix=True,
            output_file="book",
            strict_images=True,
        )
    err = excinfo.value
    assert err.unresolved == unresolved, err.unresolved
    for name in unresolved:
        assert name in str(err)
    assert not out.exists(), f"Partial PDF left at {out}"


# Each row: the conftest fixture to build, the image count pdfimages must
# report, the images the warning on stdout must name, the ones it must not
# name. Every row builds with strict_images=False and must complete.
LENIENT_IMAGE_BUILDS = [
    pytest.param(
        "broken_image_fixture",
        0,
        ["missing.png"],
        [],
        id="strict-images-false-completes-with-warning",
    ),
    # don't false-warn on the valid one
    pytest.param(
        "mixed_image_fixture",
        1,
        ["absent.png"],
        ["present.png"],
        id="mixed-images-lenient-embeds-valid-skips-missing",
    ),
]


@pytest.mark.requires_pandoc
@pytest.mark.requires_latex
@pytest.mark.parametrize("fixture, images, warned, unwarned", LENIENT_IMAGE_BUILDS)
def test_lenient_images_build_completes_with_warning(
    fixture, images, warned, unwarned, request, monkeypatch, capsys
):
    project = request.getfixturevalue(fixture)
    monkeypatch.chdir(project.parent)
    pdf = _build_pdf(project, strict_images=False)
    assert pdf.exists()
    assert_pdf_has_images(pdf, images)
    out = capsys.readouterr().out
    for name in warned:
        assert name in out
    for name in unwarned:
        assert name not in out


# --------------------------------------------------------------------------
# Pandoc / LaTeX integration
# --------------------------------------------------------------------------


@pytest.mark.requires_pandoc
@pytest.mark.requires_latex
def test_pandoc_stderr_surfaced_on_failure(minimal_book_fixture, monkeypatch):
    # Force a Pandoc error by writing an invalid metadata file.
    (minimal_book_fixture / "config" / "metadata.yaml").write_text(
        "title: [unterminated\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(minimal_book_fixture.parent)
    out = minimal_book_fixture / "output" / "book.pdf"
    with pytest.raises(ManuscriptaError) as excinfo:
        run_export(
            minimal_book_fixture,
            formats="pdf",
            output_path=out,
            skip_images=True,
            no_type_suffix=True,
            output_file="book",
        )
    msg = str(excinfo.value).lower()
    assert (
        "yaml" in msg or "metadata" in msg or "parse" in msg
    ), f"Pandoc stderr should be in the message; got: {excinfo.value}"


def test_pdf_engine_failure_produces_clear_error(minimal_book_fixture, monkeypatch):
    """Mock pandoc to exit with a LaTeX-style failure; assert wrapped exception."""
    monkeypatch.chdir(minimal_book_fixture.parent)

    def fake_run(cmd, **kwargs):
        if cmd and cmd[0] == "pandoc":
            raise subprocess.CalledProcessError(
                returncode=43,
                cmd=cmd,
                output="",
                stderr="! LaTeX Error: File `nonexistent.sty' not found.\n",
            )

        class _CP:
            stdout = ""
            stderr = ""

        return _CP()

    monkeypatch.setattr(book_mod.subprocess, "run", fake_run)

    with pytest.raises(ManuscriptaPandocError) as excinfo:
        _build_pdf(minimal_book_fixture)
    assert excinfo.value.returncode == 43
    assert "LaTeX Error" in excinfo.value.stderr
    # Generic CalledProcessError must NOT leak out.
    assert not isinstance(excinfo.value, subprocess.CalledProcessError)


# --------------------------------------------------------------------------
# Output / artifact tests
# --------------------------------------------------------------------------


# Each row: the explicit output path under tmp_path (its parents do not
# exist yet), the output_file name the library must not derive a path from.
# Every row builds minimal_book_fixture from tmp_path.
OUTPUT_PATH_CASES = [
    pytest.param("outdir/named.pdf", "ignored", id="output-path-respected"),
    pytest.param(
        "deep/nest/book.pdf", "book", id="output-directory-created-if-missing"
    ),
]


@pytest.mark.requires_pandoc
@pytest.mark.requires_latex
@pytest.mark.parametrize("out, output_file", OUTPUT_PATH_CASES)
def test_explicit_output_path_is_the_only_pdf(
    out, output_file, minimal_book_fixture, tmp_path, monkeypatch
):
    explicit = tmp_path / out
    monkeypatch.chdir(tmp_path)
    run_export(
        minimal_book_fixture,
        formats="pdf",
        output_path=explicit,
        skip_images=True,
        no_type_suffix=True,
        output_file=output_file,
    )
    assert explicit.exists()
    # Library must NOT silently dump elsewhere.
    assert not (Path.cwd() / explicit.name).exists()
    # The default derived path under source_dir/output should not be present.
    default = minimal_book_fixture / "output" / f"{output_file}.pdf"
    assert not default.exists()


@pytest.mark.requires_pandoc
@pytest.mark.requires_latex
def test_no_temp_files_left_behind(minimal_book_fixture, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pdf = _build_pdf(minimal_book_fixture)
    assert pdf.exists()
    debris_exts = {".aux", ".toc", ".out", ".lof", ".lot"}
    leftover = [
        p
        for p in list(minimal_book_fixture.rglob("*")) + list(tmp_path.glob("*"))
        if p.is_file() and p.suffix.lower() in debris_exts
    ]
    assert not leftover, f"LaTeX/Pandoc debris left behind: {leftover}"


# --------------------------------------------------------------------------
# Performance / scale
# --------------------------------------------------------------------------


@pytest.mark.slow
@pytest.mark.requires_pandoc
@pytest.mark.requires_latex
def test_large_manuscript_completes(tmp_path, monkeypatch):
    project = tmp_path / "big-book"
    (project / "manuscript" / "chapters").mkdir(parents=True)
    (project / "config").mkdir(parents=True)
    (project / "assets").mkdir(parents=True)
    (project / "config" / "metadata.yaml").write_text(
        'title: "Big Book"\nauthor: "T"\nlang: "en"\n', encoding="utf-8"
    )
    for i in range(1, 51):
        write_png(project / "assets" / f"f{i:02d}a.png", rgb=((i * 5) % 256, 80, 120))
        write_png(project / "assets" / f"f{i:02d}b.png", rgb=(80, (i * 7) % 256, 60))
        (project / "manuscript" / "chapters" / f"chapter{i:02d}.md").write_text(
            f"# Chapter {i}\n\nText {i}.\n\n"
            f"![a](f{i:02d}a.png)\n\n"
            f"![b](f{i:02d}b.png)\n",
            encoding="utf-8",
        )

    out = project / "output" / "big.pdf"
    monkeypatch.chdir(tmp_path)
    start = time.time()
    run_export(
        project,
        formats="pdf",
        output_path=out,
        skip_images=True,
        no_type_suffix=True,
        output_file="big",
        strict_images=True,
    )
    elapsed = time.time() - start
    assert out.exists()
    assert elapsed < 60, f"Large-manuscript build took {elapsed:.1f}s (>60s)"
    assert_pdf_has_images(out, 100)


# --------------------------------------------------------------------------
# Layout / API guard tests (cheap; no pandoc required)
# --------------------------------------------------------------------------


def test_layout_error_when_missing_dirs(tmp_path):
    (tmp_path / "manuscript").mkdir()
    with pytest.raises(ManuscriptaLayoutError):
        run_export(tmp_path, formats="pdf", output_path=tmp_path / "x.pdf")
