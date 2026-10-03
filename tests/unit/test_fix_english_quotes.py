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
    GERMAN,
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


# ---------------------------------------------------------------------------
# Styles
# ---------------------------------------------------------------------------
class TestStyles:
    def test_english_targets(self):
        assert (
            ENGLISH.open_double,
            ENGLISH.close_double,
            ENGLISH.open_single,
            ENGLISH.close_single,
        ) == ("“", "”", "‘", "’")

    def test_english_runs_the_single_quote_stage_only(self):
        assert ENGLISH.convert_straight_single
        assert not ENGLISH.convert_english_typographic

    def test_german_runs_the_english_typographic_stages_only(self):
        assert GERMAN.convert_english_typographic
        assert not GERMAN.convert_straight_single


# ---------------------------------------------------------------------------
# replace_straight_double_quotes with the English style
# ---------------------------------------------------------------------------
class TestStraightDoubleQuotesEnglish:
    def test_pair(self):
        stats = make_stats()
        result = replace_straight_double_quotes(
            '"Hello"', [], stats, [], 1, style=ENGLISH
        )
        assert result == f"{OD}Hello{CD}"
        assert stats["straight_double"] == 1

    def test_open_typographic_quote_takes_a_straight_close(self):
        stats = make_stats()
        result = replace_straight_double_quotes(
            f'{OD}Hello"', [], stats, [], 1, style=ENGLISH
        )
        assert result == f"{OD}Hello{CD}"

    def test_closed_typographic_pair_leaves_the_straight_pair_alone(self):
        warnings = []
        line = f'{OD}Already,{CD} he said, "and more."'
        result = replace_straight_double_quotes(
            line, [], make_stats(), warnings, 1, style=ENGLISH
        )
        assert result == f"{OD}Already,{CD} he said, {OD}and more.{CD}"
        assert warnings == []

    def test_odd_count_warns_and_keeps_the_quotes(self):
        warnings = []
        line = '"Only one'
        result = replace_straight_double_quotes(
            line, [], make_stats(), warnings, 3, style=ENGLISH
        )
        assert result == line
        assert warnings[0].startswith('Line 3: Asymmetric straight quotation mark (")')


