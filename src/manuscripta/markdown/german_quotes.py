#!/usr/bin/env python3
# scripts/fix_german_quotes.py
"""
fix-german-quotes - Converts quotation marks in Markdown files
to German typographic style.

Target format:
  Double: „ " (U+201E / U+201C)
  Single: ‚ ' (U+201A / U+2018)

Converted: straight double quotes (") and English typographic quotes
(U+201C/U+201D and U+2018/U+2019). Straight single quotes (') are left
alone on purpose: in running text they cannot be told apart from
apostrophes ("geht's" versus 'Zitat'), so converting them would break
more than it fixes.

Quotes are paired per block, not per line: a paragraph, a list item, a
heading or a table row is converted as a whole, so a quotation that a
hard line wrap split across two lines is still closed correctly. Blank
lines end a paragraph; YAML frontmatter and fenced code blocks are never
touched.

Usage:
  fix-german-quotes input.md
  fix-german-quotes input.md --dry-run
  fix-german-quotes ./my_book/           (recursive, *.md)
  fix-german-quotes ./docs/ --pattern "*.markdown"
"""

import argparse
import re
import shutil
import sys
from pathlib import Path


# --- Character constants ---

# German target characters
DE_OPEN_DOUBLE = "\u201e"  # „
DE_CLOSE_DOUBLE = "\u201c"  # "
DE_OPEN_SINGLE = "\u201a"  # ‚
DE_CLOSE_SINGLE = "\u2018"  # '

# English typographic characters (to be replaced)
EN_OPEN_DOUBLE = "\u201c"  # " (identical to DE_CLOSE_DOUBLE)
EN_CLOSE_DOUBLE = "\u201d"  # "
EN_OPEN_SINGLE = "\u2018"  # ' (identical to DE_CLOSE_SINGLE)
EN_CLOSE_SINGLE = "\u2019"  # '

# Straight (ASCII) quotation marks
STRAIGHT_DOUBLE = '"'
STRAIGHT_SINGLE = "'"

# Default glob pattern for directory mode
DEFAULT_PATTERN = "*.md"

# Lines that open a block of their own (after stripping leading whitespace):
# headings, list items (bullet or numbered) and table rows. Quotes are
# paired inside one block and never across a block boundary.
_HEADING_RE = re.compile(r"^#")
_LIST_ITEM_RE = re.compile(r"^(?:[-*+]|\d+[.)])\s")
_TABLE_ROW_RE = re.compile(r"^\|")

# Shown between the lines of a multi-line block in a warning's context excerpt
CONTEXT_LINE_SEPARATOR = " \u23ce "  # " ⏎ "


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Converts quotation marks in Markdown files "
        "to German typographic style."
    )
    parser.add_argument(
        "input",
        type=Path,
        help="Path to a Markdown file or directory (recursive).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show changes without writing files.",
    )
    parser.add_argument(
        "--pattern",
        default=DEFAULT_PATTERN,
        help=f"Glob pattern for directory mode (default: {DEFAULT_PATTERN}).",
    )
    return parser.parse_args()


def is_in_frontmatter(lines: list[str], line_idx: int) -> bool:
    """Check whether a line falls inside YAML frontmatter (--- ... ---)."""
    if not lines or not lines[0].rstrip() == "---":
        return False
    # Frontmatter starts at line 0, ends at the second ---
    fence_count = 0
    for i, line in enumerate(lines):
        if line.rstrip() == "---":
            fence_count += 1
        if fence_count == 2:
            return line_idx > 0 and line_idx <= i
    # No closing --- found, everything after the first --- is frontmatter
    return line_idx > 0


def mask_protected_regions(line: str) -> list[tuple[int, int]]:
    """
    Return a list of (start, end) ranges that must not be modified:
    inline code spans and HTML attribute values.

    ``line`` may be a whole block with embedded line breaks; a protected
    region never spans a line break.
    """
    protected = []

    # Inline code: `...`
    for m in re.finditer(r"`[^`\n]+`", line):
        protected.append((m.start(), m.end()))

    # HTML attributes: key="..." or key='...'
    for m in re.finditer(r'(?:[\w-]+)[ \t]*=[ \t]*"[^"\n]*"', line):
        protected.append((m.start(), m.end()))
    for m in re.finditer(r"(?:[\w-]+)[ \t]*=[ \t]*'[^'\n]*'", line):
        protected.append((m.start(), m.end()))

    return protected


def is_protected(pos: int, protected: list[tuple[int, int]]) -> bool:
    """Check whether a character position falls inside a protected region."""
    return any(start <= pos < end for start, end in protected)


