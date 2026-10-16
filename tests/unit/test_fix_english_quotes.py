import pytest

pytestmark = pytest.mark.unit

"""Unit tests for fix-english-quotes - English typographic quote conversion."""

import sys

from manuscripta.markdown.german_quotes import (
    DE_CLOSE_DOUBLE,
    DE_OPEN_DOUBLE,
    DE_OPEN_SINGLE,
    ENGLISH,
    EN_CLOSE_DOUBLE,
    EN_CLOSE_SINGLE,
    EN_OPEN_DOUBLE,
    EN_OPEN_SINGLE,
    FRENCH,
    GERMAN,
    SPANISH,
    main_english,
    make_stats,
    mask_protected_regions,
    print_stats,
    process_block,
    process_file,
    process_single_file,
    replace_straight_double_quotes,
    replace_straight_single_quotes,
)

OD, CD = EN_OPEN_DOUBLE, EN_CLOSE_DOUBLE
OS, CS = EN_OPEN_SINGLE, EN_CLOSE_SINGLE


def convert(text: str) -> tuple[str, dict, list]:
    """Run ``text`` through process_file in English mode."""
    stats = make_stats()
    warnings: list[str] = []
    return process_file(text, stats, warnings, ENGLISH), stats, warnings


def convert_single(text: str) -> tuple[str, dict, list]:
    """Run ``text`` through the straight single quote stage only."""
    stats = make_stats()
    warnings: list[str] = []
    protected = mask_protected_regions(text)
    result = replace_straight_single_quotes(text, protected, stats, warnings, 1)
    return result, stats, warnings


def unclosed_warnings(text: str, count: int) -> list[str]:
    """The warnings of a one-line block with ``count`` opening quotes left open."""
    if not count:
        return []
    return [
        "Line 1: Asymmetric straight quotation mark (') "
        f"- {count} opening quote(s) without a closing one\n"
        f"  Context: {text}"
    ]


# ---------------------------------------------------------------------------
# Styles
# ---------------------------------------------------------------------------
# Each row: style, whether it converts straight single quotes, whether it
# converts English typographic quotes
STAGE_CASES = [
    pytest.param(ENGLISH, True, False, id="english-runs-the-single-quote-stage-only"),
    pytest.param(
        GERMAN, False, True, id="german-runs-the-english-typographic-stages-only"
    ),
    pytest.param(FRENCH, True, True, id="french-runs-both"),
    pytest.param(SPANISH, True, True, id="spanish-runs-both"),
]


class TestStyles:
    def test_english_targets(self):
        assert (
            ENGLISH.open_double,
            ENGLISH.close_double,
            ENGLISH.open_single,
            ENGLISH.close_single,
        ) == ("“", "”", "‘", "’")

    @pytest.mark.parametrize("style, straight_single, english_typographic", STAGE_CASES)
    def test_stages(self, style, straight_single, english_typographic):
        assert style.convert_straight_single is straight_single
        assert style.convert_english_typographic is english_typographic


# ---------------------------------------------------------------------------
# replace_straight_double_quotes with the English style
# ---------------------------------------------------------------------------
# Each row: text, expected result, the straight pairs converted, the warnings.
# Every row runs the stage alone, as line 3 of a file.
STRAIGHT_DOUBLE_CASES = [
    pytest.param('"Hello"', f"{OD}Hello{CD}", 1, [], id="pair"),
    pytest.param(
        f'{OD}Hello"',
        f"{OD}Hello{CD}",
        1,
        [],
        id="open-typographic-quote-takes-a-straight-close",
    ),
    pytest.param(
        f'{OD}Already,{CD} he said, "and more."',
        f"{OD}Already,{CD} he said, {OD}and more.{CD}",
        1,
        [],
        id="closed-typographic-pair-leaves-the-straight-pair-alone",
    ),
    pytest.param(
        '"Only one',
        '"Only one',
        0,
        [
            'Line 3: Asymmetric straight quotation mark (") '
            '- 1 unpaired occurrence(s)\n  Context: "Only one'
        ],
        id="odd-count-warns-and-keeps-the-quotes",
    ),
]


class TestStraightDoubleQuotesEnglish:
    @pytest.mark.parametrize(
        "text, expected, pairs, expected_warnings", STRAIGHT_DOUBLE_CASES
    )
    def test_straight_double_quotes(self, text, expected, pairs, expected_warnings):
        stats = make_stats()
        warnings: list[str] = []
        result = replace_straight_double_quotes(
            text, [], stats, warnings, 3, style=ENGLISH
        )
        assert result == expected
        assert stats["straight_double"] == pairs
        assert warnings == expected_warnings


