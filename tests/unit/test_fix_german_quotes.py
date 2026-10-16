import pytest

pytestmark = pytest.mark.unit

"""Unit tests for fix-german-quotes - German typographic quote conversion."""

import shutil
import subprocess
import sys

from manuscripta.markdown.german_quotes import (
    CONTEXT_LINE_SEPARATOR,
    DE_CLOSE_DOUBLE,
    DE_CLOSE_SINGLE,
    DE_OPEN_DOUBLE,
    DE_OPEN_SINGLE,
    EN_CLOSE_DOUBLE,
    EN_CLOSE_SINGLE,
    EN_OPEN_DOUBLE,
    EN_OPEN_SINGLE,
    STRAIGHT_DOUBLE,
    collect_files,
    find_quote_positions,
    format_context,
    format_line_range,
    is_git_tracked,
    is_in_frontmatter,
    is_protected,
    is_single_line_block,
    main,
    make_stats,
    mask_protected_regions,
    parse_args,
    print_diff,
    print_stats,
    process_block,
    process_file,
    process_line,
    process_single_file,
    replace_english_double_quotes,
    replace_english_single_quotes,
    replace_straight_double_quotes,
    starts_own_block,
)

SEP = CONTEXT_LINE_SEPARATOR


def de(text: str) -> str:
    """A German double quotation „…“."""
    return f"{DE_OPEN_DOUBLE}{text}{DE_CLOSE_DOUBLE}"


def de_single(text: str) -> str:
    """A German single quotation ‚…‘."""
    return f"{DE_OPEN_SINGLE}{text}{DE_CLOSE_SINGLE}"


def en(text: str) -> str:
    """An English typographic double quotation “…”."""
    return f"{EN_OPEN_DOUBLE}{text}{EN_CLOSE_DOUBLE}"


def en_single(text: str) -> str:
    """An English typographic single quotation ‘…’."""
    return f"{EN_OPEN_SINGLE}{text}{EN_CLOSE_SINGLE}"


def unpaired(label: str, context: str, count: int = 1) -> str:
    """The warning for ``count`` unpaired straight quotation marks in a block,
    ``label`` being its "Line 5" or "Lines 7-8" and ``context`` its excerpt."""
    return (
        f'{label}: Asymmetric straight quotation mark (") '
        f"- {count} unpaired occurrence(s)\n  Context: {context}"
    )


# ---------------------------------------------------------------------------
# is_in_frontmatter
# ---------------------------------------------------------------------------
FRONTMATTER = ["---", "title: Test", "---", "Content"]
NO_FRONTMATTER = ["Normal text", "Another line"]
UNCLOSED_FRONTMATTER = ["---", "title: Test", "No closing"]

# Each row: the lines of a file, a 0-based line index, whether that line is
# inside the frontmatter
FRONTMATTER_CASES = [
    pytest.param(FRONTMATTER, 1, True, id="inside-frontmatter"),
    pytest.param(FRONTMATTER, 3, False, id="outside-frontmatter"),
    pytest.param(FRONTMATTER, 0, False, id="first-fence-line"),
    pytest.param(FRONTMATTER, 2, True, id="closing-fence-line"),
    pytest.param(NO_FRONTMATTER, 0, False, id="no-frontmatter"),
    pytest.param(NO_FRONTMATTER, 1, False, id="no-frontmatter-second-line"),
    pytest.param(UNCLOSED_FRONTMATTER, 1, True, id="unclosed-frontmatter"),
    pytest.param(UNCLOSED_FRONTMATTER, 2, True, id="unclosed-frontmatter-last-line"),
    pytest.param([], 0, False, id="empty-lines"),
]


class TestIsInFrontmatter:
    @pytest.mark.parametrize("lines, line_idx, expected", FRONTMATTER_CASES)
    def test_is_in_frontmatter(self, lines, line_idx, expected):
        assert is_in_frontmatter(lines, line_idx) is expected


# ---------------------------------------------------------------------------
# mask_protected_regions
# ---------------------------------------------------------------------------
# Each row: a line (or a block with line breaks) and the text every protected
# span covers, in order. A protected region never spans a line break, as
# blocks are multi-line.
PROTECTED_REGION_CASES = [
    pytest.param("Normal text", [], id="no-protected"),
    pytest.param("Text `code here` more", ["`code here`"], id="inline-code"),
    pytest.param("`a` and `b`", ["`a`", "`b`"], id="multiple-inline-code"),
    pytest.param(
        '<a href="http://example.com"> tag',
        ['href="http://example.com"'],
        id="html-attribute-double",
    ),
    pytest.param(
        "<a href='http://example.com'> tag",
        ["href='http://example.com'"],
        id="html-attribute-single",
    ),
    pytest.param("`a\nb`", [], id="inline-code-does-not-span-lines"),
    pytest.param('href="a\nb"', [], id="html-attribute-double-does-not-span-lines"),
    pytest.param("href='a\nb'", [], id="html-attribute-single-does-not-span-lines"),
    pytest.param(
        'x `"c"` y\n"z"',
        ['`"c"`'],
        id="inline-code-inside-a-block-is-still-protected",
    ),
]


