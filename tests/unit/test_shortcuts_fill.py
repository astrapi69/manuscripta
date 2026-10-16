"""Coverage-uplift tests for manuscripta.export.shortcuts.

The shortcuts module is the main CLI surface — `manuscripta.export.shortcuts`
is held at 90 % despite being a CLI_WRAPPER because the v0.7.0 image bug
traversed it (see ADR-0003 and TESTING.md §3).

Each shortcut is a small wrapper around _run_full_export or
_run_print_version with option validation. These tests mock the two
runners and assert on what argv got forwarded, that an unknown option
aborts before the runner is called, and that --help prints the usage
instead of exporting.
"""

from __future__ import annotations

import sys

import pytest

pytestmark = pytest.mark.unit

from manuscripta.export import shortcuts as sc


# --- Capture helpers ------------------------------------------------------


@pytest.fixture(autouse=True)
def shortcut_argv(monkeypatch):
    """A shortcut called without extras reads sys.argv[1:]; keep pytest's out."""
    monkeypatch.setattr(sys, "argv", ["export-shortcut"])


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


# Each row: the passthrough tokens, the ones to forward, the unknown ones.
SPLIT_CASES = [
    pytest.param(
        ["--format=pdf", "--bogus", "--cover", "x.jpg", "--nope", "--epub2"],
        ["--format=pdf", "--cover", "x.jpg", "--epub2"],
        ["--bogus", "--nope"],
        id="separates-flags",
    ),
    # A flag with no value and nothing after should just go into the right bucket.
    pytest.param(["--epub2"], ["--epub2"], [], id="handles-no-value-flag-at-end"),
    pytest.param(
        ["manuscript", "--lang", "de", "-x", "--epub2"],
        ["--lang", "de", "--epub2"],
        ["manuscript", "-x"],
        id="single-dash-and-positionals-are-unknown",
    ),
    pytest.param(
        ["--bogus=1", "--lang=de"],
        ["--lang=de"],
        ["--bogus=1"],
        id="unknown-with-inline-value",
    ),
    pytest.param(
        ["--bogus", "x", "--lang", "de"],
        ["--lang", "de"],
        ["--bogus", "x"],
        id="unknown-takes-its-value-along",
    ),
    pytest.param([], [], [], id="nothing"),
]


@pytest.mark.parametrize("extra, valid, invalid", SPLIT_CASES)
def test_split_valid_invalid_options(extra, valid, invalid):
    assert sc._split_valid_invalid_options(extra, sc.FULL_EXPORT_ALLOWED_OPTS) == (
        valid,
        invalid,
    )


# The CLI layer of manuscripta.export.book. README documents
# `export-pdf --source-dir=...`, which the allow-list dropped before #18.
@pytest.mark.parametrize(
    "name", ["--source-dir", "--resource-path", "--strict-images", "--no-strict-images"]
)
def test_full_export_allow_list_covers_the_cli_layer_option(name):
    assert name in sc.FULL_EXPORT_ALLOWED_OPTS


def test_print_version_allow_list_matches_its_parser():
    from manuscripta.export.print_version import _build_arg_parser

    parser_opts = {
        opt
        for action in _build_arg_parser()._actions
        for opt in action.option_strings
        if opt.startswith("--") and opt not in {"--help", "--format"}
    }
    assert sc.PRINT_VERSION_ALLOWED_OPTS == parser_opts


# --- list_allowed_opts ---------------------------------------------------


def test_list_allowed_opts_prints_both_lists(capsys):
    sc.list_allowed_opts()
    out = capsys.readouterr().out
    assert "full_export_book.py" in out
    assert "print_version_build.py" in out
    assert "--format" in out
    assert "--book-type" in out


# --- export() ------------------------------------------------------------


# Each row: the passthrough tokens and the token the abort message must name.
# --strict-opts is accepted for compatibility: unknown options abort with or
# without it.
UNKNOWN_OPTION_CASES = [
    pytest.param(("--unknown-flag", "--epub2"), "--unknown-flag", id="long-option"),
    pytest.param(
        ("--unknown-flag", "--strict-opts"),
        "--unknown-flag",
        id="strict-opts-changes-nothing",
    ),
    pytest.param(("manuscript",), "manuscript", id="stray-positional"),
    pytest.param(("-x",), "-x", id="short-option"),
    pytest.param(("--lang", "de", "--bogus=1"), "--bogus=1", id="with-inline-value"),
    pytest.param(("--bogus", "value"), "--bogus value", id="with-value"),
]


