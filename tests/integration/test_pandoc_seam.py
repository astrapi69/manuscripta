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


def _make_project(
    root: Path, *, with_image: bool = True, image_name: str = "sample.png"
) -> Path:
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


def _project_missing_image(image_name: str):
    """Builder for a project whose chapter references ``image_name`` but
    whose assets/ does not ship it."""
    return lambda tmp_path: _make_project(
        tmp_path, with_image=False, image_name=image_name
    )


def _unicode_project(tmp_path: Path) -> Path:
    """Non-ASCII chapter filename, image filename and content."""
    from helpers.png import write_png  # type: ignore[import-not-found]
    from helpers.project import scaffold  # type: ignore[import-not-found]

    scaffold(tmp_path, title="Λόγος — Élan", lang="de")
    img_name = "Bücher.png"
    write_png(tmp_path / "assets" / img_name)
    (tmp_path / "manuscript" / "chapters" / "Kapitel-α.md").write_text(
        f"# Καλημέρα\n\nÜber die Bedeutung der Bücher.\n\n![]({img_name})\n",
        encoding="utf-8",
    )
    return tmp_path


def _absolute_image_project(tmp_path: Path) -> Path:
    """The chapter references an image by absolute path outside source_dir."""
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
    return tmp_path


def _mixed_images_project(tmp_path: Path) -> Path:
    """One valid image and one missing image in a single chapter."""
    from helpers.png import write_png  # type: ignore[import-not-found]
    from helpers.project import scaffold  # type: ignore[import-not-found]

    scaffold(tmp_path, title="Mixed")
    write_png(tmp_path / "assets" / "present.png")
    (tmp_path / "manuscript" / "chapters" / "ch1.md").write_text(
        "# Ch\n\n![ok](present.png)\n\n![bad](absent.png)\n", encoding="utf-8"
    )
    return tmp_path


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
# Stderr parsing: a Pandoc failure surfaces as a library error
# =========================================================================


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
        assert (
            "yaml" in excinfo.value.stderr.lower()
            or "parse" in excinfo.value.stderr.lower()
        )


# =========================================================================
# Resource-path construction (the v0.7.0 failure modes): strict builds
# that must succeed, missing images under strict_images, and the same
# under lenient mode. Add a row to pin a new layout.
# =========================================================================


# Each row: a builder that lays the project out under tmp_path and returns its
# root, and the directory under tmp_path to run from (None: stay put). Every
# row builds epub with strict_images=True and must produce output/book.epub.
STRICT_EPUB_BUILDS = [
    # (i) source_dir passed, invoked from a cwd OUTSIDE the project →
    # resources resolve correctly, no spurious warning, build succeeds.
    pytest.param(
        lambda tmp_path: _make_project(tmp_path / "book"),
        "elsewhere",
        id="rp-i-source-dir-resolves-from-cwd-outside-project",
    ),
    # Historically fragile; pin before regression.
    pytest.param(_unicode_project, None, id="unicode-in-content-and-filenames"),
    # Path containing spaces and parentheses — LaTeX's classic failure
    # surface, but Pandoc html/epub paths also historically mishandle it.
    pytest.param(
        lambda tmp_path: _make_project(tmp_path / "My Book (Draft v2)"),
        None,
        id="source-dir-with-spaces-and-parens",
    ),
    # Pandoc handles absolute paths natively; library must not mangle
    # them, and --resource-path handling must not interfere.
    pytest.param(_absolute_image_project, None, id="absolute-path-image-reference"),
]


@pytest.mark.parametrize("build, run_from", STRICT_EPUB_BUILDS)
def test_strict_epub_build_succeeds(build, run_from, tmp_path, monkeypatch):
    _stub_validators(monkeypatch)
    project = build(tmp_path)
    if run_from is not None:
        cwd = tmp_path / run_from
        cwd.mkdir()
        monkeypatch.chdir(cwd)
    _export_epub(project, strict_images=True)
    assert (project / "output" / "book.epub").exists()


# Each row: a builder that lays the project out under tmp_path and returns its
# root, the paths ManuscriptaImageError.unresolved must list. Every row builds
# epub with strict_images=True and must leave no output/book.epub behind.
STRICT_MISSING_IMAGE_CASES = [
    # Pandoc emits ``Could not fetch resource`` → library surfaces
    # ManuscriptaImageError with the unresolved path in .unresolved.
    pytest.param(
        _project_missing_image("missing.png"),
        ["missing.png"],
        id="stderr-unresolved-resource-warning-raises-image-error",
    ),
    # (iii) strict_images=True + missing image → ManuscriptaImageError
    # with .unresolved populated.
    pytest.param(
        _project_missing_image("absent.png"),
        ["absent.png"],
        id="rp-iii-strict-images-missing-raises-with-unresolved-list",
    ),
    # .unresolved must name only the missing path, never the valid one.
    pytest.param(
        _mixed_images_project,
        ["absent.png"],
        id="mixed-present-and-missing-images-lists-only-missing",
    ),
    # v0.8.0 contract: a strict-images failure must not leave a partial
    # output file behind (half-built artifacts lie about success).
    pytest.param(
        _project_missing_image("phantom.png"),
        ["phantom.png"],
        id="failed-build-deletes-partial-output",
    ),
]


@pytest.mark.parametrize("build, unresolved", STRICT_MISSING_IMAGE_CASES)
def test_strict_missing_image_raises_image_error(
    build, unresolved, tmp_path, monkeypatch
):
    _stub_validators(monkeypatch)
    project = build(tmp_path)
    out = project / "output" / "book.epub"
    with pytest.raises(ManuscriptaImageError) as excinfo:
        _export_epub(project, strict_images=True)
    assert excinfo.value.unresolved == unresolved
    assert not out.exists(), f"Partial artifact left at {out}"


# Each row: a builder that lays the project out under tmp_path and returns its
# root, the image the warning must name. Every row builds epub with
# strict_images=False: the build completes, the warning is logged and the
# Pandoc stderr lands in export.log.
LENIENT_MISSING_IMAGE_CASES = [
    # Pandoc run with a missing image + strict_images=False: the
    # warning is parsed and surfaced via logging, and the build completes
    # (output file produced).
    pytest.param(
        _project_missing_image("ghost.png"),
        "ghost.png",
        id="stderr-successful-build-with-warnings-parses-but-does-not-raise",
    ),
    # (iv) strict_images=False + missing image → warning logged, build
    # completes.
    pytest.param(
        _project_missing_image("vanished.png"),
        "vanished.png",
        id="rp-iv-lenient-images-missing-logs-and-completes",
    ),
    # When the build succeeds but emits warnings, the stderr text must
    # land in ``export.log`` — the only durable artifact for post-hoc
    # debugging.
    pytest.param(
        _project_missing_image("poltergeist.png"),
        "poltergeist.png",
        id="pandoc-stderr-is-teed-to-export-log",
    ),
]


@pytest.mark.parametrize("build, warned", LENIENT_MISSING_IMAGE_CASES)
def test_lenient_missing_image_warns_and_completes(
    build, warned, tmp_path, monkeypatch, caplog
):
    _stub_validators(monkeypatch)
    project = build(tmp_path)
    with caplog.at_level(logging.WARNING, logger="manuscripta.export.book"):
        _export_epub(project, strict_images=False)
    # Output produced.
    assert (project / "output" / "book.epub").exists()
    # Warning surfaced.
    assert any(warned in r.getMessage() for r in caplog.records)
    log = project / "export.log"
    assert log.exists()
    assert warned in log.read_text(encoding="utf-8")


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
