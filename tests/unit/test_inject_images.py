# tests/test_inject_images.py
from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.unit

import manuscripta.images.inject as mod


def _text_file(tmp_path, text: str):
    pf = tmp_path / "prompts.json"
    pf.write_text(text, encoding="utf-8")
    return pf


# ---------- Prompt loading ----------


# Each row: the prompt JSON and the flat prompt list load_prompts returns
LOAD_PROMPTS_CASES = [
    pytest.param(
        {"prompts": [{"filename": "01-intro.png"}]},
        [{"filename": "01-intro.png"}],
        id="flat-ok",
    ),
    pytest.param(
        {"chapters": [{"prompts": [{"filename": "chapter_02-hero.png"}]}]},
        [{"filename": "chapter_02-hero.png"}],
        id="nested-ok",
    ),
    # entries without a filename are dropped
    pytest.param(
        {"prompts": [{"filename": "01.png"}, {"prompt": "x"}]},
        [{"filename": "01.png"}],
        id="drops-entries-without-filename",
    ),
]


@pytest.mark.parametrize("data, expected", LOAD_PROMPTS_CASES)
def test_load_prompts(tmp_path, data, expected):
    pf = _text_file(tmp_path, json.dumps(data))
    assert mod.load_prompts(pf) == expected


# Each row: a builder returning the path to load, the exception raised
LOAD_PROMPTS_ERRORS = [
    pytest.param(lambda d: _text_file(d, "{ invalid"), ValueError, id="invalid-json"),
    pytest.param(lambda d: d / "nope.json", FileNotFoundError, id="missing-file"),
    pytest.param(
        lambda d: _text_file(d, '{"prompts": []}'), ValueError, id="no-prompts"
    ),
]


@pytest.mark.parametrize("make_path, exc", LOAD_PROMPTS_ERRORS)
def test_load_prompts_errors(tmp_path, make_path, exc):
    with pytest.raises(exc):
        mod.load_prompts(make_path(tmp_path))


# ---------- Key extraction & mapping ----------


# Each row: an image filename and the two-digit chapter key it yields
CHAPTER_KEY_CASES = [
    pytest.param("01-intro.png", "01", id="leading-number"),
    pytest.param("chapter_2-cover.png", "02", id="chapter-prefix-padded"),
    pytest.param("03.png", "03", id="number-only"),
    pytest.param("ch-9-foo.png", "09", id="number-after-dash"),
    pytest.param("chapter-07.png", "07", id="chapter-dash-prefix"),
    pytest.param("Chapter_12.png", "12", id="case-insensitive"),
    pytest.param("no-number.png", "", id="no-number"),
]


@pytest.mark.parametrize("name, expected", CHAPTER_KEY_CASES)
def test_chapter_key_from_filename(name, expected):
    assert mod.chapter_key_from_filename(name) == expected


# Each row: the prompt entries and the chapter key → filename map they build
FILENAME_MAP_CASES = [
    pytest.param(
        [{"filename": "01-intro.png"}, {"filename": "chapter_2-cover.png"}],
        {"01": "01-intro.png", "02": "chapter_2-cover.png"},
        id="collects-two-digit-keys",
    ),
    pytest.param(
        [{"filename": "01-a.png"}, {"filename": "01-b.png"}],
        {"01": "01-b.png"},
        id="last-one-wins",
    ),
    pytest.param([{"filename": "no-number.png"}], {}, id="skips-unkeyed-filenames"),
]


@pytest.mark.parametrize("prompts, expected", FILENAME_MAP_CASES)
def test_build_filename_map(prompts, expected):
    assert mod.build_filename_map(prompts) == expected


# ---------- Injection detection & placement ----------


# Each row: the chapter content, the image filename, whether a link to it
# is already present
LINK_PRESENT_CASES = [
    pytest.param(
        "Intro\n\n![alt](../../assets/illustrations/01-intro.png)\n",
        "01-intro.png",
        True,
        id="detects-by-basename",
    ),
    pytest.param("![a](01-intro.png)", "01-intro.png", True, id="without-directory"),
    pytest.param("![a](img/01-INTRO.PNG)", "01-intro.png", True, id="case-insensitive"),
    pytest.param("![alt](x/02-intro.png)", "01-intro.png", False, id="other-basename"),
    pytest.param("Intro\n", "01-intro.png", False, id="no-image"),
]


@pytest.mark.parametrize("content, filename, expected", LINK_PRESENT_CASES)
def test_link_already_present(content, filename, expected):
    assert mod.link_already_present(content, filename) is expected


