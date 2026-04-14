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


# --------------------------------------------------------------------------
# 1–4: Core happy-path
# --------------------------------------------------------------------------


@pytest.mark.requires_pandoc
@pytest.mark.requires_latex
def test_single_chapter_single_image_embeds(minimal_book_fixture, monkeypatch):
    monkeypatch.chdir(minimal_book_fixture.parent)
    pdf = _build_pdf(minimal_book_fixture)
    assert pdf.exists()
    assert_pdf_has_images(pdf, 1)
    assert_pdf_contains_text(pdf, "Chapter One")


@pytest.mark.requires_pandoc
@pytest.mark.requires_latex
def test_multi_chapter_all_images_embedded(multi_chapter_fixture, monkeypatch):
    monkeypatch.chdir(multi_chapter_fixture.parent)
    pdf = _build_pdf(multi_chapter_fixture)
    assert_pdf_has_images(pdf, 3)


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
    assert found_red, (
        "Embedded image was not rendered (no red pixel found in rasterised page)"
    )


# --------------------------------------------------------------------------
# 5–8: Original-bug regression tests
# --------------------------------------------------------------------------


@pytest.mark.requires_pandoc
@pytest.mark.requires_latex
def test_called_from_different_cwd_with_source_dir(minimal_book_fixture, tmp_path, monkeypatch):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    pdf = _build_pdf(minimal_book_fixture)
    assert pdf.exists()
    assert_pdf_has_images(pdf, 1)


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
    assert Path(first) == (minimal_book_fixture / "assets").resolve(), (
        f"--resource-path[0] should be source_dir/assets; got {first}"
    )
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
# 9–10: Image edge cases
# --------------------------------------------------------------------------


@pytest.mark.requires_pandoc
@pytest.mark.requires_latex
def test_nested_asset_dirs_resolve(nested_assets_fixture, monkeypatch):
    monkeypatch.chdir(nested_assets_fixture.parent)
    pdf = _build_pdf(nested_assets_fixture)
    assert_pdf_has_images(pdf, 2)


@pytest.mark.requires_pandoc
@pytest.mark.requires_latex
def test_absolute_path_image_embeds(absolute_path_fixture, monkeypatch):
    monkeypatch.chdir(absolute_path_fixture.parent)
    pdf = _build_pdf(absolute_path_fixture)
    assert_pdf_has_images(pdf, 1)


# --------------------------------------------------------------------------
# 11–14: strict_images contract
# --------------------------------------------------------------------------


@pytest.mark.requires_pandoc
@pytest.mark.requires_latex
def test_strict_images_true_raises_on_missing(broken_image_fixture, monkeypatch):
    monkeypatch.chdir(broken_image_fixture.parent)
    out = broken_image_fixture / "output" / "book.pdf"
    with pytest.raises(ManuscriptaImageError) as excinfo:
        run_export(
            broken_image_fixture,
            formats="pdf",
            output_path=out,
            skip_images=True,
            no_type_suffix=True,
            output_file="book",
            strict_images=True,
        )
    assert "missing.png" in str(excinfo.value)
    assert not out.exists(), "Strict failure must not leave a partial PDF"


@pytest.mark.requires_pandoc
@pytest.mark.requires_latex
def test_strict_images_false_completes_with_warning(broken_image_fixture, monkeypatch, capsys):
    monkeypatch.chdir(broken_image_fixture.parent)
    pdf = _build_pdf(broken_image_fixture, strict_images=False)
    assert pdf.exists()
    assert_pdf_has_images(pdf, 0)
    out = capsys.readouterr().out
    assert "missing.png" in out


@pytest.mark.requires_pandoc
@pytest.mark.requires_latex
def test_mixed_images_strict_lists_only_missing(mixed_image_fixture, monkeypatch):
    monkeypatch.chdir(mixed_image_fixture.parent)
    out = mixed_image_fixture / "output" / "book.pdf"
    with pytest.raises(ManuscriptaImageError) as excinfo:
        run_export(
            mixed_image_fixture,
            formats="pdf",
            output_path=out,
            skip_images=True,
            no_type_suffix=True,
            output_file="book",
            strict_images=True,
        )
    err = excinfo.value
    assert err.unresolved == ["absent.png"], err.unresolved


@pytest.mark.requires_pandoc
@pytest.mark.requires_latex
def test_mixed_images_lenient_embeds_valid_skips_missing(mixed_image_fixture, monkeypatch, capsys):
    monkeypatch.chdir(mixed_image_fixture.parent)
    pdf = _build_pdf(mixed_image_fixture, strict_images=False)
    assert_pdf_has_images(pdf, 1)
    out = capsys.readouterr().out
    assert "absent.png" in out
    assert "present.png" not in out  # don't false-warn on the valid one


