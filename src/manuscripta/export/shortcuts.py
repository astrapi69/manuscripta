#!/usr/bin/env python3
# scripts/shortcuts_export.py
"""
Shortcuts for book export pipelines with **validated passthrough options**.

Features
--------
- Forwards extra CLI options to the underlying scripts after validating them
  against public allow-lists (value-agnostic, name-based).
- ``-h`` / ``--help`` prints the usage of the shortcut and of the target
  script and returns without touching the manuscript or ``output/``.
- An unknown option aborts with exit status 2 before the target runs, so a
  misspelled flag never starts an export with the defaults.
- ``--strict-opts`` is still accepted for compatibility. It is consumed here
  and has no effect, since unknown options always abort.

Targets
-------
- full_export_book.py (multi-format export)
- print_version_build.py (print-optimized EPUB export; will forward a subset to
  full_export_book.py internally)

Safe Mode
---------
Safe exports (`export-pdf-safe`, `export-epub-safe`, `export-docx-safe`,
`export-markdown-safe`, alias `export-es`) wrap the normal pipeline in a
**read-only, draft build mode**:

1. Skips **Step 1** (preprocess/convert sources) → no in-place edits of Markdown
2. Runs **Step 2** (pandoc conversion) → still produces your requested format
3. Runs **Step 3** (postprocess, e.g. cover injection, EPUB2 tweaks)
4. Skips **Step 4** (restore/cleanup sources) → nothing to restore since Step 1 was skipped

Additionally, Safe Mode **forces protective flags**:
- `--skip-images` → no image conversion or inlining
- `--keep-relative-paths` → don’t rewrite links to local assets

⚠️ Safe builds are **not production-ready**:
- ✅ Faster and safer: great for drafts, CI checks, and quick previews
- ❌ Missing images, incomplete polish: for final exports use the normal commands

Common Examples
---------------
Poetry shortcuts:
    poetry run export-pdf --output-file=final
    poetry run export-pdf-safe --output-file=draft
    poetry run export-epub2 --cover=assets/covers/cover.jpg
    poetry run export-print-version-hardcover --lang=de
    poetry run export-epub --help

Direct module execution:
    python scripts/shortcuts_export.py export --format pdf -- --skip-images --output-file=foo
    python scripts/shortcuts_export.py print-version --book-type hardcover -- --lang=de

Notes
-----
- Everything after a bare `--` is treated as passthrough to the target script and
  will be validated and (if valid) forwarded.
- `--strict-opts` is consumed by the **caller** (this module) and not forwarded further.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Iterable, List

from manuscripta.export.book import _build_arg_parser as _full_export_parser
from manuscripta.export.book import _build_cli_arg_parser as _full_export_cli_parser
from manuscripta.export.book import main as export_main
from manuscripta.export.print_version import _build_arg_parser as _print_version_parser
from manuscripta.export.print_version import main as export_print_version_main

# ──────────────────────────────────────────────────────────────────────────────
# Public allow-lists to validate extras before dispatch
# (Option *names* only, value-agnostic)
# ──────────────────────────────────────────────────────────────────────────────

FULL_EXPORT_ALLOWED_OPTS = {
    "--format",
    "--order",
    "--cover",
    "--epub2",
    "--lang",
    "--extension",
    "--book-type",
    "--output-file",
    "--no-type-suffix",
    "--toc-depth",
    "--use-manual-toc",
    "--skip-images",
    "--keep-relative-paths",
    "--copy-epub-to",
    # The CLI layer of manuscripta.export.book, peeled off before its parser
    "--source-dir",
    "--resource-path",
    "--strict-images",
    "--no-strict-images",
}

PRINT_VERSION_ALLOWED_OPTS = {
    "--book-type",
    "--export-format",
    "--dry-run",
    "--restore",
    "--exact-name",
}

# Consumed here, never forwarded: --strict-opts has no effect any more, and a
# bare -- only separates the shortcut from its passthrough.
_CONSUMED_TOKENS = {"--strict-opts", "--"}

HELP_OPTS = {"-h", "--help"}

DEFAULT_COVER = "assets/covers/cover.jpg"

# The targets, named after the scripts the shortcuts stand in for
FULL_EXPORT = "full_export_book.py"
PRINT_VERSION = "print_version_build.py"

# The console script each target runs as (the argv[0] of the synthetic argv)
_TARGET_PROG = {FULL_EXPORT: "full-export", PRINT_VERSION: "print-version-build"}

# print_version_build.py consumes its own options and forwards the rest to
# full_export_book.py, so its shortcuts accept both sets.
_TARGET_ALLOWED = {
    FULL_EXPORT: FULL_EXPORT_ALLOWED_OPTS,
    PRINT_VERSION: PRINT_VERSION_ALLOWED_OPTS | FULL_EXPORT_ALLOWED_OPTS,
}

__all__ = [
    "export",
    "export_all_formats",
    "export_all_formats_with_cover",
    "export_epub2",
    "export_epub2_with_cover",
    "export_print_version_epub",
    "export_print_version_paperback",
    "export_print_version_hardcover",
    "export_print_version_paperback_safe",
    "export_print_version_hardcover_safe",
    "export_safe",
    # Safe aliases:
    "export_pdf_safe",
    "export_epub_safe",
    "export_docx_safe",
    "export_markdown_safe",
    "export_html_safe",
    # Compat aliases:
    "export_pdf",
    "export_epub",
    "export_docx",
    "export_markdown",
    "export_html",
    # Utilities:
    "list_allowed_opts",
    "print_shortcut_help",
    "main",
]

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────


def _has_any_option(extra: Iterable[str], names: set[str]) -> bool:
    for tok in extra:
        if not tok.startswith("--"):
            continue
        if tok.split("=", 1)[0] in names:
            return True
    return False


def _split_valid_invalid_options(
    extra: List[str], allowed: set[str]
) -> tuple[list[str], list[str]]:
    """Split ``extra`` into the tokens to forward and the unknown ones.

    An option is a token that starts with ``-``; its name is the part before
    ``=``. The token after an option given without ``=`` is that option's
    value when it does not start with ``-`` and goes into the same bucket.
    Any other token (a stray positional) is unknown.
    """
    valid: List[str] = []
    invalid: List[str] = []
    i = 0
    while i < len(extra):
        tok = extra[i]
        if tok.startswith("-"):
            name = tok.split("=", 1)[0]
            bucket = valid if name in allowed else invalid
            bucket.append(tok)
            if (
                "=" not in tok
                and (i + 1) < len(extra)
                and not extra[i + 1].startswith("-")
            ):
                bucket.append(extra[i + 1])
                i += 1
        else:
            invalid.append(tok)
        i += 1
    return valid, invalid


def _wants_help(extra: Iterable[str]) -> bool:
    """Whether ``-h`` or ``--help`` is among the passthrough tokens."""
    return any(tok in HELP_OPTS for tok in extra)


def _help_parsers(target: str) -> list[argparse.ArgumentParser]:
    """The parsers whose options ``target`` accepts, in the order to print."""
    full_export = [_full_export_cli_parser(), _full_export_parser()]
    for parser in full_export:
        parser.prog = _TARGET_PROG[FULL_EXPORT]
    if target == FULL_EXPORT:
        return full_export
    print_version = _print_version_parser()
    print_version.prog = _TARGET_PROG[PRINT_VERSION]
    return [print_version, *full_export]


def print_shortcut_help(
    target: str, base_args: list[str], prog: str | None = None
) -> None:
    """Print the usage of a shortcut and the options of its target.

    ``prog`` defaults to the name the shortcut was called as.
    """
    prog = prog or Path(sys.argv[0]).name or "export-shortcut"
    runs = " ".join([_TARGET_PROG[target], *base_args])
    print(f"usage: {prog} [-h] [OPTION ...]")
    print()
    print(f"Runs {target} as")
    print(f"  {runs} [OPTION ...]")
    print()
    print(f"Every OPTION is checked against the options of {target} listed below")
    print("and forwarded unchanged. An unknown option aborts with exit status 2")
    print("before any source file is touched or anything is exported.")
    print("--strict-opts is accepted for compatibility and has no effect.")
    if target == PRINT_VERSION:
        print()
        print(f"{PRINT_VERSION} consumes its own options and forwards the rest")
        print(f"to {FULL_EXPORT}.")
    for parser in _help_parsers(target):
        print()
        print(parser.format_help(), end="")


def _run_full_export(args_list: List[str]):
    """Invoke the full export pipeline with a synthetic argv."""
    sys.argv = ["full-export", *args_list]
    export_main()


def _run_print_version(args_list: List[str]):
    """Invoke the print-version pipeline with a synthetic argv."""
    sys.argv = ["print-version-build", *args_list]
    export_print_version_main()


def _forward(target: str, base_args: list[str], extra: Iterable[str]) -> None:
    """Validate ``extra`` and run ``target`` with ``base_args`` plus the valid options.

    ``-h`` / ``--help`` anywhere in ``extra`` prints the help and returns
    without running anything. An unknown option prints the offending tokens
    and exits with status 2 before the target runs.
    """
    tokens = list(extra)
    if _wants_help(tokens):
        print_shortcut_help(target, base_args)
        return

    tokens = [t for t in tokens if t not in _CONSUMED_TOKENS]
    valid, invalid = _split_valid_invalid_options(tokens, _TARGET_ALLOWED[target])

    if invalid:
        print(f"⚠️ Invalid options for {target}:")
        print("   " + " ".join(invalid))
        print("🛑 Aborting: unknown options are never forwarded. See --help.")
        sys.exit(2)

    if valid:
        print(f"🔧 Forwarding valid options to {target}:")
        print("   " + " ".join(valid))

    args = [*base_args, *valid]
    if target == PRINT_VERSION:
        _run_print_version(args)
    else:
        _run_full_export(args)


def list_allowed_opts() -> None:
    print("Allowed options (by target):")
    print(f"  {FULL_EXPORT}:")
    print("   ", " ".join(sorted(FULL_EXPORT_ALLOWED_OPTS)))
    print(f"  {PRINT_VERSION}:")
    print("   ", " ".join(sorted(PRINT_VERSION_ALLOWED_OPTS)))


# ──────────────────────────────────────────────────────────────────────────────
# Shortcuts API (used by Poetry script entries or imports)
# ──────────────────────────────────────────────────────────────────────────────


def export(format: str, cover: str | None = None, *extra: str):
    """
    Export in a specific format via full_export_book.py, with passthrough validation.
    """
    args = ["--format", format]
    if cover:
        args.extend(["--cover", cover])
    _forward(FULL_EXPORT, args, extra)


def export_pdf(*extra: str):
    """Back-compat alias for tests/old scripts."""
    if not extra:
        extra = tuple(sys.argv[1:])
    return export("pdf", None, *extra)


def export_epub(*extra: str):
    """Back-compat alias for tests/old scripts."""
    if not extra:
        extra = tuple(sys.argv[1:])
    return export("epub", None, *extra)


def export_docx(*extra: str):
    """Back-compat alias for tests/old scripts."""
    if not extra:
        extra = tuple(sys.argv[1:])
    return export("docx", None, *extra)


def export_markdown(*extra: str):
    """Back-compat alias for tests/old scripts."""
    if not extra:
        extra = tuple(sys.argv[1:])
    return export("markdown", None, *extra)


def export_html(*extra: str):
    """Alias for exporting HTML via full_export_book.py."""
    if not extra:
        extra = tuple(sys.argv[1:])
    return export("html", None, *extra)


def _export_all_formats(include_cover: bool, *extra: str):
    """
    Internal helper for exporting all major formats, with or without a cover.
    Validates the passthrough options and forwards the allowed flags.
    """
    args = ["--format", "pdf,epub,docx,markdown,html"]
    if include_cover:
        args.extend(["--cover", DEFAULT_COVER])
    _forward(FULL_EXPORT, args, extra)


def export_all_formats(*extra: str):
    """
    Export all supported formats **without** a cover.
    """
    if not extra:
        extra = tuple(sys.argv[1:])
    return _export_all_formats(False, *extra)


def export_all_formats_with_cover(*extra: str):
    """
    Export all supported formats **with** a default cover.
    """
    if not extra:
        extra = tuple(sys.argv[1:])
    return _export_all_formats(True, *extra)


def export_epub2(*extra: str):
    """
    Export EPUB2 flavor; pass through validated extras.
    """
    if not extra:
        extra = tuple(sys.argv[1:])
    _forward(FULL_EXPORT, ["--epub2"], extra)


def export_epub_with_cover(*extra: str):
    """
    Export EPUB3 with a default cover; passthrough validated extras.
    """
    if not extra:
        extra = tuple(sys.argv[1:])
    _forward(FULL_EXPORT, ["--format", "epub", "--cover", DEFAULT_COVER], extra)


def export_epub2_with_cover(*extra: str):
    """
    Export EPUB2 with a default cover; pass through validated extras.
    """
    if not extra:
        extra = tuple(sys.argv[1:])
    _forward(FULL_EXPORT, ["--epub2", "--cover", DEFAULT_COVER], extra)


def export_print_version_epub(*extra: str):
    """
    Export the print-optimized EPUB via print_version_build.py.
    Accepts both print-version and full-export flags; validates both sets.
    """
    if not extra:
        extra = tuple(sys.argv[1:])
    _forward(PRINT_VERSION, [], extra)


def export_print_version_paperback(*extra: str):
    """
    Print-optimized EPUB for paperback book type.
    """
    if not extra:
        extra = tuple(sys.argv[1:])
    _forward(PRINT_VERSION, ["--book-type", "paperback"], extra)


def export_print_version_hardcover(*extra: str):
    """
    Print-optimized EPUB for hardcover book type.
    """
    if not extra:
        extra = tuple(sys.argv[1:])
    _forward(PRINT_VERSION, ["--book-type", "hardcover"], extra)


def export_safe(format: str, *extra: str):
    """
    Export in 'safe' mode:
      - Forces --skip-images unless user already provided one.
      - Forces --keep-relative-paths unless user already provided one.
    """
    args = ["--format", format]

    # Mutually exclusive in full_export_book.py: pick ONE
    if not _has_any_option(extra, {"--skip-images", "--keep-relative-paths"}):
        args.append("--skip-images")  # default safe behavior

    _forward(FULL_EXPORT, args, extra)


# ──────────────────────────────────────────────────────────────────────────────
# Safe shortcut aliases (for Poetry script entries)
# ──────────────────────────────────────────────────────────────────────────────
def export_pdf_safe(*extra: str):
    if not extra:
        extra = tuple(sys.argv[1:])
    return export_safe("pdf", *extra)


def export_epub_safe(*extra: str):
    if not extra:
        extra = tuple(sys.argv[1:])
    return export_safe("epub", *extra)


def export_docx_safe(*extra: str):
    if not extra:
        extra = tuple(sys.argv[1:])
    return export_safe("docx", *extra)


def export_markdown_safe(*extra: str):
    if not extra:
        extra = tuple(sys.argv[1:])
    return export_safe("markdown", *extra)


def export_html_safe(*extra: str):
    if not extra:
        extra = tuple(sys.argv[1:])
    return export_safe("html", *extra)


def _export_print_version_safe(book_type: str, *extra: str):
    """
    Print-optimized EPUB for ``book_type`` **in Safe Mode**:
      - Forces --skip-images unless the user already chose one of the two
        image flags (no in-place source edits).
      - Validates the passthrough; an unknown option aborts.
    """
    args = ["--book-type", book_type]

    # Add exactly one safe flag if none provided by user
    if not _has_any_option(extra, {"--skip-images", "--keep-relative-paths"}):
        args.append("--skip-images")

    _forward(PRINT_VERSION, args, extra)


def export_print_version_paperback_safe(*extra: str):
    """
    Print-optimized EPUB for paperback **in Safe Mode**.
    """
    if not extra:
        extra = tuple(sys.argv[1:])
    return _export_print_version_safe("paperback", *extra)


def export_print_version_hardcover_safe(*extra: str):
    """
    Print-optimized EPUB for hardcover **in Safe Mode**.
    """
    if not extra:
        extra = tuple(sys.argv[1:])
    return _export_print_version_safe("hardcover", *extra)


# ──────────────────────────────────────────────────────────────────────────────
# CLI entrypoint (optional; keeps Poetry shortcuts intact)
# ──────────────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> None:
    """
    Simple CLI wrapper mainly for local/manual invocations.

    Pattern:
      shortcuts_export.py <command> [command-args] -- [passthrough-to-target...]
    """
    parser = argparse.ArgumentParser(
        prog="shortcuts_export",
        description="Shortcuts for exporting books with validated passthrough options.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # export
    p_export = sub.add_parser("export", help="Export via full_export_book.py")
    p_export.add_argument("--format", required=True, help="pdf|epub|docx|markdown")
    p_export.add_argument("--cover", default=None)
    p_export.add_argument("--strict-opts", action="store_true")
    p_export.add_argument("passthrough", nargs=argparse.REMAINDER)

    # epub2
    p_epub2 = sub.add_parser("epub2", help="Export EPUB2 via full_export_book.py")
    p_epub2.add_argument("--strict-opts", action="store_true")
    p_epub2.add_argument("passthrough", nargs=argparse.REMAINDER)

    # epub2-with-cover
    p_epub2c = sub.add_parser(
        "epub2-with-cover", help="Export EPUB2 with default cover"
    )
    p_epub2c.add_argument("--strict-opts", action="store_true")
    p_epub2c.add_argument("passthrough", nargs=argparse.REMAINDER)

    # print-version
    p_print = sub.add_parser("print-version", help="Export print-optimized EPUB")
    p_print.add_argument("--book-type", choices=["paperback", "hardcover"])
    p_print.add_argument("--strict-opts", action="store_true")
    p_print.add_argument("passthrough", nargs=argparse.REMAINDER)

    # safe
    p_safe = sub.add_parser("safe", help="Export in safe mode (skips heavy steps)")
    p_safe.add_argument("--format", required=True)
    p_safe.add_argument("--strict-opts", action="store_true")
    p_safe.add_argument("passthrough", nargs=argparse.REMAINDER)

    # list-allowed-opts
    sub.add_parser("list-allowed-opts", help="Print valid options for targets")

    ns = parser.parse_args(argv if argv is not None else sys.argv[1:])
    extras = ns.passthrough if hasattr(ns, "passthrough") else []

    # strip a leading bare '--' from passthrough if present
    if extras and extras[0] == "--":
        extras = extras[1:]

    if ns.cmd == "export":
        export(
            ns.format, ns.cover, *extras, *(["--strict-opts"] if ns.strict_opts else [])
        )
    elif ns.cmd == "epub2":
        export_epub2(*extras, *(["--strict-opts"] if ns.strict_opts else []))
    elif ns.cmd == "epub2-with-cover":
        export_epub2_with_cover(*extras, *(["--strict-opts"] if ns.strict_opts else []))
    elif ns.cmd == "print-version":
        if ns.book_type == "hardcover":
            export_print_version_hardcover(
                *extras, *(["--strict-opts"] if ns.strict_opts else [])
            )
        elif ns.book_type == "paperback":
            export_print_version_paperback(
                *extras, *(["--strict-opts"] if ns.strict_opts else [])
            )
        else:
            export_print_version_epub(
                *extras, *(["--strict-opts"] if ns.strict_opts else [])
            )
    elif ns.cmd == "safe":
        export_safe(ns.format, *extras, *(["--strict-opts"] if ns.strict_opts else []))
    elif ns.cmd == "list-allowed-opts":
        list_allowed_opts()
    else:
        parser.error("Unknown command")


if __name__ == "__main__":
    main()
