import pytest

pytestmark = pytest.mark.unit

"""Unit tests for fix-german-quotes - German typographic quote conversion."""

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
    is_in_frontmatter,
    is_protected,
    is_single_line_block,
    main,
    make_stats,
    mask_protected_regions,
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


# ---------------------------------------------------------------------------
# is_in_frontmatter
# ---------------------------------------------------------------------------
class TestIsInFrontmatter:
    def test_inside_frontmatter(self):
        lines = ["---", "title: Test", "---", "Content"]
        assert is_in_frontmatter(lines, 1) is True

    def test_outside_frontmatter(self):
        lines = ["---", "title: Test", "---", "Content"]
        assert is_in_frontmatter(lines, 3) is False

    def test_first_fence_line(self):
        lines = ["---", "title: Test", "---", "Content"]
        assert is_in_frontmatter(lines, 0) is False

    def test_no_frontmatter(self):
        lines = ["Normal text", "Another line"]
        assert is_in_frontmatter(lines, 0) is False
        assert is_in_frontmatter(lines, 1) is False

    def test_unclosed_frontmatter(self):
        lines = ["---", "title: Test", "No closing"]
        assert is_in_frontmatter(lines, 1) is True
        assert is_in_frontmatter(lines, 2) is True

    def test_empty_lines(self):
        assert is_in_frontmatter([], 0) is False


# ---------------------------------------------------------------------------
# mask_protected_regions
# ---------------------------------------------------------------------------
class TestMaskProtectedRegions:
    def test_no_protected(self):
        assert mask_protected_regions("Normal text") == []

    def test_inline_code(self):
        line = "Text `code here` more"
        spans = mask_protected_regions(line)
        assert len(spans) >= 1
        covered = line[spans[0][0] : spans[0][1]]
        assert "code here" in covered

    def test_multiple_inline_code(self):
        line = "`a` and `b`"
        spans = mask_protected_regions(line)
        assert len(spans) == 2

    def test_html_attribute_double(self):
        line = '<a href="http://example.com"> tag'
        spans = mask_protected_regions(line)
        assert len(spans) >= 1
        full = "".join(line[s:e] for s, e in spans)
        assert "http://example.com" in full

    def test_html_attribute_single(self):
        line = "<a href='http://example.com'> tag"
        spans = mask_protected_regions(line)
        assert len(spans) >= 1


# ---------------------------------------------------------------------------
# is_protected
# ---------------------------------------------------------------------------
class TestIsProtected:
    def test_inside_span(self):
        assert is_protected(7, [(5, 10), (20, 30)]) is True

    def test_outside_span(self):
        assert is_protected(15, [(5, 10), (20, 30)]) is False

    def test_at_start_boundary(self):
        assert is_protected(5, [(5, 10)]) is True

    def test_at_end_boundary_exclusive(self):
        assert is_protected(10, [(5, 10)]) is False

    def test_empty_spans(self):
        assert is_protected(0, []) is False


# ---------------------------------------------------------------------------
# find_quote_positions
# ---------------------------------------------------------------------------
class TestFindQuotePositions:
    def test_finds_straight_doubles(self):
        positions = find_quote_positions('"Hello" world', STRAIGHT_DOUBLE, [])
        assert positions == [0, 6]

    def test_skips_protected(self):
        line = '`"code"` and "text"'
        protected = mask_protected_regions(line)
        positions = find_quote_positions(line, STRAIGHT_DOUBLE, protected)
        assert all(not is_protected(p, protected) for p in positions)

    def test_no_matches(self):
        assert find_quote_positions("No quotes here", STRAIGHT_DOUBLE, []) == []


