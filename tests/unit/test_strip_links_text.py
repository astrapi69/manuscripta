import pytest

pytestmark = pytest.mark.unit

# tests/test_strip_links_text.py
from manuscripta.markdown.strip_links import strip_links_in_text

# Each row: text, the text with its links stripped, the links counted
STRIP_LINKS_CASES = [
    pytest.param(
        "See the [guide](docs/guide.md) please.",
        "See the guide please.",
        1,
        id="basic-link-to-text",
    ),
    pytest.param(
        "[one](a) and [two](b) and [three](c)",
        "one and two and three",
        3,
        id="multiple-links",
    ),
    pytest.param(
        "image: ![alt text](pic.png) and [link](x)",
        "image: ![alt text](pic.png) and link",
        1,
        id="does-not-touch-images",
    ),
    pytest.param(
        "keep `a [b](c) d` but strip [e](f)",
        "keep `a [b](c) d` but strip e",
        1,
        id="skips-inline-code",
    ),
    # Fenced blocks come back verbatim, fence lines included (#21)
    pytest.param(
        "top [x](y)\n\n```python\nprint('[x](y)')\n```\nend [a](b)",
        "top x\n\n```python\nprint('[x](y)')\n```\nend a",
        2,
        id="skips-fenced-code-blocks-backticks-info-string",
    ),
    pytest.param(
        "pre [m](n)\n\n```\n[x](y)\n```\npost [o](p)",
        "pre m\n\n```\n[x](y)\n```\npost o",
        2,
        id="skips-fenced-code-blocks-backticks",
    ),
    pytest.param(
        "pre [m](n)\n\n~~~\n[x](y)\n~~~\npost [o](p)",
        "pre m\n\n~~~\n[x](y)\n~~~\npost o",
        2,
        id="skips-fenced-code-blocks-tildes",
    ),
    pytest.param(
        "pre [m](n)\n\n~~~python\n[x](y)\n~~~\npost [o](p)",
        "pre m\n\n~~~python\n[x](y)\n~~~\npost o",
        2,
        id="skips-fenced-code-blocks-tildes-info-string",
    ),
    # An opening fence that is never closed is no fence: the lines after it
    # are prose and their links are stripped.
    pytest.param(
        "pre [m](n)\n\n```\n[x](y)\nnever closed [q](r)",
        "pre m\n\n```\nx\nnever closed q",
        3,
        id="unclosed-fence-is-not-a-fence",
    ),
    # The fence match swallows the line break after the closing fence, so an
    # inline code span on the next line starts exactly where the fence ends;
    # it is still a code span, not prose.
    pytest.param(
        "```\n[x](y)\n```\n`[a](b)` end [c](d)",
        "```\n[x](y)\n```\n`[a](b)` end c",
        1,
        id="inline-code-right-after-a-fence-stays-code",
    ),
    # Every prose segment between code spans adds to the count.
    pytest.param(
        "[a](b) `x` [c](d) `y` [e](f)",
        "a `x` c `y` e",
        3,
        id="links-between-two-code-spans-all-count",
    ),
    # Reference links become their text and the definition line is removed;
    # each counts.
    pytest.param(
        'See [a](b) and [text][id].\n\n[id]: https://x.test "T"\n',
        "See a and text.\n\n",
        3,
        id="reference-link-and-its-definition",
    ),
    pytest.param(
        "[a][x] and [b][y]",
        "a and b",
        2,
        id="two-reference-links-both-count",
    ),
    pytest.param(
        "Use [the docs][] here.\n\n[the docs]: https://d.test\n",
        "Use the docs here.\n\n",
        2,
        id="empty-reference-link-and-its-definition",
    ),
    # A definition between two paragraphs leaves one blank line, not three.
    pytest.param(
        "A [t][id].\n\n[id]: https://x.test\n\nB",
        "A t.\n\nB",
        2,
        id="definition-between-paragraphs-leaves-one-blank-line",
    ),
]


@pytest.mark.parametrize("src, expected, count", STRIP_LINKS_CASES)
def test_strip_links_in_text(src, expected, count):
    assert strip_links_in_text(src) == (expected, count)
