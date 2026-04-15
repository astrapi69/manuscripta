# tests/test_convert_images.py
from pathlib import Path
import re
import pytest

pytestmark = pytest.mark.unit

from manuscripta.images.convert import convert_markdown_file, convert_markdown_dir

FIG_RE = re.compile(
    r'<figure(?:\s+class="[^"]+")?>\s*'
    r'<img\s+src="([^"]+)"\s+alt="([^"]+)"\s*/>\s*'
    r"<figcaption>\s*<em>(.*?)</em>\s*</figcaption>\s*"
    r"</figure>",
    re.DOTALL,
)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


# ---------- single-file tests ----------


def test_converts_simple_inline_image(tmp_path: Path):
    md = tmp_path / "a.md"
    write(md, "Hello ![Alt](img/cat.png) world.\n")

    n = convert_markdown_file(md)
    assert n == 1

    out = read(md)
    m = FIG_RE.search(out)
    assert m, f"Figure not found in:\n{out}"
    src, alt, caption = m.groups()
    assert src == "img/cat.png"
    assert alt == "Alt"
    assert caption == "Alt"


def test_uses_title_as_caption_when_present(tmp_path: Path):
    md = tmp_path / "t.md"
    write(md, '![Hund](pics/dog.jpg "Ein lieber Hund")\n')

    n = convert_markdown_file(md)
    assert n == 1
    out = read(md)
    m = FIG_RE.search(out)
    assert m is not None, f"no match in output:\n{out}"
    src, alt, caption = m.groups()
    assert src == "pics/dog.jpg"
    assert alt == "Hund"
    assert caption == "Ein lieber Hund"


@pytest.mark.parametrize(
    "wrapper", ["<pics/file with spaces.png>", "<../weird (1).png>"]
)
def test_angle_bracket_url_and_spaces_supported(tmp_path: Path, wrapper):
    md = tmp_path / "s.md"
    write(md, f'![X]({wrapper} "T")\n')

    n = convert_markdown_file(md)
    assert n == 1
    out = read(md)
    m = FIG_RE.search(out)
    assert m is not None, f"no match in output:\n{out}"
    src, alt, caption = m.groups()
    assert src == wrapper[1:-1]
    assert alt == "X"
    assert caption == "T"


def test_skips_fenced_code_blocks(tmp_path: Path):
    md = tmp_path / "code.md"
    write(md, "Before\n" "```\n" '![ALT](img/in_code.png "T")\n' "```\n" "After\n")
    n = convert_markdown_file(md)
    assert n == 0
    assert read(md).count("![ALT](") == 1


def test_skips_inline_code_spans(tmp_path: Path):
    md = tmp_path / "inline.md"
    write(md, 'Text `![ALT](path/x.png "T")` Text\n')

    n = convert_markdown_file(md)
    assert n == 0
    assert read(md).count("![ALT](") == 1


def test_reference_style_images_are_resolved(tmp_path: Path):
    md = tmp_path / "ref.md"
    write(md, "Here: ![Logo][app]\n" '[app]: assets/logo.svg "Brand"\n')

    n = convert_markdown_file(md)
    assert n == 1
    out = read(md)
    m = FIG_RE.search(out)
    assert m is not None, f"no match in output:\n{out}"
    src, alt, caption = m.groups()
    assert src == "assets/logo.svg"
    assert alt == "Logo"
    assert caption == "Brand"


def test_reference_empty_id_uses_alt_as_key(tmp_path: Path):
    md = tmp_path / "ref2.md"
    write(md, "An image: ![Foo][]\n" '[foo]: img/foo.png "Titel Foo"\n')
    n = convert_markdown_file(md)
    assert n == 1
    out = read(md)
    m = FIG_RE.search(out)
    assert m is not None, f"no match in output:\n{out}"
    src, alt, caption = m.groups()
    assert src == "img/foo.png"
    assert alt == "Foo"
    assert caption == "Titel Foo"


def test_unknown_reference_is_left_untouched(tmp_path: Path):
    md = tmp_path / "ref3.md"
    write(md, "Oops: ![Bar][missing]\n")

    n = convert_markdown_file(md)
    assert n == 0
    assert read(md) == "Oops: ![Bar][missing]\n"


def test_default_is_no_backup(tmp_path: Path):
    md = tmp_path / "nb.md"
    write(md, "![A](x.png)\n")
    n = convert_markdown_file(md)  # default: backup=False
    assert n == 1
    assert not md.with_suffix(".md.bak").exists()