@pytest.mark.parametrize("extra, named", UNKNOWN_OPTION_CASES)
def test_export_unknown_option_aborts_with_status_2(extra, named, capture_full, capsys):
    with pytest.raises(SystemExit) as exc:
        sc.export("pdf", None, *extra)
    assert exc.value.code == 2
    out = capsys.readouterr().out
    assert "Invalid options for full_export_book.py" in out
    assert named in out
    assert "Aborting" in out and "--help" in out
    # _run_full_export not called: nothing is exported.
    assert capture_full == []


# Each row: the cover, the passthrough tokens, what the forwarded argv must
# contain and what it must not.
FORWARD_CASES = [
    pytest.param(
        "c.jpg",
        ("--lang", "de"),
        ["--cover", "c.jpg", "--lang", "de"],
        [],
        id="format-and-cover",
    ),
    pytest.param(
        None,
        ("--", "--lang", "de"),
        ["--lang", "de"],
        ["--"],
        id="bare-double-dash-dropped",
    ),
    pytest.param(
        None,
        ("--source-dir=/tmp/book", "--no-strict-images"),
        ["--source-dir=/tmp/book", "--no-strict-images"],
        [],
        id="cli-layer-options-forwarded",
    ),
    pytest.param(
        None,
        ("--resource-path", "assets", "--strict-images"),
        ["--resource-path", "assets", "--strict-images"],
        [],
        id="cli-layer-option-with-value",
    ),
    pytest.param(
        None,
        ("--strict-opts", "--epub2"),
        ["--epub2"],
        ["--strict-opts"],
        id="strict-opts-not-forwarded-as-option",
    ),
]


@pytest.mark.parametrize("cover, extra, present, absent", FORWARD_CASES)
def test_export_forwards(cover, extra, present, absent, capture_full):
    sc.export("pdf", cover, *extra)
    argv = capture_full[0]
    assert argv[:2] == ["--format", "pdf"]
    for tok in present:
        assert tok in argv
    for tok in absent:
        assert tok not in argv


# --- the wrappers: the argv each one forwards -----------------------------

ALL_FORMATS = "pdf,epub,docx,markdown,html"
DEFAULT_COVER = "assets/covers/cover.jpg"

