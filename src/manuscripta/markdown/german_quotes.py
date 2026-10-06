#!/usr/bin/env python3
# scripts/fix_german_quotes.py
"""
fix-german-quotes, fix-english-quotes, fix-french-quotes,
fix-spanish-quotes - Convert quotation marks in Markdown files to German,
English, French or Spanish typographic style.

fix-german-quotes:
  Double: „ “ (U+201E / U+201C)
  Single: ‚ ‘ (U+201A / U+2018)

  Converted: straight double quotes (") and English typographic quotes
  (U+201C/U+201D and U+2018/U+2019). Straight single quotes (') are left
  alone on purpose: in running text they cannot be told apart from
  apostrophes ("geht's" versus 'Zitat'), so converting them would break
  more than it fixes.

fix-english-quotes:
  Double: “ ” (U+201C / U+201D)
  Single: ‘ ’ (U+2018 / U+2019), apostrophe ’ (U+2019)

  Converted: straight double quotes (") and straight single quotes (').
  English writes the closing single quote and the apostrophe alike, so
  only an opening ' needs its context (see replace_straight_single_quotes).
  German typographic quotes („ ‚) are left alone.

fix-french-quotes, fix-spanish-quotes:
  Double: « » (U+00AB / U+00BB), French with a no-break space inside
          (« texte »), Spanish without («texto»)
  Single: ‘ ’ and apostrophe ’, as in English

  Converted: straight double quotes, straight single quotes (as in
  English, so l'homme becomes l’homme) and the space inside every
  guillemet, existing ones included. English and German typographic
  quotes are left alone: “ ” is the second level in both languages.
  fix-french-quotes also sets a no-break space before ; : ! ? (see
  space_punctuation), so it covers French spacing as a whole.

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
  fix-english-quotes ./my_book/          (same options)
  fix-french-quotes ./my_book/           (same options)
  fix-spanish-quotes ./my_book/          (same options)
"""

import argparse
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path


# --- Character constants ---

# German target characters
DE_OPEN_DOUBLE = "\u201e"  # „
DE_CLOSE_DOUBLE = "\u201c"  # "
DE_OPEN_SINGLE = "\u201a"  # ‚
DE_CLOSE_SINGLE = "\u2018"  # '

# English typographic characters (replaced by fix-german-quotes, the
# target of fix-english-quotes)
EN_OPEN_DOUBLE = "\u201c"  # " (identical to DE_CLOSE_DOUBLE)
EN_CLOSE_DOUBLE = "\u201d"  # "
EN_OPEN_SINGLE = "\u2018"  # ' (identical to DE_CLOSE_SINGLE)
EN_CLOSE_SINGLE = "\u2019"  # '

# Straight (ASCII) quotation marks
STRAIGHT_DOUBLE = '"'
STRAIGHT_SINGLE = "'"

# French and Spanish double quotes (guillemets)
GUILLEMET_OPEN = "\u00ab"  # «
GUILLEMET_CLOSE = "\u00bb"  # »

# Space inside French guillemets: the no-break space U+00A0, which every
# e-reader font has. The narrow no-break space U+202F is the finer choice
# where the target fonts are known to carry it.
FR_GUILLEMET_SPACE = "\u00a0"

# Space before ; : ! ? in French: the same no-break space. The Imprimerie
# nationale sets the narrow U+202F before ; ! ? and U+00A0 before :.
FR_PUNCTUATION_SPACE = "\u00a0"

# Default glob pattern for directory mode
DEFAULT_PATTERN = "*.md"


@dataclass(frozen=True)
class QuoteStyle:
    """The target quotation marks of one language and the stages it runs."""

    name: str
    open_double: str
    close_double: str
    open_single: str
    close_single: str
    # Convert English typographic quotes (U+201C/U+201D, U+2018/U+2019).
    # Off for English, where they already are the target.
    convert_english_typographic: bool
    # Convert straight single quotes and apostrophes. Off for German, where
    # a straight ' cannot be told apart from an apostrophe.
    convert_straight_single: bool
    # The space inside guillemets: « x » in French, none in Spanish. None
    # for a style without guillemets, whose spacing is then left alone.
    guillemet_space: str | None = None
    # The space before ; : ! ? in French. None leaves that spacing alone.
    punctuation_space: str | None = None


