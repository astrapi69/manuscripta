import pytest

pytestmark = pytest.mark.unit

# tests/test_convert_links_to_plain_text.py
from pathlib import Path
from manuscripta.markdown.links_to_plain import (
    convert_links_in_text,
    convert_file,
    convert_many,
)


def write(p: Path, text: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


# Each row: text, the text with its links converted, the links counted
CONVERT_TEXT_CASES = [
    pytest.param(
        "Visit [Example](https://example.com) now.",
        "Visit Example: https://example.com now.",
        1,
        id="basic-link-conversion",
    ),
    pytest.param(
        "![Img](pic.png) and [anchor](#section)",
        "![Img](pic.png) and [anchor](#section)",
        0,
        id="skip-images-and-anchor-links",
    ),
    pytest.param(
        "```\n[Link](https://secret.com)\n``` and `[Another](https://skip.com)`",
        "```\n[Link](https://secret.com)\n``` and `[Another](https://skip.com)`",
        0,
        id="skip-links-in-code",
    ),
]


@pytest.mark.parametrize("text, expected, count", CONVERT_TEXT_CASES)
def test_convert_links_in_text(text, expected, count):
    assert convert_links_in_text(text) == (expected, count)


def test_file_and_many_conversion(tmp_path: Path):
    f1 = tmp_path / "file1.md"
    f2 = tmp_path / "file2.md"
    write(f1, "Check [A](https://a.com)")
    write(f2, "No links here")

    changed, cnt = convert_file(f1)
    assert changed and cnt == 1
    assert "A: https://a.com" in f1.read_text()

    files_changed, total_converted = convert_many([f1, f2])
    assert files_changed == 0
    assert total_converted == 0