# ---------------------------------------------------------------------------
# replace_straight_double_quotes
# ---------------------------------------------------------------------------
class TestReplaceStraightDoubleQuotes:
    def test_single_pair(self):
        stats = make_stats()
        result = replace_straight_double_quotes('"Hello"', [], stats, [], 1)
        assert result == f"{DE_OPEN_DOUBLE}Hello{DE_CLOSE_DOUBLE}"
        assert stats["straight_double"] >= 1

    def test_two_pairs(self):
        stats = make_stats()
        result = replace_straight_double_quotes('"One" and "Two"', [], stats, [], 1)
        assert result.count(DE_OPEN_DOUBLE) == 2
        assert result.count(DE_CLOSE_DOUBLE) == 2

    def test_odd_count_warning(self):
        stats = make_stats()
        warnings = []
        line = '"Only one'
        result = replace_straight_double_quotes(line, [], stats, warnings, 5)
        assert result == line
        assert len(warnings) == 1
        assert "Line 5" in warnings[0]

    def test_no_straight_quotes(self):
        stats = make_stats()
        result = replace_straight_double_quotes("No quotes", [], stats, [], 1)
        assert result == "No quotes"
        assert stats["straight_double"] == 0

    def test_protected_not_touched(self):
        stats = make_stats()
        line = '`"code"` and "text"'
        protected = mask_protected_regions(line)
        result = replace_straight_double_quotes(line, protected, stats, [], 1)
        assert '`"code"`' in result

    def test_mixed_german_open_with_straight_close(self):
        """Existing German opening with straight closing quote."""
        stats = make_stats()
        line = f'{DE_OPEN_DOUBLE}Hello"'
        result = replace_straight_double_quotes(line, [], stats, [], 1)
        assert result == f"{DE_OPEN_DOUBLE}Hello{DE_CLOSE_DOUBLE}"
        assert stats["straight_double"] >= 1

    def test_three_straight_quotes_warning(self):
        stats = make_stats()
        warnings = []
        replace_straight_double_quotes('"a" b "', [], stats, warnings, 1)
        assert stats["warnings"] >= 1

    def test_closed_german_pair_does_not_take_the_next_straight_quote(self):
        """An already closed „…“ leaves the following straight pair intact."""
        stats = make_stats()
        warnings = []
        line = f'{DE_OPEN_DOUBLE}Hallo{DE_CLOSE_DOUBLE}, sagte er, "und tschüss."'
        result = replace_straight_double_quotes(line, [], stats, warnings, 1)
        assert result == (
            f"{DE_OPEN_DOUBLE}Hallo{DE_CLOSE_DOUBLE}, sagte er, "
            f"{DE_OPEN_DOUBLE}und tschüss.{DE_CLOSE_DOUBLE}"
        )
        assert warnings == []
        assert stats["straight_double"] == 1

    def test_two_open_german_quotes_each_take_a_straight_close(self):
        stats = make_stats()
        line = f'{DE_OPEN_DOUBLE}a" und {DE_OPEN_DOUBLE}b"'
        result = replace_straight_double_quotes(line, [], stats, [], 1)
        assert result == (
            f"{DE_OPEN_DOUBLE}a{DE_CLOSE_DOUBLE} und "
            f"{DE_OPEN_DOUBLE}b{DE_CLOSE_DOUBLE}"
        )
        assert stats["straight_double"] == 2


# ---------------------------------------------------------------------------
# replace_english_double_quotes
# ---------------------------------------------------------------------------
class TestReplaceEnglishDoubleQuotes:
    def test_english_pair_to_german(self):
        stats = make_stats()
        text = f"{EN_OPEN_DOUBLE}Hello{EN_CLOSE_DOUBLE}"
        result = replace_english_double_quotes(text, [], stats)
        assert result == f"{DE_OPEN_DOUBLE}Hello{DE_CLOSE_DOUBLE}"
        assert stats["english_double"] >= 1

    def test_standalone_close_double(self):
        """Standalone U+201D is converted to U+201C."""
        stats = make_stats()
        text = f"Word{EN_CLOSE_DOUBLE}"
        result = replace_english_double_quotes(text, [], stats)
        assert EN_CLOSE_DOUBLE not in result
        assert DE_CLOSE_DOUBLE in result

    def test_no_english_quotes(self):
        stats = make_stats()
        result = replace_english_double_quotes("Normal text", [], stats)
        assert result == "Normal text"
        assert stats["english_double"] == 0

    def test_without_en_close_no_change(self):
        """Without U+201D nothing happens, U+201C is ambiguous."""
        stats = make_stats()
        text = f"Text {EN_OPEN_DOUBLE}word"
        replace_english_double_quotes(text, [], stats)
        assert stats["english_double"] == 0

    def test_multiple_pairs(self):
        stats = make_stats()
        text = (
            f"{EN_OPEN_DOUBLE}One{EN_CLOSE_DOUBLE} and "
            f"{EN_OPEN_DOUBLE}Two{EN_CLOSE_DOUBLE}"
        )
        result = replace_english_double_quotes(text, [], stats)
        assert result.count(DE_OPEN_DOUBLE) == 2
        assert result.count(DE_CLOSE_DOUBLE) == 2