GERMAN = QuoteStyle(
    name="German",
    open_double=DE_OPEN_DOUBLE,
    close_double=DE_CLOSE_DOUBLE,
    open_single=DE_OPEN_SINGLE,
    close_single=DE_CLOSE_SINGLE,
    convert_english_typographic=True,
    convert_straight_single=False,
)

ENGLISH = QuoteStyle(
    name="English",
    open_double=EN_OPEN_DOUBLE,
    close_double=EN_CLOSE_DOUBLE,
    open_single=EN_OPEN_SINGLE,
    close_single=EN_CLOSE_SINGLE,
    convert_english_typographic=False,
    convert_straight_single=True,
)

FRENCH = QuoteStyle(
    name="French",
    open_double=GUILLEMET_OPEN,
    close_double=GUILLEMET_CLOSE,
    open_single=EN_OPEN_SINGLE,
    close_single=EN_CLOSE_SINGLE,
    convert_english_typographic=False,
    convert_straight_single=True,
    guillemet_space=FR_GUILLEMET_SPACE,
    punctuation_space=FR_PUNCTUATION_SPACE,
)

SPANISH = QuoteStyle(
    name="Spanish",
    open_double=GUILLEMET_OPEN,
    close_double=GUILLEMET_CLOSE,
    open_single=EN_OPEN_SINGLE,
    close_single=EN_CLOSE_SINGLE,
    convert_english_typographic=False,
    convert_straight_single=True,
    guillemet_space="",
)

# Besides whitespace and the start of a block, the characters after which
# a straight ' opens a quotation: opening brackets, opening double quotes,
# Markdown emphasis markers and dashes.
_SINGLE_OPENING_CONTEXT = '([{“„«"*_—–'

# A leading apostrophe before a decade ('90s) is not an opening quote
_DECADE_RE = re.compile(r"\d\ds\b")

# A guillemet with the horizontal whitespace inside it
_INNER_SPACE = "[ \\t\u00a0\u202f]*"
_GUILLEMET_SPACING_RE = re.compile(
    f"{GUILLEMET_OPEN}{_INNER_SPACE}|{_INNER_SPACE}{GUILLEMET_CLOSE}"
)

# A run of ; : ! ? with the horizontal whitespace before it
_PUNCTUATION_SPACING_RE = re.compile(f"({_INNER_SPACE})([;:!?]+)")
# Characters after which ; : ! ? never take a space (start of a group)
_NO_SPACE_AFTER = "([{\u00ab\u201c\u2018<"
# Characters that may follow ; ! ? when they get a space: closing quotes
# and brackets, Markdown emphasis markers; : only before emphasis markers
# and the ] that ends a link text ([Vous y trouverez :](#...))
_FOLLOWS_PUNCTUATION = '\u00bb\u201d\u2019")]}*_'
_FOLLOWS_COLON = "*_]"
# A : after these is markup: the footnote definition [^1]: and the link
# reference [id]: url, the alignment colon of a table delimiter row ---:
_NO_SPACE_BEFORE_COLON = "]-"
# HTML entities such as &nbsp; end in a ; that is no punctuation
_HTML_ENTITY_RE = re.compile(r"&#?[0-9A-Za-z]+;")

# Lines that open a block of their own (after stripping leading whitespace):
# headings, list items (bullet or numbered) and table rows. Quotes are
# paired inside one block and never across a block boundary.
_HEADING_RE = re.compile(r"^#")
_LIST_ITEM_RE = re.compile(r"^(?:[-*+]|\d+[.)])\s")
_TABLE_ROW_RE = re.compile(r"^\|")

# Shown between the lines of a multi-line block in a warning's context excerpt
CONTEXT_LINE_SEPARATOR = " \u23ce "  # " ⏎ "


