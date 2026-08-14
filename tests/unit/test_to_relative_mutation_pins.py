"""Phase 4b Pass 2 Commit 11 — mutation-response tests for
``manuscripta.paths.to_relative``.

Same discipline as Commit 10 (see
tests/unit/test_convert_to_absolute_mutation_pins.py): every test
cites the mutant(s) it kills and asserts behaviour traceable to the
module's documented contract — absolute paths inside the assets
directory are rewritten relative, everything else is returned
verbatim. Full-output equality closes the substring-assertion gaps
that let the html-prefix mutant survive.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

from pathlib import Path

from manuscripta.paths import to_relative as mod


def _layout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    assets = tmp_path / "assets"
    md_dir = tmp_path / "manuscript" / "chapters"
    assets.mkdir(parents=True)
    md_dir.mkdir(parents=True)
    monkeypatch.setattr(mod, "ASSETS_DIR", assets)
    return assets, md_dir


class TestStripAnglesPairContract:
    def test_one_sided_angle_open_is_not_stripped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Angle brackets are stripped only as a matched pair. A target
        that begins with ``<`` but does not end with ``>`` must pass
        through verbatim — stripping would chop the first and last
        characters of a real path.

        Kills _strip_angles __mutmut_5 (``and`` → ``or``: the one-sided
        match strips ``<`` plus the path's final character, and the
        chopped-but-still-absolute path suddenly resolves inside
        assets and gets rewritten).
        """
        assets, md_dir = _layout(tmp_path, monkeypatch)
        img = assets / "pic.png"
        img.write_bytes(b"\x89PNG")

        raw = f"<{img}"
        assert mod.convert_target_to_relative(raw, md_dir) == raw


class TestRelativeTargetsStayUntouched:
    def test_relative_target_untouched_even_with_cwd_inside_assets(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Contract (docstring): a target is rewritten only when it is
        an *absolute* filesystem path. A relative target must come back
        verbatim even when it would happen to resolve inside the
        assets directory from the current working directory.

        Kills convert_target_to_relative __mutmut_3 (skip-guard ``or``
        → ``and``: a relative target falls through, resolves against
        the cwd into assets, and gets spuriously rewritten).
        """
        assets, md_dir = _layout(tmp_path, monkeypatch)
        (assets / "pic.png").write_bytes(b"\x89PNG")
        monkeypatch.chdir(assets)

        assert mod.convert_target_to_relative("pic.png", md_dir) == "pic.png"


class TestHtmlReplacementExactOutput:
    def test_img_and_href_rewrite_exact(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """The HTML attribute prefix (``<img … src=`` / ``<a … href=``)
        must survive the rewrite verbatim — only the quoted target
        changes.

        Kills convert_paths_in_text __mutmut_20 (``m.group(1)`` →
        ``m.group(2)`` replaces the whole prefix with the quote
        character, mangling the tag; the old substring-count assertion
        could not see the mangling).
        """
        assets, md_dir = _layout(tmp_path, monkeypatch)
        img = assets / "pic.png"
        img.write_bytes(b"\x89")

        md = md_dir / "ch1.md"
        text = f'<img src="{img}"/> <a href="{img}">l</a>'
        out = mod.convert_paths_in_text(text, md)
        assert out == (
            '<img src="../../assets/pic.png"/> ' '<a href="../../assets/pic.png">l</a>'
        )


class TestProcessFileEncodingContract:
    def test_utf8_roundtrip_under_c_locale(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Pins ``encoding="utf-8"`` on read and write explicitly —
        not by coincidence with the process locale. Same pattern as the
        Commit 9/10 locale pins.

        Kills process_md_file __mutmut_2 (read ``encoding=None``),
        __mutmut_12 (write ``encoding=None``) and __mutmut_14 (write
        encoding kwarg dropped) — under ``LC_ALL=C`` the ASCII default
        codec fails on the umlauts either on the way in or out.
        """
        import locale as _locale

        saved = _locale.setlocale(_locale.LC_ALL)
        monkeypatch.setenv("LC_ALL", "C")
        monkeypatch.setenv("LANG", "C")
        _locale.setlocale(_locale.LC_ALL, "C")
        try:
            assets, md_dir = _layout(tmp_path, monkeypatch)
            img = assets / "pic.png"
            img.write_bytes(b"\x89")

            md = md_dir / "ch1.md"
            md.write_bytes(f"Grüße\n![ü]({img})\n".encode("utf-8"))

            assert mod.process_md_file(md) is True
            out = md.read_bytes().decode("utf-8")
            assert out == "Grüße\n![ü](../../assets/pic.png)\n"
        finally:
            _locale.setlocale(_locale.LC_ALL, saved)


class TestMainWalkerContract:
    def test_missing_dir_is_skipped_not_fatal(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ):
        """A missing directory is skipped; directories after it are
        still processed (``continue``, not abort).

        Kills main __mutmut_4 (``continue`` → ``break``: the walk stops
        at the first missing directory and the later directory's file
        is never converted).
        """
        assets, md_dir = _layout(tmp_path, monkeypatch)
        img = assets / "pic.png"
        img.write_bytes(b"\x89")
        (md_dir / "ch1.md").write_text(f"![x]({img})\n", encoding="utf-8")

        missing = tmp_path / "does-not-exist"
        monkeypatch.setattr(mod, "MD_DIRECTORIES", [missing, md_dir])

        mod.main()
        assert "Files updated: 1" in capsys.readouterr().out

    def test_update_count_accumulates_across_files(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ):
        """The summary counts every changed file, not just the last
        one.

        Kills main __mutmut_8 (``changed += 1 if …`` → ``changed = 1
        if …``: the counter is overwritten per file and reports at most
        1 — or 0, depending on iteration order).
        """
        assets, md_dir = _layout(tmp_path, monkeypatch)
        img = assets / "pic.png"
        img.write_bytes(b"\x89")
        (md_dir / "ch1.md").write_text(f"![x]({img})\n", encoding="utf-8")
        (md_dir / "ch2.md").write_text(f"![y]({img})\n", encoding="utf-8")

        monkeypatch.setattr(mod, "MD_DIRECTORIES", [md_dir])

        mod.main()
        assert "Files updated: 2" in capsys.readouterr().out