# ---------------------------------------------------------------------------
# replace_english_single_quotes
# ---------------------------------------------------------------------------
class TestReplaceEnglishSingleQuotes:
    def test_english_single_pair(self):
        stats = make_stats()
        text = f"Text {EN_OPEN_SINGLE}word{EN_CLOSE_SINGLE} more"
        result = replace_english_single_quotes(text, [], stats)
        assert DE_OPEN_SINGLE in result
        assert DE_CLOSE_SINGLE in result
        assert stats["english_single"] >= 1

    def test_no_single_quotes(self):
        stats = make_stats()
        result = replace_english_single_quotes("Normal text", [], stats)
        assert result == "Normal text"
        assert stats["english_single"] == 0

    def test_only_open_no_close(self):
        """Only U+2018 without U+2019: no pair, no conversion."""
        stats = make_stats()
        text = f"Text {EN_OPEN_SINGLE}word"
        replace_english_single_quotes(text, [], stats)
        assert stats["english_single"] == 0

    def test_multiple_pairs(self):
        stats = make_stats()
        text = (
            f"{EN_OPEN_SINGLE}A{EN_CLOSE_SINGLE} " f"{EN_OPEN_SINGLE}B{EN_CLOSE_SINGLE}"
        )
        result = replace_english_single_quotes(text, [], stats)
        assert result.count(DE_OPEN_SINGLE) == 2
        assert result.count(DE_CLOSE_SINGLE) == 2


# ---------------------------------------------------------------------------
# process_line (integration)
# ---------------------------------------------------------------------------
class TestProcessLine:
    def test_straight_quotes_converted(self):
        stats = make_stats()
        result = process_line('"Hello world"', 1, stats, [])
        assert result == f"{DE_OPEN_DOUBLE}Hello world{DE_CLOSE_DOUBLE}"

    def test_inline_code_protected(self):
        stats = make_stats()
        line = 'Text `"code"` more "yes"'
        result = process_line(line, 1, stats, [])
        assert '`"code"`' in result
        assert f"{DE_OPEN_DOUBLE}yes{DE_CLOSE_DOUBLE}" in result

    def test_empty_line(self):
        stats = make_stats()
        assert process_line("", 1, stats, []) == ""

    def test_no_quotes(self):
        stats = make_stats()
        line = "A normal sentence without quotation marks."
        assert process_line(line, 1, stats, []) == line

    def test_english_double_in_line(self):
        stats = make_stats()
        line = f"He said {EN_OPEN_DOUBLE}yes{EN_CLOSE_DOUBLE}."
        result = process_line(line, 1, stats, [])
        assert DE_OPEN_DOUBLE in result
        assert DE_CLOSE_DOUBLE in result

    def test_html_attribute_protected(self):
        stats = make_stats()
        line = '<a href="http://x.com"> "Link"'
        result = process_line(line, 1, stats, [])
        assert 'href="http://x.com"' in result
        assert f"{DE_OPEN_DOUBLE}Link{DE_CLOSE_DOUBLE}" in result