class TestMaskProtectedRegions:
    @pytest.mark.parametrize("line, covered", PROTECTED_REGION_CASES)
    def test_mask_protected_regions(self, line, covered):
        spans = mask_protected_regions(line)
        assert [line[start:end] for start, end in spans] == covered


# ---------------------------------------------------------------------------
# is_protected
# ---------------------------------------------------------------------------
# Each row: a position, the protected spans, whether the position is protected
IS_PROTECTED_CASES = [
    pytest.param(7, [(5, 10), (20, 30)], True, id="inside-span"),
    pytest.param(15, [(5, 10), (20, 30)], False, id="outside-span"),
    pytest.param(5, [(5, 10)], True, id="at-start-boundary"),
    pytest.param(9, [(5, 10)], True, id="before-end-boundary"),
    pytest.param(10, [(5, 10)], False, id="at-end-boundary-exclusive"),
    pytest.param(0, [], False, id="empty-spans"),
]


class TestIsProtected:
    @pytest.mark.parametrize("pos, spans, expected", IS_PROTECTED_CASES)
    def test_is_protected(self, pos, spans, expected):
        assert is_protected(pos, spans) is expected


# ---------------------------------------------------------------------------
# find_quote_positions
# ---------------------------------------------------------------------------
# Each row: a line, the protected spans, the positions of the straight double
# quotes outside those spans
QUOTE_POSITION_CASES = [
    pytest.param('"Hello" world', [], [0, 6], id="finds-straight-doubles"),
    # (0, 8) is the span of the inline code `"code"`
    pytest.param('`"code"` and "text"', [(0, 8)], [13, 18], id="skips-protected"),
    pytest.param("No quotes here", [], [], id="no-matches"),
]


class TestFindQuotePositions:
    @pytest.mark.parametrize("line, protected, expected", QUOTE_POSITION_CASES)
    def test_find_quote_positions(self, line, protected, expected):
        assert find_quote_positions(line, STRAIGHT_DOUBLE, protected) == expected


# ---------------------------------------------------------------------------
# replace_straight_double_quotes
# ---------------------------------------------------------------------------
# Each row: line 5 of a file, the result, the pairs counted in straight_double,
# the warnings. Inline code of the line is protected.
STRAIGHT_DOUBLE_CASES = [
    pytest.param('"Hello"', de("Hello"), 1, [], id="single-pair"),
    pytest.param(
        '"One" and "Two"', f"{de('One')} and {de('Two')}", 2, [], id="two-pairs"
    ),
    pytest.param(
        '"Only one',
        '"Only one',
        0,
        [unpaired("Line 5", '"Only one')],
        id="odd-count-warning",
    ),
    pytest.param("No quotes", "No quotes", 0, [], id="no-straight-quotes"),
    pytest.param(
        '`"code"` and "text"',
        f"`\"code\"` and {de('text')}",
        1,
        [],
        id="protected-not-touched",
    ),
    # Existing German opening with straight closing quote.
    pytest.param(
        f'{DE_OPEN_DOUBLE}Hello"',
        de("Hello"),
        1,
        [],
        id="mixed-german-open-with-straight-close",
    ),
    pytest.param(
        '"a" b "',
        '"a" b "',
        0,
        [unpaired("Line 5", '"a" b "', 3)],
        id="three-straight-quotes-warning",
    ),
    # An already closed „…“ leaves the following straight pair intact.
    pytest.param(
        f'{de("Hallo")}, sagte er, "und tschüss."',
        f"{de('Hallo')}, sagte er, {de('und tschüss.')}",
        1,
        [],
        id="closed-german-pair-does-not-take-the-next-straight-quote",
    ),
    pytest.param(
        f'{DE_OPEN_DOUBLE}a" und {DE_OPEN_DOUBLE}b"',
        f"{de('a')} und {de('b')}",
        2,
        [],
        id="two-open-german-quotes-each-take-a-straight-close",
    ),
    # 1st straight = opening, 2nd = closing.
    pytest.param(
        'He said "Yes" and "No"',
        f"He said {de('Yes')} and {de('No')}",
        2,
        [],
        id="straight-quote-pair-assignment",
    ),
]


class TestReplaceStraightDoubleQuotes:
    @pytest.mark.parametrize(
        "line, expected, pairs, expected_warnings", STRAIGHT_DOUBLE_CASES
    )
    def test_replace_straight_double_quotes(
        self, line, expected, pairs, expected_warnings
    ):
        stats = make_stats()
        warnings: list[str] = []
        result = replace_straight_double_quotes(
            line, mask_protected_regions(line), stats, warnings, 5
        )
        assert result == expected
        assert stats["straight_double"] == pairs
        assert warnings == expected_warnings
        assert stats["warnings"] == len(expected_warnings)


# ---------------------------------------------------------------------------
# replace_english_double_quotes
# ---------------------------------------------------------------------------
# Each row: a line, the result, the english_double count (one per changed
# line, not per pair). Without U+201D nothing happens, U+201C is ambiguous.
ENGLISH_DOUBLE_CASES = [
    pytest.param(en("Hello"), de("Hello"), 1, id="english-pair-to-german"),
    # Standalone U+201D is converted to U+201C.
    pytest.param(
        f"Word{EN_CLOSE_DOUBLE}",
        f"Word{DE_CLOSE_DOUBLE}",
        1,
        id="standalone-close-double",
    ),
    pytest.param("Normal text", "Normal text", 0, id="no-english-quotes"),
    pytest.param(
        f"Text {EN_OPEN_DOUBLE}word",
        f"Text {EN_OPEN_DOUBLE}word",
        0,
        id="without-en-close-no-change",
    ),
    pytest.param(
        f"{en('One')} and {en('Two')}",
        f"{de('One')} and {de('Two')}",
        1,
        id="multiple-pairs",
    ),
]