# Each row: the wrapper, its passthrough tokens, the target it runs and the
# exact argv it forwards. A wrapper called without extras reads sys.argv[1:],
# which the shortcut_argv fixture keeps empty.
WRAPPER_ARGV_CASES = [
    # The format wrappers set --format ...
    pytest.param(
        sc.export_pdf,
        (),
        sc.FULL_EXPORT,
        ["--format", "pdf"],
        id="format-wrappers-forward-correct-format-pdf",
    ),
    pytest.param(
        sc.export_epub,
        (),
        sc.FULL_EXPORT,
        ["--format", "epub"],
        id="format-wrappers-forward-correct-format-epub",
    ),
    pytest.param(
        sc.export_docx,
        (),
        sc.FULL_EXPORT,
        ["--format", "docx"],
        id="format-wrappers-forward-correct-format-docx",
    ),
    pytest.param(
        sc.export_markdown,
        (),
        sc.FULL_EXPORT,
        ["--format", "markdown"],
        id="format-wrappers-forward-correct-format-markdown",
    ),
    pytest.param(
        sc.export_html,
        (),
        sc.FULL_EXPORT,
        ["--format", "html"],
        id="format-wrappers-forward-correct-format-html",
    ),
    # ... and pass the extras through
    pytest.param(
        sc.export_pdf,
        ("--lang", "de"),
        sc.FULL_EXPORT,
        ["--format", "pdf", "--lang", "de"],
        id="format-wrappers-passthrough-extras-pdf",
    ),
    pytest.param(
        sc.export_epub,
        ("--lang", "de"),
        sc.FULL_EXPORT,
        ["--format", "epub", "--lang", "de"],
        id="format-wrappers-passthrough-extras-epub",
    ),
    pytest.param(
        sc.export_docx,
        ("--lang", "de"),
        sc.FULL_EXPORT,
        ["--format", "docx", "--lang", "de"],
        id="format-wrappers-passthrough-extras-docx",
    ),
    pytest.param(
        sc.export_markdown,
        ("--lang", "de"),
        sc.FULL_EXPORT,
        ["--format", "markdown", "--lang", "de"],
        id="format-wrappers-passthrough-extras-markdown",
    ),
    pytest.param(
        sc.export_html,
        ("--lang", "de"),
        sc.FULL_EXPORT,
        ["--format", "html", "--lang", "de"],
        id="format-wrappers-passthrough-extras-html",
    ),
    # _export_all_formats / export_all_formats(_with_cover)
    pytest.param(
        sc.export_all_formats,
        ("--lang", "en"),
        sc.FULL_EXPORT,
        ["--format", ALL_FORMATS, "--lang", "en"],
        id="export-all-formats-without-cover",
    ),
    pytest.param(
        sc.export_all_formats_with_cover,
        (),
        sc.FULL_EXPORT,
        ["--format", ALL_FORMATS, "--cover", DEFAULT_COVER],
        id="export-all-formats-with-cover",
    ),
    # export_epub2 / export_epub_with_cover / export_epub2_with_cover
    pytest.param(
        sc.export_epub2,
        ("--lang", "de"),
        sc.FULL_EXPORT,
        ["--epub2", "--lang", "de"],
        id="export-epub2-sets-flag",
    ),
    pytest.param(
        sc.export_epub_with_cover,
        (),
        sc.FULL_EXPORT,
        ["--format", "epub", "--cover", DEFAULT_COVER],
        id="export-epub-with-cover-uses-default-cover",
    ),
    pytest.param(
        sc.export_epub2_with_cover,
        (),
        sc.FULL_EXPORT,
        ["--epub2", "--cover", DEFAULT_COVER],
        id="export-epub2-with-cover",
    ),
    # The print-version wrappers
    pytest.param(
        sc.export_print_version_epub,
        ("--lang", "de"),
        sc.PRINT_VERSION,
        ["--lang", "de"],
        id="export-print-version-epub",
    ),
    pytest.param(
        sc.export_print_version_paperback,
        (),
        sc.PRINT_VERSION,
        ["--book-type", "paperback"],
        id="export-print-version-paperback",
    ),
    pytest.param(
        sc.export_print_version_hardcover,
        (),
        sc.PRINT_VERSION,
        ["--book-type", "hardcover"],
        id="export-print-version-hardcover",
    ),
    pytest.param(
        sc.export_print_version_paperback_safe,
        (),
        sc.PRINT_VERSION,
        ["--book-type", "paperback", "--skip-images"],
        id="export-print-version-paperback-safe",
    ),
    pytest.param(
        sc.export_print_version_hardcover_safe,
        (),
        sc.PRINT_VERSION,
        ["--book-type", "hardcover", "--skip-images"],
        id="export-print-version-hardcover-safe",
    ),
    # If user already passed --keep-relative-paths, safe wrappers must not
    # also inject --skip-images (the two are mutually exclusive).
    pytest.param(
        sc.export_print_version_paperback_safe,
        ("--keep-relative-paths",),
        sc.PRINT_VERSION,
        ["--book-type", "paperback", "--keep-relative-paths"],
        id="export-print-version-safe-honors-user-image-flag",
    ),
    pytest.param(
        sc.export_print_version_hardcover_safe,
        ("--skip-images",),
        sc.PRINT_VERSION,
        ["--book-type", "hardcover", "--skip-images"],
        id="export-print-version-safe-does-not-double-skip-images",
    ),
    # The options print_version_build.py consumes itself (its parser, pinned by
    # test_print_version_allow_list_matches_its_parser)
    pytest.param(
        sc.export_print_version_epub,
        ("--dry-run",),
        sc.PRINT_VERSION,
        ["--dry-run"],
        id="export-print-version-forwards-its-own-option-dry-run",
    ),
    pytest.param(
        sc.export_print_version_epub,
        ("--restore",),
        sc.PRINT_VERSION,
        ["--restore"],
        id="export-print-version-forwards-its-own-option-restore",
    ),
    pytest.param(
        sc.export_print_version_epub,
        ("--exact-name",),
        sc.PRINT_VERSION,
        ["--exact-name"],
        id="export-print-version-forwards-its-own-option-exact-name",
    ),
    # export_safe + wrappers
    pytest.param(
        sc.export_pdf_safe,
        (),
        sc.FULL_EXPORT,
        ["--format", "pdf", "--skip-images"],
        id="safe-wrappers-inject-skip-images-pdf",
    ),
    pytest.param(
        sc.export_epub_safe,
        (),
        sc.FULL_EXPORT,
        ["--format", "epub", "--skip-images"],
        id="safe-wrappers-inject-skip-images-epub",
    ),
    pytest.param(
        sc.export_docx_safe,
        (),
        sc.FULL_EXPORT,
        ["--format", "docx", "--skip-images"],
        id="safe-wrappers-inject-skip-images-docx",
    ),
    pytest.param(
        sc.export_markdown_safe,
        (),
        sc.FULL_EXPORT,
        ["--format", "markdown", "--skip-images"],
        id="safe-wrappers-inject-skip-images-markdown",
    ),
    pytest.param(
        sc.export_html_safe,
        (),
        sc.FULL_EXPORT,
        ["--format", "html", "--skip-images"],
        id="safe-wrappers-inject-skip-images-html",
    ),
    # Should not double up.
    pytest.param(
        sc.export_pdf_safe,
        ("--keep-relative-paths",),
        sc.FULL_EXPORT,
        ["--format", "pdf", "--keep-relative-paths"],
        id="safe-wrapper-does-not-inject-when-user-passed-flag",
    ),
    pytest.param(
        sc.export_epub_safe,
        ("--skip-images",),
        sc.FULL_EXPORT,
        ["--format", "epub", "--skip-images"],
        id="safe-wrapper-does-not-double-skip-images",
    ),
]