# ---------------------------------------------------------------------------
# replace_straight_single_quotes
# ---------------------------------------------------------------------------
# Each row: text, expected result, the straight ' converted, the opening quotes
# left without a closing one (the block then gets one warning and keeps its
# opening quotes straight). Every row runs the stage alone, as line 1.
STRAIGHT_SINGLE_CASES = [
    # an apostrophe inside a word
    pytest.param("don't", f"don{CS}t", 1, 0, id="apostrophe-inside-a-word"),
    pytest.param("O'Brien", f"O{CS}Brien", 1, 0, id="apostrophe-inside-a-name"),
    pytest.param(
        "rock'n'roll", f"rock{CS}n{CS}roll", 2, 0, id="two-apostrophes-inside-a-word"
    ),
    pytest.param("in 2'000", f"in 2{CS}000", 1, 0, id="apostrophe-inside-a-number"),
    # an apostrophe at the end of a word
    pytest.param(
        "the students' books",
        f"the students{CS} books",
        1,
        0,
        id="apostrophe-at-the-end-of-a-word",
    ),
    pytest.param(
        "James' car.", f"James{CS} car.", 1, 0, id="apostrophe-at-the-end-of-a-name"
    ),
    # an opening quote after its context
    pytest.param(
        "'word'", f"{OS}word{CS}", 2, 0, id="opening-quote-at-the-block-start"
    ),
    pytest.param(
        "He said 'no.'", f"He said {OS}no.{CS}", 2, 0, id="opening-quote-after-a-space"
    ),
    pytest.param(
        "('paren')", f"({OS}paren{CS})", 2, 0, id="opening-quote-after-a-parenthesis"
    ),
    pytest.param(
        "['bracket']", f"[{OS}bracket{CS}]", 2, 0, id="opening-quote-after-a-bracket"
    ),
    pytest.param(
        "{'brace'}", f"{{{OS}brace{CS}}}", 2, 0, id="opening-quote-after-a-brace"
    ),
    pytest.param(
        f"{OD}'nested'{CD}",
        f"{OD}{OS}nested{CS}{CD}",
        2,
        0,
        id="opening-quote-after-a-double-quote",
    ),
    pytest.param(
        "**'bold'**", f"**{OS}bold{CS}**", 2, 0, id="opening-quote-after-bold"
    ),
    pytest.param(
        "_'italic'_", f"_{OS}italic{CS}_", 2, 0, id="opening-quote-after-italic"
    ),
    pytest.param(
        "so—'dash'", f"so—{OS}dash{CS}", 2, 0, id="opening-quote-after-an-em-dash"
    ),
    pytest.param(
        "so–'dash'", f"so–{OS}dash{CS}", 2, 0, id="opening-quote-after-an-en-dash"
    ),
    # a decade takes an apostrophe, a quoted year is still a quotation
    pytest.param("the '90s", f"the {CS}90s", 1, 0, id="decade-takes-an-apostrophe"),
    pytest.param(
        "'20s and '30s",
        f"{CS}20s and {CS}30s",
        2,
        0,
        id="two-decades-take-an-apostrophe",
    ),
    pytest.param(
        "'1984'", f"{OS}1984{CS}", 2, 0, id="quoted-year-is-still-a-quotation"
    ),
    pytest.param(
        "rock ' n roll", "rock ' n roll", 0, 0, id="lone-quote-between-spaces-stays"
    ),
    pytest.param("' x", "' x", 0, 0, id="quote-before-whitespace-at-block-start-stays"),
    pytest.param("'", "'", 0, 0, id="quote-alone-stays"),
    pytest.param(
        f"{OS}Hello,' she said",
        f"{OS}Hello,{CS} she said",
        1,
        0,
        id="typographic-opening-closed-by-a-straight-quote",
    ),
    pytest.param(
        f"'Hello,{CS} she said",
        f"{OS}Hello,{CS} she said",
        1,
        0,
        id="straight-opening-closed-by-a-typographic-quote",
    ),
    pytest.param(
        f"'Don{CS}t",
        f"'Don{CS}t",
        0,
        1,
        id="typographic-apostrophe-does-not-close-an-opening-quote",
    ),
    # the apostrophes and closing quotes of the block are still converted
    pytest.param(
        "'Tis the season, isn't it?",
        f"'Tis the season, isn{CS}t it?",
        1,
        1,
        id="unclosed-opening-quote-warns-and-stays-straight",
    ),
    pytest.param(
        "'a' and 'em",
        f"'a{CS} and 'em",
        1,
        1,
        id="one-unclosed-opening-quote-keeps-all-openers-of-the-block",
    ),
    pytest.param(
        "the students' and 'em",
        f"the students{CS} and 'em",
        1,
        1,
        id="closing-quote-before-the-opener-does-not-close-it",
    ),
    pytest.param(
        f"{OS}Tis don't",
        f"{OS}Tis don{CS}t",
        1,
        0,
        id="unclosed-typographic-opener-alone-does-not-warn",
    ),
    pytest.param(
        "`don't` 'x'", f"`don't` {OS}x{CS}", 2, 0, id="inline-code-is-protected"
    ),
    pytest.param(
        "<a title='x'>it's</a>",
        f"<a title='x'>it{CS}s</a>",
        1,
        0,
        id="html-attribute-is-protected",
    ),
    pytest.param("plain text", "plain text", 0, 0, id="no-single-quotes"),
    pytest.param("", "", 0, 0, id="empty-block"),
]