# --------------------------------------------------------------------------
# 15–17: Filesystem / encoding edge cases
# --------------------------------------------------------------------------


@pytest.mark.requires_pandoc
@pytest.mark.requires_latex
def test_unicode_in_paths_and_content(unicode_fixture, monkeypatch):
    monkeypatch.chdir(unicode_fixture.parent)
    pdf = _build_pdf(unicode_fixture)
    assert_pdf_has_images(pdf, 1)
    text = pdf_text(pdf)
    assert "Καλημέρα" in text
    assert "Élan" in text or "Elan" in text  # font fallbacks may strip accents
    assert "Bücher" in text or "B\u00fccher" in text


@pytest.mark.requires_pandoc
@pytest.mark.requires_latex
def test_source_dir_with_spaces_in_path(minimal_book_fixture, tmp_path, monkeypatch):
    target = tmp_path / "My Book (Draft)"
    shutil.copytree(minimal_book_fixture, target)
    monkeypatch.chdir(tmp_path)
    pdf = _build_pdf(target)
    assert_pdf_has_images(pdf, 1)


@pytest.mark.requires_pandoc
@pytest.mark.requires_latex
def test_source_dir_as_symlink(minimal_book_fixture, tmp_path, monkeypatch):
    link = tmp_path / "linked-book"
    link.symlink_to(minimal_book_fixture)
    monkeypatch.chdir(tmp_path)
    pdf = _build_pdf(link)
    assert pdf.exists()
    assert_pdf_has_images(pdf, 1)


# --------------------------------------------------------------------------
# 18–20: Pandoc / LaTeX integration
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
    assert "yaml" in msg or "metadata" in msg or "parse" in msg, (
        f"Pandoc stderr should be in the message; got: {excinfo.value}"
    )


@pytest.mark.requires_pandoc
@pytest.mark.requires_latex
def test_pandoc_warnings_surfaced_when_strict(broken_image_fixture, monkeypatch):
    monkeypatch.chdir(broken_image_fixture.parent)
    out = broken_image_fixture / "output" / "book.pdf"
    with pytest.raises(ManuscriptaImageError) as excinfo:
        run_export(
            broken_image_fixture,
            formats="pdf",
            output_path=out,
            skip_images=True,
            no_type_suffix=True,
            output_file="book",
            strict_images=True,
        )
    assert "missing.png" in str(excinfo.value)


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
# 21–24: Output / artifact tests
# --------------------------------------------------------------------------


@pytest.mark.requires_pandoc
@pytest.mark.requires_latex
def test_output_path_respected(minimal_book_fixture, tmp_path, monkeypatch):
    explicit = tmp_path / "outdir" / "named.pdf"
    monkeypatch.chdir(tmp_path)
    run_export(
        minimal_book_fixture,
        formats="pdf",
        output_path=explicit,
        skip_images=True,
        no_type_suffix=True,
        output_file="ignored",
    )
    assert explicit.exists()
    # Library must NOT silently dump elsewhere.
    assert not (Path.cwd() / "named.pdf").exists()
    # The default derived path under source_dir/output should not be present.
    default = minimal_book_fixture / "output" / "ignored.pdf"
    assert not default.exists()


@pytest.mark.requires_pandoc
@pytest.mark.requires_latex
def test_output_directory_created_if_missing(minimal_book_fixture, tmp_path, monkeypatch):
    out = tmp_path / "deep" / "nest" / "book.pdf"
    monkeypatch.chdir(tmp_path)
    run_export(
        minimal_book_fixture,
        formats="pdf",
        output_path=out,
        skip_images=True,
        no_type_suffix=True,
        output_file="book",
    )
    assert out.exists()


@pytest.mark.requires_pandoc
@pytest.mark.requires_latex
def test_no_temp_files_left_behind(minimal_book_fixture, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pdf = _build_pdf(minimal_book_fixture)
    assert pdf.exists()
    debris_exts = {".aux", ".toc", ".out", ".lof", ".lot"}
    leftover = [
        p
        for p in list(minimal_book_fixture.rglob("*"))
        + list(tmp_path.glob("*"))
        if p.is_file() and p.suffix.lower() in debris_exts
    ]
    assert not leftover, f"LaTeX/Pandoc debris left behind: {leftover}"


@pytest.mark.requires_pandoc
@pytest.mark.requires_latex
def test_failed_build_does_not_leave_partial_pdf(broken_image_fixture, tmp_path, monkeypatch):
    out = tmp_path / "out" / "book.pdf"
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ManuscriptaError):
        run_export(
            broken_image_fixture,
            formats="pdf",
            output_path=out,
            skip_images=True,
            no_type_suffix=True,
            output_file="book",
            strict_images=True,
        )
    assert not out.exists(), f"Partial PDF left at {out}"


# --------------------------------------------------------------------------
# 25: Performance / scale
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
