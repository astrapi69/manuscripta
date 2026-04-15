import pytest

pytestmark = pytest.mark.unit

"""Tests for text_chunking.split_text_into_chunks."""

from manuscripta.audiobook.tts.text_chunking import split_text_into_chunks


class TestSplitTextIntoChunks:
    def test_short_text_single_chunk(self):
        result = split_text_into_chunks("Hello world.", max_chars=100)
        assert result == ["Hello world."]

    def test_empty_text(self):
        assert split_text_into_chunks("") == []

    def test_whitespace_only(self):
        assert split_text_into_chunks("   \n\n  \n  ") == []

    def test_paragraphs_split(self):
        text = "Paragraph one.\n\nParagraph two.\n\nParagraph three."
        result = split_text_into_chunks(text, max_chars=30)
        assert len(result) >= 2
        assert all(len(c) <= 30 for c in result)

    def test_long_paragraph_split_by_sentences(self):
        text = "First sentence. Second sentence. Third sentence."
        result = split_text_into_chunks(text, max_chars=25)
        assert len(result) >= 2
        assert all(len(c) <= 25 for c in result)

    def test_hard_split_on_very_long_sentence(self):
        text = "A" * 100
        result = split_text_into_chunks(text, max_chars=30)
        assert len(result) == 4  # 30 + 30 + 30 + 10
        assert all(len(c) <= 30 for c in result)

    def test_respects_max_chars(self):
        text = "Word. " * 500
        result = split_text_into_chunks(text.strip(), max_chars=100)
        assert all(len(c) <= 100 for c in result)

    def test_preserves_content(self):
        text = "Absatz eins.\n\nAbsatz zwei.\n\nAbsatz drei."
        result = split_text_into_chunks(text, max_chars=5000)
        joined = "\n\n".join(result)
        assert "Absatz eins." in joined
        assert "Absatz zwei." in joined
        assert "Absatz drei." in joined

    def test_accumulates_short_paragraphs(self):
        text = "A.\n\nB.\n\nC."
        result = split_text_into_chunks(text, max_chars=100)
        assert len(result) == 1
        assert "A." in result[0] and "B." in result[0] and "C." in result[0]


class TestSplitTextIntoChunksMutationPins:
    """Behavioural tests added for Phase 4b Pass 2 Commit 8 to kill the
    nine A-category mutation survivors on ``split_text_into_chunks``.

    Each test pins a specific observable output against a specific input.
    Companion B-annotations for the six equivalent mutants live in
    ``.mutmut/equivalent.yaml`` (§14.8.3 for mutant 1; ad-hoc reasoning
    for mutants 10, 20, 24, 37, 47).
    """

    def test_paragraph_split_rejects_xx_wrapped_regex(self):
        """Pins that the paragraph-split regex ``r'\\n\\s*\\n'`` matches
        real blank-line separators, not the XX-wrapped literal.

        Kills mutant 8 (regex → ``r'XX\\n\\s*\\nXX'``).
        """
        result = split_text_into_chunks("ab\n\ncd", max_chars=5)
        assert result == ["ab", "cd"]

    def test_blank_paragraph_continues_not_breaks(self):
        """Pins that blank paragraphs are skipped (``continue``), not
        treated as loop termination (``break``).

        Kills mutant 14 (``continue`` → ``break`` on blank para).

        Input shape: leading blank element from
        ``re.split(r'\\n\\s*\\n', '\\n\\na\\n\\nb') == ['', 'a', 'b']``.
        The orig skips the leading ``''`` and produces both non-blank
        paragraphs; the mutant breaks on the first iteration and emits
        nothing.
        """
        result = split_text_into_chunks("\n\na\n\nb", max_chars=3)
        assert result == ["a", "b"]

    def test_candidate_boundary_inclusive_at_max_chars(self):
        """Pins that ``len(candidate) <= max_chars`` includes the boundary;
        candidates of exactly ``max_chars`` chars merge, not split.

        Kills mutant 16 (outer-loop ``<=`` → ``<``).
        """
        result = split_text_into_chunks("ab\n\ncd", max_chars=6)
        assert result == ["ab\n\ncd"]

    def test_reset_does_not_leak_sentinel_token(self):
        """Pins that ``current_chunk`` is reset to an empty-equivalent
        value, not to any literal sentinel string.

        Kills mutant 21 (reset ``''`` → ``'XXXX'``).
        """
        result = split_text_into_chunks("aa\n\nccc ddd. eee fff.", max_chars=10)
        assert "XXXX" not in result
        for chunk in result:
            assert "XXXX" not in chunk

    def test_paragraph_boundary_at_max_chars_preserves_single_space_join(self):
        """Pins that ``len(para) <= max_chars`` uses inclusive comparison;
        paragraphs of exactly max_chars chars bypass sentence-split and
        preserve their internal whitespace verbatim.

        Kills mutant 22 (``<=`` → ``<`` on para boundary).
        """
        result = split_text_into_chunks("xx\n\na.  b", max_chars=5)
        assert result == ["xx", "a.  b"]

    def test_sentence_split_rejects_xx_wrapped_regex(self):
        """Pins that the sentence-split regex matches real sentence
        terminators, not the XX-wrapped literal.

        Kills mutant 31 (regex → ``r'XX(?<=[.!?])\\s+XX'``).
        """
        result = split_text_into_chunks("xxx\n\na. b. c. d.", max_chars=5)
        assert "a. b." in result

    def test_inner_candidate_boundary_inclusive(self):
        """Pins that the inner-loop (sentence-merge) candidate boundary
        is inclusive, matching outer-loop semantics.

        Kills mutant 34 (inner-loop ``<=`` → ``<``).
        """
        result = split_text_into_chunks("xx\n\naa. b", max_chars=5)
        assert "aa. b" in result

    def test_hard_split_preserves_first_character(self):
        """Pins that the hard-split window starts at index 0, not
        index 1; the first character of the oversized sentence must
        appear in the first output chunk.

        Kills mutant 44 (``range(0, ...)`` → ``range(1, ...)``).
        """
        result = split_text_into_chunks("aaabbb", max_chars=3)
        assert result[0].startswith("a")
        assert "".join(result) == "aaabbb"

    def test_single_fit_trailing_sentence_preserved(self):
        """Pins that a trailing single-fit sentence is assigned to
        ``current_chunk`` and appended at end-of-loop, not dropped via
        a None assignment.

        Kills mutant 49 (``current_chunk = sentence`` → ``= None``).
        """
        result = split_text_into_chunks("xx\n\naaaa. b", max_chars=5)
        assert result == ["xx", "aaaa.", "b"]
