"""Exception-hierarchy contract tests.

Seventeen tests: the cheap structural/behavioural ones (1–9, 14, 16–17)
need no Pandoc; 10–13 and 15 drive an actual build so require pandoc +
xelatex. The full file runs in under two seconds on the fast path, and a
few extra seconds for the build-based tests where the toolchain is
present.
"""

from __future__ import annotations

import logging
import pickle
from pathlib import Path

import pytest

from manuscripta import (
    ManuscriptaError,
    ManuscriptaImageError,
    ManuscriptaLayoutError,
    ManuscriptaPandocError,
)
from manuscripta.exceptions import (
    ManuscriptaError as _ExcMod_Err,
    ManuscriptaImageError as _ExcMod_Img,
    ManuscriptaLayoutError as _ExcMod_Layout,
)
from manuscripta.export.book import run_export


# --------------------------------------------------------------------------
# Shared helpers for the build-based tests
# --------------------------------------------------------------------------


def _scaffold(root: Path, *, include: tuple[str, ...] = ("manuscript", "config", "assets")) -> Path:
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


def _run_pdf(project: Path, out: Path, *, strict_images: bool = True):
    """Invoke the library for a PDF build rooted at ``project``."""
    run_export(
        project,
        formats="pdf",
        output_path=out,
        skip_images=True,
        no_type_suffix=True,
        output_file="book",
        strict_images=strict_images,
    )


# --------------------------------------------------------------------------
# 1–5: Hierarchy
# --------------------------------------------------------------------------


def test_manuscripta_error_is_exception():
    assert issubclass(ManuscriptaError, Exception)


def test_layout_error_inherits_from_base():
    assert issubclass(ManuscriptaLayoutError, ManuscriptaError)


def test_image_error_inherits_from_base():
    assert issubclass(ManuscriptaImageError, ManuscriptaError)


def test_exceptions_exported_at_package_level():
    # Package-level re-exports must be the very same objects as the module
    # definitions — not accidental rebindings or copies.
    assert ManuscriptaError is _ExcMod_Err
    assert ManuscriptaLayoutError is _ExcMod_Layout
    assert ManuscriptaImageError is _ExcMod_Img


@pytest.mark.parametrize(
    "exc",
    [
        ManuscriptaLayoutError("/tmp/nope", ["manuscript"]),
        ManuscriptaImageError(["images/missing.png"]),
    ],
)
def test_single_except_catches_all(exc):
    with pytest.raises(ManuscriptaError):
        raise exc


# --------------------------------------------------------------------------
# 6–9: ManuscriptaLayoutError behavior
# --------------------------------------------------------------------------


@pytest.mark.parametrize("missing_dir", ["manuscript", "config", "assets"])
def test_layout_error_message_names_missing_dir(tmp_path, missing_dir):
    keep = tuple(d for d in ("manuscript", "config", "assets") if d != missing_dir)
    _scaffold(tmp_path, include=keep)

    with pytest.raises(ManuscriptaLayoutError) as excinfo:
        run_export(tmp_path, formats="pdf", output_path=tmp_path / "x.pdf")

    err = excinfo.value
    assert err.missing == [missing_dir]
    msg = str(err)
    assert missing_dir in msg
    assert str(tmp_path.resolve()) in msg or str(tmp_path) in msg


def test_layout_error_lists_all_missing_at_once(tmp_path):
    # Only create `manuscript/`; `config/` and `assets/` are missing.
    _scaffold(tmp_path, include=("manuscript",))

    with pytest.raises(ManuscriptaLayoutError) as excinfo:
        run_export(tmp_path, formats="pdf", output_path=tmp_path / "x.pdf")

    err = excinfo.value
    assert set(err.missing) == {"config", "assets"}
    msg = str(err)
    assert "config" in msg and "assets" in msg, (
        "Error message must name every missing dir, not just the first one"
    )


def test_layout_error_when_source_dir_itself_missing(tmp_path):
    nonexistent = tmp_path / "does-not-exist"
    with pytest.raises(ManuscriptaLayoutError) as excinfo:
        run_export(nonexistent, formats="pdf", output_path=tmp_path / "x.pdf")

    err = excinfo.value
    # Must be the specific "source_dir missing" flavor, not "subdir missing".
    assert err.reason == "nonexistent"
    msg = str(err).lower()
    assert "does not exist" in msg
    assert "subdirectories" not in msg


def test_layout_error_when_source_dir_is_a_file(tmp_path):
    file_path = tmp_path / "not-a-dir.txt"
    file_path.write_text("x", encoding="utf-8")

    with pytest.raises(ManuscriptaLayoutError) as excinfo:
        run_export(file_path, formats="pdf", output_path=tmp_path / "x.pdf")

    err = excinfo.value
    assert err.reason == "not_a_directory"
    assert "not a directory" in str(err).lower()


# --------------------------------------------------------------------------
# 10–13: ManuscriptaImageError behavior (needs a real build)
# --------------------------------------------------------------------------


def _two_missing_images_fixture(root: Path) -> Path:
    _scaffold(root)
    (root / "manuscript" / "chapters" / "ch1.md").write_text(
        "# Ch\n\n![a](one.png)\n\n![b](two.png)\n", encoding="utf-8"
    )
    return root