def find_quote_positions(
    line: str, quote_char: str, protected: list[tuple[int, int]]
) -> list[int]:
    """Find all unprotected positions of a given character in the line."""
    positions = []
    for i, ch in enumerate(line):
        if ch == quote_char and not is_protected(i, protected):
            positions.append(i)
    return positions


def format_line_range(first: int, last: int | None = None) -> str:
    """Return "Line 7" for a single line and "Lines 7-8" for a line range."""
    if last is None or last == first:
        return f"Line {first}"
    return f"Lines {first}-{last}"


def format_context(text: str) -> str:
    """Return a one-line excerpt of a block for a warning message.

    Trailing whitespace is dropped and the line breaks of a multi-line
    block are shown as ``CONTEXT_LINE_SEPARATOR``.
    """
    return CONTEXT_LINE_SEPARATOR.join(
        part.rstrip() for part in text.rstrip().split("\n")
    )


def replace_straight_double_quotes(
    line: str,
    protected: list[tuple[int, int]],
    stats: dict,
    warnings: list,
    line_num: int,
    line_end: int | None = None,
) -> str:
    """
    Replace straight double quotation marks pairwise with German „ ".

    ``line`` is one block of text and may contain line breaks; ``line_num``
    is the 1-based file line number of its first line and ``line_end``
    that of its last line (``None`` for a single line). Both only appear
    in the warning for an odd number of quotation marks.

    Also handles mixed cases: if a German opening „ (U+201E) is already
    present and a straight " follows as closing quote, only the closing
    character is converted.
    """
    chars = list(line)
    straight_positions = find_quote_positions(line, STRAIGHT_DOUBLE, protected)

    if not straight_positions:
        return line

    # Phase 1: Find existing German opening „ (U+201E) that expect
    # a straight " as their closing counterpart.
    orphan_openers = []
    for i, ch in enumerate(chars):
        if ch == DE_OPEN_DOUBLE and not is_protected(i, protected):
            orphan_openers.append(i)

    # Match each „ with the next following straight "
    consumed_straight = set()
    for opener_pos in orphan_openers:
        for sp in straight_positions:
            if sp > opener_pos and sp not in consumed_straight:
                chars[sp] = DE_CLOSE_DOUBLE
                consumed_straight.add(sp)
                stats["straight_double"] += 1
                break

    # Phase 2: Convert remaining straight " pairwise
    remaining = [p for p in straight_positions if p not in consumed_straight]

    if len(remaining) % 2 != 0:
        warnings.append(
            f"{format_line_range(line_num, line_end)}: "
            f'Asymmetric straight quotation mark (") '
            f"- {len(remaining)} unpaired occurrence(s)\n"
            f"  Context: {format_context(line)}"
        )
        stats["warnings"] += 1
        # Keep already converted characters
        return "".join(chars)

    for i in range(0, len(remaining), 2):
        open_pos = remaining[i]
        close_pos = remaining[i + 1]
        chars[close_pos] = DE_CLOSE_DOUBLE
        chars[open_pos] = DE_OPEN_DOUBLE
        stats["straight_double"] += 1

    return "".join(chars)


def replace_english_double_quotes(
    line: str, protected: list[tuple[int, int]], stats: dict
) -> str:
    """
    Replace English typographic double quotation marks with German ones.

    Only active when U+201D (EN_CLOSE_DOUBLE) is present.
    U+201C is ambiguous (= DE_CLOSE_DOUBLE), so it is only treated as
    EN_OPEN_DOUBLE when a matching U+201D follows.

    Strategy:
    - U+201C...U+201D pairs -> U+201E...U+201C (German)
    - Standalone U+201D -> U+201C
    """
    chars = list(line)

    # Only act when U+201D is present at all
    close_positions = []
    for i, ch in enumerate(chars):
        if ch == EN_CLOSE_DOUBLE and not is_protected(i, protected):
            close_positions.append(i)

    if not close_positions:
        return line

    # Find U+201C positions as potential openers
    open_positions = []
    for i, ch in enumerate(chars):
        if ch == EN_OPEN_DOUBLE and not is_protected(i, protected):
            open_positions.append(i)

    changed = False

    # Match pairs: U+201C followed by U+201D
    used_close = set()
    used_open = set()
    for op in open_positions:
        for ci, cp in enumerate(close_positions):
            if cp > op and ci not in used_close:
                # Pair found: U+201C -> U+201E, U+201D -> U+201C
                chars[op] = DE_OPEN_DOUBLE
                chars[cp] = DE_CLOSE_DOUBLE
                used_close.add(ci)
                used_open.add(open_positions.index(op))
                changed = True
                break

    # Convert remaining standalone U+201D to U+201C
    for ci, cp in enumerate(close_positions):
        if ci not in used_close:
            chars[cp] = DE_CLOSE_DOUBLE
            changed = True

    if changed:
        stats["english_double"] += 1

    return "".join(chars)


