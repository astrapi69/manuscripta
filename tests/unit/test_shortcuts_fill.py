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
    valid, invalid = sc._split_valid_invalid_options(
        ["--epub2"], sc.FULL_EXPORT_ALLOWED_OPTS
    )
    assert valid == ["--epub2"]
    assert invalid == []


# Each row: the passthrough tokens, the ones to forward, the unknown ones.
SPLIT_CASES = [
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


# --- export() and format-specific wrappers ------------------------------


def test_export_forwards_format_and_cover(capture_full):
    sc.export("pdf", "c.jpg", "--lang", "de")
    assert capture_full[0][:2] == ["--format", "pdf"]
    assert "--cover" in capture_full[0] and "c.jpg" in capture_full[0]
    assert "--lang" in capture_full[0] and "de" in capture_full[0]


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


# Each row: the passthrough tokens, what the forwarded argv must contain and
# what it must not.
FORWARD_CASES = [
    pytest.param(
        ("--", "--lang", "de"), ["--lang", "de"], ["--"], id="bare-double-dash-dropped"
    ),
    pytest.param(
        ("--source-dir=/tmp/book", "--no-strict-images"),
        ["--source-dir=/tmp/book", "--no-strict-images"],
        [],
        id="cli-layer-options-forwarded",
    ),
    pytest.param(
        ("--resource-path", "assets", "--strict-images"),
        ["--resource-path", "assets", "--strict-images"],
        [],
        id="cli-layer-option-with-value",
    ),
]


@pytest.mark.parametrize("extra, present, absent", FORWARD_CASES)
def test_export_forwards(extra, present, absent, capture_full):
    sc.export("pdf", None, *extra)
    argv = capture_full[0]
    assert argv[:2] == ["--format", "pdf"]
    for tok in present:
        assert tok in argv
    for tok in absent:
        assert tok not in argv


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


# --- export_epub2 / export_epub_with_cover / export_epub2_with_cover ----


def test_export_epub2_sets_flag(capture_full):
    sc.export_epub2("--lang", "de")
    argv = capture_full[0]
    assert "--epub2" in argv
    assert "--lang" in argv and "de" in argv


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


# The options print_version_build.py consumes itself (its parser, pinned by
# test_print_version_allow_list_matches_its_parser)
@pytest.mark.parametrize("opt", ["--dry-run", "--restore", "--exact-name"])
def test_export_print_version_forwards_its_own_option(opt, capture_print):
    sc.export_print_version_epub(opt)
    assert opt in capture_print[0]


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
