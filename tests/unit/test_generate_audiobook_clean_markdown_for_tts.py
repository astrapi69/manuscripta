import pytest

pytestmark = pytest.mark.unit

# tests/test_generate_audiobook_clean_markdown_for_tts.py
import textwrap
from manuscripta.audiobook.generator import clean_markdown_for_tts

# Each row: the Markdown source and the text clean_markdown_for_tts makes of it
CLEAN_MARKDOWN_CASES = [
    pytest.param(
        textwrap.dedent(
            """
            <p>Intro before.</p>
            <figure class="img">
              <img src="assets/village-without-money.png" alt="_..._" />
              <figcaption><em>_..._</em></figcaption>
            </figure>
            <p>After figure.</p>
            """
        ),
        "Intro before.\nAfter figure.",
        id="removes-full-figure-block",
    ),
    # no URL residue
    pytest.param(
        "Text ![alt](img.png) and [click here](https://example.com  ).",
        "Text and click here.",
        id="removes-markdown-images-and-keeps-link-text",
    ),
    pytest.param(
        textwrap.dedent(
            """
            Some [text][id] and [more][] around.

            [id]: https://example.com
            [more]: https://example.org
            """
        ),
        "Some text and more around.",
        id="reference-links-and-definitions-removed",
    ),
    # inline code content preserved
    pytest.param(
        textwrap.dedent(
            """
            Here is code:
            ```
            print("hello")
            ```
            Inline `x = 1` end.
            """
        ),
        "Here is code:\nInline x = 1 end.",
        id="code-blocks-and-inline-code-removed",
    ),
    pytest.param(
        textwrap.dedent(
            """
            # Title
            This is **bold** and _italic_ and __strong__.

            | a | b |
            |---|---|
            | 1 | 2 |
            """
        ),
        "Title This is bold and italic and strong.",
        id="headings-bold-italics-tables-removed",
    ),
    pytest.param(
        "A<!-- hidden -->\n\n\nB",
        "A\nB",
        id="html-comments-removed-and-excess-newlines-collapsed",
    ),
    pytest.param(
        textwrap.dedent(
            """\
            ---
            title: Test
            author: You &amp; Me
            ---
            Hello&nbsp;World &amp; Co.
            """
        ),
        "Hello World & Co.",
        id="yaml-front-matter-removed-and-entities-unescaped",
    ),
]


@pytest.mark.parametrize("src, expected", CLEAN_MARKDOWN_CASES)
def test_clean_markdown_for_tts(src, expected):
    assert clean_markdown_for_tts(src) == expected