@pytest.mark.parametrize("func, extra, target, argv", WRAPPER_ARGV_CASES)
def test_wrappers_forward_their_argv(
    func, extra, target, argv, capture_full, capture_print
):
    func(*extra)
    captured = {sc.FULL_EXPORT: capture_full, sc.PRINT_VERSION: capture_print}
    assert captured.pop(target) == [argv]
    # The other runner is not called.
    assert list(captured.values()) == [[]]


# --- every wrapper: --help / -h and unknown options ----------------------

FULL_EXPORT_WRAPPERS = [
    sc.export_pdf,
    sc.export_epub,
    sc.export_docx,
    sc.export_markdown,
    sc.export_html,
    sc.export_all_formats,
    sc.export_all_formats_with_cover,
    sc.export_epub2,
    sc.export_epub_with_cover,
    sc.export_epub2_with_cover,
    sc.export_pdf_safe,
    sc.export_epub_safe,
    sc.export_docx_safe,
    sc.export_markdown_safe,
    sc.export_html_safe,
]

PRINT_VERSION_WRAPPERS = [
    sc.export_print_version_epub,
    sc.export_print_version_paperback,
    sc.export_print_version_hardcover,
    sc.export_print_version_paperback_safe,
    sc.export_print_version_hardcover_safe,
]


# Every wrapper with the target whose allow-list it validates against
ALL_WRAPPERS = [
    *[pytest.param(f, sc.FULL_EXPORT, id=f.__name__) for f in FULL_EXPORT_WRAPPERS],
    *[pytest.param(f, sc.PRINT_VERSION, id=f.__name__) for f in PRINT_VERSION_WRAPPERS],
]

# What the help of a target must show: its "Runs ... as" line and one option
# of every parser it prints (print-version-build forwards to full-export)
HELP_FRAGMENTS = {
    sc.FULL_EXPORT: [
        "Runs full_export_book.py as\n  full-export ",
        "--output-file OUTPUT_FILE",
        "--source-dir SOURCE_DIR",
    ],
    sc.PRINT_VERSION: [
        "Runs print_version_build.py as\n  print-version-build ",
        "--export-format {epub,pdf}",
        "--output-file OUTPUT_FILE",
        "--source-dir SOURCE_DIR",
    ],
}