# ---------------------------------------------------------------------------
# process_file (integration: frontmatter, code blocks)
# ---------------------------------------------------------------------------
class TestProcessFile:
    def test_frontmatter_preserved(self):
        stats = make_stats()
        content = '---\ntitle: "My Book"\n---\n"Content"'
        result = process_file(content, stats, [])
        lines = result.split("\n")
        assert lines[1] == 'title: "My Book"'
        assert DE_OPEN_DOUBLE in lines[3]

    def test_fenced_code_block_preserved(self):
        stats = make_stats()
        content = 'Text "yes"\n```\n"code"\n```\nText "no"'
        result = process_file(content, stats, [])
        lines = result.split("\n")
        assert DE_OPEN_DOUBLE in lines[0]
        assert lines[2] == '"code"'
        assert DE_OPEN_DOUBLE in lines[4]

    def test_fenced_code_with_language(self):
        stats = make_stats()
        content = '```python\nprint("hello")\n```\n"Text"'
        result = process_file(content, stats, [])
        lines = result.split("\n")
        assert lines[1] == 'print("hello")'
        assert DE_OPEN_DOUBLE in lines[3]

    def test_no_frontmatter(self):
        stats = make_stats()
        content = '"Hello"\n"World"'
        result = process_file(content, stats, [])
        assert result.count(DE_OPEN_DOUBLE) == 2
        assert result.count(DE_CLOSE_DOUBLE) == 2

    def test_empty_content(self):
        stats = make_stats()
        assert process_file("", stats, []) == ""

    def test_multiple_code_blocks(self):
        stats = make_stats()
        content = '"a"\n```\n"b"\n```\n"c"\n```\n"d"\n```\n"e"'
        result = process_file(content, stats, [])
        lines = result.split("\n")
        assert DE_OPEN_DOUBLE in lines[0]
        assert DE_OPEN_DOUBLE in lines[4]
        assert DE_OPEN_DOUBLE in lines[8]
        assert lines[2] == '"b"'
        assert lines[6] == '"d"'

    def test_already_german_quotes_untouched(self):
        stats = make_stats()
        content = f"{DE_OPEN_DOUBLE}Already correct{DE_CLOSE_DOUBLE}"
        result = process_file(content, stats, [])
        assert result == content
        assert stats["straight_double"] == 0

    def test_lines_changed_counter(self):
        stats = make_stats()
        content = '"Line one"\nNo quotes\n"Line three"'
        process_file(content, stats, [])
        assert stats["lines_changed"] == 2

    def test_frontmatter_and_code_combined(self):
        stats = make_stats()
        content = '---\nkey: "val"\n---\n\n```\n"safe"\n```\n\n"convert"'
        result = process_file(content, stats, [])
        assert 'key: "val"' in result
        assert '"safe"' in result
        assert f"{DE_OPEN_DOUBLE}convert{DE_CLOSE_DOUBLE}" in result


# ---------------------------------------------------------------------------
# collect_files (directory support)
# ---------------------------------------------------------------------------
class TestCollectFiles:
    def test_single_file(self, tmp_path):
        f = tmp_path / "test.md"
        f.write_text("content")
        result = collect_files(f, "*.md")
        assert result == [f]

    def test_directory_recursive(self, tmp_path):
        (tmp_path / "sub").mkdir()
        (tmp_path / "a.md").write_text("a")
        (tmp_path / "sub" / "b.md").write_text("b")
        (tmp_path / "ignore.txt").write_text("x")
        result = collect_files(tmp_path, "*.md")
        names = sorted(p.name for p in result)
        assert names == ["a.md", "b.md"]

    def test_directory_empty(self, tmp_path):
        result = collect_files(tmp_path, "*.md")
        assert result == []

    def test_directory_custom_pattern(self, tmp_path):
        (tmp_path / "doc.markdown").write_text("x")
        (tmp_path / "doc.md").write_text("y")
        result = collect_files(tmp_path, "*.markdown")
        assert len(result) == 1
        assert result[0].name == "doc.markdown"

    def test_nonexistent_path(self, tmp_path):
        fake = tmp_path / "nonexistent"
        result = collect_files(fake, "*.md")
        assert result == []

    def test_deeply_nested(self, tmp_path):
        deep = tmp_path / "a" / "b" / "c"
        deep.mkdir(parents=True)
        (deep / "deep.md").write_text("content")
        result = collect_files(tmp_path, "*.md")
        assert len(result) == 1
        assert result[0].name == "deep.md"

    def test_sorted_output(self, tmp_path):
        for name in ["c.md", "a.md", "b.md"]:
            (tmp_path / name).write_text("x")
        result = collect_files(tmp_path, "*.md")
        names = [p.name for p in result]
        assert names == sorted(names)


