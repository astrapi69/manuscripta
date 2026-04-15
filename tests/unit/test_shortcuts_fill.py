"""Coverage-uplift tests for manuscripta.export.shortcuts.

The shortcuts module is the main CLI surface — `manuscripta.export.shortcuts`
is held at 90 % despite being a CLI_WRAPPER because the v0.7.0 image bug
traversed it (see ADR-0003 and TESTING.md §3).

Each shortcut is a small wrapper around _run_full_export or
_run_print_version with option validation. These tests mock the two
runners and assert on what argv got forwarded, which invalid options got
filtered, and how --strict-opts aborts propagation.
"""

from __future__ import annotations


import pytest

pytestmark = pytest.mark.unit

from manuscripta.export import shortcuts as sc


# --- Capture helpers ------------------------------------------------------


@pytest.fixture
def capture_full(monkeypatch):
    """Replace _run_full_export and yield the captured args list."""
    captured: list[list[str]] = []
    monkeypatch.setattr(sc, "_run_full_export", lambda args: captured.append(args))
    return captured


@pytest.fixture
def capture_print(monkeypatch):
    """Replace _run_print_version and yield the captured args list."""
    captured: list[list[str]] = []
    monkeypatch.setattr(sc, "_run_print_version", lambda args: captured.append(args))
    return captured


# --- _has_any_option / _split_valid_invalid_options ----------------------


@pytest.mark.parametrize(
    "extras, names, expected",
    [
        (["--skip-images"], {"--skip-images"}, True),
        (["--skip-images=true"], {"--skip-images"}, True),
        (["--other"], {"--skip-images"}, False),
        ([], {"--skip-images"}, False),
    ],
)
def test_has_any_option(extras, names, expected):
    assert sc._has_any_option(extras, names) is expected


def test_split_valid_invalid_separates_flags():
    valid, invalid = sc._split_valid_invalid_options(
        ["--format=pdf", "--bogus", "--cover", "x.jpg", "--nope", "--epub2"],
        sc.FULL_EXPORT_ALLOWED_OPTS,
    )
    assert "--format=pdf" in valid
    assert "--cover" in valid and "x.jpg" in valid
    assert "--epub2" in valid
    assert "--bogus" in invalid
    assert "--nope" in invalid


def test_split_valid_invalid_handles_no_value_flag_at_end():
    # A flag with no value and nothing after should just go into the right bucket.
    valid, invalid = sc._split_valid_invalid_options(["--epub2"], sc.FULL_EXPORT_ALLOWED_OPTS)
    assert valid == ["--epub2"]
    assert invalid == []


# --- list_allowed_opts ---------------------------------------------------


def test_list_allowed_opts_prints_both_lists(capsys):
    sc.list_allowed_opts()
    out = capsys.readouterr().out
    assert "full_export_book.py" in out
    assert "print_version_build.py" in out
    assert "--format" in out
    assert "--book-type" in out


# --- export() and format-specific wrappers ------------------------------


def test_export_forwards_format_and_cover(capture_full):
    sc.export("pdf", "c.jpg", "--lang", "de")
    assert capture_full[0][:2] == ["--format", "pdf"]
    assert "--cover" in capture_full[0] and "c.jpg" in capture_full[0]
    assert "--lang" in capture_full[0] and "de" in capture_full[0]


def test_export_invalid_opts_logged_but_still_forwarded(capture_full, capsys):
    sc.export("pdf", None, "--unknown-flag", "--epub2")
    out = capsys.readouterr().out
    assert "Invalid options" in out
    assert "--unknown-flag" in out
    # Valid flag still forwarded.
    assert "--epub2" in capture_full[0]
    # Invalid flag NOT forwarded.
    assert "--unknown-flag" not in capture_full[0]


def test_export_strict_opts_aborts_when_invalid_present(capture_full, capsys):
    sc.export("pdf", None, "--unknown-flag", "--strict-opts")
    out = capsys.readouterr().out
    assert "Aborting due to --strict-opts" in out
    # _run_full_export not called.
    assert capture_full == []


def test_export_strict_opts_not_forwarded_as_option(capture_full):
    sc.export("pdf", None, "--strict-opts", "--epub2")
    assert "--strict-opts" not in capture_full[0]