def replace_english_single_quotes(
    line: str, protected: list[tuple[int, int]], stats: dict
) -> str:
    """
    Replace English typographic single quotation marks with German ones.

    U+2018 (') -> DE_CLOSE_SINGLE (stays, is identical)
    U+2019 (') -> must be handled context-dependently.

    Strategy: U+2018...U+2019 pairs -> U+201A...U+2018 (German)
    """
    chars = list(line)

    open_positions = []
    close_positions = []
    for i, ch in enumerate(chars):
        if is_protected(i, protected):
            continue
        if ch == EN_OPEN_SINGLE:
            open_positions.append(i)
        elif ch == EN_CLOSE_SINGLE:
            close_positions.append(i)

    if not open_positions and not close_positions:
        return line

    # Match pairs: each U+2018 with the next U+2019
    changed = False
    used_close = set()
    for op in open_positions:
        for ci, cp in enumerate(close_positions):
            if cp > op and ci not in used_close:
                # Pair found
                chars[op] = DE_OPEN_SINGLE
                chars[cp] = DE_CLOSE_SINGLE
                used_close.add(ci)
                changed = True
                break

    if changed:
        stats["english_single"] += 1

    return "".join(chars)


def process_block(text: str, first_line_num: int, stats: dict, warnings: list) -> str:
    """Run one block of text through all quote replacement stages.

    ``text`` is a paragraph, list item, heading or table row and may span
    several lines joined with "\\n"; quotes are paired across those lines.
    ``first_line_num`` is the 1-based file line number of the first line
    and is used, together with the computed last line, in warnings.
    """
    last_line_num = first_line_num + text.count("\n")
    protected = mask_protected_regions(text)

    # 1. Straight double quotation marks
    text = replace_straight_double_quotes(
        text, protected, stats, warnings, first_line_num, last_line_num
    )

    # Recompute protected regions after modification
    protected = mask_protected_regions(text)

    # 2. English typographic double quotation marks
    text = replace_english_double_quotes(text, protected, stats)

    protected = mask_protected_regions(text)

    # 3. English typographic single quotation marks
    text = replace_english_single_quotes(text, protected, stats)

    return text


def process_line(line: str, line_num: int, stats: dict, warnings: list) -> str:
    """Process a single line as a block of its own (see ``process_block``)."""
    return process_block(line, line_num, stats, warnings)


def starts_own_block(line: str) -> bool:
    """Return True for a heading, a list item or a table row.

    Such a line ends the running block and opens a new one, so the quotes
    of neighbouring list items or of a heading and the paragraph below it
    are never paired with each other.
    """
    stripped = line.lstrip()
    return bool(
        _HEADING_RE.match(stripped)
        or _LIST_ITEM_RE.match(stripped)
        or _TABLE_ROW_RE.match(stripped)
    )


def is_single_line_block(line: str) -> bool:
    """Return True for a heading or a table row, which never continue on the next line."""
    stripped = line.lstrip()
    return bool(_HEADING_RE.match(stripped) or _TABLE_ROW_RE.match(stripped))


def process_file(content: str, stats: dict, warnings: list) -> str:
    """Process the entire file content.

    YAML frontmatter and fenced code blocks pass through untouched.
    Everything else is grouped into blocks: a block ends at a blank line,
    at a code fence, before a line that starts its own block (heading,
    list item, table row) and after a heading or table row. Each block is
    converted as a whole, so a quotation that a hard line wrap split
    across two lines is still paired correctly. Line numbers in warnings
    are 1-based file line numbers.
    """
    lines = content.split("\n")
    result_lines: list[str] = []

    in_code_block = False
    in_frontmatter = False

    block: list[str] = []
    block_start = 1  # 1-based file line number of block[0]

    def flush_block() -> None:
        """Convert the running block and append its lines to the result."""
        if not block:
            return
        converted = process_block("\n".join(block), block_start, stats, warnings)
        new_lines = converted.split("\n")
        stats["lines_changed"] += sum(
            1 for old, new in zip(block, new_lines) if old != new
        )
        result_lines.extend(new_lines)
        block.clear()

    for line_num_0, line in enumerate(lines):
        line_num = line_num_0 + 1
        stripped = line.rstrip()

        # Frontmatter: only at the very top of the file, stays untouched
        if line_num_0 == 0 and stripped == "---":
            in_frontmatter = True
            result_lines.append(line)
            continue

        if in_frontmatter:
            if stripped == "---":
                in_frontmatter = False
            result_lines.append(line)
            continue

        # Fenced code blocks (```): the fence lines and everything inside
        # stay untouched; a fence also ends the running block
        if stripped.startswith("```"):
            flush_block()
            in_code_block = not in_code_block
            result_lines.append(line)
            continue

        if in_code_block:
            result_lines.append(line)
            continue

        # A blank line ends the running block
        if stripped == "":
            flush_block()
            result_lines.append(line)
            continue

        if starts_own_block(line):
            flush_block()
        if not block:
            block_start = line_num
        block.append(line)
        if is_single_line_block(line):
            flush_block()

    flush_block()
    return "\n".join(result_lines)


