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
    ManuscriptaPandocError as _ExcMod_Pandoc,
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


def _a_file(root: Path) -> Path:
    """A plain file where a source directory is expected."""
    file_path = root / "not-a-dir.txt"
    file_path.write_text("x", encoding="utf-8")
    return file_path


# 1–5 Hierarchy ------------------------------------------------------------

# Each row: the class, the base it must inherit from
HIERARCHY = [
    pytest.param(ManuscriptaError, Exception, id="manuscripta-error-is-exception"),
    pytest.param(
        ManuscriptaLayoutError, ManuscriptaError, id="layout-error-inherits-from-base"
    ),
    pytest.param(
        ManuscriptaImageError, ManuscriptaError, id="image-error-inherits-from-base"
    ),
    pytest.param(
        ManuscriptaPandocError, ManuscriptaError, id="pandoc-error-inherits-from-base"
    ),
]


@pytest.mark.parametrize("cls, base", HIERARCHY)
def test_hierarchy(cls, base):
    assert issubclass(cls, base)


# Each row: the name the package exports, the class manuscripta.exceptions defines
PACKAGE_EXPORTS = [
    pytest.param(ManuscriptaError, _ExcMod_Err, id="error"),
    pytest.param(ManuscriptaLayoutError, _ExcMod_Layout, id="layout-error"),
    pytest.param(ManuscriptaImageError, _ExcMod_Img, id="image-error"),
    pytest.param(ManuscriptaPandocError, _ExcMod_Pandoc, id="pandoc-error"),
]


@pytest.mark.parametrize("exported, defined", PACKAGE_EXPORTS)
def test_exceptions_exported_at_package_level(exported, defined):
    assert exported is defined


# Each row: how to make an exception a single ``except ManuscriptaError`` catches
CAUGHT_BY_BASE = [
    pytest.param(
        lambda: ManuscriptaLayoutError("/tmp/nope", ["manuscript"]), id="layout-error"
    ),
    pytest.param(
        lambda: ManuscriptaImageError(["images/missing.png"]), id="image-error"
    ),
    pytest.param(
        lambda: ManuscriptaPandocError(1, "! LaTeX err", ["pandoc"]), id="pandoc-error"
    ),
]


@pytest.mark.parametrize("make", CAUGHT_BY_BASE)
def test_single_except_catches_all(make):
    with pytest.raises(ManuscriptaError):
        raise make()


# 6–9 ManuscriptaLayoutError behavior --------------------------------------

# Each row: the subdirectories the source dir gets, the ones the error reports
# missing (in the order the layout check walks them)
LAYOUT_MISSING_CASES = [
    pytest.param(("config", "assets"), ["manuscript"], id="message-names-manuscript"),
    pytest.param(("manuscript", "assets"), ["config"], id="message-names-config"),
    pytest.param(("manuscript", "config"), ["assets"], id="message-names-assets"),
    pytest.param(("manuscript",), ["config", "assets"], id="lists-all-missing-at-once"),
]


@pytest.mark.parametrize("include, missing", LAYOUT_MISSING_CASES)
def test_layout_error_names_missing_dirs(tmp_path, include, missing):
    _scaffold(tmp_path, include=include)

    with pytest.raises(ManuscriptaLayoutError) as excinfo:
        run_export(tmp_path, formats="pdf", output_path=tmp_path / "x.pdf")

    err = excinfo.value
    assert err.missing == missing
    msg = str(err)
    for missing_dir in missing:
        assert missing_dir in msg
    assert str(tmp_path.resolve()) in msg or str(tmp_path) in msg


# Each row: how to make the bad source path under tmp_path, the reason the
# error carries, a text its (lower-cased) message carries
LAYOUT_REASON_CASES = [
    pytest.param(
        lambda root: root / "does-not-exist",
        "nonexistent",
        "does not exist",
        id="source-dir-itself-missing",
    ),
    pytest.param(
        _a_file, "not_a_directory", "not a directory", id="source-dir-is-a-file"
    ),
]


@pytest.mark.parametrize("make_path, reason, text", LAYOUT_REASON_CASES)
def test_layout_error_reason(tmp_path, make_path, reason, text):
    with pytest.raises(ManuscriptaLayoutError) as excinfo:
        run_export(make_path(tmp_path), formats="pdf", output_path=tmp_path / "x.pdf")
    err = excinfo.value
    assert err.reason == reason
    msg = str(err).lower()
    assert text in msg
    assert "subdirectories" not in msg


# 14 Defensive default for .unresolved -------------------------------------