@pytest.mark.parametrize("func, target", ALL_WRAPPERS)
@pytest.mark.parametrize("flag", ["--help", "-h"])
def test_wrappers_help_prints_usage_and_exports_nothing(
    func, target, flag, capture_full, capture_print, capsys
):
    func(flag)
    assert capture_full == [] and capture_print == []
    out = capsys.readouterr().out
    assert out.startswith("usage: export-shortcut [-h] [OPTION ...]")
    assert "exit status 2" in out
    for fragment in HELP_FRAGMENTS[target]:
        assert fragment in out


@pytest.mark.parametrize("func, target", ALL_WRAPPERS)
def test_wrappers_abort_on_an_unknown_option(
    func, target, capture_full, capture_print, capsys
):
    with pytest.raises(SystemExit) as exc:
        func("--bogus")
    assert exc.value.code == 2
    assert capture_full == [] and capture_print == []
    out = capsys.readouterr().out
    assert f"Invalid options for {target}" in out
    assert "Aborting" in out


# Each row: a wrapper and the command line its help says it runs
RUNS_AS = [
    pytest.param(sc.export_pdf, "full-export --format pdf", id="export_pdf"),
    pytest.param(sc.export_epub2, "full-export --epub2", id="export_epub2"),
    pytest.param(
        sc.export_epub2_with_cover,
        "full-export --epub2 --cover assets/covers/cover.jpg",
        id="export_epub2_with_cover",
    ),
    pytest.param(
        sc.export_all_formats_with_cover,
        "full-export --format pdf,epub,docx,markdown,html --cover assets/covers/cover.jpg",
        id="export_all_formats_with_cover",
    ),
    pytest.param(
        sc.export_html_safe,
        "full-export --format html --skip-images",
        id="export_html_safe",
    ),
    pytest.param(
        sc.export_print_version_epub,
        "print-version-build",
        id="export_print_version_epub",
    ),
    pytest.param(
        sc.export_print_version_hardcover_safe,
        "print-version-build --book-type hardcover --skip-images",
        id="export_print_version_hardcover_safe",
    ),
]


@pytest.mark.parametrize("func, runs", RUNS_AS)
def test_help_names_what_the_wrapper_runs(func, runs, capsys):
    func("--help")
    assert f"\n  {runs} [OPTION ...]\n" in capsys.readouterr().out


@pytest.mark.parametrize(
    "extra",
    [
        pytest.param(("--lang=de", "--bogus", "--help"), id="help-last"),
        pytest.param(("--help", "--bogus"), id="help-first"),
        pytest.param(("--lang", "-h", "de"), id="short-help-between"),
    ],
)
def test_help_wins_over_other_options_and_unknown_ones(extra, capture_full, capsys):
    sc.export_pdf(*extra)
    assert capture_full == []
    assert "usage:" in capsys.readouterr().out


