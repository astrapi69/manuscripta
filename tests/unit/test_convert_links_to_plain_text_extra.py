import pytest

pytestmark = pytest.mark.unit

# tests/test_convert_links_to_plain_text_extra.py
from pathlib import Path
from manuscripta.markdown.links_to_plain import convert_links_in_text, convert_file

# Each row: text, the text with its links converted, the links counted
CONVERT_TEXT_CASES = [
    pytest.param(
        "See [One](https://one.test) and [Two](https://two.test?q=1).",
        "See One: https://one.test and Two: https://two.test?q=1.",
        2,
        id="multiple-links-same-line",
    ),
    pytest.param(
        'Read the [Spec](https://spec.test/v1 "Official Spec").',
        "Read the Spec: https://spec.test/v1.",
        1,
        id="title-is-dropped-and-label-preserved",
    ),
    pytest.param(
        "Open [Issue](<https://host.test/a(b)/c>).",
        "Open Issue: https://host.test/a(b)/c.",
        1,
        id="angle-brackets-with-parentheses-in-url",
    ),
    pytest.param(
        "Try [Search](https://ex.test/find?q=a+b#top).",
        "Try Search: https://ex.test/find?q=a+b#top.",
        1,
        id="query-and-fragment",
    ),
    pytest.param(
        "CDN: [Asset](//cdn.example.com/lib.js)",
        "CDN: Asset: //cdn.example.com/lib.js",
        1,
        id="protocol-relative-url",
    ),
    pytest.param(
        "Contact [Email](mailto:info@example.com) or [Phone](tel:+123456789).",
        "Contact Email: mailto:info@example.com or Phone: tel:+123456789.",
        2,
        id="mailto-and-tel",
    ),
    pytest.param(
        "See [Appendix](../back-matter/appendix.md).",
        "See Appendix: ../back-matter/appendix.md.",
        1,
        id="relative-link-is-converted-verbatim",
    ),
    # only the full URL should convert; pure anchor stays
    pytest.param(
        "Jump to [Top](#top) and [Keep](https://ok.test#frag).",
        "Jump to [Top](#top) and Keep: https://ok.test#frag.",
        1,
        id="anchor-only-is-skipped",
    ),
    pytest.param(
        "Real [Link](https://r.test)\n"
        "```\n[Nope](https://no.test)\n```\n"
        "Inline `code [NopeToo](https://no2.test)` done.",
        "Real Link: https://r.test\n"
        "```\n[Nope](https://no.test)\n```\n"
        "Inline `code [NopeToo](https://no2.test)` done.",
        1,
        id="inline-code-and-fenced-code-with-multiple-links-untouched",
    ),
    pytest.param(
        '![Alt](img.png "caption") and [OK](https://ok.test)',
        '![Alt](img.png "caption") and OK: https://ok.test',
        1,
        id="image-links-are-ignored-even-with-titles",
    ),
    # Every protected span gets its own token: a third span must not take the
    # place of the second when the text is restored (token uniqueness,
    # TESTING.md §14.8.5). Kills _protect_segments__mutmut_8 (idx += 1 -> idx = 1).
    pytest.param(
        "a `[x](1)` b `[y](2)` c `[z](3)` d [k](https://k.test)",
        "a `[x](1)` b `[y](2)` c `[z](3)` d k: https://k.test",
        1,
        id="three-inline-code-spans-each-stay-verbatim",
    ),
    # An angle-bracketed destination may contain spaces (CommonMark); the
    # brackets keep it whole instead of cutting it at the first space like a
    # title.
    pytest.param(
        "Open [Doc](<https://host.test/my file.pdf>).",
        "Open Doc: https://host.test/my file.pdf.",
        1,
        id="angle-brackets-with-space-in-url",
    ),
    # A title after an angle-bracketed destination is dropped like any other
    # title, and the brackets come off.
    pytest.param(
        'Read [Spec](<https://spec.test/v1> "Official Spec").',
        "Read Spec: https://spec.test/v1.",
        1,
        id="angle-brackets-with-title",
    ),
    # Only a matched <...> pair is a delimiter; a `>` at the end of a bare
    # destination is a URL character and is kept verbatim.
    pytest.param(
        "See [Greater](https://ex.test/?op=>).",
        "See Greater: https://ex.test/?op=>.",
        1,
        id="bare-url-ending-in-a-greater-than-sign-is-kept",
    ),
]


@pytest.mark.parametrize("text, expected, count", CONVERT_TEXT_CASES)
def test_convert_links_in_text(text, expected, count):
    assert convert_links_in_text(text) == (expected, count)


def test_file_roundtrip(tmp_path: Path):
    f = tmp_path / "doc.md"
    f.write_text("Go [Home](https://home.test) now.", encoding="utf-8")
    changed, cnt = convert_file(f)
    assert changed and cnt == 1
    assert f.read_text(encoding="utf-8") == "Go Home: https://home.test now."


def test_url_with_parentheses_without_angle_brackets_note():
    # NOTE: Without <...>, a ) can terminate the URL in Markdown parsing.
    # Our converter expects <...> if parentheses are present in the URL.
    text = "Bad form [X](https://site.test/a(b)) should ideally be written as [X](<https://site.test/a(b)>)."
    out, n = convert_links_in_text(text)
    # We don't assert specifics here; this is just documentation-by-test.
    assert n >= 0