@pytest.mark.parametrize(
    "func, fmt",
    [
        (sc.export_pdf, "pdf"),
        (sc.export_epub, "epub"),
        (sc.export_docx, "docx"),
        (sc.export_markdown, "markdown"),
        (sc.export_html, "html"),
    ],
)
def test_format_wrappers_forward_correct_format(func, fmt, capture_full):
    func()  # uses sys.argv when extra is empty
    assert capture_full[0][:2] == ["--format", fmt]


@pytest.mark.parametrize(
    "func, fmt",
    [
        (sc.export_pdf, "pdf"),
        (sc.export_epub, "epub"),
        (sc.export_docx, "docx"),
        (sc.export_markdown, "markdown"),
        (sc.export_html, "html"),
    ],
)
def test_format_wrappers_passthrough_extras(func, fmt, capture_full):
    func("--lang", "de")
    assert "--lang" in capture_full[0] and "de" in capture_full[0]


# --- _export_all_formats / export_all_formats(_with_cover) ---------------


def test_export_all_formats_without_cover(capture_full):
    sc.export_all_formats("--lang", "en")
    argv = capture_full[0]
    assert argv[:2] == ["--format", "pdf,epub,docx,markdown,html"]
    assert "--cover" not in argv
    assert "--lang" in argv


def test_export_all_formats_with_cover(capture_full):
    sc.export_all_formats_with_cover()
    argv = capture_full[0]
    assert argv[:2] == ["--format", "pdf,epub,docx,markdown,html"]
    assert "--cover" in argv
    assert any("cover.jpg" in a for a in argv)


def test_export_all_formats_strict_aborts(capture_full, capsys):
    sc.export_all_formats("--bogus", "--strict-opts")
    assert capture_full == []
    assert "Aborting" in capsys.readouterr().out


# --- export_epub2 / export_epub_with_cover / export_epub2_with_cover ----


def test_export_epub2_sets_flag(capture_full):
    sc.export_epub2("--lang", "de")
    argv = capture_full[0]
    assert "--epub2" in argv
    assert "--lang" in argv and "de" in argv


def test_export_epub2_strict_aborts(capture_full, capsys):
    sc.export_epub2("--not-a-flag", "--strict-opts")
    assert capture_full == []
    assert "Aborting" in capsys.readouterr().out


def test_export_epub_with_cover_uses_default_cover(capture_full):
    sc.export_epub_with_cover()
    argv = capture_full[0]
    assert "--format" in argv and "epub" in argv
    assert "--cover" in argv
    assert any("cover.jpg" in a for a in argv)


def test_export_epub2_with_cover(capture_full):
    sc.export_epub2_with_cover()
    argv = capture_full[0]
    assert "--epub2" in argv
    assert "--cover" in argv


def test_export_epub2_with_cover_strict_aborts(capture_full, capsys):
    sc.export_epub2_with_cover("--bogus", "--strict-opts")
    assert capture_full == []
    assert "Aborting" in capsys.readouterr().out


# --- print-version wrappers ----------------------------------------------


def test_export_print_version_epub(capture_print):
    sc.export_print_version_epub("--lang", "de")
    argv = capture_print[0]
    assert "--lang" in argv and "de" in argv


def test_export_print_version_paperback(capture_print):
    sc.export_print_version_paperback()
    argv = capture_print[0]
    assert "--book-type" in argv and "paperback" in argv


def test_export_print_version_hardcover(capture_print):
    sc.export_print_version_hardcover()
    argv = capture_print[0]
    assert "--book-type" in argv and "hardcover" in argv


def test_export_print_version_paperback_safe(capture_print):
    sc.export_print_version_paperback_safe()
    argv = capture_print[0]
    assert "--book-type" in argv and "paperback" in argv
    assert "--skip-images" in argv


def test_export_print_version_hardcover_safe(capture_print):
    sc.export_print_version_hardcover_safe()
    argv = capture_print[0]
    assert "--book-type" in argv and "hardcover" in argv
    assert "--skip-images" in argv


def test_export_print_version_safe_honors_user_image_flag(capture_print):
    # If user already passed --keep-relative-paths, safe wrappers must not
    # also inject --skip-images (the two are mutually exclusive).
    sc.export_print_version_paperback_safe("--keep-relative-paths")
    argv = capture_print[0]
    assert "--keep-relative-paths" in argv
    assert "--skip-images" not in argv