def parse_args(style: QuoteStyle = GERMAN):
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Converts quotation marks in Markdown files "
        f"to {style.name} typographic style."
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
    style: QuoteStyle = GERMAN,
) -> str:
    """
    Replace straight double quotation marks pairwise with the double
    quotes of ``style`` (German „ “ by default).

    ``line`` is one block of text and may contain line breaks; ``line_num``
    is the 1-based file line number of its first line and ``line_end``
    that of its last line (``None`` for a single line). Both only appear
    in the warning for an odd number of quotation marks.

    Also handles mixed cases: if a typographic opening quote of ``style``
    („ in German, “ in English) is already present and a straight "
    follows as closing quote, only the closing character is converted.
    """
    chars = list(line)
    straight_positions = find_quote_positions(line, STRAIGHT_DOUBLE, protected)

    if not straight_positions:
        return line

    # Phase 1: An existing typographic opening quote (German „ U+201E)
    # that is still open, i.e. not yet closed by its closing quote (German
    # “ U+201C), takes the next straight " as its closing counterpart. An
    # opener that is already closed takes none, so in „Hallo“ und "Welt"
    # the two straight quotes pair with each other.
    consumed_straight = set()
    open_count = 0
    for i, ch in enumerate(chars):
        if is_protected(i, protected):
            continue
        if ch == style.open_double:
            open_count += 1
        elif ch == style.close_double:
            open_count = max(open_count - 1, 0)
        elif ch == STRAIGHT_DOUBLE and open_count:
            chars[i] = style.close_double
            consumed_straight.add(i)
            stats["straight_double"] += 1
            open_count -= 1

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
        chars[close_pos] = style.close_double
        chars[open_pos] = style.open_double
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


def replace_straight_single_quotes(
    line: str,
    protected: list[tuple[int, int]],
    stats: dict,
    warnings: list,
    line_num: int,
    line_end: int | None = None,
    style: QuoteStyle = ENGLISH,
) -> str:
    """
    Replace straight single quotation marks and apostrophes.

    Only for a style that writes the closing single quote and the
    apostrophe alike (English ’ U+2019), so only an opening ' needs its
    context. A straight ' becomes:

    - an apostrophe between two letters or digits (don't, O'Brien)
    - an opening quote at the start of the block or after whitespace, an
      opening bracket, an opening double quote, an emphasis marker or a
      dash, when a non-space character follows; before a decade ('90s)
      it is an apostrophe instead
    - a closing quote or apostrophe after a non-space character when no
      letter or digit follows ('word', the students' books)

    A lone ' between spaces stays as it is. An opening quote needs a
    closing one (straight or typographic) later in the same block. If one
    stays open, for example the elision in 'tis or 'em, the block's
    opening quotes stay straight and a warning names the block; its
    apostrophes and closing quotes are still converted. ``line_num`` and
    ``line_end`` only appear in that warning (see
    ``replace_straight_double_quotes``). ``stats["straight_single"]``
    counts the converted characters.
    """
    chars = list(line)
    openers: list[int] = []
    open_count = 0

    for i, ch in enumerate(chars):
        if is_protected(i, protected):
            continue
        prev = line[i - 1] if i > 0 else ""
        nxt = line[i + 1] if i + 1 < len(line) else ""
        if ch == style.open_single:
            open_count += 1
        elif ch not in (STRAIGHT_SINGLE, style.close_single):
            continue
        elif prev.isalnum() and nxt.isalnum():
            # Apostrophe inside a word
            if ch == STRAIGHT_SINGLE:
                chars[i] = style.close_single
                stats["straight_single"] += 1
        elif (
            ch == STRAIGHT_SINGLE
            and (not prev or prev.isspace() or prev in _SINGLE_OPENING_CONTEXT)
            and nxt
            and not nxt.isspace()
        ):
            if _DECADE_RE.match(line, i + 1):
                chars[i] = style.close_single
                stats["straight_single"] += 1
            else:
                openers.append(i)
                open_count += 1
        elif prev and not prev.isspace() and not nxt.isalnum():
            # Closing quote, or an apostrophe at the end of a word
            if ch == STRAIGHT_SINGLE:
                chars[i] = style.close_single
                stats["straight_single"] += 1
            open_count = max(open_count - 1, 0)

    if open_count and openers:
        warnings.append(
            f"{format_line_range(line_num, line_end)}: "
            f"Asymmetric straight quotation mark (') "
            f"- {open_count} opening quote(s) without a closing one\n"
            f"  Context: {format_context(line)}"
        )
        stats["warnings"] += 1
        return "".join(chars)

    for i in openers:
        chars[i] = style.open_single
        stats["straight_single"] += 1

    return "".join(chars)


def find_paired_guillemets(line: str, protected: list[tuple[int, int]]) -> set[int]:
    """Return the positions of the unprotected guillemets that pair up.

    Each » closes the nearest open « before it, so nested quotations pair
    as well. A « that is never closed in the block and a » without an open
    « are not in the result.
    """
    paired: set[int] = set()
    open_positions: list[int] = []
    for i, ch in enumerate(line):
        if is_protected(i, protected):
            continue
        if ch == GUILLEMET_OPEN:
            open_positions.append(i)
        elif ch == GUILLEMET_CLOSE and open_positions:
            paired.add(open_positions.pop())
            paired.add(i)
    return paired


