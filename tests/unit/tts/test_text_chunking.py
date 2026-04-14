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
