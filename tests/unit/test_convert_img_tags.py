import pytest

pytestmark = pytest.mark.unit

# tests/test_convert_img_tags.py
import sys
from pathlib import Path, PurePath
import os
import re

from manuscripta.paths.img_tags import build_img_tag, convert_markdown_tree, main


def write(p: Path, text: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def test_to_absolute_converts_relative_and_leaves_abs(tmp_path: Path):
    base = tmp_path
    # Project structure
    chapters = base / "manuscript" / "chapters"
    assets = base / "assets" / "figures"
    img = assets / "scene" / "pic.png"
    write(img, "binary")  # just to create the file

    # Markdown with mixed <img> tags (single and double quotes, extra attrs)
    md = chapters / "01.md"
    rel_path = os.path.relpath(img, start=md.parent)
    content = (
        f"Before\n"
        f'<img src="{rel_path}" alt="rel" class="c"/>\n'
        f'<img alt="already-abs" src="{img}" width="100">\n'
        f"<img src='{rel_path}' alt='single-quoted'>\n"
        f"After\n"
    )
    write(md, content)

    changed, converted = convert_markdown_tree(base, to_absolute=True)
    assert changed == 1
    assert converted == 2  # only the two relative ones

    new_text = md.read_text(encoding="utf-8")
    # Both relative srcs should now be absolute
    abs_pattern = re.compile(r'<img[^>]*\bsrc="([^"]+)"')
    srcs = abs_pattern.findall(new_text)
    assert any(str(img) in s for s in srcs)
    assert new_text.count(str(img)) == 3  # one was already absolute, plus two converted


def test_to_relative_only_under_assets(tmp_path: Path):
    base = tmp_path
    chapters = base / "manuscript" / "chapters"
    assets = base / "assets" / "figures"
    other_abs_dir = base / "outside"
    img_assets = assets / "hero.png"
    img_outside = other_abs_dir / "not-in-assets.png"
    write(img_assets, "x")
    write(img_outside, "x")

    md = chapters / "02.md"
    text = (
        f'<img src="{img_assets}" alt="ok">\n' f'<img src="{img_outside}" alt="skip">\n'
    )
    write(md, text)

    changed, converted = convert_markdown_tree(
        base, to_absolute=False, assets_dir=base / "assets"
    )
    assert changed == 1
    assert converted == 1

    new_text = md.read_text(encoding="utf-8")
    first_line = new_text.splitlines()[0]
    # The assets image becomes relative (not absolute), the outside one stays absolute
    assert 'alt="ok"' in first_line
    assert not first_line.startswith("/") and not first_line.startswith(
        str(base)
    )  # relative, not absolute
    assert str(img_outside) in new_text  # untouched


def test_no_write_when_no_change(tmp_path: Path):
    base = tmp_path
    chapters = base / "manuscript" / "chapters"
    img = base / "assets" / "pic.png"
    write(img, "x")
    md = chapters / "03.md"
    # Already absolute inside assets; converting to absolute should not change
    text = f'<img src="{img}" alt="abs"/>\n'
    write(md, text)

    changed, converted = convert_markdown_tree(base, to_absolute=True)
    assert changed == 0
    assert converted == 0
    assert md.read_text(encoding="utf-8") == text


def test_preserves_other_attributes_and_normalizes_order(tmp_path: Path):
    base = tmp_path
    chapters = base / "manuscript" / "chapters"
    img = base / "assets" / "a.png"
    write(img, "x")
    md = chapters / "04.md"
    rel = os.path.relpath(img, start=md.parent)
    # alt before src, extra attributes and irregular spacing
    write(md, f'<img   alt="x"   data-id="123"   src="{rel}"   class="y">')

    convert_markdown_tree(base, to_absolute=True)

    t = md.read_text(encoding="utf-8")
    # Normalized to src then alt then others (alpha order)
    assert t.startswith("<img ")
    assert 'src="' in t and 'alt="' in t
    src_pos = t.index('src="')
    alt_pos = t.index('alt="')
    assert src_pos < alt_pos
    # Other attributes present
    assert 'class="y"' in t and 'data-id="123"' in t


def layout(tmp_path: Path) -> tuple[Path, Path]:
    """assets/pic.png in a project; returns (the chapter file to fill, the image)."""
    md = tmp_path / "manuscript" / "chapters" / "01.md"
    img = tmp_path / "assets" / "pic.png"
    write(img, "binary")
    return md, img


# Each row: the <img> tag written ({rel}: the relative path to assets/pic.png,
# {abs}: its absolute path, {ghost}: a relative path to no file), to absolute?
TAGS_LEFT_ALONE = [
    pytest.param('<img alt="no source">', True, id="no-src-to-absolute"),
    pytest.param("<img>", False, id="bare-tag-to-relative"),
    pytest.param('<img src="{ghost}">', True, id="relative-to-missing-file"),
    pytest.param('<img src="{rel}" alt="r">', False, id="relative-under-to-relative"),
    pytest.param('<img src="{abs}">', True, id="absolute-under-to-absolute"),
]


@pytest.mark.parametrize("tag, to_absolute", TAGS_LEFT_ALONE)
def test_tags_left_alone(tag, to_absolute, tmp_path: Path):
    md, img = layout(tmp_path)
    rel = os.path.relpath(img, start=md.parent)
    text = tag.format(rel=rel, abs=img, ghost="../../assets/ghost.png") + "\n"
    write(md, text)
    assert convert_markdown_tree(tmp_path, to_absolute=to_absolute) == (0, 0)
    assert md.read_text(encoding="utf-8") == text


# Each row: the tag with an absolute src ({assets}: the image under assets/,
# {outside}: a file outside), the counts returned, the tag afterwards ({rel}:
# the relative path to the assets image)
WITHOUT_IS_RELATIVE_TO = [
    pytest.param(
        '<img alt="ok" src="{assets}">',
        (1, 1),
        '<img src="{rel}" alt="ok">',
        id="under-assets-made-relative",
    ),
    pytest.param(
        '<img src="{outside}" alt="skip">',
        (0, 0),
        '<img src="{outside}" alt="skip">',
        id="outside-assets-untouched",
    ),
    pytest.param(
        '<img src="{assets}" alt="a">\n<img src="{assets}" alt="b">',
        (1, 2),
        '<img src="{rel}" alt="a">\n<img src="{rel}" alt="b">',
        id="every-tag-under-assets-counted",
    ),
]


@pytest.mark.parametrize("tag, counts, after", WITHOUT_IS_RELATIVE_TO)
def test_to_relative_without_is_relative_to(tag, counts, after, tmp_path, monkeypatch):
    """Interpreters lacking PurePath.is_relative_to take the relative_to() route."""
    md, img = layout(tmp_path)
    outside = tmp_path / "outside" / "x.png"
    write(outside, "x")
    names = dict(assets=img, outside=outside, rel=os.path.relpath(img, md.parent))
    write(md, tag.format(**names) + "\n")
    monkeypatch.delattr(PurePath, "is_relative_to")
    assert convert_markdown_tree(tmp_path, to_absolute=False) == counts
    assert md.read_text(encoding="utf-8") == after.format(**names) + "\n"


def run_main():
    """Runs main() and returns the exit code it raised (None: it returned)."""
    try:
        main()
    except SystemExit as ex:
        return ex.code
    return None


CHAPTER = '<img src="{rel}" alt="a">\n<img alt="b" src="{abs}">\n'

# Each row: how the project is named ("--base-dir": passed explicitly; "cwd":
# the working directory, no --base-dir), the direction flags, the exit code
# (None: main returns), the line printed, the chapter afterwards ({rel}/{abs}:
# the image's relative and absolute path)
MAIN_RUNS = [
    pytest.param(
        "--base-dir",
        ["--to-absolute"],
        None,
        "✅ Converted 1 <img> tag(s) to absolute across 1 file(s).",
        '<img src="{abs}" alt="a">\n<img src="{abs}" alt="b">\n',
        id="to-absolute",
    ),
    pytest.param(
        "--base-dir",
        ["--to-relative"],
        None,
        "🔄 Reverted 1 <img> tag(s) to relative across 1 file(s).",
        '<img src="{rel}" alt="a">\n<img src="{rel}" alt="b">\n',
        id="to-relative",
    ),
    pytest.param(
        "cwd",
        ["--to-absolute"],
        None,
        "✅ Converted 1 <img> tag(s) to absolute across 1 file(s).",
        '<img src="{abs}" alt="a">\n<img src="{abs}" alt="b">\n',
        id="base-dir-defaults-to-the-working-directory",
    ),
    pytest.param(
        "--base-dir",
        [],
        2,
        "❌ Please specify exactly one of --to-absolute or --to-relative.",
        CHAPTER,
        id="neither-direction",
    ),
    pytest.param(
        "--base-dir",
        ["--to-absolute", "--to-relative"],
        2,
        "❌ Please specify exactly one of --to-absolute or --to-relative.",
        CHAPTER,
        id="both-directions",
    ),
]


@pytest.mark.parametrize("project, flags, code, line, after", MAIN_RUNS)
def test_main(project, flags, code, line, after, tmp_path, monkeypatch, capsys):
    md, img = layout(tmp_path)
    names = dict(rel=os.path.relpath(img, start=md.parent), abs=img)
    write(md, CHAPTER.format(**names))
    if project == "cwd":
        monkeypatch.chdir(tmp_path)
        argv = ["convert-img-tags", *flags]
    else:
        argv = ["convert-img-tags", "--base-dir", str(tmp_path), *flags]
    monkeypatch.setattr(sys, "argv", argv)
    assert run_main() == code
    assert capsys.readouterr().out == line + "\n"
    assert md.read_text(encoding="utf-8") == after.format(**names)


# Each row: the attributes of a tag, the tag rebuilt from them (src first, alt
# second, the rest in alphabetical order, a space only when there are any)
BUILT_TAGS = [
    pytest.param({}, "<img>", id="no-attributes"),
    pytest.param({"src": "a.png"}, '<img src="a.png">', id="src-only"),
    pytest.param(
        {"width": "1", "alt": "x", "class": "c", "src": "a.png"},
        '<img src="a.png" alt="x" class="c" width="1">',
        id="src-alt-then-alphabetical",
    ),
]


@pytest.mark.parametrize("attrs, tag", BUILT_TAGS)
def test_build_img_tag(attrs, tag):
    assert build_img_tag(attrs) == tag


# Each row: the chapter ({rel}/{abs}: the image's relative and absolute path),
# to absolute?, the counts returned, the chapter afterwards
MIXED_CHAPTERS = [
    pytest.param(
        '<img alt="no source">\n<img src="{rel}">\n',
        True,
        (1, 1),
        '<img alt="no source">\n<img src="{abs}">\n',
        id="tag-without-src-kept-verbatim-beside-a-converted-one",
    ),
    pytest.param(
        '<img src="{abs}" alt="a">\n<img src="{abs}" alt="b">\n',
        False,
        (1, 2),
        '<img src="{rel}" alt="a">\n<img src="{rel}" alt="b">\n',
        id="every-tag-under-assets-counted-to-relative",
    ),
]


@pytest.mark.parametrize("before, to_absolute, counts, after", MIXED_CHAPTERS)
def test_mixed_chapters(before, to_absolute, counts, after, tmp_path):
    md, img = layout(tmp_path)
    names = dict(rel=os.path.relpath(img, start=md.parent), abs=img)
    write(md, before.format(**names))
    assert convert_markdown_tree(tmp_path, to_absolute=to_absolute) == counts
    assert md.read_text(encoding="utf-8") == after.format(**names)


# Each row: the directory under the project holding the chapter, the
# md_directories argument (None: the defaults manuscript/chapters,
# front-matter and back-matter; {base}: the project), the counts returned
SCANNED_DIRECTORIES = [
    pytest.param("manuscript/chapters", None, (1, 1), id="default-chapters"),
    pytest.param("manuscript/front-matter", None, (1, 1), id="default-front-matter"),
    pytest.param("manuscript/back-matter", None, (1, 1), id="default-back-matter"),
    pytest.param("manuscript/appendix", None, (0, 0), id="not-a-default-directory"),
    pytest.param("docs", ["docs"], (1, 1), id="explicit-relative-directory"),
    pytest.param("docs", ["{base}/docs"], (1, 1), id="explicit-absolute-directory"),
]


@pytest.mark.parametrize("directory, md_directories, counts", SCANNED_DIRECTORIES)
def test_scanned_directories(directory, md_directories, counts, tmp_path):
    img = tmp_path / "assets" / "pic.png"
    write(img, "binary")
    md = tmp_path / directory / "01.md"
    rel = os.path.relpath(img, start=md.parent)
    write(md, f'<img src="{rel}">\n')
    if md_directories is not None:
        md_directories = [
            Path(d.replace("{base}", str(tmp_path))) for d in md_directories
        ]
    assert convert_markdown_tree(tmp_path, md_directories, to_absolute=True) == counts
    after = f'<img src="{img}">\n' if counts == (1, 1) else f'<img src="{rel}">\n'
    assert md.read_text(encoding="utf-8") == after


def test_counts_accumulate_across_files(tmp_path):
    img = tmp_path / "assets" / "pic.png"
    write(img, "binary")
    chapters = tmp_path / "manuscript" / "chapters"
    for name, tags in (("01.md", 1), ("02.md", 2)):
        rel = os.path.relpath(img, start=chapters)
        write(chapters / name, f'<img src="{rel}">\n' * tags)
    assert convert_markdown_tree(tmp_path, to_absolute=True) == (2, 3)
    for name, tags in (("01.md", 1), ("02.md", 2)):
        assert (chapters / name).read_text(encoding="utf-8") == (
            f'<img src="{img}">\n' * tags
        )


def test_utf8_round_trip_under_c_locale(tmp_path, monkeypatch):
    """The chapter is read and written as UTF-8 whatever the locale: under
    LC_ALL=C the locale codec is ASCII and cannot carry the umlauts."""
    import locale

    saved = locale.setlocale(locale.LC_ALL)
    monkeypatch.setenv("LC_ALL", "C")
    monkeypatch.setenv("LANG", "C")
    locale.setlocale(locale.LC_ALL, "C")
    try:
        md, img = layout(tmp_path)
        rel = os.path.relpath(img, start=md.parent)
        md.parent.mkdir(parents=True, exist_ok=True)
        md.write_bytes(f'Grüße\n<img src="{rel}" alt="Bär">\n'.encode("utf-8"))
        assert convert_markdown_tree(tmp_path, to_absolute=True) == (1, 1)
        after = f'Grüße\n<img src="{img}" alt="Bär">\n'
        assert md.read_bytes().decode("utf-8") == after
    finally:
        locale.setlocale(locale.LC_ALL, saved)


def help_output(monkeypatch, capsys) -> str:
    """The --help page, rendered wide enough that no entry wraps."""
    monkeypatch.setenv("COLUMNS", "200")
    monkeypatch.setattr(sys, "argv", ["convert-img-tags", "--help"])
    assert run_main() == 0
    return capsys.readouterr().out


def option_help_text(help_out: str, flag: str) -> str:
    """The help text argparse attached to the listing entry of ``flag`` (""
    when the entry carries none)."""
    sections = re.split(
        r"^(?:positional arguments|options):$", help_out, maxsplit=1, flags=re.M
    )
    for line in sections[1].splitlines():
        entry = line.strip()
        if entry.startswith(flag):
            parts = re.split(r"\s{2,}", entry, maxsplit=1)
            return parts[1] if len(parts) > 1 else ""
    raise AssertionError(f"{flag} is not listed")


# Each row: an option whose --help entry must carry some help text; what the
# text says is not asserted
OPTIONS_WITH_HELP = [
    pytest.param("--to-absolute", id="to-absolute"),
    pytest.param("--to-relative", id="to-relative"),
    pytest.param("--base-dir", id="base-dir"),
]


@pytest.mark.parametrize("flag", OPTIONS_WITH_HELP)
def test_every_option_has_help_text(flag, monkeypatch, capsys):
    assert option_help_text(help_output(monkeypatch, capsys), flag) != ""


def test_help_has_a_description_paragraph(monkeypatch, capsys):
    out = help_output(monkeypatch, capsys)
    paragraphs = [p.strip() for p in out.split("\n\n") if p.strip()]
    assert not paragraphs[1].startswith(("positional arguments:", "options:"))
