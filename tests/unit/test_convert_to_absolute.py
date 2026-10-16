import pytest

pytestmark = pytest.mark.unit

# tests/test_convert_to_absolute.py
from pathlib import Path
import os
from manuscripta.paths.to_absolute import convert_to_absolute, convert_file_to_absolute


def write(p: Path, text: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


# Each row: the image file under assets/, the chapter body, the expected
# (changed, count) and the text of the chapter afterwards (None: unchanged).
# {rel} is the image path relative to the chapter, {img} its absolute path.
SINGLE_FILE_CASES = [
    pytest.param(
        "figs/a.png",
        "Before\n![alt]({rel})\nAfter\n",
        (True, 1),
        "Before\n![alt]({img})\nAfter\n",
        id="converts-relative-image-to-absolute",
    ),
    # one absolute (should remain), one missing (should remain unchanged)
    pytest.param(
        "b.png",
        "![abs]({img}) and ![missing](images/notthere.png)",
        (False, 0),
        None,
        id="keeps-already-absolute-and-skips-missing",
    ),
    # with a title and with angle-brackets
    pytest.param(
        "weird (name).png",
        '![titled](<{rel}> "Cover")\n![angled](<{rel}>)',
        (True, 2),
        '![titled]({img} "Cover")\n![angled]({img})',
        id="preserves-title-and-handles-angle-brackets",
    ),
    # Only the visible one converted; code-block and inline stayed as-is
    pytest.param(
        "c.png",
        "Visible ![ok]({rel})\n"
        "```\ncode ![nope]({rel})\n```\n"
        "Inline `![nope2]({rel})` end.",
        (True, 1),
        "Visible ![ok]({img})\n"
        "```\ncode ![nope]({rel})\n```\n"
        "Inline `![nope2]({rel})` end.",
        id="skips-inside-code-blocks-and-inline-code",
    ),
    pytest.param(
        "x.png",
        "![abs]({img})",
        (False, 0),
        None,
        id="no-write-when-no-change",
    ),
]


@pytest.mark.parametrize("image, body, expected, after", SINGLE_FILE_CASES)
def test_convert_file_to_absolute(image, body, expected, after, tmp_path: Path):
    img = tmp_path / "assets" / image
    write(img, "x")
    md = tmp_path / "manuscript" / "chapters" / "doc.md"
    fields = {"rel": os.path.relpath(img, start=md.parent), "img": img.resolve()}
    text = body.format(**fields)
    write(md, text)

    assert convert_file_to_absolute(md) == expected
    assert md.read_text(encoding="utf-8") == (
        text if after is None else after.format(**fields)
    )


def test_directory_walk_multiple_dirs(tmp_path: Path):
    base = tmp_path
    ch = base / "manuscript" / "chapters"
    fm = base / "manuscript" / "front-matter"
    img1 = base / "assets" / "d.png"
    img2 = base / "assets" / "e.png"
    write(img1, "x")
    write(img2, "x")

    md1 = ch / "a.md"
    md2 = fm / "b.md"
    rel1 = os.path.relpath(img1, start=md1.parent)
    rel2 = os.path.relpath(img2, start=md2.parent)
    write(md1, f"![a]({rel1})")
    write(md2, f"![b]({rel2})")

    files_changed, converted = convert_to_absolute([ch, fm])
    assert files_changed == 2
    assert converted == 2