@pytest.mark.parametrize(
    "argv0, prog",
    [
        pytest.param("/venv/bin/export-pvh", "export-pvh", id="console-script-path"),
        pytest.param("export-e", "export-e", id="bare-name"),
        pytest.param("", "export-shortcut", id="no-name-falls-back"),
    ],
)
def test_help_uses_the_name_the_wrapper_was_called_as(argv0, prog, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", [argv0, "--help"])
    sc.export_print_version_hardcover()
    assert capsys.readouterr().out.startswith(f"usage: {prog} [-h] [OPTION ...]")


@pytest.mark.parametrize(
    "target, base_args, runs",
    [
        pytest.param(
            sc.FULL_EXPORT, ["--format", "pdf"], "full-export --format pdf", id="full"
        ),
        pytest.param(
            sc.PRINT_VERSION,
            ["--book-type", "paperback"],
            "print-version-build --book-type paperback",
            id="print-version",
        ),
    ],
)
def test_print_shortcut_help_takes_an_explicit_prog(target, base_args, runs, capsys):
    sc.print_shortcut_help(target, base_args, prog="my-export")
    out = capsys.readouterr().out
    assert out.startswith("usage: my-export [-h] [OPTION ...]")
    assert f"\n  {runs} [OPTION ...]\n" in out


# --- main() dispatch -----------------------------------------------------


def _record_call(name: str, monkeypatch) -> list[tuple]:
    calls: list[tuple] = []

    def fake(*a, **kw):
        calls.append((a, kw))

    monkeypatch.setattr(sc, name, fake)
    return calls


# Each row: the main() arguments, the shortcut it dispatches to and the
# positional arguments it passes (for export: format, cover, *extras)
MAIN_DISPATCH_CASES = [
    pytest.param(
        ["export", "--format", "pdf"],
        "export",
        ("pdf", None),
        id="export-dispatches-to-export",
    ),
    pytest.param(["epub2"], "export_epub2", (), id="epub2"),
    pytest.param(
        ["epub2-with-cover"], "export_epub2_with_cover", (), id="epub2-with-cover"
    ),
    pytest.param(
        ["print-version", "--book-type", "paperback"],
        "export_print_version_paperback",
        (),
        id="print-version-paperback",
    ),
    pytest.param(
        ["print-version", "--book-type", "hardcover"],
        "export_print_version_hardcover",
        (),
        id="print-version-hardcover",
    ),
    pytest.param(
        ["print-version"],
        "export_print_version_epub",
        (),
        id="print-version-default-ebook",
    ),
    pytest.param(["safe", "--format", "pdf"], "export_safe", ("pdf",), id="safe"),
    # "--" must have been stripped from the passthrough
    pytest.param(
        ["export", "--format", "pdf", "--", "--lang", "de"],
        "export",
        ("pdf", None, "--lang", "de"),
        id="strips-leading-double-dash-from-passthrough",
    ),
    pytest.param(
        ["export", "--format", "pdf", "--strict-opts"],
        "export",
        ("pdf", None, "--strict-opts"),
        id="strict-opts-is-forwarded",
    ),
    pytest.param(
        ["export", "--format", "pdf", "--cover", "c.jpg", "--", "--lang", "de"],
        "export",
        ("pdf", "c.jpg", "--lang", "de"),
        id="export-passes-the-cover",
    ),
    pytest.param(
        ["print-version", "--", "--lang", "de"],
        "export_print_version_epub",
        ("--lang", "de"),
        id="print-version-passes-the-passthrough",
    ),
    pytest.param(
        ["safe", "--format", "epub", "--", "--keep-relative-paths"],
        "export_safe",
        ("epub", "--keep-relative-paths"),
        id="safe-passes-the-passthrough",
    ),
]


@pytest.mark.parametrize("argv, shortcut, args", MAIN_DISPATCH_CASES)
def test_main_dispatches(argv, shortcut, args, monkeypatch):
    calls = _record_call(shortcut, monkeypatch)
    sc.main(argv)
    assert calls == [(args, {})]


def test_main_list_allowed_opts(capsys):
    sc.main(["list-allowed-opts"])
    assert "full_export_book.py" in capsys.readouterr().out


# Each row: the main() arguments and the command line the help names
MAIN_HELP_CASES = [
    pytest.param(
        ["export", "--format", "pdf", "--", "--help"],
        "full-export --format pdf",
        id="export",
    ),
    pytest.param(["epub2", "--", "-h"], "full-export --epub2", id="epub2"),
    pytest.param(
        ["print-version", "--book-type", "hardcover", "--", "--help"],
        "print-version-build --book-type hardcover",
        id="print-version",
    ),
    pytest.param(
        ["safe", "--format", "epub", "--", "--help"],
        "full-export --format epub --skip-images",
        id="safe",
    ),
]


@pytest.mark.parametrize("argv, runs", MAIN_HELP_CASES)
def test_main_passthrough_help_prints_the_shortcut_help(
    argv, runs, capture_full, capture_print, capsys
):
    sc.main(argv)
    assert capture_full == [] and capture_print == []
    assert f"\n  {runs} [OPTION ...]\n" in capsys.readouterr().out