def test_backup_when_enabled(tmp_path: Path):
    md = tmp_path / "b.md"
    write(md, "![A](x.png)\n")
    bak = md.with_suffix(".md.bak")
    assert not bak.exists()

    n = convert_markdown_file(md, backup=True)
    assert n == 1
    assert bak.exists()
    assert read(bak) == "![A](x.png)\n"  # original preserved in backup


def test_dry_run_writes_nothing(tmp_path: Path):
    md = tmp_path / "dry.md"
    before = "Start ![A](x.png) End\n"
    write(md, before)

    n = convert_markdown_file(md, dry_run=True)
    assert n == 1
    assert read(md) == before
    assert not md.with_suffix(".md.bak").exists()


def test_applies_figure_class_when_provided(tmp_path: Path):
    md = tmp_path / "cls.md"
    write(md, "![A](x.png)\n")

    n = convert_markdown_file(md, figure_class="img-figure")
    assert n == 1
    out = read(md)
    assert '<figure class="img-figure">' in out


def test_file_not_found_returns_zero(tmp_path: Path):
    missing = tmp_path / "nope.md"
    n = convert_markdown_file(missing)
    assert n == 0


def test_no_images_no_change(tmp_path: Path):
    md = tmp_path / "plain.md"
    write(md, "No image here.\n")
    n = convert_markdown_file(md)
    assert n == 0
    assert read(md) == "No image here.\n"


# ---------- directory (recursive) tests ----------


def test_directory_recursive_conversion(tmp_path: Path):
    sub = tmp_path / "chapter1" / "images"
    sub.mkdir(parents=True)
    f1 = tmp_path / "root.md"
    f2 = sub / "nested.md"

    write(f1, "Intro ![A](a.png)")
    write(f2, "Nested ![B](b.png)")

    total = convert_markdown_dir(tmp_path)  # default: no backups
    assert total == 2

    assert FIG_RE.search(read(f1))
    assert FIG_RE.search(read(f2))


def test_dry_run_directory(tmp_path: Path):
    sub = tmp_path / "part"
    sub.mkdir()
    f = sub / "c.md"
    write(f, "![Alt](c.png)")

    total = convert_markdown_dir(tmp_path, dry_run=True)
    assert total == 1
    # original file unchanged
    assert "![Alt](" in read(f)


# ---------------------------------------------------------------------------
# Phase 4b Pass 2 Commit 9 — mutation-survivor A-category kills.
# Companion B-annotations live in .mutmut/equivalent.yaml under the
# §14.8.1, §14.8.3, §14.8.4, and ad-hoc sections; this test block is the
# A side of the triage. Each test asserts a specific observable contract;
# the docstring names the mutant(s) it kills.
# ---------------------------------------------------------------------------


from manuscripta.images.convert import (
    _parse_ref_defs,
    _replace_inline,
    _replace_reference,
    _split_outside_code,
    _unangle,
)


class TestUnangleContract:
    def test_unangle_requires_both_angle_brackets(self):
        """Pins that _unangle strips angle brackets only when BOTH the
        leading ``<`` and the trailing ``>`` are present. A URL with
        only one of them is returned unchanged.

        Kills _unangle __mutmut_5 (``and`` → ``or`` on the bracket
        check).
        """
        assert _unangle("<http://example.com>") == "http://example.com"
        assert _unangle("<broken") == "<broken"
        assert _unangle("broken>") == "broken>"


class TestRefDefParsing:
    def test_ref_def_single_quoted_title_parses(self):
        """Pins that ref defs with single-quoted titles resolve through
        the ``title_sq`` named group.

        Kills _parse_ref_defs __mutmut_18 (``m.group(None)`` raises),
        __mutmut_19 (``m.group('XXtitle_sqXX')`` raises), and
        __mutmut_20 (``m.group('TITLE_SQ')`` raises).
        """
        refs = _parse_ref_defs("[logo]: img/x.png 'Single Title'\n")
        assert "logo" in refs
        assert refs["logo"]["title"] == "Single Title"
        assert refs["logo"]["src"] == "img/x.png"

    def test_ref_def_parenthesized_title_parses(self):
        """Pins that ref defs with parenthesized titles resolve through
        the ``title_par`` named group, and pins the title-precedence
        short-circuit semantics (``or or`` — first match wins — not
        ``or and``).

        Kills _parse_ref_defs __mutmut_21 (``m.group(None)``),
        __mutmut_22 (``XXtitle_parXX``), __mutmut_23 (``TITLE_PAR``),
        and __mutmut_13 (``or or`` → ``or and``; with only title_par,
        the ``and`` mutation collapses to ``None`` where the orig
        returns the parenthesised title).
        """
        refs = _parse_ref_defs("[pic]: img/y.png (Par Title)\n")
        assert "pic" in refs
        assert refs["pic"]["title"] == "Par Title"