class TestStraightSingleQuotes:
    @pytest.mark.parametrize("text, expected, marks, unclosed", STRAIGHT_SINGLE_CASES)
    def test_straight_single_quotes(self, text, expected, marks, unclosed):
        result, stats, warnings = convert_single(text)
        expected_warnings = unclosed_warnings(text, unclosed)
        assert result == expected
        assert stats["straight_single"] == marks
        assert stats["warnings"] == len(expected_warnings)
        assert warnings == expected_warnings

    def test_warning_names_the_line_range(self):
        stats = make_stats()
        warnings: list[str] = []
        replace_straight_single_quotes("'Tis\nso", [], stats, warnings, 4, 5)
        assert warnings[0].startswith("Lines 4-5: ")
        assert "Context: 'Tis ⏎ so" in warnings[0]


# ---------------------------------------------------------------------------
# process_block / process_file with the English style
# ---------------------------------------------------------------------------
# Each row: text, expected result, the stats that must change, the warnings
PROCESS_CASES = [
    pytest.param(
        '"Hello," she said. "It\'s fine."',
        f"{OD}Hello,{CD} she said. {OD}It{CS}s fine.{CD}",
        {"straight_double": 2, "straight_single": 1},
        [],
        id="doubles-singles-and-apostrophes",
    ),
    pytest.param(
        "\"He said 'no.'\"",
        f"{OD}He said {OS}no.{CS}{CD}",
        {"straight_double": 1, "straight_single": 2},
        [],
        id="single-quotes-nested-in-double-quotes",
    ),
    pytest.param(
        f"{OD}Done{CD} and {OS}done{CS}, it{CS}s done.",
        f"{OD}Done{CD} and {OS}done{CS}, it{CS}s done.",
        {"english_double": 0, "english_single": 0, "lines_changed": 0},
        [],
        id="typographic-english-quotes-stay-and-are-not-counted",
    ),
    pytest.param(
        f"{DE_OPEN_DOUBLE}Hallo{DE_CLOSE_DOUBLE} und {DE_OPEN_SINGLE}x",
        f"{DE_OPEN_DOUBLE}Hallo{DE_CLOSE_DOUBLE} und {DE_OPEN_SINGLE}x",
        {"lines_changed": 0},
        [],
        id="german-quotes-are-left-alone",
    ),
    pytest.param(
        "Line one \"opens\nand closes\" with 'one\ntwo'.",
        f"Line one {OD}opens\nand closes{CD} with {OS}one\ntwo{CS}.",
        {"straight_double": 1, "straight_single": 2, "lines_changed": 3},
        [],
        id="quotes-pair-across-a-hard-wrap",
    ),
    pytest.param(
        "# 'Title\n\ntext'",
        f"# 'Title\n\ntext{CS}",
        {"straight_single": 1, "warnings": 1},
        unclosed_warnings("# 'Title", 1),
        id="headings-are-their-own-block",
    ),
    pytest.param(
        "---\ntitle: \"It's\"\n---\n```\nx = 'a'\n```\n'b'",
        f"---\ntitle: \"It's\"\n---\n```\nx = 'a'\n```\n{OS}b{CS}",
        {"straight_double": 0, "straight_single": 2},
        [],
        id="code-and-frontmatter-are-untouched",
    ),
    pytest.param("", "", {"lines_changed": 0}, [], id="empty-file"),
]