class TestReplaceEnglishDoubleQuotes:
    @pytest.mark.parametrize("text, expected, count", ENGLISH_DOUBLE_CASES)
    def test_replace_english_double_quotes(self, text, expected, count):
        stats = make_stats()
        assert replace_english_double_quotes(text, [], stats) == expected
        assert stats["english_double"] == count


# ---------------------------------------------------------------------------
# replace_english_single_quotes
# ---------------------------------------------------------------------------
# Each row: a line, the result, the english_single count (one per changed
# line, not per pair)
ENGLISH_SINGLE_CASES = [
    pytest.param(
        f"Text {en_single('word')} more",
        f"Text {de_single('word')} more",
        1,
        id="english-single-pair",
    ),
    pytest.param("Normal text", "Normal text", 0, id="no-single-quotes"),
    # Only U+2018 without U+2019: no pair, no conversion.
    pytest.param(
        f"Text {EN_OPEN_SINGLE}word",
        f"Text {EN_OPEN_SINGLE}word",
        0,
        id="only-open-no-close",
    ),
    pytest.param(
        f"{en_single('A')} {en_single('B')}",
        f"{de_single('A')} {de_single('B')}",
        1,
        id="multiple-pairs",
    ),
]


class TestReplaceEnglishSingleQuotes:
    @pytest.mark.parametrize("text, expected, count", ENGLISH_SINGLE_CASES)
    def test_replace_english_single_quotes(self, text, expected, count):
        stats = make_stats()
        assert replace_english_single_quotes(text, [], stats) == expected
        assert stats["english_single"] == count


# ---------------------------------------------------------------------------
# process_line (integration)
# ---------------------------------------------------------------------------
# Each row: line 1 of a file, the result, the warnings
PROCESS_LINE_CASES = [
    pytest.param(
        '"Hello world"', de("Hello world"), [], id="straight-quotes-converted"
    ),
    pytest.param(
        'Text `"code"` more "yes"',
        f"Text `\"code\"` more {de('yes')}",
        [],
        id="inline-code-protected",
    ),
    pytest.param("", "", [], id="empty-line"),
    pytest.param(
        "A normal sentence without quotation marks.",
        "A normal sentence without quotation marks.",
        [],
        id="no-quotes",
    ),
    pytest.param(
        f"He said {en('yes')}.",
        f"He said {de('yes')}.",
        [],
        id="english-double-in-line",
    ),
    pytest.param(
        '<a href="http://x.com"> "Link"',
        f"<a href=\"http://x.com\"> {de('Link')}",
        [],
        id="html-attribute-protected",
    ),
    pytest.param("   ", "   ", [], id="only-whitespace-line"),
    pytest.param(
        '"', '"', [unpaired("Line 1", '"')], id="single-straight-quote-warning"
    ),
    pytest.param(de("Correct"), de("Correct"), [], id="german-open-close-pair-intact"),
    # Straight and English typographic in the same line: after the straight
    # stage it reads „Straight“ and “English”, and the “ that closes the first
    # pair must not be taken for the opener of the second (fixed in e042679)
    pytest.param(
        f'"Straight" and {en("English")}',
        f"{de('Straight')} and {de('English')}",
        [],
        id="mixed-straight-and-english",
    ),
    # an unclosed earlier opener stays; the nearest one opens the pair
    pytest.param(
        f"{EN_OPEN_DOUBLE} {en('a')}",
        f"{EN_OPEN_DOUBLE} {de('a')}",
        [],
        id="unclosed-earlier-opener-stays",
    ),
    # process_line is a single-line block (see process_block)
    pytest.param('"a"', de("a"), [], id="is-a-single-line-block"),
]


class TestProcessLine:
    @pytest.mark.parametrize("line, expected, expected_warnings", PROCESS_LINE_CASES)
    def test_process_line(self, line, expected, expected_warnings):
        stats = make_stats()
        warnings: list[str] = []
        assert process_line(line, 1, stats, warnings) == expected
        assert warnings == expected_warnings

    def test_mixed_straight_and_english(self):
        """Straight and English typographic in the same line: two German pairs
        of characters come out, though not yet in the right places (see the
        mixed-straight-and-english row of PROCESS_LINE_CASES)."""
        stats = make_stats()
        text = f'"Straight" and {en("English")}'
        result = process_line(text, 1, stats, [])
        assert result.count(DE_OPEN_DOUBLE) == 2
        assert result.count(DE_CLOSE_DOUBLE) == 2