# ---------------------------------------------------------------------------
# replace_straight_single_quotes
# ---------------------------------------------------------------------------
class TestStraightSingleQuotes:
    @pytest.mark.parametrize(
        "text, expected",
        [
            ("don't", f"don{CS}t"),
            ("O'Brien", f"O{CS}Brien"),
            ("rock'n'roll", f"rock{CS}n{CS}roll"),
            ("in 2'000", f"in 2{CS}000"),
        ],
    )
    def test_apostrophe_inside_a_word(self, text, expected):
        result, stats, warnings = convert_single(text)
        assert result == expected
        assert stats["straight_single"] == text.count("'")
        assert warnings == []

    @pytest.mark.parametrize(
        "text, expected",
        [
            ("the students' books", f"the students{CS} books"),
            ("James' car.", f"James{CS} car."),
        ],
    )
    def test_apostrophe_at_the_end_of_a_word(self, text, expected):
        assert convert_single(text)[0] == expected

    @pytest.mark.parametrize(
        "text, expected",
        [
            ("'word'", f"{OS}word{CS}"),
            ("He said 'no.'", f"He said {OS}no.{CS}"),
            ("('paren')", f"({OS}paren{CS})"),
            ("['bracket']", f"[{OS}bracket{CS}]"),
            ("{'brace'}", f"{{{OS}brace{CS}}}"),
            (f"{OD}'nested'{CD}", f"{OD}{OS}nested{CS}{CD}"),
            ("**'bold'**", f"**{OS}bold{CS}**"),
            ("_'italic'_", f"_{OS}italic{CS}_"),
            ("so—'dash'", f"so—{OS}dash{CS}"),
            ("so–'dash'", f"so–{OS}dash{CS}"),
        ],
    )
    def test_opening_quote_after_its_context(self, text, expected):
        result, stats, warnings = convert_single(text)
        assert result == expected
        assert stats["straight_single"] == 2
        assert warnings == []

    @pytest.mark.parametrize(
        "text, expected",
        [
            ("the '90s", f"the {CS}90s"),
            ("'20s and '30s", f"{CS}20s and {CS}30s"),
        ],
    )
    def test_decade_takes_an_apostrophe(self, text, expected):
        result, _, warnings = convert_single(text)
        assert result == expected
        assert warnings == []

    def test_quoted_year_is_still_a_quotation(self):
        assert convert_single("'1984'")[0] == f"{OS}1984{CS}"

    def test_lone_quote_between_spaces_stays(self):
        result, stats, warnings = convert_single("rock ' n roll")
        assert result == "rock ' n roll"
        assert stats["straight_single"] == 0
        assert warnings == []

    def test_quote_before_whitespace_at_block_start_stays(self):
        assert convert_single("' x")[0] == "' x"

    def test_quote_alone_stays(self):
        assert convert_single("'")[0] == "'"

    def test_typographic_opening_closed_by_a_straight_quote(self):
        result, _, warnings = convert_single(f"{OS}Hello,' she said")
        assert result == f"{OS}Hello,{CS} she said"
        assert warnings == []

    def test_straight_opening_closed_by_a_typographic_quote(self):
        result, _, warnings = convert_single(f"'Hello,{CS} she said")
        assert result == f"{OS}Hello,{CS} she said"
        assert warnings == []

    def test_typographic_apostrophe_does_not_close_an_opening_quote(self):
        result, _, warnings = convert_single(f"'Don{CS}t")
        assert result == f"'Don{CS}t"
        assert len(warnings) == 1

    def test_unclosed_opening_quote_warns_and_stays_straight(self):
        result, stats, warnings = convert_single("'Tis the season, isn't it?")
        assert result == f"'Tis the season, isn{CS}t it?"
        assert stats["straight_single"] == 1
        assert stats["warnings"] == 1
        assert warnings == [
            "Line 1: Asymmetric straight quotation mark (') "
            "- 1 opening quote(s) without a closing one\n"
            "  Context: 'Tis the season, isn't it?"
        ]

    def test_one_unclosed_opening_quote_keeps_all_openers_of_the_block(self):
        result, _, warnings = convert_single("'a' and 'em")
        assert result == f"'a{CS} and 'em"
        assert len(warnings) == 1

    def test_closing_quote_before_the_opener_does_not_close_it(self):
        result, _, warnings = convert_single("the students' and 'em")
        assert result == f"the students{CS} and 'em"
        assert len(warnings) == 1

    def test_unclosed_typographic_opener_alone_does_not_warn(self):
        result, _, warnings = convert_single(f"{OS}Tis don't")
        assert result == f"{OS}Tis don{CS}t"
        assert warnings == []

    def test_warning_names_the_line_range(self):
        stats = make_stats()
        warnings: list[str] = []
        replace_straight_single_quotes("'Tis\nso", [], stats, warnings, 4, 5)
        assert warnings[0].startswith("Lines 4-5: ")
        assert "Context: 'Tis ⏎ so" in warnings[0]

    def test_inline_code_is_protected(self):
        assert convert_single("`don't` 'x'")[0] == f"`don't` {OS}x{CS}"

    def test_html_attribute_is_protected(self):
        text = "<a title='x'>it's</a>"
        assert convert_single(text)[0] == f"<a title='x'>it{CS}s</a>"

    def test_no_single_quotes(self):
        result, stats, warnings = convert_single("plain text")
        assert result == "plain text"
        assert stats["straight_single"] == 0
        assert warnings == []