class TestProcessEnglish:
    @pytest.mark.parametrize(
        "text, expected, expected_stats, expected_warnings", PROCESS_CASES
    )
    def test_process_file(self, text, expected, expected_stats, expected_warnings):
        result, stats, warnings = convert(text)
        assert result == expected
        assert {key: stats[key] for key in expected_stats} == expected_stats
        assert warnings == expected_warnings

    def test_process_block_defaults_to_german(self):
        stats = make_stats()
        result = process_block('"It\'s"', 1, stats, [])
        assert result == f"{DE_OPEN_DOUBLE}It's{DE_CLOSE_DOUBLE}"
        assert stats["straight_single"] == 0


# ---------------------------------------------------------------------------
# Reporting and CLI
# ---------------------------------------------------------------------------
# Each row: style (None: the German default), the summary lines it prints, the
# ones it leaves out. Every row reports 2 straight pairs, 3 straight single
# marks and 4 changed lines.
SUMMARY_ROW_CASES = [
    pytest.param(
        ENGLISH,
        [
            '  Straight " -> English:      2 pair(s)',
            "  Straight ' -> English:      3 mark(s)",
            "  Total replacements:         5",
        ],
        ["English typographic"],
        id="print-stats-shows-the-english-rows",
    ),
    pytest.param(
        None,
        [
            '  Straight " -> German:       2 pair(s)',
            "  English typographic single: 0 correction(s)",
        ],
        ["Straight '"],
        id="print-stats-german-has-no-single-quote-row",
    ),
]


class TestReportingEnglish:
    @pytest.mark.parametrize("style, present, absent", SUMMARY_ROW_CASES)
    def test_summary_rows(self, style, present, absent, capsys):
        stats = make_stats()
        stats["straight_double"] = 2
        stats["straight_single"] = 3
        stats["lines_changed"] = 4
        styles = () if style is None else (style,)
        print_stats(stats, *styles)
        out = capsys.readouterr().out
        for line in present:
            assert line in out
        for text in absent:
            assert text not in out

    def test_process_single_file_counts_apostrophe_only_files(self, tmp_path):
        f = tmp_path / "a.md"
        f.write_text("It's here.", encoding="utf-8")
        global_stats = make_stats()
        process_single_file(f, False, global_stats, ENGLISH)
        assert f.read_text(encoding="utf-8") == f"It{CS}s here."
        assert global_stats["straight_single"] == 1
        assert (tmp_path / "a.md.bak").read_text(encoding="utf-8") == "It's here."


# Each row: file text, the options after the path, the file text afterwards, a
# line of stdout, a text stderr carries (None: stderr stays empty)
MAIN_CASES = [
    pytest.param(
        "\"Hello,\" she said. 'It's fine.'",
        [],
        f"{OD}Hello,{CD} she said. {OS}It{CS}s fine.{CS}",
        "Straight ' -> English:      3 mark(s)",
        None,
        id="file-mode-writes-english-quotes",
    ),
    pytest.param(
        "'Tis true.",
        ["--dry-run"],
        "'Tis true.",
        "Warnings (asymmetric):      1",
        "a.md] Line 1: Asymmetric straight quotation mark (')",
        id="dry-run-reports-unclosed-single-quote",
    ),
]


class TestMainEnglish:
    @pytest.mark.parametrize("text, options, expected, out_line, err_text", MAIN_CASES)
    def test_main(
        self, text, options, expected, out_line, err_text, tmp_path, monkeypatch, capsys
    ):
        f = tmp_path / "a.md"
        f.write_text(text, encoding="utf-8")
        monkeypatch.setattr(sys, "argv", ["fix-english-quotes", str(f), *options])
        main_english()
        assert f.read_text(encoding="utf-8") == expected
        captured = capsys.readouterr()
        assert out_line in captured.out
        if err_text is None:
            assert captured.err == ""
        else:
            assert err_text in captured.err

    def test_help_names_english(self, monkeypatch, capsys):
        monkeypatch.setenv("COLUMNS", "200")
        monkeypatch.setattr(sys, "argv", ["fix-english-quotes", "--help"])
        with pytest.raises(SystemExit):
            main_english()
        assert "to English typographic style" in capsys.readouterr().out