def _one_valid_image_fixture(root: Path) -> Path:
    from conftest import write_png  # type: ignore[import-not-found]

    _scaffold(root)
    write_png(root / "assets" / "ok.png")
    (root / "manuscript" / "chapters" / "ch1.md").write_text(
        "# Ch\n\n![ok](ok.png)\n", encoding="utf-8"
    )
    return root


@pytest.mark.requires_pandoc
@pytest.mark.requires_latex
def test_image_error_unresolved_attribute_populated(tmp_path):
    project = _two_missing_images_fixture(tmp_path)
    out = tmp_path / "out.pdf"
    with pytest.raises(ManuscriptaImageError) as excinfo:
        _run_pdf(project, out)
    err = excinfo.value
    assert isinstance(err.unresolved, list)
    assert len(err.unresolved) == 2
    assert "one.png" in err.unresolved
    assert "two.png" in err.unresolved


@pytest.mark.requires_pandoc
@pytest.mark.requires_latex
def test_image_error_message_lists_all_unresolved(tmp_path):
    project = _two_missing_images_fixture(tmp_path)
    out = tmp_path / "out.pdf"
    with pytest.raises(ManuscriptaImageError) as excinfo:
        _run_pdf(project, out)
    msg = str(excinfo.value)
    assert "one.png" in msg
    assert "two.png" in msg


@pytest.mark.requires_pandoc
@pytest.mark.requires_latex
def test_image_error_not_raised_when_strict_false(tmp_path, caplog):
    project = _two_missing_images_fixture(tmp_path)
    out = tmp_path / "out.pdf"
    with caplog.at_level(logging.WARNING, logger="manuscripta.export.book"):
        _run_pdf(project, out, strict_images=False)

    warning_text = " ".join(rec.getMessage() for rec in caplog.records if rec.levelno >= logging.WARNING)
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
        r for r in caplog.records
        if r.levelno >= logging.WARNING and "unresolved image" in r.getMessage()
    ]
    assert not unresolved_warnings


# --------------------------------------------------------------------------
# 14: Defensive default for .unresolved
# --------------------------------------------------------------------------


def test_image_error_unresolved_is_empty_list_never_none():
    for args in ((), (None,), ([],)):
        err = ManuscriptaImageError(*args)
        assert err.unresolved == []
        # Proves iteration won't blow up downstream.
        for _ in err.unresolved:
            pass


# --------------------------------------------------------------------------
# 15: Consumer-facing catch patterns (documentation-by-test)
# --------------------------------------------------------------------------


@pytest.mark.requires_pandoc
@pytest.mark.requires_latex
@pytest.mark.parametrize(
    "kind",
    ["layout", "image"],
)
def test_consumer_can_catch_either_specific_or_base(tmp_path, kind):
    if kind == "layout":
        target = tmp_path
        _scaffold(tmp_path, include=("manuscript",))  # missing config, assets
        specific_cls = ManuscriptaLayoutError
    else:
        target = _two_missing_images_fixture(tmp_path)
        specific_cls = ManuscriptaImageError

    out = tmp_path / "out.pdf"

    # 1. `except SpecificError` catches it.
    with pytest.raises(specific_cls):
        _run_pdf(target, out)

    # 2. `except ManuscriptaError` (the base) also catches it.
    with pytest.raises(ManuscriptaError):
        _run_pdf(target, out)


# --------------------------------------------------------------------------
# 16: Picklability
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "exc,check",
    [
        (
            ManuscriptaLayoutError("/abs/path", ["manuscript", "config"]),
            lambda e: e.missing == ["manuscript", "config"]
            and str(e.source_dir) == "/abs/path",
        ),
        (
            ManuscriptaLayoutError("/abs/path", reason="nonexistent"),
            lambda e: e.reason == "nonexistent",
        ),
        (
            ManuscriptaImageError(["images/a.png", "images/b.png"]),
            lambda e: e.unresolved == ["images/a.png", "images/b.png"],
        ),
        (
            ManuscriptaPandocError(42, "! LaTeX err", ["pandoc", "--bad"]),
            lambda e: e.returncode == 42 and "LaTeX err" in e.stderr,
        ),
    ],
)
def test_exceptions_are_picklable(exc, check):
    restored = pickle.loads(pickle.dumps(exc))
    assert type(restored) is type(exc)
    assert isinstance(restored, ManuscriptaError)
    assert check(restored), f"Round-tripped exception lost state: {restored!r}"


# --------------------------------------------------------------------------
# 17: Useful repr / str
# --------------------------------------------------------------------------


def test_layout_error_repr_is_useful():
    err = ManuscriptaLayoutError("/tmp/book", ["manuscript", "config"])
    rendered = repr(err) + " / " + str(err)
    assert "ManuscriptaLayoutError" in rendered
    assert "manuscript" in rendered
    assert "config" in rendered


def test_image_error_repr_is_useful():
    err = ManuscriptaImageError(["img/foo.png", "img/bar.png"])
    rendered = repr(err) + " / " + str(err)
    assert "ManuscriptaImageError" in rendered
    assert "foo.png" in rendered
    assert "bar.png" in rendered