# ---------------------------------------------------------------------------
# process_single_file (integration with filesystem)
# ---------------------------------------------------------------------------
class TestProcessSingleFile:
    def test_writes_file_and_backup(self, tmp_path):
        f = tmp_path / "test.md"
        f.write_text('"Hello"', encoding="utf-8")
        global_stats = make_stats()
        process_single_file(f, dry_run=False, global_stats=global_stats)
        content = f.read_text(encoding="utf-8")
        assert DE_OPEN_DOUBLE in content
        assert DE_CLOSE_DOUBLE in content
        assert (tmp_path / "test.md.bak").exists()

    def test_dry_run_no_write(self, tmp_path):
        f = tmp_path / "test.md"
        f.write_text('"Hello"', encoding="utf-8")
        global_stats = make_stats()
        process_single_file(f, dry_run=True, global_stats=global_stats)
        content = f.read_text(encoding="utf-8")
        assert content == '"Hello"'
        assert not (tmp_path / "test.md.bak").exists()

    def test_unchanged_file_no_backup(self, tmp_path):
        f = tmp_path / "test.md"
        f.write_text("No quotes here", encoding="utf-8")
        global_stats = make_stats()
        process_single_file(f, dry_run=False, global_stats=global_stats)
        assert not (tmp_path / "test.md.bak").exists()

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

    def test_returns_warnings(self, tmp_path):
        f = tmp_path / "test.md"
        f.write_text('"Only one', encoding="utf-8")
        global_stats = make_stats()
        warnings = process_single_file(f, dry_run=False, global_stats=global_stats)
        assert len(warnings) >= 1


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------
class TestEdgeCases:
    def test_only_whitespace_line(self):
        stats = make_stats()
        assert process_line("   ", 1, stats, []) == "   "

    def test_single_straight_quote_warning(self):
        stats = make_stats()
        warnings = []
        process_line('"', 1, stats, warnings)
        assert len(warnings) == 1

    def test_german_open_close_pair_intact(self):
        stats = make_stats()
        text = f"{DE_OPEN_DOUBLE}Correct{DE_CLOSE_DOUBLE}"
        assert process_line(text, 1, stats, []) == text

    def test_multiline_preserves_line_count(self):
        stats = make_stats()
        content = "Line 1\nLine 2\nLine 3"
        result = process_file(content, stats, [])
        assert result.count("\n") == content.count("\n")

    def test_frontmatter_only(self):
        stats = make_stats()
        content = '---\ntitle: "Test"\n---'
        assert process_file(content, stats, []) == content

    def test_unclosed_code_block(self):
        """Unclosed code block: everything from ``` onward stays protected."""
        stats = make_stats()
        content = '"before"\n```\n"inside"\n"also inside"'
        result = process_file(content, stats, [])
        lines = result.split("\n")
        assert DE_OPEN_DOUBLE in lines[0]
        assert lines[2] == '"inside"'
        assert lines[3] == '"also inside"'

    def test_straight_quote_pair_assignment(self):
        """1st straight = opening, 2nd = closing."""
        stats = make_stats()
        text = 'He said "Yes" and "No"'
        result = replace_straight_double_quotes(text, [], stats, [], 1)
        assert f"{DE_OPEN_DOUBLE}Yes{DE_CLOSE_DOUBLE}" in result
        assert f"{DE_OPEN_DOUBLE}No{DE_CLOSE_DOUBLE}" in result

    def test_mixed_straight_and_english(self):
        """Straight and English typographic in the same line."""
        stats = make_stats()
        text = f'"Straight" and {EN_OPEN_DOUBLE}English{EN_CLOSE_DOUBLE}'
        result = process_line(text, 1, stats, [])
        assert result.count(DE_OPEN_DOUBLE) == 2
        assert result.count(DE_CLOSE_DOUBLE) == 2

    def test_no_warnings_on_clean_input(self):
        stats = make_stats()
        warnings = []
        process_file('"Clean" and "correct"', stats, warnings)
        assert len(warnings) == 0
        assert stats["warnings"] == 0

    def test_stats_accumulate_across_lines(self):
        stats = make_stats()
        process_file('"Line one"\n"Line two"\n"Line three"', stats, [])
        assert stats["straight_double"] >= 3


