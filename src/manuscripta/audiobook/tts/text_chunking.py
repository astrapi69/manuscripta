"""Reusable text-chunking for TTS adapters.

Splits long text into chunks that respect paragraph and sentence
boundaries, so that each chunk stays within an engine's character limit.
"""

import re


def split_text_into_chunks(text: str, max_chars: int = 4000) -> list[str]:
    """Split *text* into chunks of at most *max_chars* characters.

    Strategy:
    1. Split by double newlines (paragraphs).
    2. If a paragraph is still too long, split by sentences.
    3. If a sentence is still too long, hard-split at *max_chars*.
    """
    paragraphs = re.split(r"\n\s*\n", text)
    chunks: list[str] = []
    current_chunk = ""

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        candidate = f"{current_chunk}\n\n{para}" if current_chunk else para
        if len(candidate) <= max_chars:
            current_chunk = candidate
            continue

        if current_chunk:
            chunks.append(current_chunk)
            current_chunk = ""

        if len(para) <= max_chars:
            current_chunk = para
            continue

        # Paragraph too long: split by sentences
        sentences = re.split(r"(?<=[.!?])\s+", para)
        for sentence in sentences:
            if not sentence.strip():
                continue
            candidate = f"{current_chunk} {sentence}" if current_chunk else sentence
            if len(candidate) <= max_chars:
                current_chunk = candidate
            else:
                if current_chunk:
                    chunks.append(current_chunk)
                if len(sentence) > max_chars:
                    for i in range(0, len(sentence), max_chars):
                        chunks.append(sentence[i : i + max_chars])
                    current_chunk = ""
                else:
                    current_chunk = sentence

    if current_chunk:
        chunks.append(current_chunk)

    return chunks
