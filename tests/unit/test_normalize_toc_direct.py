"""Direct unit tests for manuscripta.markdown.normalize_toc.

The existing test_normalize_toc_links.py invokes the module via subprocess,
which doesn't count toward coverage of the module itself. This file calls
the functions directly and asserts on outputs, not on whether they ran.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

from manuscripta.markdown.normalize_toc import (
    main,
    replace_extension,
    strip_to_anchors,
)


# strip_to_anchors --------------------------------------------------------


def test_strip_to_anchors_converts_md_links_to_anchors():
    assert strip_to_anchors("(chapters/01.md#intro)") == "(#intro)"


def test_strip_to_anchors_converts_gfm_links():
    assert strip_to_anchors("(chapters/01.gfm#intro)") == "(#intro)"


def test_strip_to_anchors_converts_markdown_ext():
    assert strip_to_anchors("(chapters/01.markdown#intro)") == "(#intro)"


def test_strip_to_anchors_preserves_anchor_only_links():
    assert strip_to_anchors("(#intro)") == "(#intro)"


def test_strip_to_anchors_leaves_plain_urls_alone():
    assert strip_to_anchors("(http://example.com/page)") == "(http://example.com/page)"


def test_strip_to_anchors_handles_nested_paths():
    assert strip_to_anchors("(front-matter/sub/toc.md#x)") == "(#x)"


def test_strip_to_anchors_handles_multiple_in_one_string():
    s = "[a](c/01.md#a) and [b](c/02.md#b)"
    assert strip_to_anchors(s) == "[a](#a) and [b](#b)"


def test_strip_to_anchors_leaves_non_link_dots_alone():
    # Prose containing words that look like an ext should not be rewritten.
    assert strip_to_anchors("the file name.md is here") == "the file name.md is here"


# replace_extension -------------------------------------------------------
#
# ⚠ Behavioral ambiguity (see Step 2 report §Behavioral ambiguity discovered):
# the docstring promises "Ersetzt Vorkommen von .gfm/.markdown/.md in Link-
# Zielen" (i.e. any link extension → target ext). The implementation's inner
# regex uses a lookahead `(?=(?:\)|#))` but runs on group(1) of the outer
# `\(([^)]+)\)` capture, which strips the trailing `)`. Consequence:
# extension rewriting only fires when the URL is followed by an anchor `#…`,
# never at a bare end-of-URL. Tests below pin the ACTUAL behaviour; the
# docstring-contract tests are xfail pending triage.


def test_replace_extension_swaps_before_anchor():
    assert replace_extension("(chapters/01.md#x)", "gfm") == "(chapters/01.gfm#x)"


def test_replace_extension_leaves_non_matching_extensions():
    assert replace_extension("(a.png)", "md") == "(a.png)"


def test_replace_extension_only_affects_link_urls_not_prose():
    assert replace_extension("foo.md is a file", "gfm") == "foo.md is a file"


def test_replace_extension_does_not_touch_bare_url_without_anchor():
    # Actual behaviour — pins the ambiguity observed. Do not "fix" this
    # test without also fixing the module and the docstring together.
    assert replace_extension("(chapters/01.md)", "gfm") == "(chapters/01.md)"


@pytest.mark.xfail(
    reason="docstring promises extension rewrite without anchor; actual "
    "implementation requires a trailing anchor (see §Behavioral ambiguity)"
)
def test_replace_extension_should_swap_bare_url_per_docstring():
    assert replace_extension("(chapters/01.md)", "gfm") == "(chapters/01.gfm)"


@pytest.mark.xfail(
    reason="same underlying ambiguity — bare .markdown URL not rewritten"
)
def test_replace_extension_should_handle_markdown_ext_per_docstring():
    assert replace_extension("(a.markdown)", "gfm") == "(a.gfm)"


# main -------------------------------------------------------------------


def test_main_strip_to_anchors_rewrites_file(tmp_path, monkeypatch, capsys):
    toc = tmp_path / "toc.md"
    toc.write_text("- [Ch1](chapters/01.md#intro)\n", encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        ["normalize_toc", "--toc", str(toc), "--mode", "strip-to-anchors"],
    )
    main()
    assert toc.read_text(encoding="utf-8") == "- [Ch1](#intro)\n"
    out = capsys.readouterr().out
    assert "✅ TOC normalized" in out


def test_main_replace_extension_rewrites_file(tmp_path, monkeypatch, capsys):
    toc = tmp_path / "toc.md"
    # Must include anchor — see §Behavioral ambiguity above.
    toc.write_text("[Ch1](chapters/01.md#intro)\n", encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        ["normalize_toc", "--toc", str(toc), "--mode", "replace-ext", "--ext", "gfm"],
    )
    main()
    assert toc.read_text(encoding="utf-8") == "[Ch1](chapters/01.gfm#intro)\n"


def test_main_missing_toc_warns_and_returns(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        "sys.argv",
        ["normalize_toc", "--toc", str(tmp_path / "does-not-exist.md")],
    )
    main()  # must not raise
    out = capsys.readouterr().out
    assert "TOC not found" in out


def test_main_no_change_when_already_normalized(tmp_path, monkeypatch, capsys):
    toc = tmp_path / "toc.md"
    content = "- [Ch1](#intro)\n"
    toc.write_text(content, encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        ["normalize_toc", "--toc", str(toc), "--mode", "strip-to-anchors"],
    )
    main()
    assert toc.read_text(encoding="utf-8") == content  # unchanged
    assert "unchanged" in capsys.readouterr().out