# ---------------------------------------------------------------------------
# process_block: quotes pair across the lines of one block
# ---------------------------------------------------------------------------
# Each row: a block, the file line number of its first line, the result, the
# warnings
PROCESS_BLOCK_CASES = [
    pytest.param(
        '"a\nb"',
        1,
        f"{DE_OPEN_DOUBLE}a\nb{DE_CLOSE_DOUBLE}",
        [],
        id="pairs-across-lines",
    ),
    pytest.param(
        '"a\nb',
        7,
        '"a\nb',
        [unpaired("Lines 7-8", f'"a{SEP}b')],
        id="warning-names-line-range-and-joined-context",
    ),
    pytest.param(
        '"a',
        5,
        '"a',
        [unpaired("Line 5", '"a')],
        id="single-line-block-warning-keeps-line-label",
    ),
]


class TestProcessBlock:
    @pytest.mark.parametrize(
        "text, first_line, expected, expected_warnings", PROCESS_BLOCK_CASES
    )
    def test_process_block(self, text, first_line, expected, expected_warnings):
        stats = make_stats()
        warnings: list[str] = []
        assert process_block(text, first_line, stats, warnings) == expected
        assert warnings == expected_warnings


# ---------------------------------------------------------------------------
# process_file (integration: frontmatter, code blocks, paragraph-level pairing)
# ---------------------------------------------------------------------------
# Each row: the file content, the result, the warnings, the stats that must
# match. Add a row to pin a new case.
PROCESS_FILE_CASES = [
    # Frontmatter and fenced code blocks pass through untouched
    pytest.param(
        '---\ntitle: "My Book"\n---\n"Content"',
        f'---\ntitle: "My Book"\n---\n{de("Content")}',
        [],
        {},
        id="frontmatter-preserved",
    ),
    pytest.param(
        'Text "yes"\n```\n"code"\n```\nText "no"',
        f'Text {de("yes")}\n```\n"code"\n```\nText {de("no")}',
        [],
        {},
        id="fenced-code-block-preserved",
    ),
    pytest.param(
        '```python\nprint("hello")\n```\n"Text"',
        f'```python\nprint("hello")\n```\n{de("Text")}',
        [],
        {},
        id="fenced-code-with-language",
    ),
    pytest.param(
        '"Hello"\n"World"',
        f"{de('Hello')}\n{de('World')}",
        [],
        {},
        id="no-frontmatter",
    ),
    pytest.param("", "", [], {}, id="empty-content"),
    pytest.param(
        '"a"\n```\n"b"\n```\n"c"\n```\n"d"\n```\n"e"',
        f'{de("a")}\n```\n"b"\n```\n{de("c")}\n```\n"d"\n```\n{de("e")}',
        [],
        {},
        id="multiple-code-blocks",
    ),
    pytest.param(
        de("Already correct"),
        de("Already correct"),
        [],
        {"straight_double": 0},
        id="already-german-quotes-untouched",
    ),
    pytest.param(
        '"Line one"\nNo quotes\n"Line three"',
        f"{de('Line one')}\nNo quotes\n{de('Line three')}",
        [],
        {"lines_changed": 2},
        id="lines-changed-counter",
    ),
    pytest.param(
        '---\nkey: "val"\n---\n\n```\n"safe"\n```\n\n"convert"',
        f'---\nkey: "val"\n---\n\n```\n"safe"\n```\n\n{de("convert")}',
        [],
        {},
        id="frontmatter-and-code-combined",
    ),
    # Edge cases
    pytest.param(
        "Line 1\nLine 2\nLine 3",
        "Line 1\nLine 2\nLine 3",
        [],
        {},
        id="multiline-preserves-line-count",
    ),
    pytest.param(
        '---\ntitle: "Test"\n---',
        '---\ntitle: "Test"\n---',
        [],
        {},
        id="frontmatter-only",
    ),
    # Unclosed code block: everything from ``` onward stays protected.
    pytest.param(
        '"before"\n```\n"inside"\n"also inside"',
        f'{de("before")}\n```\n"inside"\n"also inside"',
        [],
        {},
        id="unclosed-code-block",
    ),
    pytest.param(
        '"Clean" and "correct"',
        f"{de('Clean')} and {de('correct')}",
        [],
        {"warnings": 0},
        id="no-warnings-on-clean-input",
    ),
    pytest.param(
        '"Line one"\n"Line two"\n"Line three"',
        f"{de('Line one')}\n{de('Line two')}\n{de('Line three')}",
        [],
        {"straight_double": 3},
        id="stats-accumulate-across-lines",
    ),
    # Paragraph-level pairing: a block ends at a blank line, at a code fence,
    # before a heading, list item or table row and after a heading or table row
    pytest.param(
        'Er sagte: "Das war\nein Test." Und ging.',
        f"Er sagte: {DE_OPEN_DOUBLE}Das war\nein Test.{DE_CLOSE_DOUBLE} Und ging.",
        [],
        {"warnings": 0, "straight_double": 1, "lines_changed": 2},
        id="quote-split-over-two-wrapped-lines-is-paired",
    ),
    pytest.param(
        '"Erster Absatz\nohne Schluss.\n\nZweiter "Absatz\n\n"Dritter" Absatz',
        f'"Erster Absatz\nohne Schluss.\n\nZweiter "Absatz\n\n{de("Dritter")} Absatz',
        [
            unpaired("Lines 1-2", f'"Erster Absatz{SEP}ohne Schluss.'),
            unpaired("Line 4", 'Zweiter "Absatz'),
        ],
        {"warnings": 2},
        id="odd-paragraphs-warn-separately-with-file-line-numbers",
    ),
    pytest.param(
        '- "Nur eine\n- "Paar" hier\n- "Noch ein Paar"',
        f'- "Nur eine\n- {de("Paar")} hier\n- {de("Noch ein Paar")}',
        [unpaired("Line 1", '- "Nur eine')],
        {},
        id="list-items-are-paired-per-item",
    ),
    pytest.param(
        '- "Ein Zitat\n  über zwei Zeilen" fertig\n- Zweiter Punkt',
        f"- {DE_OPEN_DOUBLE}Ein Zitat\n  über zwei Zeilen{DE_CLOSE_DOUBLE} fertig\n"
        "- Zweiter Punkt",
        [],
        {},
        id="list-item-continuation-line-belongs-to-the-item",
    ),
    pytest.param(
        '1. "a\n2. "b"',
        f'1. "a\n2. {de("b")}',
        [unpaired("Line 1", '1. "a')],
        {},
        id="numbered-list-items-are-separate-blocks",
    ),
    pytest.param(
        '# Kapitel "auf\nText "zu',
        '# Kapitel "auf\nText "zu',
        [unpaired("Line 1", '# Kapitel "auf'), unpaired("Line 2", 'Text "zu')],
        {},
        id="heading-is-not-paired-with-the-paragraph-below",
    ),
    pytest.param(
        '| "a" | "b |\n| "c" | d |',
        f'| "a" | "b |\n| {de("c")} | d |',
        [unpaired("Line 1", '| "a" | "b |', 3)],
        {},
        id="table-rows-are-paired-per-row",
    ),
    pytest.param(
        '> "Zitat über\n> zwei Zeilen"',
        f"> {DE_OPEN_DOUBLE}Zitat über\n> zwei Zeilen{DE_CLOSE_DOUBLE}",
        [],
        {},
        id="blockquote-lines-join-the-running-block",
    ),
    pytest.param(
        'Text "a\nb"\n```\n"code"\n```\n"c\nd"',
        f'Text {DE_OPEN_DOUBLE}a\nb{DE_CLOSE_DOUBLE}\n```\n"code"\n```\n'
        f"{DE_OPEN_DOUBLE}c\nd{DE_CLOSE_DOUBLE}",
        [],
        {},
        id="paragraph-directly-before-a-fence-is-converted",
    ),
    pytest.param(
        '---\ntitle: "x"\n---\n"Eins\nzwei"',
        f'---\ntitle: "x"\n---\n{DE_OPEN_DOUBLE}Eins\nzwei{DE_CLOSE_DOUBLE}',
        [],
        {},
        id="frontmatter-then-wrapped-paragraph",
    ),
    pytest.param(
        '"Eins\nzwei"\nunverändert\n"drei"',
        f"{DE_OPEN_DOUBLE}Eins\nzwei{DE_CLOSE_DOUBLE}\nunverändert\n{de('drei')}",
        [],
        {"lines_changed": 3},
        id="lines-changed-counts-each-changed-line-once",
    ),
    pytest.param(
        f"{EN_OPEN_DOUBLE}Eins\nzwei{EN_CLOSE_DOUBLE}",
        f"{DE_OPEN_DOUBLE}Eins\nzwei{DE_CLOSE_DOUBLE}",
        [],
        {},
        id="english-double-quotes-pair-across-lines",
    ),
    pytest.param(
        f"{EN_OPEN_SINGLE}Eins\nzwei{EN_CLOSE_SINGLE}",
        f"{DE_OPEN_SINGLE}Eins\nzwei{DE_CLOSE_SINGLE}",
        [],
        {},
        id="english-single-quotes-pair-across-lines",
    ),
]


