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
]


@pytest.mark.parametrize("src, expected, count", STRIP_LINKS_CASES)
def test_strip_links_in_text(src, expected, count):
    assert strip_links_in_text(src) == (expected, count)