# ---------------------------------------------------------------------------
# Protected regions never span a line break (blocks are multi-line)
# ---------------------------------------------------------------------------
class TestMaskProtectedRegionsAcrossLines:
    def test_inline_code_does_not_span_lines(self):
        assert mask_protected_regions("`a\nb`") == []

    def test_html_attributes_do_not_span_lines(self):
        assert mask_protected_regions('href="a\nb"') == []
        assert mask_protected_regions("href='a\nb'") == []

    def test_inline_code_inside_a_block_is_still_protected(self):
        text = 'x `"c"` y\n"z"'
        spans = mask_protected_regions(text)
        assert len(spans) == 1
        assert text[spans[0][0] : spans[0][1]] == '`"c"`'


# ---------------------------------------------------------------------------
# Block detection and warning helpers
# ---------------------------------------------------------------------------
class TestBlockDetection:
    @pytest.mark.parametrize(
        "line",
        [
            "# Heading",
            "## Sub heading",
            "- item",
            "* item",
            "+ item",
            "1. first",
            "2) second",
            "| a | b |",
            "  - nested item",
        ],
    )
    def test_starts_own_block(self, line):
        assert starts_own_block(line) is True

    @pytest.mark.parametrize(
        "line",
        [
            "Plain text",
            "> quoted",
            "-dash without space",
            "1.5 percent",
            "*emphasis* text",
            "",
        ],
    )
    def test_does_not_start_own_block(self, line):
        assert starts_own_block(line) is False

    def test_headings_and_table_rows_are_single_line_blocks(self):
        assert is_single_line_block("# Heading") is True
        assert is_single_line_block("| a | b |") is True

    def test_list_items_and_text_may_continue(self):
        assert is_single_line_block("- item") is False
        assert is_single_line_block("Plain text") is False


class TestWarningFormatHelpers:
    def test_single_line_label(self):
        assert format_line_range(7) == "Line 7"
        assert format_line_range(7, 7) == "Line 7"

    def test_line_range_label(self):
        assert format_line_range(7, 8) == "Lines 7-8"

    def test_context_single_line_strips_trailing_whitespace(self):
        assert format_context('"Only one  ') == '"Only one'

    def test_context_joins_lines_with_separator(self):
        expected = f'first "a{CONTEXT_LINE_SEPARATOR}second'
        assert format_context('first "a \nsecond  \n') == expected


# ---------------------------------------------------------------------------
# process_block / process_line
# ---------------------------------------------------------------------------
class TestProcessBlock:
    def test_process_line_is_a_single_line_block(self):
        stats = make_stats()
        assert (
            process_line('"a"', 3, stats, []) == f"{DE_OPEN_DOUBLE}a{DE_CLOSE_DOUBLE}"
        )

    def test_pairs_across_lines(self):
        stats = make_stats()
        warnings = []
        result = process_block('"a\nb"', 1, stats, warnings)
        assert result == f"{DE_OPEN_DOUBLE}a\nb{DE_CLOSE_DOUBLE}"
        assert warnings == []

    def test_warning_names_line_range_and_joined_context(self):
        stats = make_stats()
        warnings = []
        result = process_block('"a\nb', 7, stats, warnings)
        assert result == '"a\nb'
        assert len(warnings) == 1
        assert warnings[0].startswith("Lines 7-8: Asymmetric straight quotation mark")
        assert f'Context: "a{CONTEXT_LINE_SEPARATOR}b' in warnings[0]

    def test_single_line_block_warning_keeps_line_label(self):
        stats = make_stats()
        warnings = []
        process_block('"a', 5, stats, warnings)
        assert warnings[0].startswith("Line 5: ")


