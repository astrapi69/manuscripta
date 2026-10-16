"""Direct unit tests for manuscripta.paths.to_relative.

The existing test_convert_to_relative.py loads the module via importlib
relative to the repo checkout, bypassing the installed package. This
file imports the installed module normally and asserts on outputs.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

from manuscripta.paths import to_relative as mod


def _layout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """assets/ and manuscript/chapters/ under tmp_path, the module's
    ASSETS_DIR pointed at the former."""
    assets = tmp_path / "assets"
    md_dir = tmp_path / "manuscript" / "chapters"
    assets.mkdir(parents=True)
    md_dir.mkdir(parents=True)
    monkeypatch.setattr(mod, "ASSETS_DIR", assets)
    return assets, md_dir


# Helpers ------------------------------------------------------------------

# Each row: the raw target and the (text, had_angles) pair _strip_angles returns
STRIP_ANGLES_CASES = [
    pytest.param("<foo>", ("foo", True), id="removes-pair"),
    pytest.param("foo", ("foo", False), id="leaves-unbracketed"),
    # Brackets are stripped only as a matched pair.
    pytest.param("<foo", ("<foo", False), id="leaves-one-sided-open"),
    pytest.param("foo>", ("foo>", False), id="leaves-one-sided-close"),
]

# Each row: the target and whether _is_absolute_path accepts it
IS_ABSOLUTE_PATH_CASES = [
    pytest.param("/abs/path", True, id="true-for-abs"),
    pytest.param("rel/path", False, id="false-for-rel"),
    # An empty string is neither absolute nor starting with "/".
    pytest.param("", False, id="false-for-empty"),
]

# Each row: the target and whether _is_url_or_anchor treats it as one
IS_URL_OR_ANCHOR_CASES = [
    pytest.param("", True, id="detects-empty"),
    pytest.param("#anchor", True, id="detects-anchor"),
    pytest.param("http://e.com", True, id="detects-scheme-http"),
    pytest.param("mailto:a@b", True, id="detects-scheme-mailto"),
    pytest.param("data:abc", True, id="detects-scheme-data"),
    pytest.param("rel/path", False, id="rejects-plain-relative-path"),
    pytest.param("/abs/path", False, id="rejects-plain-absolute-path"),
    pytest.param("file.png", False, id="rejects-plain-file-name"),
]


@pytest.mark.parametrize("raw, expected", STRIP_ANGLES_CASES)
def test_strip_angles(raw, expected):
    assert mod._strip_angles(raw) == expected


@pytest.mark.parametrize("target, expected", IS_ABSOLUTE_PATH_CASES)
def test_is_absolute_path(target, expected):
    assert mod._is_absolute_path(target) is expected


@pytest.mark.parametrize("target, expected", IS_URL_OR_ANCHOR_CASES)
def test_is_url_or_anchor(target, expected):
    assert mod._is_url_or_anchor(target) is expected


# convert_target_to_relative ----------------------------------------------

# Each row: the raw target and what comes back for the chapter directory
# manuscript/chapters. {img} is the absolute path of assets/pic.png,
# {outside} that of elsewhere/pic.png.
CONVERT_TARGET_CASES = [
    pytest.param(
        "{img}", "../../assets/pic.png", id="converts-absolute-path-inside-assets"
    ),
    pytest.param("<{img}>", "<../../assets/pic.png>", id="preserves-angle-brackets"),
    pytest.param("http://example.com", "http://example.com", id="leaves-url-untouched"),
    pytest.param("#intro", "#intro", id="leaves-anchor-untouched"),
    pytest.param(
        "images/foo.png", "images/foo.png", id="leaves-relative-path-untouched"
    ),
    pytest.param(
        "{outside}", "{outside}", id="leaves-absolute-path-outside-assets-untouched"
    ),
]


@pytest.mark.parametrize("target, expected", CONVERT_TARGET_CASES)
def test_convert_target_to_relative(target, expected, tmp_path, monkeypatch):
    assets, md_dir = _layout(tmp_path, monkeypatch)
    img = assets / "pic.png"
    img.write_bytes(b"\x89PNG")
    outside = tmp_path / "elsewhere" / "pic.png"
    outside.parent.mkdir()
    outside.write_bytes(b"\x89PNG")
    fields = {"img": img, "outside": outside}

    result = mod.convert_target_to_relative(target.format(**fields), md_dir)
    assert result == expected.format(**fields)


# convert_paths_in_text ----------------------------------------------------

# Each row: the text of the chapter manuscript/chapters/ch1.md and its
# conversion. {img} is the absolute path of assets/pic.png.
CONVERT_PATHS_IN_TEXT_CASES = [
    pytest.param(
        "![alt]({img})", "![alt](../../assets/pic.png)", id="handles-markdown-image"
    ),
    pytest.param(
        '<img src="{img}"/> <a href="{img}">l</a>',
        '<img src="../../assets/pic.png"/> <a href="../../assets/pic.png">l</a>',
        id="handles-html-img-and-a",
    ),
    pytest.param(
        "[text]({img})", "[text](../../assets/pic.png)", id="handles-markdown-link"
    ),
]


@pytest.mark.parametrize("text, expected", CONVERT_PATHS_IN_TEXT_CASES)
def test_convert_paths_in_text(text, expected, tmp_path, monkeypatch):
    assets, md_dir = _layout(tmp_path, monkeypatch)
    img = assets / "pic.png"
    img.write_bytes(b"\x89")

    md = md_dir / "ch1.md"
    assert mod.convert_paths_in_text(text.format(img=img), md) == expected


# process_md_file ----------------------------------------------------------

# Each row: the text of the chapter manuscript/chapters/ch1.md, whether
# process_md_file reports a change and the text afterwards. {img} is the
# absolute path of assets/pic.png.
PROCESS_MD_FILE_CASES = [
    pytest.param(
        "![alt]({img})\n",
        True,
        "![alt](../../assets/pic.png)\n",
        id="rewrites-when-changed",
    ),
    pytest.param(
        "![alt](relative/path.png)\n",
        False,
        "![alt](relative/path.png)\n",
        id="no-change-returns-false",
    ),
]


@pytest.mark.parametrize("text, changed, after", PROCESS_MD_FILE_CASES)
def test_process_md_file(text, changed, after, tmp_path, monkeypatch, capsys):
    assets, md_dir = _layout(tmp_path, monkeypatch)
    img = assets / "pic.png"
    img.write_bytes(b"\x89")

    md = md_dir / "ch1.md"
    md.write_text(text.format(img=img), encoding="utf-8")

    assert mod.process_md_file(md) is changed
    assert md.read_text(encoding="utf-8") == after


# main --------------------------------------------------------------------

# Each row: the chapters to write into manuscript/chapters (name → text), the
# directories main walks (under tmp_path) and the count the summary line
# reports. {img} is the absolute path of assets/pic.png.
MAIN_CASES = [
    # Build a fake project layout; point module globals at tmp_path.
    pytest.param(
        {"ch1.md": "![x]({img})\n", "ch2.md": "![y](rel.png)\n"},
        ["manuscript/chapters"],
        1,
        id="iterates-and-reports-count",
    ),
    pytest.param({}, ["does-not-exist"], 0, id="skips-nonexistent-dirs"),
]


@pytest.mark.parametrize("chapters, directories, updated", MAIN_CASES)
def test_main(chapters, directories, updated, tmp_path, monkeypatch, capsys):
    assets, md_dir = _layout(tmp_path, monkeypatch)
    img = assets / "pic.png"
    img.write_bytes(b"\x89")
    for name, text in chapters.items():
        (md_dir / name).write_text(text.format(img=img), encoding="utf-8")
    monkeypatch.setattr(mod, "MD_DIRECTORIES", [tmp_path / d for d in directories])

    mod.main()
    assert f"Files updated: {updated}" in capsys.readouterr().out
