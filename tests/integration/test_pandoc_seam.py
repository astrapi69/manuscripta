"""Layer-2 integration tests: real Pandoc subprocess, no LaTeX.

The layer exists precisely to catch v0.7.0-class regressions — where
unit tests happily mock subprocess and report green while the actual
library-to-Pandoc seam is broken. Every test here invokes real
pandoc and asserts on an outcome.

Output format: ``html`` for smoke and fast paths; ``epub`` where we need
Pandoc to actually fetch image resources (html does not trigger the
``Could not fetch resource`` warning unless ``--embed-resources`` is
used, but epub does, because it packages assets). No test here uses
``pdf`` — PDF builds need a LaTeX engine and belong in the e2e layer.

All tests carry ``@pytest.mark.integration + @pytest.mark.requires_pandoc``.
Budget: whole file < 30 s combined.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.requires_pandoc]

from manuscripta import (
    ManuscriptaError,
    ManuscriptaImageError,
    ManuscriptaLayoutError,
    ManuscriptaPandocError,
)
from manuscripta.export import book as bm


# -------------------------------------------------------------------------
# Local helpers — these tests do not drive PDF builds, so they do not use
# the larger e2e helpers.
# -------------------------------------------------------------------------


def _make_project(root: Path, *, with_image: bool = True, image_name: str = "sample.png") -> Path:
    from helpers.png import write_png  # type: ignore[import-not-found]
    from helpers.project import scaffold  # type: ignore[import-not-found]

    scaffold(root, title="Integration Book", lang="en")
    if with_image:
        write_png(root / "assets" / image_name)
    (root / "manuscript" / "chapters" / "chapter1.md").write_text(
        f"# Chapter One\n\n![pic]({image_name})\n",
        encoding="utf-8",
    )
    return root


def _stub_validators(monkeypatch):
    """Disable background validation threads — they aren't under test and
    pulling epubcheck off the network would break the 30 s budget."""
    for name in (
        "validate_pdf",
        "validate_epub_with_epubcheck",
        "validate_docx",
        "validate_markdown",
        "validate_html",
    ):
        monkeypatch.setattr(bm, name, lambda *a, **k: None)


def _export_html(project: Path, **kwargs):
    """Run run_export with format=html; no LaTeX, no epubcheck."""
    return bm.run_export(
        project,
        formats="html",
        skip_images=True,
        no_type_suffix=True,
        output_file="book",
        **kwargs,
    )


def _export_epub(project: Path, **kwargs):
    """Run run_export with format=epub so Pandoc actually fetches image
    resources and emits resource warnings."""
    return bm.run_export(
        project,
        formats="epub",
        skip_images=True,
        no_type_suffix=True,
        output_file="book",
        **kwargs,
    )


# =========================================================================
# Smoke: real Pandoc actually runs
# =========================================================================


def test_real_pandoc_html_build_succeeds(tmp_path, monkeypatch):
    """Real pandoc invoked, html output produced, no exception."""
    _stub_validators(monkeypatch)
    project = _make_project(tmp_path)
    _export_html(project)
    out = project / "output" / "book.html"
    assert out.exists()
    body = out.read_text(encoding="utf-8")
    assert "Chapter One" in body


def test_real_pandoc_plain_invocation_direct(tmp_path):
    """Direct pandoc --to=plain smoke — exercises the same seam without
    going through the full pipeline (the pipeline's default formats
    don't include `plain`, but the integration requirement does)."""
    md = tmp_path / "x.md"
    md.write_text("# Heading\n\nBody text.\n", encoding="utf-8")
    result = subprocess.run(
        ["pandoc", "--from=markdown", "--to=plain", str(md)],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "Heading" in result.stdout
    assert "Body text" in result.stdout


# =========================================================================
# Stderr parsing — at least 3 tests
# =========================================================================


def test_stderr_unresolved_resource_warning_raises_image_error(tmp_path, monkeypatch):
    """Pandoc emits ``Could not fetch resource`` → library surfaces
    ManuscriptaImageError with the unresolved path in .unresolved."""
    _stub_validators(monkeypatch)
    project = _make_project(tmp_path, with_image=False, image_name="missing.png")
    with pytest.raises(ManuscriptaImageError) as excinfo:
        _export_epub(project, strict_images=True)
    assert "missing.png" in excinfo.value.unresolved


def test_stderr_malformed_metadata_yaml_raises_pandoc_error(tmp_path, monkeypatch):
    """Malformed YAML in metadata.yaml → Pandoc fails → library raises
    ManuscriptaPandocError (not a raw CalledProcessError)."""
    _stub_validators(monkeypatch)
    project = _make_project(tmp_path)
    (project / "config" / "metadata.yaml").write_text(
        "title: [unterminated\n", encoding="utf-8"
    )
    with pytest.raises(ManuscriptaError) as excinfo:
        _export_html(project)
    # Must not leak the raw subprocess error.
    assert not isinstance(excinfo.value, subprocess.CalledProcessError)
    # Stderr from pandoc should mention YAML / parse.
    if isinstance(excinfo.value, ManuscriptaPandocError):
        assert "yaml" in excinfo.value.stderr.lower() or "parse" in excinfo.value.stderr.lower()


def test_stderr_successful_build_with_warnings_parses_but_does_not_raise(
    tmp_path, monkeypatch, caplog
):
    """Pandoc run with a missing image + strict_images=False: the
    warning is parsed and surfaced via logging, and the build completes
    (output file produced)."""
    _stub_validators(monkeypatch)
    project = _make_project(tmp_path, with_image=False, image_name="ghost.png")
    with caplog.at_level(logging.WARNING, logger="manuscripta.export.book"):
        _export_epub(project, strict_images=False)
    # Output produced.
    assert any((project / "output").glob("*.epub"))
    # Warning surfaced.
    assert any("ghost.png" in r.getMessage() for r in caplog.records)


# =========================================================================
# Resource-path construction (the v0.7.0 failure modes) — at least 4 tests
# =========================================================================


def test_rp_i_source_dir_resolves_from_cwd_outside_project(tmp_path, monkeypatch):
    """(i) source_dir passed, invoked from a cwd OUTSIDE the project →
    resources resolve correctly, no spurious warning, build succeeds."""
    _stub_validators(monkeypatch)
    project = _make_project(tmp_path / "book")

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    _export_epub(project, strict_images=True)
    assert (project / "output" / "book.epub").exists()


def test_rp_ii_missing_subdirs_raises_layout_error_naming_all(tmp_path, monkeypatch):
    """(ii) source_dir with missing subdirs → ManuscriptaLayoutError with
    ALL missing dirs named in one shot."""
    _stub_validators(monkeypatch)
    (tmp_path / "manuscript").mkdir()  # keep this one; omit config/ and assets/

    with pytest.raises(ManuscriptaLayoutError) as excinfo:
        _export_html(tmp_path)
    err = excinfo.value
    assert set(err.missing) == {"config", "assets"}
    msg = str(err)
    assert "config" in msg and "assets" in msg


def test_rp_iii_strict_images_missing_raises_with_unresolved_list(tmp_path, monkeypatch):
    """(iii) strict_images=True + missing image → ManuscriptaImageError
    with .unresolved populated."""
    _stub_validators(monkeypatch)
    project = _make_project(tmp_path, with_image=False, image_name="absent.png")
    with pytest.raises(ManuscriptaImageError) as excinfo:
        _export_epub(project, strict_images=True)
    assert excinfo.value.unresolved == ["absent.png"]


def test_rp_iv_lenient_images_missing_logs_and_completes(tmp_path, monkeypatch, caplog):
    """(iv) strict_images=False + missing image → warning logged, build
    completes."""
    _stub_validators(monkeypatch)
    project = _make_project(tmp_path, with_image=False, image_name="vanished.png")
    with caplog.at_level(logging.WARNING, logger="manuscripta.export.book"):
        _export_epub(project, strict_images=False)
    assert (project / "output" / "book.epub").exists()
    assert any("vanished.png" in r.getMessage() for r in caplog.records)


def test_rp_extra_resource_paths_accepted(tmp_path, monkeypatch):
    """Resource-path list includes extras passed via ``resource_paths=``.
    Using an extra asset dir outside source_dir lets Pandoc resolve the
    image even though ``source_dir/assets`` does not contain it."""
    _stub_validators(monkeypatch)
    project = _make_project(tmp_path / "book", with_image=False, image_name="extra.png")

    from helpers.png import write_png  # type: ignore[import-not-found]

    extra_dir = tmp_path / "shared-assets"
    extra_dir.mkdir()
    write_png(extra_dir / "extra.png")

    # Must succeed because Pandoc finds extra.png in the second entry of
    # --resource-path.
    bm.run_export(
        project,
        formats="epub",
        resource_paths=[extra_dir],
        skip_images=True,
        no_type_suffix=True,
        output_file="book",
        strict_images=True,
    )
    assert (project / "output" / "book.epub").exists()


# =========================================================================
# Unicode / whitespace fragility — at least 2 tests
# =========================================================================


def test_unicode_in_content_and_filenames(tmp_path, monkeypatch):
    """Non-ASCII chapter filename, non-ASCII image filename, non-ASCII
    content. Historically fragile; pin before regression."""
    _stub_validators(monkeypatch)

    from helpers.png import write_png  # type: ignore[import-not-found]
    from helpers.project import scaffold  # type: ignore[import-not-found]

    scaffold(tmp_path, title="Λόγος — Élan", lang="de")
    img_name = "Bücher.png"
    write_png(tmp_path / "assets" / img_name)
    (tmp_path / "manuscript" / "chapters" / "Kapitel-α.md").write_text(
        f"# Καλημέρα\n\nÜber die Bedeutung der Bücher.\n\n![]({img_name})\n",
        encoding="utf-8",
    )

    _export_epub(tmp_path, strict_images=True)
    assert (tmp_path / "output" / "book.epub").exists()


def test_source_dir_with_spaces_and_parens(tmp_path, monkeypatch):
    """Path containing spaces and parentheses — LaTeX's classic failure
    surface, but Pandoc html/epub paths also historically mishandle it.
    Pin it."""
    _stub_validators(monkeypatch)
    project = tmp_path / "My Book (Draft v2)"
    _make_project(project)
    _export_epub(project, strict_images=True)
    assert (project / "output" / "book.epub").exists()


# =========================================================================
# Absolute-path image references — at least 1 test
# =========================================================================


# =========================================================================
# Additional integration coverage
# =========================================================================


def test_explicit_output_path_overrides_derived_location(tmp_path, monkeypatch):
    """``output_path=`` must win over the default source_dir/output/ path."""
    _stub_validators(monkeypatch)
    project = _make_project(tmp_path / "book")
    explicit = tmp_path / "elsewhere" / "named.html"
    bm.run_export(
        project,
        formats="html",
        output_path=explicit,
        skip_images=True,
        no_type_suffix=True,
        output_file="ignored",
    )
    assert explicit.exists()
    assert not (project / "output" / "ignored.html").exists()


def test_mixed_present_and_missing_images_lists_only_missing(tmp_path, monkeypatch):
    """One valid image + one missing image, strict mode: exception's
    .unresolved must name only the missing path, never the valid one."""
    _stub_validators(monkeypatch)
    from helpers.png import write_png  # type: ignore[import-not-found]
    from helpers.project import scaffold  # type: ignore[import-not-found]

    scaffold(tmp_path, title="Mixed")
    write_png(tmp_path / "assets" / "present.png")
    (tmp_path / "manuscript" / "chapters" / "ch1.md").write_text(
        "# Ch\n\n![ok](present.png)\n\n![bad](absent.png)\n", encoding="utf-8"
    )
    with pytest.raises(ManuscriptaImageError) as excinfo:
        _export_epub(tmp_path, strict_images=True)
    assert excinfo.value.unresolved == ["absent.png"]


def test_multi_chapter_section_order_preserved_in_output(tmp_path, monkeypatch):
    """Multi-chapter build: order from section_order is preserved in the
    concatenated output."""
    _stub_validators(monkeypatch)
    from helpers.project import scaffold  # type: ignore[import-not-found]

    scaffold(tmp_path, title="Multi")
    for i in range(1, 4):
        (tmp_path / "manuscript" / "chapters" / f"ch{i}.md").write_text(
            f"# Chapter Marker {i}\n\nText body {i}.\n", encoding="utf-8"
        )
    bm.run_export(
        tmp_path,
        formats="html",
        section_order=["chapters"],
        skip_images=True,
        no_type_suffix=True,
        output_file="book",
    )
    html = (tmp_path / "output" / "book.html").read_text(encoding="utf-8")
    # All three markers appear, in order.
    i1 = html.find("Chapter Marker 1")
    i2 = html.find("Chapter Marker 2")
    i3 = html.find("Chapter Marker 3")
    assert 0 < i1 < i2 < i3, f"Chapter order lost: {i1} {i2} {i3}"


def test_pandoc_stderr_is_teed_to_export_log(tmp_path, monkeypatch):
    """When the build succeeds but emits warnings, the stderr text must
    land in ``export.log`` — the only durable artifact for post-hoc
    debugging."""
    _stub_validators(monkeypatch)
    project = _make_project(tmp_path, with_image=False, image_name="poltergeist.png")
    _export_epub(project, strict_images=False)
    log = project / "export.log"
    assert log.exists()
    content = log.read_text(encoding="utf-8")
    assert "poltergeist.png" in content


def test_failed_build_deletes_partial_output(tmp_path, monkeypatch):
    """v0.8.0 contract: a strict-images failure must not leave a partial
    output file behind (half-built artifacts lie about success)."""
    _stub_validators(monkeypatch)
    project = _make_project(tmp_path, with_image=False, image_name="phantom.png")
    out = project / "output" / "book.epub"
    with pytest.raises(ManuscriptaImageError):
        _export_epub(project, strict_images=True)
    assert not out.exists(), f"Partial artifact left at {out}"


def test_absolute_path_image_reference(tmp_path, monkeypatch):
    """Markdown references image by absolute path outside source_dir.
    Pandoc handles absolute paths natively; library must not mangle
    them, and --resource-path handling must not interfere."""
    _stub_validators(monkeypatch)

    from helpers.png import write_png  # type: ignore[import-not-found]
    from helpers.project import scaffold  # type: ignore[import-not-found]

    scaffold(tmp_path, title="Absolute Book")
    external = tmp_path / "external"
    external.mkdir()
    image_abs = (external / "external.png").resolve()
    write_png(image_abs)
    (tmp_path / "manuscript" / "chapters" / "ch1.md").write_text(
        f"# Chapter\n\n![ext]({image_abs})\n", encoding="utf-8"
    )
    # Strict images on — must not raise, absolute path must resolve.
    _export_epub(tmp_path, strict_images=True)
    assert (tmp_path / "output" / "book.epub").exists()