def test_export_print_version_epub_strict_aborts(capture_print, capsys):
    sc.export_print_version_epub("--bogus", "--strict-opts")
    assert capture_print == []
    assert "Aborting" in capsys.readouterr().out


def test_export_print_version_paperback_strict_aborts(capture_print, capsys):
    sc.export_print_version_paperback("--bogus", "--strict-opts")
    assert capture_print == []


def test_export_print_version_hardcover_strict_aborts(capture_print, capsys):
    sc.export_print_version_hardcover("--bogus", "--strict-opts")
    assert capture_print == []


def test_export_print_version_paperback_safe_strict_aborts(capture_print, capsys):
    sc.export_print_version_paperback_safe("--bogus", "--strict-opts")
    assert capture_print == []


def test_export_print_version_hardcover_safe_strict_aborts(capture_print, capsys):
    sc.export_print_version_hardcover_safe("--bogus", "--strict-opts")
    assert capture_print == []


# --- export_safe + wrappers ---------------------------------------------


@pytest.mark.parametrize(
    "func, fmt",
    [
        (sc.export_pdf_safe, "pdf"),
        (sc.export_epub_safe, "epub"),
        (sc.export_docx_safe, "docx"),
        (sc.export_markdown_safe, "markdown"),
        (sc.export_html_safe, "html"),
    ],
)
def test_safe_wrappers_inject_skip_images(func, fmt, capture_full):
    func()
    argv = capture_full[0]
    assert argv[:2] == ["--format", fmt]
    assert "--skip-images" in argv


def test_safe_wrapper_does_not_inject_when_user_passed_flag(capture_full):
    sc.export_pdf_safe("--keep-relative-paths")
    argv = capture_full[0]
    assert "--keep-relative-paths" in argv
    # Should not double up.
    assert "--skip-images" not in argv


def test_export_safe_strict_aborts(capture_full, capsys):
    sc.export_safe("pdf", "--bogus", "--strict-opts")
    assert capture_full == []
    assert "Aborting" in capsys.readouterr().out


# --- main() dispatch -----------------------------------------------------


def _record_call(name: str, monkeypatch) -> list[tuple]:
    calls: list[tuple] = []

    def fake(*a, **kw):
        calls.append((a, kw))

    monkeypatch.setattr(sc, name, fake)
    return calls


def test_main_export_dispatches_to_export(monkeypatch):
    calls = _record_call("export", monkeypatch)
    sc.main(["export", "--format", "pdf"])
    assert calls
    args, _ = calls[0]
    assert args[0] == "pdf"


def test_main_epub2(monkeypatch):
    calls = _record_call("export_epub2", monkeypatch)
    sc.main(["epub2"])
    assert calls


def test_main_epub2_with_cover(monkeypatch):
    calls = _record_call("export_epub2_with_cover", monkeypatch)
    sc.main(["epub2-with-cover"])
    assert calls


def test_main_print_version_paperback(monkeypatch):
    calls = _record_call("export_print_version_paperback", monkeypatch)
    sc.main(["print-version", "--book-type", "paperback"])
    assert calls


def test_main_print_version_hardcover(monkeypatch):
    calls = _record_call("export_print_version_hardcover", monkeypatch)
    sc.main(["print-version", "--book-type", "hardcover"])
    assert calls


def test_main_print_version_default_ebook(monkeypatch):
    calls = _record_call("export_print_version_epub", monkeypatch)
    sc.main(["print-version"])
    assert calls


def test_main_safe(monkeypatch):
    calls = _record_call("export_safe", monkeypatch)
    sc.main(["safe", "--format", "pdf"])
    assert calls


def test_main_list_allowed_opts(capsys):
    sc.main(["list-allowed-opts"])
    assert "full_export_book.py" in capsys.readouterr().out


def test_main_strips_leading_double_dash_from_passthrough(monkeypatch):
    calls = _record_call("export", monkeypatch)
    sc.main(["export", "--format", "pdf", "--", "--lang", "de"])
    args, _ = calls[0]
    # args = (format, cover, *extras) — "--" must have been stripped
    extras = args[2:]
    assert "--" not in extras
    assert "--lang" in extras


def test_main_strict_opts_is_forwarded(monkeypatch):
    calls = _record_call("export", monkeypatch)
    sc.main(["export", "--format", "pdf", "--strict-opts"])
    args, _ = calls[0]
    assert "--strict-opts" in args[2:]