def space_guillemets(
    line: str, protected: list[tuple[int, int]], stats: dict, style: QuoteStyle
) -> str:
    """
    Set the space inside every paired guillemet to ``style.guillemet_space``.

    The horizontal whitespace after « and before », whether an ordinary
    space, a no-break space or none, becomes exactly that space: U+00A0 in
    French (« texte »), nothing in Spanish («texto»). Only guillemets
    that pair up in the block are touched; a lone one, such as the marker
    in a heading "### » Title", an arrow, or a quotation that runs on into
    the next paragraph, keeps its spacing. A guillemet at a line break is
    left alone too, so a line never starts or ends with an inserted space.
    ``stats["guillemet_space"]`` counts the guillemets whose spacing changed.

    Runs last because it can change the length of the block.
    """
    space = style.guillemet_space
    if space is None:
        return line

    paired = find_paired_guillemets(line, protected)

    def respace(m: re.Match) -> str:
        found = m.group(0)
        if found.startswith(GUILLEMET_OPEN):
            if m.start() not in paired or line[m.end()] == "\n":
                return found
            wanted = GUILLEMET_OPEN + space
        else:
            if m.end() - 1 not in paired or line[m.start() - 1] == "\n":
                return found
            wanted = space + GUILLEMET_CLOSE
        if wanted != found:
            stats["guillemet_space"] += 1
        return wanted

    return _GUILLEMET_SPACING_RE.sub(respace, line)


def space_punctuation(
    line: str, protected: list[tuple[int, int]], stats: dict, style: QuoteStyle
) -> str:
    """
    Set the space before ; : ! ? to ``style.punctuation_space`` (French).

    The horizontal whitespace before a run of these marks (Quoi ?!), an
    ordinary space, a no-break space or none, becomes exactly that space.
    A run is left alone where it is no French punctuation:

    - at the start of a line or after an opening bracket or quote: (?)
    - a ; that ends an HTML entity: &nbsp;
    - a : that is not followed by whitespace, the end of the block, an
      emphasis marker or ] (https://, 10:30, :) and a : after ] or - (the
      footnote definition [^1]:, the link reference [id]: url, the table
      delimiter row | ---: |)
    - ; ! ? followed by anything but whitespace, the end of the block, a
      closing quote or bracket or an emphasis marker (![image], ?id=1)

    ``stats["punctuation_space"]`` counts the runs whose spacing changed.
    Runs after the other stages because it can change the length.
    """
    space = style.punctuation_space
    if space is None:
        return line

    protected = protected + [
        (m.start(), m.end()) for m in _HTML_ENTITY_RE.finditer(line)
    ]

    def respace(m: re.Match) -> str:
        found = m.group(0)
        marks = m.group(2)
        if m.start() == 0 or is_protected(m.start(2), protected):
            return found
        before = line[m.start() - 1]
        after = line[m.end()] if m.end() < len(line) else ""
        if before == "\n" or before in _NO_SPACE_AFTER:
            return found
        if ":" in marks:
            if before in _NO_SPACE_BEFORE_COLON:
                return found
            allowed = after == "" or after.isspace() or after in _FOLLOWS_COLON
        else:
            allowed = after == "" or after.isspace() or after in _FOLLOWS_PUNCTUATION
        if not allowed:
            return found
        wanted = space + marks
        if wanted != found:
            stats["punctuation_space"] += 1
        return wanted

    return _PUNCTUATION_SPACING_RE.sub(respace, line)


