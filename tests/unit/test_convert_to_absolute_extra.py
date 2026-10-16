import pytest

pytestmark = pytest.mark.unit

# tests/test_convert_to_absolute_extra.py
from pathlib import Path
import os
from manuscripta.paths.to_absolute import convert_file_to_absolute, convert_to_absolute


def write(p: Path, txt: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(txt, encoding="utf-8")


# Each row: the chapter under manuscript/, the image files under assets/, the
# chapter body, the expected (changed, count) and the text of the chapter
# afterwards (None: unchanged). {rel0}/{img0} are the first image's path
# relative to the chapter and its absolute path, {rel1}/{img1} the second's.
SINGLE_FILE_CASES = [
    # ./../../assets/imgs/a.png is still valid
    pytest.param(
        "chapters/sub/doc.md",
        ["imgs/a.png"],
        "![one]({rel0}) and ![two](./{rel0})",
        (True, 2),
        "![one]({img0}) and ![two]({img0})",
        id="relative-with-dot-and-dotdot",
    ),
    # nothing to convert; all are "url-like"
    pytest.param(
        "chapters/urls.md",
        [],
        "![http](https://example.com/a.png) "
        "![proto-rel](//cdn.example.com/a.png) "
        "![mailto](mailto:info@example.com) "
        "![data](data:image/png;base64,iVBORw0KGgo...)",
        (False, 0),
        None,
        id="protocol-and-data-urls-are-ignored",
    ),
    pytest.param(
        "chapters/multi.md",
        ["a.png", "b.png"],
        "![a]({rel0})![b]({rel1}) ![skip](https://host/p.png)",
        (True, 2),
        "![a]({img0})![b]({img1}) ![skip](https://host/p.png)",
        id="multiple-images-same-line-mixed",
    ),
    # title stays inside parens; path becomes absolute
    pytest.param(
        "chapters/title_single_quote.md",
        ["c.png"],
        "![sq](<{rel0}> 'Cover')",
        (True, 1),
        "![sq]({img0} 'Cover')",
        id="single-quoted-title-is-preserved",
    ),
    pytest.param(
        "chapters/mix.md",
        ["d.png"],
        "![ok]({rel0})\n"
        "![missing](images/none.png)\n"
        "![url](https://ex.com/x.png)\n"
        "`inline ![nope]({rel0})`\n"
        "```\nblock ![nope2]({rel0})\n```\n",
        (True, 1),
        "![ok]({img0})\n"
        "![missing](images/none.png)\n"
        "![url](https://ex.com/x.png)\n"
        "`inline ![nope]({rel0})`\n"
        "```\nblock ![nope2]({rel0})\n```\n",
        id="mixed-convertible-and-nonconvertible",
    ),
]


@pytest.mark.parametrize("chapter, images, body, expected, after", SINGLE_FILE_CASES)
def test_convert_file_to_absolute(
    chapter, images, body, expected, after, tmp_path: Path
):
    md = tmp_path / "manuscript" / chapter
    fields = {}
    for i, name in enumerate(images):
        img = tmp_path / "assets" / name
        write(img, "x")
        fields[f"rel{i}"] = os.path.relpath(img, start=md.parent)
        fields[f"img{i}"] = img.resolve()
    text = body.format(**fields)
    write(md, text)

    assert convert_file_to_absolute(md) == expected
    assert md.read_text(encoding="utf-8") == (
        text if after is None else after.format(**fields)
    )


def test_walk_three_default_dirs_with_mixed_content(tmp_path: Path):
    base = tmp_path
    ch = base / "manuscript" / "chapters"
    fm = base / "manuscript" / "front-matter"
    bm = base / "manuscript" / "back-matter"
    img = base / "assets" / "e.png"
    write(img, "x")

    md1 = ch / "a.md"
    md2 = fm / "b.md"
    md3 = bm / "c.md"
    rel1 = os.path.relpath(img, start=md1.parent)
    rel2 = os.path.relpath(img, start=md2.parent)
    write(md1, f"![a]({rel1})")
    write(
        md2, f'![b]({rel2}) "trailer text"'
    )  # trailing text after tag to ensure we match minimally
    write(md3, "No images here")

    files_changed, converted = convert_to_absolute([ch, fm, bm])
    assert files_changed == 2 and converted == 2
