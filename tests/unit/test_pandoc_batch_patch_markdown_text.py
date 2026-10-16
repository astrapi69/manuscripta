import pytest

pytestmark = pytest.mark.unit

# tests/test_pandoc_batch_patch_markdown_text.py
from manuscripta.utils.pandoc_batch import patch_markdown_text


# Each row: the raw text, the patched text and the number of patches counted
PATCH_CASES = [
    # the BOM goes, CRLF becomes LF and an HR gets its blank line
    pytest.param(
        "﻿Line1\r\n---\r\nLine2",
        "Line1\n---\n\nLine2",
        1,
        id="strips-bom-and-normalizes-newlines",
    ),
    # newline normalization alone is not a patch
    pytest.param("a\r\nb", "a\nb", 0, id="crlf-alone-is-not-counted"),
    # a classic-Mac line ending is normalized too
    pytest.param("a\rb\r", "a\nb\n", 0, id="lone-cr-becomes-lf"),
    pytest.param(
        "Hello\n\n---\n\nWorld\n",
        "Hello\n\n---\n\nWorld\n",
        0,
        id="no-change-on-clean-text",
    ),
]


@pytest.mark.parametrize("raw, expected, n", PATCH_CASES)
def test_patch_markdown_text(raw, expected, n):
    assert patch_markdown_text(raw) == (expected, n)
