import pytest

pytestmark = pytest.mark.unit

# tests/test_generate_audiobook_cleaner_use_cases.py
import textwrap
from manuscripta.audiobook.generator import clean_markdown_for_tts

# Each row: the Markdown source and the text clean_markdown_for_tts makes of it
CLEAN_MARKDOWN_CASES = [
    # Essentials preserved, noise (figure, table, fenced code) gone
    pytest.param(
        textwrap.dedent(
            """
            <!-- intro -->
            # Chapter 01: Arrival

            <figure class="hero">
              <img src="assets/hero.png" alt="Hero"/>
              <figcaption><em>Caption</em></figcaption>
            </figure>

            Welcome to **New Eden** — see [docs](https://example.com/docs).
            Table below (should be removed):
            | a | b |
            |---|---|
            | 1 | 2 |

            Code:
            ```
            print("nope")
            ```

            Inline `var = 42` is ok.
            """
        ),
        "Chapter 01: Arrival\n"
        "Welcome to New Eden — see docs. Table below (should be removed):\n"
        "Code:\n"
        "Inline var = 42 is ok.",
        id="mixed-markdown-html-content-is-readable",
    ),
    # NBSP normalized to plain space; &amp; unescaped; ü from &uuml; handled
    pytest.param(
        "Hola&nbsp;niña &amp; niño — déjà vu &uuml;ber alles",
        "Hola niña & niño — déjà vu über alles",
        id="multilingual-and-entities",
    ),
    # no remaining definition lines
    pytest.param(
        textwrap.dedent(
            """
            Read about the [last spark][ls] and [universal fire][] now.
            [ls]: https://a.example
            [universal fire]: https://b.example
            """
        ),
        "Read about the last spark and universal fire now.",
        id="reference-link-spam-removed",
    ),
    pytest.param(
        "# Only a Title", "Only a Title", id="heading-only-chapter-still-produces-text"
    ),
]


@pytest.mark.parametrize("src, expected", CLEAN_MARKDOWN_CASES)
def test_clean_markdown_for_tts(src, expected):
    assert clean_markdown_for_tts(src) == expected