class TestProcessFile:
    @pytest.mark.parametrize(
        "content, expected, expected_warnings, expected_stats", PROCESS_FILE_CASES
    )
    def test_process_file(self, content, expected, expected_warnings, expected_stats):
        stats = make_stats()
        warnings: list[str] = []
        assert process_file(content, stats, warnings) == expected
        assert warnings == expected_warnings
        assert {key: stats[key] for key in expected_stats} == expected_stats


# ---------------------------------------------------------------------------
# collect_files (directory support)
# ---------------------------------------------------------------------------
# Each row: the files to create (relative paths), the path to collect from
# (relative, "." for the directory itself), the pattern, the files collected
# (relative paths, in order)
COLLECT_FILES_CASES = [
    pytest.param(["test.md"], "test.md", "*.md", ["test.md"], id="single-file"),
    pytest.param(
        ["a.md", "sub/b.md", "ignore.txt"],
        ".",
        "*.md",
        ["a.md", "sub/b.md"],
        id="directory-recursive",
    ),
    pytest.param([], ".", "*.md", [], id="directory-empty"),
    pytest.param(
        ["doc.markdown", "doc.md"],
        ".",
        "*.markdown",
        ["doc.markdown"],
        id="directory-custom-pattern",
    ),
    pytest.param([], "nonexistent", "*.md", [], id="nonexistent-path"),
    pytest.param(["a/b/c/deep.md"], ".", "*.md", ["a/b/c/deep.md"], id="deeply-nested"),
    pytest.param(
        ["c.md", "a.md", "b.md"],
        ".",
        "*.md",
        ["a.md", "b.md", "c.md"],
        id="sorted-output",
    ),
]


