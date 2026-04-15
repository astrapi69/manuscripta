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


# Helpers ------------------------------------------------------------------


def test_strip_angles_removes_pair():
    text, had = mod._strip_angles("<foo>")
    assert (text, had) == ("foo", True)


def test_strip_angles_leaves_unbracketed():
    text, had = mod._strip_angles("foo")
    assert (text, had) == ("foo", False)


def test_is_absolute_path_true_for_abs():
    assert mod._is_absolute_path("/abs/path") is True


def test_is_absolute_path_false_for_rel():
    assert mod._is_absolute_path("rel/path") is False


def test_is_absolute_path_false_for_empty():
    # An empty string is neither absolute nor starting with "/".
    assert mod._is_absolute_path("") is False


@pytest.mark.parametrize(
    "target", ["", "#anchor", "http://e.com", "mailto:a@b", "data:abc"]
)
def test_is_url_or_anchor_detects_scheme_and_anchor(target):
    assert mod._is_url_or_anchor(target) is True


@pytest.mark.parametrize("target", ["rel/path", "/abs/path", "file.png"])
def test_is_url_or_anchor_rejects_plain_paths(target):
    assert mod._is_url_or_anchor(target) is False


# convert_target_to_relative ----------------------------------------------


def test_converts_absolute_path_inside_assets(tmp_path, monkeypatch):
    assets = tmp_path / "assets"
    md_dir = tmp_path / "manuscript" / "chapters"
    assets.mkdir(parents=True)
    md_dir.mkdir(parents=True)
    img = assets / "pic.png"
    img.write_bytes(b"\x89PNG")

    monkeypatch.setattr(mod, "ASSETS_DIR", assets)

    rel = mod.convert_target_to_relative(str(img), md_dir)
    assert rel == "../../assets/pic.png"


def test_preserves_angle_brackets(tmp_path, monkeypatch):
    assets = tmp_path / "assets"
    md_dir = tmp_path / "manuscript" / "chapters"
    assets.mkdir(parents=True)
    md_dir.mkdir(parents=True)
    img = assets / "pic.png"
    img.write_bytes(b"\x89PNG")
    monkeypatch.setattr(mod, "ASSETS_DIR", assets)

    out = mod.convert_target_to_relative(f"<{img}>", md_dir)
    assert out.startswith("<") and out.endswith(">")
    assert "../../assets/pic.png" in out


def test_leaves_url_untouched():
    result = mod.convert_target_to_relative("http://example.com", Path("/any"))
    assert result == "http://example.com"


def test_leaves_anchor_untouched():
    result = mod.convert_target_to_relative("#intro", Path("/any"))
    assert result == "#intro"


def test_leaves_relative_path_untouched():
    result = mod.convert_target_to_relative("images/foo.png", Path("/any"))
    assert result == "images/foo.png"


def test_leaves_absolute_path_outside_assets_untouched(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "ASSETS_DIR", tmp_path / "assets")
    (tmp_path / "assets").mkdir()
    outside = tmp_path / "elsewhere" / "pic.png"
    outside.parent.mkdir()
    outside.write_bytes(b"\x89PNG")
    result = mod.convert_target_to_relative(str(outside), tmp_path / "manuscript")
    assert result == str(outside)


# convert_paths_in_text ----------------------------------------------------


def test_convert_paths_in_text_handles_markdown_image(tmp_path, monkeypatch):
    assets = tmp_path / "assets"
    md_dir = tmp_path / "manuscript" / "chapters"
    assets.mkdir(parents=True)
    md_dir.mkdir(parents=True)
    img = assets / "pic.png"
    img.write_bytes(b"\x89")
    monkeypatch.setattr(mod, "ASSETS_DIR", assets)

    md = md_dir / "ch1.md"
    text = f"![alt]({img})"
    out = mod.convert_paths_in_text(text, md)
    assert out == "![alt](../../assets/pic.png)"


def test_convert_paths_in_text_handles_html_img_and_a(tmp_path, monkeypatch):
    assets = tmp_path / "assets"
    md_dir = tmp_path / "manuscript" / "chapters"
    assets.mkdir(parents=True)
    md_dir.mkdir(parents=True)
    img = assets / "pic.png"
    img.write_bytes(b"\x89")
    monkeypatch.setattr(mod, "ASSETS_DIR", assets)

    md = md_dir / "ch1.md"
    text = f'<img src="{img}"/> <a href="{img}">l</a>'
    out = mod.convert_paths_in_text(text, md)
    assert out.count("../../assets/pic.png") == 2
    assert str(img) not in out


# process_md_file ----------------------------------------------------------


def test_process_md_file_rewrites_when_changed(tmp_path, monkeypatch, capsys):
    assets = tmp_path / "assets"
    md_dir = tmp_path / "manuscript" / "chapters"
    assets.mkdir(parents=True)
    md_dir.mkdir(parents=True)
    img = assets / "pic.png"
    img.write_bytes(b"\x89")
    monkeypatch.setattr(mod, "ASSETS_DIR", assets)

    md = md_dir / "ch1.md"
    md.write_text(f"![alt]({img})\n", encoding="utf-8")

    changed = mod.process_md_file(md)
    assert changed is True
    assert md.read_text(encoding="utf-8").strip() == "![alt](../../assets/pic.png)"


def test_process_md_file_no_change_returns_false(tmp_path, monkeypatch):
    assets = tmp_path / "assets"
    md_dir = tmp_path / "manuscript" / "chapters"
    assets.mkdir(parents=True)
    md_dir.mkdir(parents=True)
    monkeypatch.setattr(mod, "ASSETS_DIR", assets)

    md = md_dir / "ch1.md"
    md.write_text("![alt](relative/path.png)\n", encoding="utf-8")
    assert mod.process_md_file(md) is False


# main --------------------------------------------------------------------


def test_main_iterates_and_reports_count(tmp_path, monkeypatch, capsys):
    # Build a fake project layout; point module globals at tmp_path.
    chapters = tmp_path / "manuscript" / "chapters"
    assets = tmp_path / "assets"
    chapters.mkdir(parents=True)
    assets.mkdir(parents=True)
    img = assets / "pic.png"
    img.write_bytes(b"\x89")

    monkeypatch.setattr(mod, "ASSETS_DIR", assets)
    monkeypatch.setattr(mod, "MD_DIRECTORIES", [chapters])

    (chapters / "ch1.md").write_text(f"![x]({img})\n", encoding="utf-8")
    (chapters / "ch2.md").write_text("![y](rel.png)\n", encoding="utf-8")

    mod.main()
    out = capsys.readouterr().out
    assert "Files updated: 1" in out


def test_main_skips_nonexistent_dirs(tmp_path, monkeypatch, capsys):
    missing = tmp_path / "does-not-exist"
    monkeypatch.setattr(mod, "MD_DIRECTORIES", [missing])
    mod.main()
    out = capsys.readouterr().out
    assert "Files updated: 0" in out
