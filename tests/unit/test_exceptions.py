"""Exception-hierarchy contract tests — unit layer.

Structural / behavioural tests that do not spawn Pandoc:
  1–9  hierarchy and layout-error messages
  14   defensive default for .unresolved
  16   picklability
  17   useful repr

Build-driven tests (10–13, 15) live in tests/e2e/test_exceptions_pdf_build.py.
"""

from __future__ import annotations

import pickle
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

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


# 1–5 Hierarchy ------------------------------------------------------------


def test_manuscripta_error_is_exception():
    assert issubclass(ManuscriptaError, Exception)


def test_layout_error_inherits_from_base():
    assert issubclass(ManuscriptaLayoutError, ManuscriptaError)


def test_image_error_inherits_from_base():
    assert issubclass(ManuscriptaImageError, ManuscriptaError)


def test_exceptions_exported_at_package_level():
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


# 6–9 ManuscriptaLayoutError behavior --------------------------------------


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
    _scaffold(tmp_path, include=("manuscript",))
    with pytest.raises(ManuscriptaLayoutError) as excinfo:
        run_export(tmp_path, formats="pdf", output_path=tmp_path / "x.pdf")
    err = excinfo.value
    assert set(err.missing) == {"config", "assets"}
    msg = str(err)
    assert "config" in msg and "assets" in msg


def test_layout_error_when_source_dir_itself_missing(tmp_path):
    nonexistent = tmp_path / "does-not-exist"
    with pytest.raises(ManuscriptaLayoutError) as excinfo:
        run_export(nonexistent, formats="pdf", output_path=tmp_path / "x.pdf")
    err = excinfo.value
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


# 14 Defensive default for .unresolved -------------------------------------


def test_image_error_unresolved_is_empty_list_never_none():
    for args in ((), (None,), ([],)):
        err = ManuscriptaImageError(*args)
        assert err.unresolved == []
        for _ in err.unresolved:
            pass


# 16 Picklability ----------------------------------------------------------


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


# 17 Useful repr / str -----------------------------------------------------


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