class TestCollectFiles:
    @pytest.mark.parametrize("files, target, pattern, expected", COLLECT_FILES_CASES)
    def test_collect_files(self, files, target, pattern, expected, tmp_path):
        for name in files:
            path = tmp_path / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("x", encoding="utf-8")
        result = collect_files(tmp_path / target, pattern)
        assert [str(p.relative_to(tmp_path)) for p in result] == expected


# ---------------------------------------------------------------------------
# process_single_file (integration with filesystem)
# ---------------------------------------------------------------------------
# Each row: the text of test.md, dry run?, its text afterwards, whether
# test.md.bak exists afterwards, the warnings returned
PROCESS_SINGLE_FILE_CASES = [
    pytest.param('"Hello"', False, de("Hello"), True, [], id="writes-file-and-backup"),
    pytest.param('"Hello"', True, '"Hello"', False, [], id="dry-run-no-write"),
    pytest.param(
        "No quotes here",
        False,
        "No quotes here",
        False,
        [],
        id="unchanged-file-no-backup",
    ),
    pytest.param(
        '"Only one',
        False,
        '"Only one',
        False,
        [unpaired("Line 1", '"Only one')],
        id="returns-warnings",
    ),
]


class TestProcessSingleFile:
    @pytest.mark.parametrize(
        "text, dry_run, expected, expect_bak, expected_warnings",
        PROCESS_SINGLE_FILE_CASES,
    )
    def test_process_single_file(
        self, text, dry_run, expected, expect_bak, expected_warnings, tmp_path
    ):
        f = tmp_path / "test.md"
        f.write_text(text, encoding="utf-8")
        warnings = process_single_file(f, dry_run=dry_run, global_stats=make_stats())
        assert f.read_text(encoding="utf-8") == expected
        assert (tmp_path / "test.md.bak").exists() is expect_bak
        assert warnings == expected_warnings

    def test_stats_accumulated(self, tmp_path):
        f1 = tmp_path / "a.md"
        f2 = tmp_path / "b.md"
        f1.write_text('"One"', encoding="utf-8")
        f2.write_text('"Two"', encoding="utf-8")
        global_stats = make_stats()
        process_single_file(f1, dry_run=False, global_stats=global_stats)
        process_single_file(f2, dry_run=False, global_stats=global_stats)
        assert global_stats["straight_double"] >= 2
        assert global_stats["lines_changed"] >= 2


# ---------------------------------------------------------------------------
# Block detection and warning helpers
# ---------------------------------------------------------------------------
# Each row: a line, whether it starts its own block (heading, list item,
# table row), whether it is a single-line block (heading, table row)
BLOCK_LINE_CASES = [
    pytest.param("# Heading", True, True, id="heading"),
    pytest.param("## Sub heading", True, True, id="sub-heading"),
    pytest.param("- item", True, False, id="dash-item"),
    pytest.param("* item", True, False, id="star-item"),
    pytest.param("+ item", True, False, id="plus-item"),
    pytest.param("1. first", True, False, id="numbered-dot-item"),
    pytest.param("2) second", True, False, id="numbered-paren-item"),
    pytest.param("| a | b |", True, True, id="table-row"),
    pytest.param("  - nested item", True, False, id="nested-item"),
    pytest.param("Plain text", False, False, id="plain-text"),
    pytest.param("> quoted", False, False, id="blockquote"),
    pytest.param("-dash without space", False, False, id="dash-without-space"),
    pytest.param("1.5 percent", False, False, id="decimal-number"),
    pytest.param("*emphasis* text", False, False, id="emphasis"),
    pytest.param("", False, False, id="empty-line"),
]


class TestBlockDetection:
    @pytest.mark.parametrize("line, starts_block, single_line", BLOCK_LINE_CASES)
    def test_block_line(self, line, starts_block, single_line):
        assert starts_own_block(line) is starts_block
        assert is_single_line_block(line) is single_line


# Each row: the arguments of format_line_range and the label
LINE_RANGE_CASES = [
    pytest.param((7,), "Line 7", id="single-line-label"),
    pytest.param((7, 7), "Line 7", id="single-line-label-same-last-line"),
    pytest.param((7, 8), "Lines 7-8", id="line-range-label"),
]

# Each row: the text of a block and its one-line excerpt for a warning
CONTEXT_CASES = [
    pytest.param(
        '"Only one  ', '"Only one', id="single-line-strips-trailing-whitespace"
    ),
    pytest.param(
        'first "a \nsecond  \n',
        f'first "a{SEP}second',
        id="joins-lines-with-separator",
    ),
    pytest.param("", "", id="empty"),
]


class TestWarningFormatHelpers:
    @pytest.mark.parametrize("args, expected", LINE_RANGE_CASES)
    def test_format_line_range(self, args, expected):
        assert format_line_range(*args) == expected

    @pytest.mark.parametrize("text, expected", CONTEXT_CASES)
    def test_format_context(self, text, expected):
        assert format_context(text) == expected