def collect_files(input_path: Path, pattern: str) -> list[Path]:
    """
    Collect files to process.

    If input_path is a file, return it as a single-element list.
    If input_path is a directory, recursively glob for the given pattern.
    """
    if input_path.is_file():
        return [input_path]

    if input_path.is_dir():
        files = sorted(input_path.rglob(pattern))
        return files

    return []


def make_stats() -> dict:
    """Create a fresh statistics dictionary."""
    return {
        "straight_double": 0,
        "english_double": 0,
        "english_single": 0,
        "lines_changed": 0,
        "warnings": 0,
    }


def print_diff(original: str, modified: str):
    """Display line-by-line differences between original and result."""
    orig_lines = original.split("\n")
    mod_lines = modified.split("\n")

    max_lines = max(len(orig_lines), len(mod_lines))
    changes_shown = 0

    for i in range(max_lines):
        orig = orig_lines[i] if i < len(orig_lines) else ""
        mod = mod_lines[i] if i < len(mod_lines) else ""

        if orig != mod:
            print(f"  Line {i + 1}:")
            print(f"    - {orig.rstrip()}")
            print(f"    + {mod.rstrip()}")
            changes_shown += 1

    if changes_shown == 0:
        print("  No changes.")


def print_stats(stats: dict):
    """Print the summary statistics for a single file or aggregated run."""
    total_replacements = (
        stats["straight_double"] + stats["english_double"] + stats["english_single"]
    )

    print(f"  Straight \" -> German:       {stats['straight_double']} pair(s)")
    print(f"  English typographic double: {stats['english_double']} correction(s)")
    print(f"  English typographic single: {stats['english_single']} correction(s)")
    print(f"  Lines changed:              {stats['lines_changed']}")
    print(f"  Warnings (asymmetric):      {stats['warnings']}")
    print(f"  Total replacements:         {total_replacements}")


def process_single_file(
    file_path: Path, dry_run: bool, global_stats: dict
) -> list[str]:
    """
    Process a single file: read, convert, optionally write.

    Returns a list of warning strings. Updates global_stats in-place.
    """
    content = file_path.read_text(encoding="utf-8")

    stats = make_stats()
    warnings: list[str] = []

    result = process_file(content, stats, warnings)

    # Accumulate into global stats
    for key in global_stats:
        global_stats[key] += stats[key]

    total = stats["straight_double"] + stats["english_double"] + stats["english_single"]

    if total == 0 and not warnings:
        return warnings

    if dry_run:
        print(f"\n--- {file_path} (dry-run) ---")
        print_diff(content, result)
    else:
        if result != content:
            backup_path = file_path.with_suffix(file_path.suffix + ".bak")
            shutil.copy2(file_path, backup_path)
            file_path.write_text(result, encoding="utf-8")
            print(f"  Written: {file_path} (backup: {backup_path})")
        else:
            print(f"  Unchanged: {file_path}")

    return warnings


def main():
    args = parse_args()
    input_path: Path = args.input

    if not input_path.exists():
        print(f"Error: Path not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    files = collect_files(input_path, args.pattern)

    if not files:
        print(
            f"Error: No files matching '{args.pattern}' found in: {input_path}",
            file=sys.stderr,
        )
        sys.exit(1)

    if input_path.is_dir():
        print(
            f"Processing {len(files)} file(s) in: {input_path} "
            f"(pattern: {args.pattern})"
        )

    global_stats = make_stats()
    all_warnings: list[str] = []

    for file_path in files:
        file_warnings = process_single_file(file_path, args.dry_run, global_stats)
        # Prefix warnings with file path for directory mode
        for w in file_warnings:
            all_warnings.append(f"[{file_path}] {w}")

    # Print warnings to stderr
    if all_warnings:
        print("\n--- WARNINGS ---", file=sys.stderr)
        for w in all_warnings:
            print(f"  WARNING: {w}", file=sys.stderr)
        print(f"--- {len(all_warnings)} warning(s) ---\n", file=sys.stderr)

    # Summary
    print("\n--- Summary ---")
    if input_path.is_dir():
        print(f"  Files processed:            {len(files)}")
    print_stats(global_stats)

    if args.dry_run:
        print("\nNo files written (--dry-run).")


if __name__ == "__main__":
    main()