class TestReplaceInlineMutationPins:
    def test_inline_image_single_quoted_title_caption(self):
        """Pins the title-precedence short-circuit in _replace_inline:
        with only a single-quoted title, the caption must be the sq
        title (not None from an ``and``-collapse).

        Kills _replace_inline __mutmut_15 (``or`` → ``and`` on the
        middle link of the title precedence).
        """
        out, count = _replace_inline(
            "![A](img/pic.png 'SQ Caption')", figure_class=None
        )
        assert count == 1
        assert "SQ Caption" in out

    def test_inline_image_empty_alt_preserved(self):
        """Pins that an inline image with no alt text (``![](src)``)
        yields ``alt=""`` in the rendered figure — not a sentinel.

        Kills _replace_inline __mutmut_8 (``alt or ""`` → ``alt or
        "XXXX"``).
        """
        out, count = _replace_inline("![](img/a.png)", figure_class=None)
        assert count == 1
        assert 'alt=""' in out
        assert "XXXX" not in out

    def test_inline_image_count_sums_multiple(self):
        """Pins that the per-chunk inline-image count accumulates
        across matches (``count += 1``), not resets to 1 per match.

        Kills _replace_inline __mutmut_31 (``count += 1`` →
        ``count = 1``).
        """
        _, count = _replace_inline(
            "![A](a.png) and ![B](b.png) and ![C](c.png)",
            figure_class=None,
        )
        assert count == 3


class TestReplaceReferenceMutationPins:
    def test_reference_image_empty_alt_preserved(self):
        """Pins that a reference image with empty alt (``![][id]``)
        yields ``alt=""``, not a sentinel.

        Kills _replace_reference __mutmut_8 (``alt or ""`` → ``alt or
        "XXXX"``).
        """
        refs = {"pic": {"src": "img/x.png", "title": "T"}}
        out, count = _replace_reference("![][pic]", refs, figure_class=None)
        assert count == 1
        assert 'alt=""' in out
        assert "XXXX" not in out

    def test_reference_image_unknown_ref_kept_verbatim(self):
        """Pins that when a reference image points to an unknown id,
        the full original markdown match is preserved — not replaced
        by the alt text alone.

        Kills _replace_reference __mutmut_19 (``return m.group(0)`` →
        ``return m.group(1)``; group(1) is the alt named group, not
        the full match).
        """
        out, count = _replace_reference("![MyAlt][missing]", refs={}, figure_class=None)
        assert count == 0
        assert out == "![MyAlt][missing]"

    def test_reference_image_no_title_uses_alt_as_caption(self):
        """Pins that when a ref def carries no title, the caption
        falls back to the image's alt text — not to ``None``.

        Kills _replace_reference __mutmut_24 (``_caption(alt, …)`` →
        ``_caption(None, …)``); with ``title=None``, _caption returns
        alt, and the alt must be real, not None.
        """
        refs = {"pic": {"src": "img/x.png", "title": None}}
        out, count = _replace_reference("![MyAlt][pic]", refs, figure_class=None)
        assert count == 1
        assert "MyAlt" in out
        # Caption tag must not render literal "None"
        assert "<em>None</em>" not in out

    def test_reference_image_count_sums_multiple(self):
        """Pins that the per-chunk reference-image count accumulates.

        Kills _replace_reference __mutmut_30 (``count += 1`` →
        ``count = 1``).
        """
        refs = {
            "a": {"src": "a.png", "title": "A"},
            "b": {"src": "b.png", "title": "B"},
            "c": {"src": "c.png", "title": "C"},
        }
        _, count = _replace_reference(
            "![x][a] ![y][b] ![z][c]", refs, figure_class=None
        )
        assert count == 3


