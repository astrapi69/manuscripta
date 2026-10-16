# tests/test_shortcuts_export_passthrough.py
import pytest

pytestmark = pytest.mark.unit
from unittest.mock import patch
import manuscripta.export.shortcuts as se


def test_export_pdf_passthrough():
    with patch("manuscripta.export.shortcuts.export_main") as exp:
        se.export(
            "pdf", None, "--skip-images", "--keep-relative-paths", "--output-file=foo"
        )
        _ = exp.call_args  # export_main(*args, **kwargs)
        # sys.argv is assembled inside _run_full_export; we just ensure it was called once
        assert exp.called


ALL_FORMATS = "pdf,epub,docx,markdown,html"
DEFAULT_COVER = "assets/covers/cover.jpg"

# Each row: the wrapper, its options and the argv it hands to
# full_export_book.py: --format first, then the valid options unchanged.
WRAPPER_ARGS_CASES = [
    pytest.param(
        se.export_html,
        ("--skip-images", "--output-file=foo", "--lang=de"),
        ["--format", "html", "--skip-images", "--output-file=foo", "--lang=de"],
        id="export-html-forwards-valid-options",
    ),
    # Safe-Mode erzwingt mindestens einen Schutz-Flag
    pytest.param(
        se.export_html_safe,
        ("--output-file=bar",),
        ["--format", "html", "--skip-images", "--output-file=bar"],
        id="export-html-safe-adds-skip-images-by-default",
    ),
    # User gibt schon einen der Safe-Flags mit: keinen doppelten Safe-Flag injizieren
    pytest.param(
        se.export_html_safe,
        ("--keep-relative-paths", "--output-file=baz"),
        ["--format", "html", "--keep-relative-paths", "--output-file=baz"],
        id="export-html-safe-does-not-duplicate-safety-flags",
    ),
    # Alle einfachen Wrapper (pdf/epub/docx/markdown/html) sollen --format
    # korrekt setzen und gültige Optionen unverändert weiterreichen
    pytest.param(
        se.export_pdf,
        ("--output-file=mybook", "--lang=de"),
        ["--format", "pdf", "--output-file=mybook", "--lang=de"],
        id="export-wrappers-forward-args-and-format-pdf",
    ),
    pytest.param(
        se.export_epub,
        ("--output-file=mybook", "--lang=de"),
        ["--format", "epub", "--output-file=mybook", "--lang=de"],
        id="export-wrappers-forward-args-and-format-epub",
    ),
    pytest.param(
        se.export_docx,
        ("--output-file=mybook", "--lang=de"),
        ["--format", "docx", "--output-file=mybook", "--lang=de"],
        id="export-wrappers-forward-args-and-format-docx",
    ),
    pytest.param(
        se.export_markdown,
        ("--output-file=mybook", "--lang=de"),
        ["--format", "markdown", "--output-file=mybook", "--lang=de"],
        id="export-wrappers-forward-args-and-format-markdown",
    ),
    pytest.param(
        se.export_html,
        ("--output-file=mybook", "--lang=de"),
        ["--format", "html", "--output-file=mybook", "--lang=de"],
        id="export-wrappers-forward-args-and-format-html",
    ),
    # Wenn der Aufrufer schon --keep-relative-paths/--skip-images setzt,
    # darf kein zusätzlicher Safety-Flag erzwungen werden.
    pytest.param(
        se.export_pdf_safe,
        ("--keep-relative-paths", "--output-file=draft"),
        ["--format", "pdf", "--keep-relative-paths", "--output-file=draft"],
        id="export-safe-wrappers-respect-existing-safety-flag-pdf",
    ),
    pytest.param(
        se.export_epub_safe,
        ("--keep-relative-paths", "--output-file=draft"),
        ["--format", "epub", "--keep-relative-paths", "--output-file=draft"],
        id="export-safe-wrappers-respect-existing-safety-flag-epub",
    ),
    pytest.param(
        se.export_docx_safe,
        ("--keep-relative-paths", "--output-file=draft"),
        ["--format", "docx", "--keep-relative-paths", "--output-file=draft"],
        id="export-safe-wrappers-respect-existing-safety-flag-docx",
    ),
    pytest.param(
        se.export_markdown_safe,
        ("--keep-relative-paths", "--output-file=draft"),
        ["--format", "markdown", "--keep-relative-paths", "--output-file=draft"],
        id="export-safe-wrappers-respect-existing-safety-flag-markdown",
    ),
    pytest.param(
        se.export_html_safe,
        ("--keep-relative-paths", "--output-file=draft"),
        ["--format", "html", "--keep-relative-paths", "--output-file=draft"],
        id="export-safe-wrappers-respect-existing-safety-flag-html",
    ),
    # Formatliste inkl. html, Cover gesetzt, Extra-Option weitergereicht
    pytest.param(
        se.export_all_formats_with_cover,
        ("--output-file=mybook",),
        ["--format", ALL_FORMATS, "--cover", DEFAULT_COVER, "--output-file=mybook"],
        id="export-all-formats-with-cover-includes-html-and-cover",
    ),
    # kein Cover-Argument
    pytest.param(
        se.export_all_formats,
        ("--output-file=test",),
        ["--format", ALL_FORMATS, "--output-file=test"],
        id="export-all-formats-without-cover",
    ),
]


@pytest.mark.parametrize("func, extra, args", WRAPPER_ARGS_CASES)
def test_wrappers_forward_args(func, extra, args):
    with patch("manuscripta.export.shortcuts._run_full_export") as run:
        func(*extra)

        run.assert_called_once_with(args)


# Each row: the options and what the abort message must name. An unknown
# option starts no export (#18), with --strict-opts just the same.
INVALID_OPTION_CASES = [
    pytest.param(
        ("--output-file=ok", "--bogus-flag", "value"),
        "--bogus-flag value",
        id="unknown-flag-with-value",
    ),
    pytest.param(
        ("--output-file=ok", "--bogus-flag", "--strict-opts"),
        "--bogus-flag",
        id="strict-opts-changes-nothing",
    ),
    pytest.param(("manuscript",), "manuscript", id="stray-positional"),
]


@pytest.mark.parametrize("extra, named", INVALID_OPTION_CASES)
def test_export_aborts_on_invalid_options(extra, named, capsys):
    with patch("manuscripta.export.shortcuts._run_full_export") as run:
        with pytest.raises(SystemExit) as exc:
            se.export_pdf(*extra)

        assert exc.value.code == 2
        run.assert_not_called()

        out, _ = capsys.readouterr()
        assert "Invalid options for full_export_book.py" in out
        assert named in out


@pytest.mark.parametrize("flag", ["--help", "-h"])
def test_export_help_prints_usage_instead_of_exporting(flag, capsys):
    with patch("manuscripta.export.shortcuts._run_full_export") as run:
        se.export_pdf(flag)

        run.assert_not_called()
        out, _ = capsys.readouterr()
        assert out.startswith("usage: ")
        assert "full-export --format pdf [OPTION ...]" in out