# ---------------------------------------------------------------------------
# process_file: paragraph-level pairing
# ---------------------------------------------------------------------------
class TestProcessFileBlocks:
    def test_quote_split_over_two_wrapped_lines_is_paired(self):
        stats = make_stats()
        warnings = []
        content = 'Er sagte: "Das war\nein Test." Und ging.'
        result = process_file(content, stats, warnings)
        lines = result.split("\n")
        assert lines[0] == f"Er sagte: {DE_OPEN_DOUBLE}Das war"
        assert lines[1] == f"ein Test.{DE_CLOSE_DOUBLE} Und ging."
        assert warnings == []
        assert stats["warnings"] == 0
        assert stats["straight_double"] == 1
        assert stats["lines_changed"] == 2

    def test_odd_paragraphs_warn_separately_with_file_line_numbers(self):
        stats = make_stats()
        warnings = []
        content = '"Erster Absatz\nohne Schluss.\n\nZweiter "Absatz\n\n"Dritter" Absatz'
        result = process_file(content, stats, warnings)
        assert len(warnings) == 2
        assert warnings[0].startswith("Lines 1-2: ")
        assert (
            f'Context: "Erster Absatz{CONTEXT_LINE_SEPARATOR}ohne Schluss.'
            in warnings[0]
        )
        assert warnings[1].startswith("Line 4: ")
        assert stats["warnings"] == 2
        lines = result.split("\n")
        assert lines[0] == '"Erster Absatz'
        assert lines[3] == 'Zweiter "Absatz'
        assert lines[5] == f"{DE_OPEN_DOUBLE}Dritter{DE_CLOSE_DOUBLE} Absatz"

    def test_list_items_are_paired_per_item(self):
        stats = make_stats()
        warnings = []
        content = '- "Nur eine\n- "Paar" hier\n- "Noch ein Paar"'
        result = process_file(content, stats, warnings)
        lines = result.split("\n")
        assert lines[0] == '- "Nur eine'
        assert lines[1] == f"- {DE_OPEN_DOUBLE}Paar{DE_CLOSE_DOUBLE} hier"
        assert lines[2] == f"- {DE_OPEN_DOUBLE}Noch ein Paar{DE_CLOSE_DOUBLE}"
        assert len(warnings) == 1
        assert warnings[0].startswith("Line 1: ")

    def test_list_item_continuation_line_belongs_to_the_item(self):
        stats = make_stats()
        warnings = []
        content = '- "Ein Zitat\n  über zwei Zeilen" fertig\n- Zweiter Punkt'
        result = process_file(content, stats, warnings)
        lines = result.split("\n")
        assert lines[0] == f"- {DE_OPEN_DOUBLE}Ein Zitat"
        assert lines[1] == f"  über zwei Zeilen{DE_CLOSE_DOUBLE} fertig"
        assert lines[2] == "- Zweiter Punkt"
        assert warnings == []

    def test_numbered_list_items_are_separate_blocks(self):
        stats = make_stats()
        warnings = []
        result = process_file('1. "a\n2. "b"', stats, warnings)
        lines = result.split("\n")
        assert lines[0] == '1. "a'
        assert lines[1] == f"2. {DE_OPEN_DOUBLE}b{DE_CLOSE_DOUBLE}"
        assert len(warnings) == 1
        assert warnings[0].startswith("Line 1: ")

    def test_heading_is_not_paired_with_the_paragraph_below(self):
        stats = make_stats()
        warnings = []
        content = '# Kapitel "auf\nText "zu'
        result = process_file(content, stats, warnings)
        assert result == content
        assert [w.split(":")[0] for w in warnings] == ["Line 1", "Line 2"]

    def test_table_rows_are_paired_per_row(self):
        stats = make_stats()
        warnings = []
        content = '| "a" | "b |\n| "c" | d |'
        result = process_file(content, stats, warnings)
        lines = result.split("\n")
        assert lines[0] == '| "a" | "b |'
        assert lines[1] == f"| {DE_OPEN_DOUBLE}c{DE_CLOSE_DOUBLE} | d |"
        assert len(warnings) == 1
        assert warnings[0].startswith("Line 1: ")

    def test_blockquote_lines_join_the_running_block(self):
        stats = make_stats()
        warnings = []
        result = process_file('> "Zitat über\n> zwei Zeilen"', stats, warnings)
        lines = result.split("\n")
        assert lines[0] == f"> {DE_OPEN_DOUBLE}Zitat über"
        assert lines[1] == f"> zwei Zeilen{DE_CLOSE_DOUBLE}"
        assert warnings == []

    def test_paragraph_directly_before_a_fence_is_converted(self):
        stats = make_stats()
        content = 'Text "a\nb"\n```\n"code"\n```\n"c\nd"'
        result = process_file(content, stats, [])
        lines = result.split("\n")
        assert lines[0] == f"Text {DE_OPEN_DOUBLE}a"
        assert lines[1] == f"b{DE_CLOSE_DOUBLE}"
        assert lines[2] == "```"
        assert lines[3] == '"code"'
        assert lines[4] == "```"
        assert lines[5] == f"{DE_OPEN_DOUBLE}c"
        assert lines[6] == f"d{DE_CLOSE_DOUBLE}"

    def test_frontmatter_then_wrapped_paragraph(self):
        stats = make_stats()
        content = '---\ntitle: "x"\n---\n"Eins\nzwei"'
        result = process_file(content, stats, [])
        lines = result.split("\n")
        assert lines[1] == 'title: "x"'
        assert lines[3] == f"{DE_OPEN_DOUBLE}Eins"
        assert lines[4] == f"zwei{DE_CLOSE_DOUBLE}"

    def test_lines_changed_counts_each_changed_line_once(self):
        stats = make_stats()
        process_file('"Eins\nzwei"\nunverändert\n"drei"', stats, [])
        assert stats["lines_changed"] == 3

    def test_english_double_quotes_pair_across_lines(self):
        stats = make_stats()
        result = process_file(f"{EN_OPEN_DOUBLE}Eins\nzwei{EN_CLOSE_DOUBLE}", stats, [])
        lines = result.split("\n")
        assert lines[0] == f"{DE_OPEN_DOUBLE}Eins"
        assert lines[1] == f"zwei{DE_CLOSE_DOUBLE}"
        assert EN_CLOSE_DOUBLE not in result

    def test_english_single_quotes_pair_across_lines(self):
        stats = make_stats()
        result = process_file(f"{EN_OPEN_SINGLE}Eins\nzwei{EN_CLOSE_SINGLE}", stats, [])
        lines = result.split("\n")
        assert lines[0] == f"{DE_OPEN_SINGLE}Eins"
        assert lines[1] == f"zwei{DE_CLOSE_SINGLE}"