class TestSplitOutsideCodeMutationPins:
    def test_text_segments_marked_non_code(self):
        """Pins that plain-text segments between code fences are
        labelled ``(False, …)`` (non-code), so the downstream loop
        runs image replacement on them.

        Kills _split_outside_code __mutmut_7 (``(False, …)`` →
        ``(True, …)``).
        """
        text = "intro text\n\n```\nfenced\n```\n\ntrailing text"
        segs = _split_outside_code(text)
        non_code = [s for is_code, s in segs if not is_code]
        assert any("intro text" in s for s in non_code)
        assert any("trailing text" in s for s in non_code)

    def test_full_code_fence_preserved_in_segment(self):
        """Pins that when a code fence is captured, the full matched
        text (``m.group(0)``) is carried forward — not just the
        leading anchor capture group (``m.group(1)`` is ``(^|\\n)``,
        which is empty or a single newline).

        Kills _split_outside_code __mutmut_11 (``m.group(0)`` →
        ``m.group(1)``).
        """
        text = "pre\n```python\nprint('hi')\n```\npost"
        segs = _split_outside_code(text)
        code_segments = [s for is_code, s in segs if is_code]
        assert any("print('hi')" in s for s in code_segments)

    def test_inline_code_refinement_marks_surrounding_text_non_code(self):
        """Pins that when inline code splits a non-code segment, the
        surrounding text keeps its non-code label.

        Kills _split_outside_code __mutmut_24 (``(False, seg[...])`` →
        ``(True, seg[...])`` in the inline-code refinement path).
        """
        text = "text before `inline` text after"
        segs = _split_outside_code(text)
        non_code = [s for is_code, s in segs if not is_code]
        assert any("text before" in s for s in non_code)
        assert any("text after" in s for s in non_code)