# ---------------------------------------------------------------------------
# Reporting helpers
# ---------------------------------------------------------------------------
# Each row: the original text, the modified text, what print_diff prints
PRINT_DIFF_CASES = [
    pytest.param(
        '"a"\nsame',
        f"{de('a')}\nsame",
        f'  Line 1:\n    - "a"\n    + {de("a")}\n',
        id="shows-only-changed-lines",
    ),
    pytest.param("x", "x", "  No changes.\n", id="without-changes"),
    pytest.param(
        "a", "a\nb", "  Line 2:\n    - \n    + b\n", id="with-different-line-counts"
    ),
]


class TestPrintHelpers:
    @pytest.mark.parametrize("original, modified, expected", PRINT_DIFF_CASES)
    def test_print_diff(self, original, modified, expected, capsys):
        print_diff(original, modified)
        assert capsys.readouterr().out == expected

    def test_print_stats_totals(self, capsys):
        stats = make_stats()
        stats["straight_double"] = 2
        stats["english_double"] = 1
        stats["lines_changed"] = 3
        print_stats(stats)
        out = capsys.readouterr().out
        assert "2 pair(s)" in out
        assert "Lines changed:              3" in out
        assert "Total replacements:         3" in out


# ---------------------------------------------------------------------------
# main (CLI)
# ---------------------------------------------------------------------------
# Each row: the files to create (relative paths), the input path argument
# (relative, "." for the directory itself), the options, the exit status, a
# text of the error message
MAIN_EXIT_CASES = [
    pytest.param([], "nope.md", [], 1, "Path not found", id="missing-path"),
    pytest.param(
        ["notes.txt"],
        ".",
        ["--pattern", "*.markdown"],
        1,
        "No files matching '*.markdown'",
        id="no-matching-files",
    ),
    pytest.param([], ".", [], 1, "No files matching '*.md'", id="empty-directory"),
]