# ---------------------------------------------------------------------------
# Reporting helpers
# ---------------------------------------------------------------------------
class TestPrintHelpers:
    def test_print_diff_shows_only_changed_lines(self, capsys):
        print_diff('"a"\nsame', f"{DE_OPEN_DOUBLE}a{DE_CLOSE_DOUBLE}\nsame")
        out = capsys.readouterr().out
        assert "Line 1:" in out
        assert '- "a"' in out
        assert f"+ {DE_OPEN_DOUBLE}a{DE_CLOSE_DOUBLE}" in out
        assert "Line 2" not in out

    def test_print_diff_without_changes(self, capsys):
        print_diff("x", "x")
        assert "No changes." in capsys.readouterr().out

    def test_print_diff_with_different_line_counts(self, capsys):
        print_diff("a", "a\nb")
        out = capsys.readouterr().out
        assert "Line 2:" in out
        assert "+ b" in out

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
class TestMain:
    def test_file_mode_writes_file_and_prints_summary(
        self, tmp_path, monkeypatch, capsys
    ):
        f = tmp_path / "a.md"
        f.write_text('"Hallo"', encoding="utf-8")
        monkeypatch.setattr(sys, "argv", ["fix-german-quotes", str(f)])
        main()
        assert (
            f.read_text(encoding="utf-8") == f"{DE_OPEN_DOUBLE}Hallo{DE_CLOSE_DOUBLE}"
        )
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

    def test_missing_path_exits_with_error(self, tmp_path, monkeypatch, capsys):
        missing = tmp_path / "nope.md"
        monkeypatch.setattr(sys, "argv", ["fix-german-quotes", str(missing)])
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 1
        assert "Path not found" in capsys.readouterr().err

    def test_no_matching_files_exits_with_error(self, tmp_path, monkeypatch, capsys):
        (tmp_path / "notes.txt").write_text("x", encoding="utf-8")
        monkeypatch.setattr(
            sys, "argv", ["fix-german-quotes", str(tmp_path), "--pattern", "*.markdown"]
        )
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 1
        assert "No files matching '*.markdown'" in capsys.readouterr().err