class TestConvertFilePipelineMutationPins:
    def test_code_segment_preserved_verbatim(self, tmp_path: Path):
        """Pins that a fenced code block's contents are written back
        unchanged — the segment-loop appends ``chunk``, not ``None``.

        Kills convert_markdown_file __mutmut_17 (``converted.append(
        chunk)`` → ``converted.append(None)``).
        """
        md = tmp_path / "a.md"
        code = "```python\nx = 1\ny = 2\n```"
        write(md, f"pre ![A](a.png) mid\n\n{code}\n\npost")
        convert_markdown_file(md)
        out = read(md)
        assert "x = 1\ny = 2" in out
        # The fenced segment must not have been overwritten with "None".
        assert "None" not in out.split("```")[1]

    def test_processing_continues_past_code_fence(self, tmp_path: Path):
        """Pins that the per-segment loop uses ``continue`` to skip
        code fences without aborting; images after a fence must still
        be processed.

        Kills convert_markdown_file __mutmut_18 (``continue`` →
        ``break``).
        """
        md = tmp_path / "a.md"
        write(md, "```\ncode\n```\n\n![TailImg](img/tail.png)")
        n = convert_markdown_file(md)
        assert n == 1
        assert "TailImg" in read(md)

    def test_figure_class_reaches_reference_images(self, tmp_path: Path):
        """Pins that ``figure_class`` is forwarded to
        _replace_reference, not dropped to ``None``, so the CSS class
        lands on reference-image figures too.

        Kills convert_markdown_file __mutmut_27
        (``_replace_reference(chunk, refs, figure_class)`` →
        ``_replace_reference(chunk, refs, None)``).
        """
        md = tmp_path / "a.md"
        write(md, '![Alt][pic]\n\n[pic]: img/x.png "T"\n')
        convert_markdown_file(md, figure_class="my-fig")
        out = read(md)
        assert 'class="my-fig"' in out

    def test_total_accumulates_across_segments(self, tmp_path: Path):
        """Pins that the per-file total sums image counts across every
        non-code segment, not just the last one.

        Kills convert_markdown_file __mutmut_31 (``total += c1 + c2``
        → ``total = c1 + c2``).
        """
        md = tmp_path / "a.md"
        write(md, "![A](a.png)\n\n```\ncode\n```\n\n![B](b.png)")
        n = convert_markdown_file(md)
        assert n == 2

    def test_segments_joined_without_sentinel_separator(self, tmp_path: Path):
        """Pins that per-segment strings are concatenated with ``""``
        (empty) as joiner, not a sentinel.

        Kills convert_markdown_file __mutmut_40 (``"".join(converted)``
        → ``"XXXX".join(converted)``).
        """
        md = tmp_path / "a.md"
        write(md, "pre ![A](a.png)\n\n```\nfenced\n```\n\npost ![B](b.png)")
        convert_markdown_file(md)
        out = read(md)
        assert "XXXX" not in out

    def test_utf8_non_ascii_roundtrip_under_c_locale(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Pins that file reads and writes pin ``encoding="utf-8"``
        explicitly, not by coincidence with the process locale. Under
        ``LC_ALL=C``, ``Path.read_text(encoding=None)`` resolves to
        ASCII and fails on any byte ≥ 0x80 — so any mutant that
        removes the explicit ``encoding="utf-8"`` (or replaces it with
        ``None``) will raise ``UnicodeDecodeError`` here even though
        it passes under a UTF-8 test host.

        Kills convert_markdown_file __mutmut_7 and __mutmut_52
        (``encoding="utf-8"`` → ``encoding=None`` on read_text /
        write_text), and __mutmut_54 (the ``encoding`` kwarg dropped
        entirely from write_text).

        This is exactly the class of latent locale-coupling the
        explicit encoding contract is meant to prevent: the bug would
        surface only on a deploy host whose locale differs from CI's,
        and without this pin we would discover it in production.
        """
        import locale as _locale

        # Snapshot and restore process locale; monkeypatch fixtures do not
        # cover locale state because setlocale is process-global.
        saved = _locale.setlocale(_locale.LC_ALL)
        monkeypatch.setenv("LC_ALL", "C")
        monkeypatch.setenv("LANG", "C")
        _locale.setlocale(_locale.LC_ALL, "C")
        try:
            md = tmp_path / "note.md"
            # Non-ASCII bytes (UTF-8-encoded German umlauts + ß). Under
            # LC_ALL=C, encoding=None resolves to ASCII and cannot decode
            # these bytes.
            md.write_bytes("Grüße: ![Fig](ä.png)\n".encode("utf-8"))
            n = convert_markdown_file(md)
            assert n == 1
            # The written file must still decode as UTF-8 regardless of
            # process locale — this asserts write_text(encoding="utf-8")
            # was honored by the pipeline.
            out = md.read_bytes().decode("utf-8")
            assert "Grüße" in out
            assert "ä.png" in out
        finally:
            _locale.setlocale(_locale.LC_ALL, saved)


class TestConvertDirKwargForwardingMutationPins:
    def test_passes_backup_kwarg(self, tmp_path: Path):
        """Pins that ``backup=True`` propagates through the dir
        wrapper to each file call, producing a ``.bak`` sidecar.

        Kills convert_markdown_dir __mutmut_11 (``backup=backup`` →
        ``backup=None`` in the per-file call).
        """
        f = tmp_path / "file.md"
        write(f, "![A](a.png)")
        convert_markdown_dir(tmp_path, backup=True)
        assert (tmp_path / "file.md.bak").exists()

    def test_passes_figure_class_kwarg(self, tmp_path: Path):
        """Pins that ``figure_class`` propagates through the dir
        wrapper to each file call.

        Kills convert_markdown_dir __mutmut_13 (``figure_class=
        figure_class`` → ``figure_class=None``).
        """
        f = tmp_path / "file.md"
        write(f, "![A](a.png)")
        convert_markdown_dir(tmp_path, figure_class="dir-fig")
        assert 'class="dir-fig"' in read(f)

    def test_kwarg_drop_silently_uses_per_file_default(self, tmp_path: Path):
        """Pins that the per-file call in the dir wrapper includes
        every forwarded kwarg explicitly; dropping any of them makes
        the per-file call use convert_markdown_file's own default for
        that parameter — silently losing the caller's value.

        Kills convert_markdown_dir __mutmut_15 (``backup=backup``
        entry dropped; per-file default ``backup=False`` overrides
        the dir-call's ``backup=True``).
        """
        f = tmp_path / "file.md"
        write(f, "![A](a.png)")
        convert_markdown_dir(tmp_path, backup=True)
        assert (tmp_path / "file.md.bak").exists()

    def test_last_positional_kwarg_forwarded(self, tmp_path: Path):
        """Pins that the last forwarded kwarg (``figure_class=``) is
        present in the per-file call; a trailing-comma-only variant
        that drops it would silently make every per-file call use the
        per-file default of ``None``.

        Kills convert_markdown_dir __mutmut_17 (the last kwarg in the
        per-file call signature dropped).
        """
        f = tmp_path / "file.md"
        write(f, "![A](a.png)")
        convert_markdown_dir(tmp_path, figure_class="dir-fig2")
        assert 'class="dir-fig2"' in read(f)