class TestMain:
    def test_file_mode_writes_file_and_prints_summary(
        self, tmp_path, monkeypatch, capsys
    ):
        f = tmp_path / "a.md"
        f.write_text('"Hallo"', encoding="utf-8")
        monkeypatch.setattr(sys, "argv", ["fix-german-quotes", str(f)])
        main()
        assert f.read_text(encoding="utf-8") == de("Hallo")
        captured = capsys.readouterr()
        assert "--- Summary ---" in captured.out
        assert "Files processed" not in captured.out
        assert captured.err == ""

    def test_directory_dry_run_reports_warnings_and_writes_nothing(
        self, tmp_path, monkeypatch, capsys
    ):
        (tmp_path / "a.md").write_text('"Nur eine', encoding="utf-8")
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "b.md").write_text('"Paar"', encoding="utf-8")
        monkeypatch.setattr(
            sys, "argv", ["fix-german-quotes", str(tmp_path), "--dry-run"]
        )
        main()
        captured = capsys.readouterr()
        assert "Processing 2 file(s)" in captured.out
        assert "Files processed:            2" in captured.out
        assert "No files written (--dry-run)." in captured.out
        assert "--- WARNINGS ---" in captured.err
        assert "a.md] Line 1: Asymmetric" in captured.err
        assert "--- 1 warning(s) ---" in captured.err
        assert (tmp_path / "a.md").read_text(encoding="utf-8") == '"Nur eine'
        assert (tmp_path / "sub" / "b.md").read_text(encoding="utf-8") == '"Paar"'

    @pytest.mark.parametrize("files, target, options, code, text", MAIN_EXIT_CASES)
    def test_exits_with_error(
        self, files, target, options, code, text, tmp_path, monkeypatch, capsys
    ):
        for name in files:
            (tmp_path / name).write_text("x", encoding="utf-8")
        monkeypatch.setattr(
            sys, "argv", ["fix-german-quotes", str(tmp_path / target), *options]
        )
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == code
        assert text in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Backups: <file>.bak unless Git tracks the file, --backup / --no-backup (#17)
# ---------------------------------------------------------------------------
def _make_file(
    tmp_path, *, repo: bool, tracked: bool, subdir: bool = False, text='"Hello"'
):
    """A Markdown file, inside a Git repository when ``repo`` and staged there
    when ``tracked`` (no commit needed), in a subdirectory when ``subdir``."""
    if repo:
        if shutil.which("git") is None:
            pytest.skip("git is not installed")
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    folder = tmp_path / "manuscript" if subdir else tmp_path
    folder.mkdir(exist_ok=True)
    f = folder / "t.md"
    f.write_text(text, encoding="utf-8")
    if tracked:
        subprocess.run(["git", "add", "--", f.name], cwd=f.parent, check=True)
    return f


# Each row: in a repository?, tracked?, the backup argument, dry run?, whether
# t.md.bak exists afterwards, the note of the "Written:" line (None: no such
# line, as in a dry run). {bak} is the backup path.
BACKUP_DECISIONS = [
    pytest.param(
        False, False, None, False, True, "backup: {bak}", id="default-outside-repo"
    ),
    pytest.param(
        True, False, None, False, True, "backup: {bak}", id="default-untracked"
    ),
    pytest.param(
        True,
        True,
        None,
        False,
        False,
        "no backup, tracked by Git",
        id="default-tracked",
    ),
    pytest.param(True, True, True, False, True, "backup: {bak}", id="backup-tracked"),
    pytest.param(
        False, False, True, False, True, "backup: {bak}", id="backup-outside-repo"
    ),
    pytest.param(
        False,
        False,
        False,
        False,
        False,
        "no backup, --no-backup",
        id="no-backup-outside-repo",
    ),
    pytest.param(
        True,
        False,
        False,
        False,
        False,
        "no backup, --no-backup",
        id="no-backup-untracked",
    ),
    pytest.param(False, False, True, True, False, None, id="dry-run-never-copies"),
]

# Each row: in a repository?, tracked?, in a subdirectory?, git on PATH?, expected
GIT_TRACKED_CASES = [
    pytest.param(False, False, False, True, False, id="outside-a-repository"),
    pytest.param(True, False, False, True, False, id="untracked"),
    pytest.param(True, True, False, True, True, id="tracked"),
    pytest.param(True, True, True, True, True, id="tracked-in-a-subdirectory"),
    pytest.param(True, False, True, True, False, id="untracked-in-a-subdirectory"),
    pytest.param(True, True, False, False, False, id="git-not-installed"),
]

# Each row: the arguments after the input path and the backup value parsed
PARSE_ARGS_CASES = [
    pytest.param([], None, id="default-is-git-aware"),
    pytest.param(["--backup"], True, id="backup"),
    pytest.param(["--no-backup"], False, id="no-backup"),
]

# Each row: the arguments, the exit status, the stream and a text it carries
PARSE_ARGS_EXITS = [
    pytest.param(
        ["x.md", "--backup", "--no-backup"],
        2,
        "err",
        "not allowed with argument --backup",
        id="both-flags-conflict",
    ),
    pytest.param(
        ["--help"],
        0,
        "out",
        "only for a file Git does not track",
        id="help-documents-default",
    ),
]

# Each row: in a repository?, tracked?, the flags, whether t.md.bak exists afterwards
MAIN_BACKUP_CASES = [
    pytest.param(False, False, ["--no-backup"], False, id="no-backup"),
    pytest.param(True, True, ["--backup"], True, id="backup-forces-copy-for-tracked"),
    pytest.param(True, True, [], False, id="default-tracked"),
    pytest.param(False, False, [], True, id="default-outside-repo"),
]


class TestBackup:
    @pytest.mark.parametrize(
        "repo, tracked, backup, dry_run, expect_bak, note", BACKUP_DECISIONS
    )
    def test_backup_decision(
        self, repo, tracked, backup, dry_run, expect_bak, note, tmp_path, capsys
    ):
        f = _make_file(tmp_path, repo=repo, tracked=tracked)
        bak = f.parent / "t.md.bak"
        process_single_file(
            f, dry_run=dry_run, global_stats=make_stats(), backup=backup
        )
        assert bak.exists() is expect_bak
        if expect_bak:
            assert bak.read_text(encoding="utf-8") == '"Hello"'
        out = capsys.readouterr().out
        if note is None:
            assert f.read_text(encoding="utf-8") == '"Hello"'
            assert "Written:" not in out
        else:
            assert DE_OPEN_DOUBLE in f.read_text(encoding="utf-8")
            assert f"Written: {f} ({note.format(bak=bak)})" in out

    def test_an_unchanged_file_asks_git_nothing(self, tmp_path, monkeypatch):
        calls: list = []
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: calls.append(a))
        f = tmp_path / "t.md"
        f.write_text("No quotes here", encoding="utf-8")
        process_single_file(f, dry_run=False, global_stats=make_stats())
        assert calls == []

    @pytest.mark.parametrize(
        "repo, tracked, subdir, git_on_path, expected", GIT_TRACKED_CASES
    )
    def test_is_git_tracked(
        self, repo, tracked, subdir, git_on_path, expected, tmp_path, monkeypatch
    ):
        f = _make_file(tmp_path, repo=repo, tracked=tracked, subdir=subdir)
        if not git_on_path:

            def no_git(*args, **kwargs):
                raise FileNotFoundError("git")

            monkeypatch.setattr(subprocess, "run", no_git)
        assert is_git_tracked(f) is expected

    @pytest.mark.parametrize("argv_tail, expected", PARSE_ARGS_CASES)
    def test_parse_args_backup_option(self, argv_tail, expected, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["fix-german-quotes", "x.md", *argv_tail])
        assert parse_args().backup is expected

    @pytest.mark.parametrize("argv, code, stream, text", PARSE_ARGS_EXITS)
    def test_parse_args_exits(self, argv, code, stream, text, monkeypatch, capsys):
        monkeypatch.setattr(sys, "argv", ["fix-german-quotes", *argv])
        with pytest.raises(SystemExit) as exc:
            parse_args()
        assert exc.value.code == code
        assert text in getattr(capsys.readouterr(), stream)

    @pytest.mark.parametrize("repo, tracked, flags, expect_bak", MAIN_BACKUP_CASES)
    def test_main_backup(self, repo, tracked, flags, expect_bak, tmp_path, monkeypatch):
        f = _make_file(tmp_path, repo=repo, tracked=tracked)
        monkeypatch.setattr(sys, "argv", ["fix-german-quotes", str(f), *flags])
        main()
        assert DE_OPEN_DOUBLE in f.read_text(encoding="utf-8")
        assert (tmp_path / "t.md.bak").exists() is expect_bak
