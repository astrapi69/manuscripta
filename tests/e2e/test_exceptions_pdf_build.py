"""Exception-hierarchy e2e tests: the ones that require a real Pandoc +
LaTeX build to exercise ManuscriptaImageError surfacing.

Split from tests/unit/test_exceptions.py; structural/pure-logic checks
live there.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e

from manuscripta import (
    ManuscriptaError,
    ManuscriptaImageError,
    ManuscriptaLayoutError,
)
from manuscripta.export.book import run_export


def _scaffold(
    root: Path, *, include: tuple[str, ...] = ("manuscript", "config", "assets")
) -> Path:
    if "manuscript" in include:
        (root / "manuscript" / "chapters").mkdir(parents=True)
    if "config" in include:
        (root / "config").mkdir()
        (root / "config" / "metadata.yaml").write_text(
            'title: "T"\nauthor: "A"\nlang: "en"\n', encoding="utf-8"
        )
    if "assets" in include:
        (root / "assets").mkdir()
    return root


def _two_missing_images_fixture(root: Path) -> Path:
    _scaffold(root)
    (root / "manuscript" / "chapters" / "ch1.md").write_text(
        "# Ch\n\n![a](one.png)\n\n![b](two.png)\n", encoding="utf-8"
    )
    return root


def _one_valid_image_fixture(root: Path) -> Path:
    from helpers.png import write_png

    _scaffold(root)
    write_png(root / "assets" / "ok.png")
    (root / "manuscript" / "chapters" / "ch1.md").write_text(
        "# Ch\n\n![ok](ok.png)\n", encoding="utf-8"
    )
    return root


def _run_pdf(project: Path, out: Path, *, strict_images: bool = True):
    run_export(
        project,
        formats="pdf",
        output_path=out,
        skip_images=True,
        no_type_suffix=True,
        output_file="book",
        strict_images=strict_images,
    )


# 10–13 ManuscriptaImageError behavior (real build) ------------------------


# Each row: a surface of the ManuscriptaImageError raised for the
# two-missing-images project; it must name both images
IMAGE_ERROR_SURFACES = [
    pytest.param(lambda err: err.unresolved, id="unresolved-attribute-populated"),
    pytest.param(lambda err: str(err), id="message-lists-all-unresolved"),
]


@pytest.mark.requires_pandoc
@pytest.mark.requires_latex
@pytest.mark.parametrize("surface", IMAGE_ERROR_SURFACES)
def test_image_error_names_every_unresolved_image(surface, tmp_path):
    project = _two_missing_images_fixture(tmp_path)
    out = tmp_path / "out.pdf"
    with pytest.raises(ManuscriptaImageError) as excinfo:
        _run_pdf(project, out)
    err = excinfo.value
    assert isinstance(err.unresolved, list)
    assert len(err.unresolved) == 2
    named = surface(err)
    assert "one.png" in named
    assert "two.png" in named


@pytest.mark.requires_pandoc
@pytest.mark.requires_latex
def test_image_error_not_raised_when_strict_false(tmp_path, caplog):
    project = _two_missing_images_fixture(tmp_path)
    out = tmp_path / "out.pdf"
    with caplog.at_level(logging.WARNING, logger="manuscripta.export.book"):
        _run_pdf(project, out, strict_images=False)
    warning_text = " ".join(
        rec.getMessage() for rec in caplog.records if rec.levelno >= logging.WARNING
    )
    assert "one.png" in warning_text
    assert "two.png" in warning_text


@pytest.mark.requires_pandoc
@pytest.mark.requires_latex
def test_image_error_not_raised_when_all_images_resolve(tmp_path, caplog):
    project = _one_valid_image_fixture(tmp_path)
    out = tmp_path / "out.pdf"
    with caplog.at_level(logging.WARNING, logger="manuscripta.export.book"):
        _run_pdf(project, out, strict_images=True)
    assert out.exists()
    unresolved_warnings = [
        r
        for r in caplog.records
        if r.levelno >= logging.WARNING and "unresolved image" in r.getMessage()
    ]
    assert not unresolved_warnings


# 15 Consumer-facing catch patterns ----------------------------------------


# Each row: a builder that lays the project out under tmp_path and returns
# the directory to export, the specific error the build raises
CATCH_CASES = [
    # missing config, assets
    pytest.param(
        lambda root: _scaffold(root, include=("manuscript",)),
        ManuscriptaLayoutError,
        id="layout",
    ),
    pytest.param(_two_missing_images_fixture, ManuscriptaImageError, id="image"),
]


@pytest.mark.requires_pandoc
@pytest.mark.requires_latex
@pytest.mark.parametrize("build, specific_cls", CATCH_CASES)
def test_consumer_can_catch_either_specific_or_base(build, specific_cls, tmp_path):
    target = build(tmp_path)
    out = tmp_path / "out.pdf"

    with pytest.raises(specific_cls):
        _run_pdf(target, out)

    with pytest.raises(ManuscriptaError):
        _run_pdf(target, out)