def test_inject_image_after_h1_and_not_duplicate(tmp_path):
    md = "# Title\n\nSome text.\n"
    rel = "assets/illustrations/01-intro.png"
    new, injected = mod.inject_image(md, rel)
    assert injected is True
    # now re-run should not inject again
    newer, injected2 = mod.inject_image(new, rel)
    assert injected2 is False
    assert new.count("![") == 1


def test_inject_image_at_top_when_no_h1():
    md = "First line\nSecond line\n"
    rel = "assets/illustrations/x.png"
    new, injected = mod.inject_image(md, rel, alt_text="An image")
    assert injected is True
    assert new.splitlines()[0].startswith("![")


def test_compute_relative_path(tmp_path):
    ch = tmp_path / "manuscript" / "chapters"
    img = tmp_path / "assets" / "illustrations"
    ch.mkdir(parents=True)
    img.mkdir(parents=True)
    chapter = ch / "01-intro.md"
    chapter.write_text("# T\n", encoding="utf-8")
    image = img / "01-intro.png"
    image.write_bytes(b"x")
    rel = mod.compute_relative_image_path(chapter, image)
    # from manuscript/chapters to assets/illustrations
    assert rel.replace("\\", "/").endswith("assets/illustrations/01-intro.png")


# ---------- End-to-end process ----------


def _mk_tree(tmp_path):
    ch_dir = tmp_path / "manuscript" / "chapters"
    img_dir = tmp_path / "assets" / "illustrations"
    ch_dir.mkdir(parents=True)
    img_dir.mkdir(parents=True)
    return ch_dir, img_dir


# Each row: the chapters (name → text), the images present, the prompt JSON,
# dry_run, the Stats process returns, lines the report must print, the image
# line each chapter must carry afterwards; a chapter not listed there must be
# unchanged
PROCESS_CASES = [
    pytest.param(
        {"01-intro.md": "# Intro\n\nText\n", "02-next.md": "# Next\n\nText\n"},
        ["01-intro.png", "chapter_02-hero.png"],
        {
            "chapters": [
                {
                    "prompts": [
                        {"filename": "01-intro.png"},
                        {"filename": "chapter_02-hero.png"},
                    ]
                }
            ]
        },
        False,
        mod.Stats(total=2, injected=2),
        ["Image injected into: 01-intro.md", "Image injected into: 02-next.md"],
        {
            "01-intro.md": "![01-intro](../../assets/illustrations/01-intro.png)",
            "02-next.md": (
                "![chapter_02-hero](../../assets/illustrations/chapter_02-hero.png)"
            ),
        },
        id="injects-when-available",
    ),
    pytest.param(
        {"01-intro.md": "# Intro\n\n![x](../../assets/illustrations/01-intro.png)\n"},
        ["01-intro.png"],
        {"prompts": [{"filename": "01-intro.png"}]},
        False,
        mod.Stats(total=1, skipped_existing=1),
        ["Already contains image"],
        {},
        id="skips-if-already-present",
    ),
    # only one prompt, for chapter 01, and its image file is missing;
    # chapter 03 has no prompt at all
    pytest.param(
        {"01-intro.md": "# Intro\n", "03-other.md": "# Other\n"},
        [],
        {"prompts": [{"filename": "01-intro.png"}]},
        False,
        mod.Stats(total=2, missing_prompt=1, missing_image=1),
        ["No image defined", "Image not found"],
        {},
        id="counts-missing-prompt-and-image",
    ),
    pytest.param(
        {"01-intro.md": "# Intro\n\nPara\n"},
        ["01-intro.png"],
        {"prompts": [{"filename": "01-intro.png"}]},
        True,
        mod.Stats(total=1, injected=1),
        ["Dry-run: would inject"],
        {},
        id="dry-run-does-not-write",
    ),
]


@pytest.mark.parametrize(
    "chapters, images, prompts, dry_run, stats, lines, injected", PROCESS_CASES
)
def test_process(
    tmp_path, capsys, chapters, images, prompts, dry_run, stats, lines, injected
):
    ch_dir, img_dir = _mk_tree(tmp_path)
    for name, text in chapters.items():
        (ch_dir / name).write_text(text, encoding="utf-8")
    for name in images:
        (img_dir / name).write_bytes(b"a")
    pf = _text_file(tmp_path, json.dumps(prompts))

    assert mod.process(ch_dir, img_dir, pf, dry_run=dry_run) == stats
    out = capsys.readouterr().out
    for line in lines:
        assert line in out
    for name, text in chapters.items():
        content = (ch_dir / name).read_text(encoding="utf-8")
        if name in injected:
            assert injected[name] in content
        else:
            assert content == text