def process_block(
    text: str,
    first_line_num: int,
    stats: dict,
    warnings: list,
    style: QuoteStyle = GERMAN,
) -> str:
    """Run one block of text through the quote replacement stages of ``style``.

    ``text`` is a paragraph, list item, heading or table row and may span
    several lines joined with "\\n"; quotes are paired across those lines.
    ``first_line_num`` is the 1-based file line number of the first line
    and is used, together with the computed last line, in warnings.
    """
    last_line_num = first_line_num + text.count("\n")
    protected = mask_protected_regions(text)

    # 1. Straight double quotation marks
    text = replace_straight_double_quotes(
        text, protected, stats, warnings, first_line_num, last_line_num, style
    )

    if style.convert_english_typographic:
        # Recompute protected regions after modification
        protected = mask_protected_regions(text)

        # 2. English typographic double quotation marks
        text = replace_english_double_quotes(text, protected, stats)

        protected = mask_protected_regions(text)

        # 3. English typographic single quotation marks
        text = replace_english_single_quotes(text, protected, stats)

    if style.convert_straight_single:
        protected = mask_protected_regions(text)

        # 4. Straight single quotation marks and apostrophes
        text = replace_straight_single_quotes(
            text, protected, stats, warnings, first_line_num, last_line_num, style
        )

    if style.guillemet_space is not None:
        protected = mask_protected_regions(text)

        # 5. Space inside guillemets (it can change the length)
        text = space_guillemets(text, protected, stats, style)

    if style.punctuation_space is not None:
        protected = mask_protected_regions(text)

        # 6. Space before ; : ! ? (it can change the length)
        text = space_punctuation(text, protected, stats, style)

    return text


def process_line(
    line: str,
    line_num: int,
    stats: dict,
    warnings: list,
    style: QuoteStyle = GERMAN,
) -> str:
    """Process a single line as a block of its own (see ``process_block``)."""
    return process_block(line, line_num, stats, warnings, style)


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


def process_file(
    content: str, stats: dict, warnings: list, style: QuoteStyle = GERMAN
) -> str:
    """Process the entire file content with the quotes of ``style``.

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
        converted = process_block("\n".join(block), block_start, stats, warnings, style)
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
        "straight_single": 0,
        "guillemet_space": 0,
        "punctuation_space": 0,
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


def count_replacements(stats: dict) -> int:
    """Return the number of replacements recorded in ``stats``."""
    return (
        stats["straight_double"]
        + stats["english_double"]
        + stats["english_single"]
        + stats["straight_single"]
        + stats["guillemet_space"]
        + stats["punctuation_space"]
    )


def print_stats(stats: dict, style: QuoteStyle = GERMAN):
    """Print the summary statistics for a single file or aggregated run.

    Only the stages that ``style`` runs get a line of their own.
    """
    rows: list[tuple[str, object]] = [
        (f'Straight " -> {style.name}:', f"{stats['straight_double']} pair(s)")
    ]
    if style.convert_english_typographic:
        rows.append(
            ("English typographic double:", f"{stats['english_double']} correction(s)")
        )
        rows.append(
            ("English typographic single:", f"{stats['english_single']} correction(s)")
        )
    if style.convert_straight_single:
        rows.append(
            (f"Straight ' -> {style.name}:", f"{stats['straight_single']} mark(s)")
        )
    if style.guillemet_space is not None:
        rows.append(("Guillemet spacing:", f"{stats['guillemet_space']} correction(s)"))
    if style.punctuation_space is not None:
        rows.append(
            ("Space before ; : ! ?:", f"{stats['punctuation_space']} correction(s)")
        )
    rows.append(("Lines changed:", stats["lines_changed"]))
    rows.append(("Warnings (asymmetric):", stats["warnings"]))
    rows.append(("Total replacements:", count_replacements(stats)))

    for label, value in rows:
        print(f"  {label:<28}{value}")


def process_single_file(
    file_path: Path, dry_run: bool, global_stats: dict, style: QuoteStyle = GERMAN
) -> list[str]:
    """
    Process a single file: read, convert, optionally write.

    Returns a list of warning strings. Updates global_stats in-place.
    """
    content = file_path.read_text(encoding="utf-8")

    stats = make_stats()
    warnings: list[str] = []

    result = process_file(content, stats, warnings, style)

    # Accumulate into global stats
    for key in global_stats:
        global_stats[key] += stats[key]

    if count_replacements(stats) == 0 and not warnings:
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


def main(style: QuoteStyle = GERMAN):
    """Command line entry point of fix-german-quotes."""
    args = parse_args(style)
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
        file_warnings = process_single_file(
            file_path, args.dry_run, global_stats, style
        )
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
    print_stats(global_stats, style)

    if args.dry_run:
        print("\nNo files written (--dry-run).")


def main_english():
    """Command line entry point of fix-english-quotes."""
    main(ENGLISH)


def main_french():
    """Command line entry point of fix-french-quotes."""
    main(FRENCH)


def main_spanish():
    """Command line entry point of fix-spanish-quotes."""
    main(SPANISH)


if __name__ == "__main__":
    main()
