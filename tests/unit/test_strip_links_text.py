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
    # unchanged inside ~~~
    pytest.param(
        "pre [m](n)\n\n~~~\n[x](y)\n~~~\npost [o](p)",
        "pre m\n\n~~~\n[x](y)\n~~~\npost o",
        2,
        id="skips-fenced-code-blocks-tildes",
    ),
]


@pytest.mark.parametrize("src, expected, count", STRIP_LINKS_CASES)
def test_strip_links_in_text(src, expected, count):
    assert strip_links_in_text(src) == (expected, count)


# Not a STRIP_LINKS_CASES row: the fence lines of a ```python block do not come
# back verbatim, so only the content and both ends of the text are pinned.
def test_skips_fenced_code_blocks_triple_backticks():
    src = "top [x](y)\n\n```python\nprint('[x](y)')\n```\nend [a](b)"
    out, n = strip_links_in_text(src)
    # Only top and end should be stripped, not inside the fence
    assert out.startswith("top x")
    assert "print('[x](y)')" in out
    assert out.rstrip().endswith("end a")
    assert n == 2
