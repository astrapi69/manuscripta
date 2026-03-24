#!/usr/bin/env python3
"""
Builds the print version (paperback or hardcover) of a book project.

Current pipeline (kept minimal to satisfy tests):
  1) manuscripta.export.book (via python -m)
  2) git restore .   (ONLY if --restore is set)

CLI examples:
    print-version-build --book-type paperback
    print-version-build --dry-run --export-format epub
    print-version-build --restore
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

# All paths relative to cwd (= book repo root)
PROJECT_ROOT = Path.cwd()


# --------------------------------------------------------------------------- #
# Normalizers
# --------------------------------------------------------------------------- #
def _normalize_export_format(fmt: Optional[str]) -> str:
    """Return normalized export format ('epub'|'pdf')."""
    if not fmt:
        return "epub"
    fmt = fmt.lower().strip()
    return "pdf" if fmt.startswith("p") else "epub"


def _normalize_book_type(bt: Optional[str]) -> str:
    """Return normalized book type ('paperback'|'hardcover'), warn on invalid input."""
    if not bt:
        return "paperback"
    v = bt.lower().strip()
    if v in ("paperback", "p"):
        return "paperback"
    if v in ("hardcover", "h"):
        return "hardcover"
    print(f"Invalid book type: {bt}. Falling back to 'paperback'.")
    return "paperback"


# --------------------------------------------------------------------------- #
# Core runner
# --------------------------------------------------------------------------- #
def run_script(module_path: str, *script_args: str, dry_run: bool = False) -> bool:
    """
    Execute a manuscripta module via python -m.

    Returns:
        True on success (returncode 0), False otherwise.

    Notes:
      - Uses `python3 -m <module> <args...>` to run installed modules.
      - Never raises on failure; caller handles control flow (tests expect boolean).
      - `dry_run=True` prints the command and returns True without executing.
    """
    cmd: List[str] = ["python3", "-m", module_path] + list(script_args)

    if dry_run:
        print("[dry-run] Would run: " + " ".join(cmd))
        return True

    try:
        proc = subprocess.run(cmd, check=True)
        return proc.returncode == 0
    except subprocess.CalledProcessError as e:
        print(f"Command failed with exit code {e.returncode}: " + " ".join(cmd))
        return False


# --------------------------------------------------------------------------- #
# Build pipeline
# --------------------------------------------------------------------------- #
def build_print_version(
    export_format: str,
    book_type: str,
    forwarded_args: list[str],
    dry_run: bool = False,
    exact_name: bool = False,
    restore: bool = False,
) -> bool:
    """
    Run the minimal pipeline for building the print version.

    Invokes manuscripta.export.book and (optionally) performs a git restore
    at the end if `restore=True`.
    """
    toc_file = PROJECT_ROOT / "manuscript" / "front-matter" / "toc.md"
    if not toc_file.exists():
        print(f"No TOC file at {toc_file}; skipping TOC link stripping.")

    print(f"Building PRINT version of the book ({book_type.upper()})...\n")

    base_args = [
        f"--format={export_format}",
        f"--book-type={book_type}",
        "--skip-images",
    ]

    if dry_run:
        print("DRY-RUN mode enabled (no actual execution).\n")

    ok = True
    ok &= run_script(
        "manuscripta.export.book", *base_args, *forwarded_args, dry_run=dry_run
    )

    if not ok:
        print("One or more pipeline steps failed.")
        print("Build process aborted.")
        return False

    # Final cleanup step (explicit opt-in)
    if restore:
        git_cmd = ["git", "restore", "."]
        if dry_run:
            print("[dry-run] Would run: " + " ".join(git_cmd))
        else:
            try:
                subprocess.run(git_cmd, check=True)
            except subprocess.CalledProcessError:
                print("git restore failed (non-fatal).")

    print("Pipeline finished successfully.")
    return True


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """
    Parse known args and collect unknown args to forward to manuscripta.export.book.

    Namespace fields:
      - dry_run, restore, export_format, book_type, exact_name, extra
    """
    p = argparse.ArgumentParser(description="Build print version of a book project.")
    p.add_argument(
        "--dry-run", action="store_true", help="Print commands without executing."
    )
    p.add_argument(
        "--restore", action="store_true", help="Run git restore at the end (opt-in)."
    )
    p.add_argument(
        "--export-format",
        dest="export_format",
        choices=["epub", "pdf"],
        default="epub",
        help="Export format for the print pipeline (epub|pdf).",
    )
    # Alias for backward compatibility
    p.add_argument(
        "--format",
        dest="export_format",
        choices=["epub", "pdf"],
        help=argparse.SUPPRESS,
    )
    p.add_argument(
        "--book-type", type=str, help="paperback or hardcover (default: paperback)."
    )
    p.add_argument(
        "--exact-name", action="store_true", help="Use exact output name (no suffix)."
    )

    known, unknown = p.parse_known_args(argv)

    ns = argparse.Namespace(
        dry_run=known.dry_run,
        restore=known.restore,
        export_format=_normalize_export_format(known.export_format),
        book_type=_normalize_book_type(known.book_type),
        exact_name=known.exact_name,
        extra=unknown,
    )
    return ns


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)

    ok = build_print_version(
        args.export_format,
        args.book_type,
        args.extra,
        dry_run=args.dry_run,
        exact_name=args.exact_name,
        restore=args.restore,
    )

    if ok:
        if args.export_format == "epub":
            print("\nPrint version EPUB successfully generated!")
        elif args.export_format == "pdf":
            print("\nPrint version PDF successfully generated!")
        sys.exit(0)
    else:
        print("\nPrint version build failed.")
        sys.exit(1)


if __name__ == "__main__":
    main()
