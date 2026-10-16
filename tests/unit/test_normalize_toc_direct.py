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

# Each row: the text and what strip_to_anchors makes of it
STRIP_TO_ANCHORS_CASES = [
    pytest.param(
        "(chapters/01.md#intro)", "(#intro)", id="converts-md-links-to-anchors"
    ),
    pytest.param("(chapters/01.gfm#intro)", "(#intro)", id="converts-gfm-links"),
    pytest.param(
        "(chapters/01.markdown#intro)", "(#intro)", id="converts-markdown-ext"
    ),
    pytest.param("(#intro)", "(#intro)", id="preserves-anchor-only-links"),
    pytest.param(
        "(http://example.com/page)",
        "(http://example.com/page)",
        id="leaves-plain-urls-alone",
    ),
    pytest.param("(front-matter/sub/toc.md#x)", "(#x)", id="handles-nested-paths"),
    pytest.param(
        "[a](c/01.md#a) and [b](c/02.md#b)",
        "[a](#a) and [b](#b)",
        id="handles-multiple-in-one-string",
    ),
    # Prose containing words that look like an ext should not be rewritten.
    pytest.param(
        "the file name.md is here",
        "the file name.md is here",
        id="leaves-non-link-dots-alone",
    ),
]


@pytest.mark.parametrize("text, expected", STRIP_TO_ANCHORS_CASES)
def test_strip_to_anchors(text, expected):
    assert strip_to_anchors(text) == expected


# replace_extension -------------------------------------------------------
#
# ⚠ Behavioral ambiguity (see Step 2 report §Behavioral ambiguity discovered):
# the docstring promises "Ersetzt Vorkommen von .gfm/.markdown/.md in Link-
# Zielen" (i.e. any link extension → target ext). The implementation's inner
# regex uses a lookahead `(?=(?:\)|#))` but runs on group(1) of the outer
# `\(([^)]+)\)` capture, which strips the trailing `)`. Consequence:
# extension rewriting only fires when the URL is followed by an anchor `#…`,
# never at a bare end-of-URL. Rows below pin the ACTUAL behaviour; the
# docstring-contract rows are xfail pending triage.

# Each row: the text, the target extension and what replace_extension returns
REPLACE_EXTENSION_CASES = [
    pytest.param(
        "(chapters/01.md#x)", "gfm", "(chapters/01.gfm#x)", id="swaps-before-anchor"
    ),
    pytest.param("(a.png)", "md", "(a.png)", id="leaves-non-matching-extensions"),
    pytest.param(
        "foo.md is a file",
        "gfm",
        "foo.md is a file",
        id="only-affects-link-urls-not-prose",
    ),
    # Actual behaviour — pins the ambiguity observed. Do not "fix" this
    # row without also fixing the module and the docstring together.
    pytest.param(
        "(chapters/01.md)",
        "gfm",
        "(chapters/01.md)",
        id="does-not-touch-bare-url-without-anchor",
    ),
    pytest.param(
        "(chapters/01.md)",
        "gfm",
        "(chapters/01.gfm)",
        marks=pytest.mark.xfail(
            reason="docstring promises extension rewrite without anchor; actual "
            "implementation requires a trailing anchor (see §Behavioral ambiguity)"
        ),
        id="should-swap-bare-url-per-docstring",
    ),
    pytest.param(
        "(a.markdown)",
        "gfm",
        "(a.gfm)",
        marks=pytest.mark.xfail(
            reason="same underlying ambiguity — bare .markdown URL not rewritten"
        ),
        id="should-handle-markdown-ext-per-docstring",
    ),
]


@pytest.mark.parametrize("text, ext, expected", REPLACE_EXTENSION_CASES)
def test_replace_extension(text, ext, expected):
    assert replace_extension(text, ext) == expected


# main -------------------------------------------------------------------

# Each row: the TOC text (None: no file), the arguments after ``--toc <path>``,
# the text afterwards (None: no file) and a fragment of the summary line
MAIN_CASES = [
    pytest.param(
        "- [Ch1](chapters/01.md#intro)\n",
        ["--mode", "strip-to-anchors"],
        "- [Ch1](#intro)\n",
        "✅ TOC normalized",
        id="strip-to-anchors-rewrites-file",
    ),
    # Must include anchor — see §Behavioral ambiguity above.
    pytest.param(
        "[Ch1](chapters/01.md#intro)\n",
        ["--mode", "replace-ext", "--ext", "gfm"],
        "[Ch1](chapters/01.gfm#intro)\n",
        "✅ TOC normalized",
        id="replace-extension-rewrites-file",
    ),
    # main() must not raise
    pytest.param(None, [], None, "TOC not found", id="missing-toc-warns-and-returns"),
    pytest.param(
        "- [Ch1](#intro)\n",
        ["--mode", "strip-to-anchors"],
        "- [Ch1](#intro)\n",
        "unchanged",
        id="no-change-when-already-normalized",
    ),
]


@pytest.mark.parametrize("text, argv, after, note", MAIN_CASES)
def test_main(text, argv, after, note, tmp_path, monkeypatch, capsys):
    toc = tmp_path / "toc.md"
    if text is not None:
        toc.write_text(text, encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["normalize_toc", "--toc", str(toc), *argv])
    main()
    assert (toc.read_text(encoding="utf-8") if toc.exists() else None) == after
    assert note in capsys.readouterr().out