# Each row: the constructor arguments that mean "nothing unresolved"
IMAGE_ERROR_EMPTY_ARGS = [
    pytest.param((), id="no-argument"),
    pytest.param((None,), id="none"),
    pytest.param(([],), id="empty-list"),
]


@pytest.mark.parametrize("args", IMAGE_ERROR_EMPTY_ARGS)
def test_image_error_unresolved_is_empty_list_never_none(args):
    err = ManuscriptaImageError(*args)
    assert err.unresolved == []
    for _ in err.unresolved:
        pass


# 16 Picklability ----------------------------------------------------------

# Each row: how to make the exception, a check that the round trip kept its state
PICKLE_CASES = [
    pytest.param(
        lambda: ManuscriptaLayoutError("/abs/path", ["manuscript", "config"]),
        lambda e: e.missing == ["manuscript", "config"]
        and str(e.source_dir) == "/abs/path",
        id="layout-error-missing",
    ),
    pytest.param(
        lambda: ManuscriptaLayoutError("/abs/path", reason="nonexistent"),
        lambda e: e.reason == "nonexistent",
        id="layout-error-reason",
    ),
    pytest.param(
        lambda: ManuscriptaImageError(["images/a.png", "images/b.png"]),
        lambda e: e.unresolved == ["images/a.png", "images/b.png"],
        id="image-error",
    ),
    pytest.param(
        lambda: ManuscriptaPandocError(42, "! LaTeX err", ["pandoc", "--bad"]),
        lambda e: e.returncode == 42 and "LaTeX err" in e.stderr,
        id="pandoc-error",
    ),
]


@pytest.mark.parametrize("make, check", PICKLE_CASES)
def test_exceptions_are_picklable(make, check):
    exc = make()
    restored = pickle.loads(pickle.dumps(exc))
    assert type(restored) is type(exc)
    assert isinstance(restored, ManuscriptaError)
    assert check(restored), f"Round-tripped exception lost state: {restored!r}"


# 17 Useful repr / str -----------------------------------------------------

# Each row: how to make the exception, the texts its repr and str together carry
REPR_CASES = [
    pytest.param(
        lambda: ManuscriptaLayoutError("/tmp/book", ["manuscript", "config"]),
        ["ManuscriptaLayoutError", "manuscript", "config"],
        id="layout-error",
    ),
    pytest.param(
        lambda: ManuscriptaImageError(["img/foo.png", "img/bar.png"]),
        ["ManuscriptaImageError", "foo.png", "bar.png"],
        id="image-error",
    ),
]


@pytest.mark.parametrize("make, texts", REPR_CASES)
def test_repr_is_useful(make, texts):
    err = make()
    rendered = repr(err) + " / " + str(err)
    for text in texts:
        assert text in rendered


# 18–19 ManuscriptaPandocError attribute-contract pinning ------------------
# Per ADR-0004 the rendered __str__() output is diagnostic, not contractual;
# the attributes (.returncode, .stderr, .cmd) are the programmatic surface.
# These rows pin the attribute surface so that mutations which silently
# coerce them to sentinel values (the "XXXX" and None mutants surfaced by
# Phase 4b Pass 2 triage against src/manuscripta/exceptions.py) fail here.

# Each row: the constructor arguments, the attribute read back, its value, its type
PANDOC_ATTRIBUTE_CASES = [
    # .stderr preserves empty-string input; consumers doing ``if err.stderr:``
    # rely on empty staying empty (and specifically not being coerced to some
    # sentinel like ``"XXXX"`` or ``None``).
    pytest.param(
        {"returncode": 1, "stderr": "", "cmd": ["pandoc"]},
        "stderr",
        "",
        str,
        id="stderr-preserves-empty-string",
    ),
    # .cmd is the argv list as a ``list``; consumers logging or serialising it
    # depend on the list type (not ``None``, not a tuple, not the original
    # iterable).
    pytest.param(
        {"returncode": 2, "stderr": "boom", "cmd": ["pandoc", "--to=pdf", "input.md"]},
        "cmd",
        ["pandoc", "--to=pdf", "input.md"],
        list,
        id="cmd-is-list",
    ),
    pytest.param(
        {"returncode": 42, "stderr": "boom", "cmd": ["pandoc"]},
        "returncode",
        42,
        int,
        id="returncode-is-int",
    ),
]


@pytest.mark.parametrize("kwargs, attribute, expected, kind", PANDOC_ATTRIBUTE_CASES)
def test_pandoc_error_attribute_contract(kwargs, attribute, expected, kind):
    value = getattr(ManuscriptaPandocError(**kwargs), attribute)
    assert value == expected
    assert value is not None
    assert isinstance(value, kind)
