"""Phase 4b Pass 2 Commit 12 — mutation-response tests for
``manuscripta.markdown.normalize_toc``.

All 38 baseline survivors sit in ``main()`` — the argparse surface and
the file round-trip. The §14.8.1 boundary drives the split:

- Help/description **wording** (case changes, ``XX…XX`` wrapping) is
  incidental → B, annotated in ``.mutmut/equivalent.yaml``.
- Help/description **presence**, defaulted **values**, and ``choices``
  validation are parser behaviour → A, killed here. The presence
  assertions deliberately check only that *some* help text is attached
  to each flag, never its wording — pinning wording is the
  invited-dependency anti-pattern §14.8.1 exists to prevent.
"""

from __future__ import annotations

import re

import pytest

pytestmark = pytest.mark.unit

from manuscripta.markdown.normalize_toc import main


def run_main(monkeypatch, argv):
    monkeypatch.setattr("sys.argv", ["normalize_toc", *argv])
    main()


def help_output(monkeypatch, capsys) -> str:
    monkeypatch.setattr("sys.argv", ["normalize_toc", "--help"])
    with pytest.raises(SystemExit):
        main()
    return capsys.readouterr().out


def option_help_text(help_out: str, flag: str) -> str:
    """Return the help text argparse attached to ``flag``, joining
    wrapped continuation lines; empty string if the entry has none."""
    lines = help_out.splitlines()
    collected: list[str] = []
    started = False
    for ln in lines:
        s = ln.strip()
        if s.startswith(flag):
            started = True
            parts = re.split(r"\s{2,}", s, maxsplit=1)
            if len(parts) > 1:
                collected.append(parts[1])
            continue
        if started:
            if not s or s.startswith("-") or s.endswith(":"):
                break
            collected.append(s)
    return " ".join(collected).strip()


class TestHelpSurfacePresence:
    def test_every_option_has_help_text(self, monkeypatch, capsys):
        """§14.8.1: dropping a ``help=`` kwarg (or nulling it) removes
        a line from ``--help`` — observable presence, A-category. The
        assertion checks presence only, not wording.

        Kills main __mutmut_8/11 (``--toc`` help None/dropped),
        __mutmut_22/26 (``--mode``), __mutmut_40/43 (``--ext``).
        """
        out = help_output(monkeypatch, capsys)
        for flag in ("--toc", "--mode", "--ext"):
            assert option_help_text(out, flag) != ""

    def test_parser_has_description_paragraph(self, monkeypatch, capsys):
        """The CLI carries a description paragraph between the usage
        block and the options listing; ``description=None`` removes it.

        Kills main __mutmut_2.
        """
        out = help_output(monkeypatch, capsys)
        chunks = [c.strip() for c in out.split("\n\n") if c.strip()]
        prose = [
            c
            for c in chunks
            if not c.startswith("usage:")
            and not c.startswith("options:")
            and not c.startswith("positional")
        ]
        assert prose


class TestDefaultedValuesAreBehaviour:
    def test_default_toc_path_is_the_manuscript_layout(
        self, tmp_path, monkeypatch, capsys
    ):
        """Invoked without ``--toc``, the tool must look for the
        documented manuscript layout path — and report it gracefully
        when absent (docstring of the missing-file branch).

        Kills main __mutmut_7/10 (default None/dropped →
        ``Path(None)`` TypeError) and __mutmut_14/15 (default path
        literal rewritten → a different path is reported). The path is
        extracted and compared exactly — a substring check would also
        match an ``XX…XX``-wrapped rewrite of the default.
        """
        monkeypatch.chdir(tmp_path)
        run_main(monkeypatch, [])
        out = capsys.readouterr().out
        m = re.search(r"TOC not found: (\S+)", out)
        assert m is not None
        assert m.group(1) == "manuscript/front-matter/toc.md"

    def test_default_mode_is_strip_to_anchors(self, tmp_path, monkeypatch, capsys):
        """Invoked without ``--mode``, the tool strips file links to
        pure anchors — the documented default behaviour.

        Kills main __mutmut_21/25 (default None/dropped → the
        strip-to-anchors comparison fails and the replace-ext branch
        runs) and __mutmut_33/34 (default literal rewritten — argparse
        validates string defaults against ``choices``, so the run
        errors out instead of normalizing).
        """
        toc = tmp_path / "toc.md"
        toc.write_text("- [Ch1](chapters/01.md#intro)\n", encoding="utf-8")
        run_main(monkeypatch, ["--toc", str(toc)])
        assert toc.read_text(encoding="utf-8") == "- [Ch1](#intro)\n"
        assert "TOC normalized" in capsys.readouterr().out

    def test_default_ext_is_md(self, tmp_path, monkeypatch, capsys):
        """``--mode replace-ext`` without ``--ext`` targets ``.md`` —
        a ``.md`` link is already normalized and the file must stay
        byte-identical.

        Kills main __mutmut_39/42 (default None/dropped → links
        rewritten to ``.None``) and __mutmut_46/47 (default literal
        rewritten → links rewritten to ``.XXmdXX`` / ``.MD``).
        """
        toc = tmp_path / "toc.md"
        content = "[Ch1](chapters/01.md#intro)\n"
        toc.write_text(content, encoding="utf-8")
        run_main(monkeypatch, ["--toc", str(toc), "--mode", "replace-ext"])
        assert toc.read_text(encoding="utf-8") == content
        assert "unchanged" in capsys.readouterr().out

    def test_invalid_mode_is_rejected(self, tmp_path, monkeypatch, capsys):
        """``choices`` is a validation contract: an unknown mode must
        error out, not silently fall into an arbitrary branch.

        Kills main __mutmut_20/24 (choices None/dropped → any string
        accepted and the else-branch runs replace_extension).
        """
        toc = tmp_path / "toc.md"
        toc.write_text("[Ch1](chapters/01.md#intro)\n", encoding="utf-8")
        monkeypatch.setattr(
            "sys.argv",
            ["normalize_toc", "--toc", str(toc), "--mode", "bogus"],
        )
        with pytest.raises(SystemExit):
            main()


class TestFileEncodingContract:
    def test_utf8_roundtrip_under_c_locale(self, tmp_path, monkeypatch, capsys):
        """Pins ``encoding="utf-8"`` on the TOC read and write
        explicitly — same locale-pin pattern as Commits 9/10/11.

        Kills main __mutmut_57 (read ``encoding=None``), __mutmut_72
        (write ``encoding=None``) and __mutmut_74 (write encoding
        kwarg dropped).
        """
        import locale as _locale

        saved = _locale.setlocale(_locale.LC_ALL)
        monkeypatch.setenv("LC_ALL", "C")
        monkeypatch.setenv("LANG", "C")
        _locale.setlocale(_locale.LC_ALL, "C")
        try:
            toc = tmp_path / "toc.md"
            toc.write_bytes("- [Grüße](chapters/01.md#grüße)\n".encode("utf-8"))
            run_main(monkeypatch, ["--toc", str(toc)])
            out = toc.read_bytes().decode("utf-8")
            assert out == "- [Grüße](#grüße)\n"
        finally:
            _locale.setlocale(_locale.LC_ALL, saved)