# ---------------------------------------------------------------------------
# process_block / process_file with the English style
# ---------------------------------------------------------------------------
class TestProcessEnglish:
    def test_doubles_singles_and_apostrophes(self):
        result, stats, warnings = convert('"Hello," she said. "It\'s fine."')
        assert result == f"{OD}Hello,{CD} she said. {OD}It{CS}s fine.{CD}"
        assert stats["straight_double"] == 2
        assert stats["straight_single"] == 1
        assert warnings == []

    def test_single_quotes_nested_in_double_quotes(self):
        result, _, _ = convert("\"He said 'no.'\"")
        assert result == f"{OD}He said {OS}no.{CS}{CD}"

    def test_typographic_english_quotes_stay_and_are_not_counted(self):
        text = f"{OD}Done{CD} and {OS}done{CS}, it{CS}s done."
        result, stats, _ = convert(text)
        assert result == text
        assert stats["english_double"] == 0
        assert stats["english_single"] == 0
        assert stats["lines_changed"] == 0

    def test_german_quotes_are_left_alone(self):
        text = f"{DE_OPEN_DOUBLE}Hallo{DE_CLOSE_DOUBLE} und {DE_OPEN_SINGLE}x"
        assert convert(text)[0] == text

    def test_quotes_pair_across_a_hard_wrap(self):
        result, _, warnings = convert("Line one \"opens\nand closes\" with 'one\ntwo'.")
        assert result == (f"Line one {OD}opens\nand closes{CD} with {OS}one\ntwo{CS}.")
        assert warnings == []

    def test_headings_are_their_own_block(self):
        result, _, warnings = convert("# 'Title\n\ntext'")
        assert result == "# 'Title\n\ntext’"
        assert len(warnings) == 1
        assert warnings[0].startswith("Line 1:")

    def test_code_and_frontmatter_are_untouched(self):
        text = "---\ntitle: \"It's\"\n---\n```\nx = 'a'\n```\n'b'"
        result, _, _ = convert(text)
        assert result == f"---\ntitle: \"It's\"\n---\n```\nx = 'a'\n```\n{OS}b{CS}"

    def test_process_block_defaults_to_german(self):
        stats = make_stats()
        result = process_block('"It\'s"', 1, stats, [])
        assert result == f"{DE_OPEN_DOUBLE}It's{DE_CLOSE_DOUBLE}"
        assert stats["straight_single"] == 0


# ---------------------------------------------------------------------------
# Reporting and CLI
# ---------------------------------------------------------------------------
class TestReportingEnglish:
    def test_print_stats_shows_the_english_rows(self, capsys):
        stats = make_stats()
        stats["straight_double"] = 2
        stats["straight_single"] = 3
        stats["lines_changed"] = 4
        print_stats(stats, ENGLISH)
        out = capsys.readouterr().out
        assert '  Straight " -> English:      2 pair(s)' in out
        assert "  Straight ' -> English:      3 mark(s)" in out
        assert "English typographic" not in out
        assert "  Total replacements:         5" in out

    def test_print_stats_german_has_no_single_quote_row(self, capsys):
        print_stats(make_stats())
        out = capsys.readouterr().out
        assert '  Straight " -> German:       0 pair(s)' in out
        assert "  English typographic single: 0 correction(s)" in out
        assert "Straight '" not in out

    def test_process_single_file_counts_apostrophe_only_files(self, tmp_path):
        f = tmp_path / "a.md"
        f.write_text("It's here.", encoding="utf-8")
        global_stats = make_stats()
        process_single_file(f, False, global_stats, ENGLISH)
        assert f.read_text(encoding="utf-8") == f"It{CS}s here."
        assert global_stats["straight_single"] == 1
        assert (tmp_path / "a.md.bak").read_text(encoding="utf-8") == "It's here."


class TestMainEnglish:
    def test_file_mode_writes_english_quotes(self, tmp_path, monkeypatch, capsys):
        f = tmp_path / "a.md"
        f.write_text("\"Hello,\" she said. 'It's fine.'", encoding="utf-8")
        monkeypatch.setattr(sys, "argv", ["fix-english-quotes", str(f)])
        main_english()
        assert f.read_text(encoding="utf-8") == (
            f"{OD}Hello,{CD} she said. {OS}It{CS}s fine.{CS}"
        )
        captured = capsys.readouterr()
        assert "Straight ' -> English:      3 mark(s)" in captured.out
        assert captured.err == ""

    def test_dry_run_reports_unclosed_single_quote(self, tmp_path, monkeypatch, capsys):
        f = tmp_path / "a.md"
        f.write_text("'Tis true.", encoding="utf-8")
        monkeypatch.setattr(sys, "argv", ["fix-english-quotes", str(f), "--dry-run"])
        main_english()
        captured = capsys.readouterr()
        assert "a.md] Line 1: Asymmetric straight quotation mark (')" in captured.err
        assert f.read_text(encoding="utf-8") == "'Tis true."

    def test_help_names_english(self, monkeypatch, capsys):
        monkeypatch.setenv("COLUMNS", "200")
        monkeypatch.setattr(sys, "argv", ["fix-english-quotes", "--help"])
        with pytest.raises(SystemExit):
            main_english()
        assert "to English typographic style" in capsys.readouterr().out
