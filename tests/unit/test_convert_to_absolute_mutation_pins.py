"""Phase 4b Pass 2 Commit 10 — mutation-response tests for
``manuscripta.paths.to_absolute``.

Each test cites the mutant(s) it kills, per the A-category discipline
in TESTING.md §14.5: assertions trace to the module's documented
contract (docstrings: URL-like/absolute targets are skipped, code
spans are protected, titles are preserved, parentheses in bare URLs
are balanced), never to incidental literals.

Scanner and split tests carry ``@pytest.mark.timeout(5)``: the
infinite-loop mutants on ``_find_image_tag`` / ``_split_inside_parens``
/ ``_convert_images_in_text`` previously hung the suite and were
recorded as ``timeout`` (counting against the score, ADR-0002 strict
reading). The marker turns the hang into a fast test failure, which is
a kill. Full-output equality is asserted throughout — the ``in out``
style of the older tests is what let the tag-boundary mutant
(``_find_image_tag__mutmut_83``) survive.

Per-mutant map: docs/audits/phase-4b-commit-10-triage-map.md.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

import os
from pathlib import Path

from manuscripta.paths.to_absolute import convert_file_to_absolute


def write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def make_md(tmp_path: Path, body: str) -> Path:
    md = tmp_path / "manuscript" / "chapters" / "doc.md"
    write(md, body)
    return md


def make_img(tmp_path: Path, name: str) -> Path:
    img = tmp_path / "assets" / name
    write(img, "x")
    return img


class TestProtectSegmentsTokenUniqueness:
    def test_three_distinct_inline_spans_restore_verbatim(self, tmp_path: Path):
        """Pins the token-uniqueness contract of the protect/restore
        round trip: every protected span must come back verbatim, in
        place, exactly once.

        Kills _protect_segments __mutmut_8 (``idx += 1`` → ``idx = 1``):
        the collapsed counter hands the second and third span the same
        token, the mapping loses one original (last-write-wins), and
        restore duplicates the surviving span — the §14.8.5 canonical
        uniqueness-broken A-mutant.
        """
        img = make_img(tmp_path, "a.png")
        md = make_md(tmp_path, "seed")
        rel = os.path.relpath(img, start=md.parent)
        body = f"`alpha` and `beta` and `gamma`\n![x]({rel})\n"
        write(md, body)

        changed, count = convert_file_to_absolute(md)
        assert changed and count == 1
        out = md.read_text(encoding="utf-8")
        assert out == f"`alpha` and `beta` and `gamma`\n![x]({img.resolve()})\n"


class TestUrlLikeSkipContract:
    @pytest.mark.timeout(5)
    def test_url_like_target_untouched_even_if_matching_file_exists(
        self, tmp_path: Path
    ):
        """Module docstring: URL-like targets (scheme prefix) are
        skipped — unconditionally, not only when no local file happens
        to shadow them. A file literally named ``data:image.png`` makes
        the two behaviours observable.

        Kills _is_url_like __mutmut_1 (regex match → ``bool(None)``:
        nothing is URL-like, the shadow file gets converted) and
        _convert_images_in_text __mutmut_24 (skip-guard ``or`` →
        ``and``: URL-like non-absolute targets fall through to
        conversion).
        """
        md = make_md(tmp_path, "seed")
        write(md.parent / "data:image.png", "x")
        body = "![d](data:image.png)\n"
        write(md, body)

        changed, count = convert_file_to_absolute(md)
        assert (changed, count) == (False, 0)
        assert md.read_text(encoding="utf-8") == body

    @pytest.mark.timeout(5)
    def test_url_skip_then_next_image_converts_exact(self, tmp_path: Path):
        """After skipping a URL-like tag the scanner must resume right
        behind it and still convert the next image.

        Kills _convert_images_in_text __mutmut_28 (post-skip
        ``idx = tag_end`` → ``None``: rescan restarts at 0 and loops on
        the first tag forever — the timeout marker converts the hang
        into a kill).
        """
        img = make_img(tmp_path, "b.png")
        md = make_md(tmp_path, "seed")
        rel = os.path.relpath(img, start=md.parent)
        write(md, f"![u](https://example.com/x.png) ![a]({rel})\n")

        changed, count = convert_file_to_absolute(md)
        assert changed and count == 1
        out = md.read_text(encoding="utf-8")
        assert out == f"![u](https://example.com/x.png) ![a]({img.resolve()})\n"


class TestImageTagScannerPins:
    @pytest.mark.timeout(5)
    def test_basic_conversion_exact_output(self, tmp_path: Path):
        """One relative image between prose lines converts, and the
        output equals the input with exactly the target swapped —
        nothing duplicated, nothing dropped at the tag boundary.

        The equality assertion kills _find_image_tag __mutmut_83
        (``tag_end`` = ``k - 1``: the convert path re-appends the last
        two tag chars after the rewritten tag). The timeout marker
        kills the scan-restart loops: _find_image_tag __mutmut_1/6/8
        (find start pinned to 0/None), __mutmut_12/13 (end-of-scan −1
        no longer returns None), __mutmut_92/93 (plain scan cursor
        reset/reversed), and _convert_images_in_text __mutmut_11
        (caller re-finds the first tag forever) / __mutmut_37
        (post-convert index reset).
        """
        img = make_img(tmp_path, "c.png")
        md = make_md(tmp_path, "seed")
        rel = os.path.relpath(img, start=md.parent)
        write(md, f"Before\n![alt]({rel})\nAfter\n")

        changed, count = convert_file_to_absolute(md)
        assert changed and count == 1
        out = md.read_text(encoding="utf-8")
        assert out == f"Before\n![alt]({img.resolve()})\nAfter\n"

    @pytest.mark.timeout(5)
    def test_empty_alt_converts(self, tmp_path: Path):
        """Markdown allows an empty alt text; ``![](target)`` is a
        well-formed image whose ``]`` sits directly after ``![``.

        Kills _find_image_tag __mutmut_22 (alt-scan starts at ``i + 3``
        and can no longer see the ``]`` at ``i + 2``).
        """
        img = make_img(tmp_path, "d.png")
        md = make_md(tmp_path, "seed")
        rel = os.path.relpath(img, start=md.parent)
        write(md, f"![]({rel})\n")

        changed, count = convert_file_to_absolute(md)
        assert changed and count == 1
        assert md.read_text(encoding="utf-8") == f"![]({img.resolve()})\n"

    @pytest.mark.timeout(5)
    def test_text_ending_right_after_alt_bracket_unchanged(self, tmp_path: Path):
        """A candidate whose ``]`` is the final character has no
        ``(`` to look at; the scanner must classify it malformed and
        return cleanly instead of reading past the end of the text.

        Kills _find_image_tag __mutmut_27 (``j - 1 >= n`` disables the
        bounds guard → IndexError at ``text[j + 1]``) and __mutmut_29
        (``>`` admits ``j + 1 == n`` → IndexError at ``text[n]``).
        """
        md = make_md(tmp_path, "seed")
        body = "some prose ![alt]"
        write(md, body)

        changed, count = convert_file_to_absolute(md)
        assert (changed, count) == (False, 0)
        assert md.read_text(encoding="utf-8") == body

    @pytest.mark.timeout(5)
    def test_paren_at_text_start_with_unclosed_candidate_unchanged(
        self, tmp_path: Path
    ):
        """``(x) ![nope`` has no ``]`` after the candidate; the
        malformed-skip must fire even when the text happens to start
        with ``(``.

        Kills _find_image_tag __mutmut_24/25 (the ``j == -1`` check is
        broken; with ``text[0] == "("`` the j=−1 fall-through fabricates
        a tuple with ``tag_end < tag_start`` and the caller loops —
        the timeout marker makes that a kill).
        """
        md = make_md(tmp_path, "seed")
        body = "(x) ![nope"
        write(md, body)

        changed, count = convert_file_to_absolute(md)
        assert (changed, count) == (False, 0)
        assert md.read_text(encoding="utf-8") == body

    @pytest.mark.timeout(5)
    def test_link_before_image_converts_exact(self, tmp_path: Path):
        """A regular ``[link](url)`` before the image puts a ``](``
        pair ahead of the tag; the alt-scan must start at the
        candidate, not at the beginning of the text.

        Kills _find_image_tag __mutmut_16/18 (``find("]", …)`` start
        dropped to 0/default: the link's ``]`` hijacks the parse,
        ``tag_end`` lands before ``tag_start``, the caller loops).
        """
        img = make_img(tmp_path, "e.png")
        md = make_md(tmp_path, "seed")
        rel = os.path.relpath(img, start=md.parent)
        write(md, f"[l](u) ![a]({rel})\n")

        changed, count = convert_file_to_absolute(md)
        assert changed and count == 1
        assert md.read_text(encoding="utf-8") == f"[l](u) ![a]({img.resolve()})\n"

    @pytest.mark.timeout(5)
    def test_gt_in_prefix_before_angle_target_exact(self, tmp_path: Path):
        """Prose containing ``>`` before an angle-bracketed image must
        not derail the angle scan — the scan state is local to the
        tag, not to the whole text.

        Kills _find_image_tag __mutmut_52 (angle-enter cursor reset to
        text index 1: the scan re-consumes the prefix in angle mode and
        the prefix ``>`` corrupts/loops the parse).
        """
        img = make_img(tmp_path, "f.png")
        md = make_md(tmp_path, "seed")
        rel = os.path.relpath(img, start=md.parent)
        write(md, f"a>b ![i](<{rel}>)\n")

        changed, count = convert_file_to_absolute(md)
        assert changed and count == 1
        assert md.read_text(encoding="utf-8") == f"a>b ![i]({img.resolve()})\n"

    @pytest.mark.timeout(5)
    def test_gt_directly_before_angle_open_unchanged(self, tmp_path: Path):
        """Target text ``a><c>.png``: the ``>`` immediately before
        ``<`` must simply be a target character; no such file exists,
        so the tag stays untouched.

        Kills _find_image_tag __mutmut_53 (angle-enter ``k -= 1``: the
        cursor oscillates between the ``>``/``<`` pair forever; the
        timeout marker converts the hang into a kill).
        """
        md = make_md(tmp_path, "seed")
        body = "![x](a><c>.png)\n"
        write(md, body)

        changed, count = convert_file_to_absolute(md)
        assert (changed, count) == (False, 0)
        assert md.read_text(encoding="utf-8") == body

    @pytest.mark.timeout(5)
    def test_angle_target_converts_exact(self, tmp_path: Path):
        """Plain angle-bracketed target converts (docstring feature:
        ``![alt](<assets/a(b).png> "Cover")``).

        Kills _find_image_tag __mutmut_60/61 (angle-consume cursor
        reset/reversed: every char inside ``<…>`` loops the scan).
        """
        img = make_img(tmp_path, "g h.png")
        md = make_md(tmp_path, "seed")
        rel = os.path.relpath(img, start=md.parent)
        write(md, f"![a](<{rel}>)\n")

        changed, count = convert_file_to_absolute(md)
        assert changed and count == 1
        assert md.read_text(encoding="utf-8") == f"![a]({img.resolve()})\n"

    @pytest.mark.timeout(5)
    def test_nested_paren_filename_converts(self, tmp_path: Path):
        """Docstring feature: parentheses in bare URLs are balanced by
        the scanner. Depth-2 nesting is the case a boolean depth flag
        cannot represent.

        Kills _find_image_tag __mutmut_66 (``depth += 1`` →
        ``depth = 1``: the second ``(`` is forgotten and the tag closes
        one ``)`` early, so the real file is never found). The timeout
        marker additionally kills the paren-branch cursor loops
        __mutmut_69/70/88 and _split_inside_parens __mutmut_46.
        """
        img = make_img(tmp_path, "a((b)).png")
        md = make_md(tmp_path, "seed")
        rel = os.path.relpath(img, start=md.parent)
        write(md, f"![n]({rel})\n")

        changed, count = convert_file_to_absolute(md)
        assert changed and count == 1
        assert md.read_text(encoding="utf-8") == f"![n]({img.resolve()})\n"

    @pytest.mark.timeout(5)
    def test_empty_paren_pair_in_filename_converts(self, tmp_path: Path):
        """``()`` directly adjacent in a filename: the closing ``)``
        follows the opening ``(`` with no char between.

        Kills _find_image_tag __mutmut_71 (post-``(`` cursor skips a
        char: the ``)`` of the empty pair is never seen, depth never
        closes, the tag is misread as malformed and the file is not
        converted).
        """
        img = make_img(tmp_path, "x().png")
        md = make_md(tmp_path, "seed")
        rel = os.path.relpath(img, start=md.parent)
        write(md, f"![p]({rel})\n")

        changed, count = convert_file_to_absolute(md)
        assert changed and count == 1
        assert md.read_text(encoding="utf-8") == f"![p]({img.resolve()})\n"

    @pytest.mark.timeout(5)
    def test_target_ending_at_nested_close_converts(self, tmp_path: Path):
        """A target whose final character is a balanced ``)`` puts the
        tag-closing ``)`` directly after the nested close.

        Kills _find_image_tag __mutmut_90 (post-nested-close cursor
        skips a char — exactly the tag-close ``)`` here — so the tag
        never closes and the file is not converted).
        """
        img = make_img(tmp_path, "x(y)")
        md = make_md(tmp_path, "seed")
        rel = os.path.relpath(img, start=md.parent)
        write(md, f"![q]({rel})\n")

        changed, count = convert_file_to_absolute(md)
        assert changed and count == 1
        assert md.read_text(encoding="utf-8") == f"![q]({img.resolve()})\n"

    @pytest.mark.timeout(5)
    def test_malformed_candidate_then_valid_image_converts(self, tmp_path: Path):
        """A ``![x]`` without a following ``(`` is not an image — but
        the scanner must keep searching and still convert a
        well-formed image later in the text (docstring: find the
        *next* well-formed image).

        Kills _find_image_tag __mutmut_41 (the malformed-skip
        ``continue`` replaced by ``break``: the scanner gives up on the
        whole text at the first malformed candidate and the later
        valid image is never converted).
        """
        img = make_img(tmp_path, "m.png")
        md = make_md(tmp_path, "seed")
        rel = os.path.relpath(img, start=md.parent)
        write(md, f"![x] gap ![ok]({rel})\n")

        changed, count = convert_file_to_absolute(md)
        assert changed and count == 1
        assert md.read_text(encoding="utf-8") == f"![x] gap ![ok]({img.resolve()})\n"

    @pytest.mark.timeout(5)
    def test_unclosed_parens_unchanged(self, tmp_path: Path):
        """An image whose ``(…`` never closes is malformed; the
        scanner must skip past it and terminate.

        Kills _find_image_tag __mutmut_95 (malformed-skip ``pos``
        reset to None: the same candidate is rescanned forever; the
        timeout marker makes the hang a kill).
        """
        md = make_md(tmp_path, "seed")
        body = "text ![a](no-close and more prose"
        write(md, body)

        changed, count = convert_file_to_absolute(md)
        assert (changed, count) == (False, 0)
        assert md.read_text(encoding="utf-8") == body


class TestSplitInsideParensPins:
    @pytest.mark.timeout(5)
    def test_double_space_before_title_preserved(self, tmp_path: Path):
        """Docstring: titles are preserved. The angle-target regex
        keeps the raw whitespace between target and title verbatim; a
        rebuild through the bare-target scanner would collapse it to a
        single space, silently reformatting the document.

        Kills _split_inside_parens __mutmut_3 (angle regex replaced by
        ``None``) and __mutmut_8 (pattern wrapped ``XX…XX``, never
        matches) — both drop to the bare-scan fallback and lose the
        second space.
        """
        img = make_img(tmp_path, "t.png")
        md = make_md(tmp_path, "seed")
        rel = os.path.relpath(img, start=md.parent)
        write(md, f'![x](<{rel}>  "T")\n')

        changed, count = convert_file_to_absolute(md)
        assert changed and count == 1
        assert md.read_text(encoding="utf-8") == f'![x]({img.resolve()}  "T")\n'

    @pytest.mark.timeout(5)
    def test_quote_after_space_inside_parens_is_target_text(self, tmp_path: Path):
        """A quote after a space *inside* parentheses is part of the
        target, not a title — the title lookahead only applies at
        paren depth 0 (docstring: quoted title at top-level).

        Kills _split_inside_parens __mutmut_29 (``(`` comparison
        broken so depth never rises and the in-paren quote is misread
        as a title) and __mutmut_50 (``and`` → ``or`` makes the
        lookahead fire inside parens). The timeout marker also kills
        the paren-append cursor loops __mutmut_34/35.
        """
        img = make_img(tmp_path, 'a(b "c").png')
        md = make_md(tmp_path, "seed")
        rel = os.path.relpath(img, start=md.parent)
        write(md, f"![s]({rel})\n")

        changed, count = convert_file_to_absolute(md)
        assert changed and count == 1
        assert md.read_text(encoding="utf-8") == f"![s]({img.resolve()})\n"

    @pytest.mark.timeout(5)
    def test_quote_after_space_inside_nested_parens_is_target_text(
        self, tmp_path: Path
    ):
        """Same contract at nesting depth 2 — the case a collapsed
        depth counter gets wrong while single parens still work.

        Kills _split_inside_parens __mutmut_30 (``depth += 1`` →
        ``depth = 1``: after ``((`` one ``)`` drops depth to 0 and the
        in-paren quote is misread as a title).
        """
        img = make_img(tmp_path, 'a((b) "c").png')
        md = make_md(tmp_path, "seed")
        rel = os.path.relpath(img, start=md.parent)
        write(md, f"![t]({rel})\n")

        changed, count = convert_file_to_absolute(md)
        assert changed and count == 1
        assert md.read_text(encoding="utf-8") == f"![t]({img.resolve()})\n"

    @pytest.mark.timeout(5)
    def test_space_in_filename_without_title_converts(self, tmp_path: Path):
        """Docstring: spaces are allowed in the target; only a quoted
        title terminates it.

        Timeout-kills the space-append cursor loops
        _split_inside_parens __mutmut_69/70 and the plain-append loop
        __mutmut_74.
        """
        img = make_img(tmp_path, "has space.png")
        md = make_md(tmp_path, "seed")
        rel = os.path.relpath(img, start=md.parent)
        write(md, f"![w]({rel})\n")

        changed, count = convert_file_to_absolute(md)
        assert changed and count == 1
        assert md.read_text(encoding="utf-8") == f"![w]({img.resolve()})\n"


class TestStripAngleBracketsPins:
    @pytest.mark.timeout(5)
    def test_one_sided_angle_bracket_is_not_stripped(self, tmp_path: Path):
        """Brackets are stripped only as a matched pair. A target that
        merely *starts* with ``<`` (here ``<a>b`` — the scanner closes
        the angle at ``>`` and the rest continues the target) must be
        used verbatim.

        Kills _strip_angle_brackets __mutmut_4 (``and`` → ``or``:
        one-sided match strips first+last char, mangling ``<a>b`` into
        ``a>`` and losing the real file). The file must sit beside the
        md file: the target has to *begin* with ``<`` for the one-sided
        ``startswith`` to fire.
        """
        md = make_md(tmp_path, "seed")
        img = md.parent / "<a>b"
        write(img, "x")
        write(md, "![v](<a>b)\n")

        changed, count = convert_file_to_absolute(md)
        assert changed and count == 1
        assert md.read_text(encoding="utf-8") == f"![v]({img.resolve()})\n"


class TestFileEncodingContract:
    def test_utf8_roundtrip_under_c_locale(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Pins ``encoding="utf-8"`` on both the read and the write —
        explicitly, not by coincidence with the process locale. Under
        ``LC_ALL=C`` the locale-default codec is ASCII: a mutant that
        drops the read encoding fails decoding the umlauts, one that
        drops the write encoding fails encoding them back.

        Kills convert_file_to_absolute __mutmut_2 (read
        ``encoding=None``), __mutmut_12 (write ``encoding=None``) and
        __mutmut_14 (write encoding kwarg dropped). Same pattern as
        the convert.py locale pins from Pass 2 Commit 9.
        """
        import locale as _locale

        saved = _locale.setlocale(_locale.LC_ALL)
        monkeypatch.setenv("LC_ALL", "C")
        monkeypatch.setenv("LANG", "C")
        _locale.setlocale(_locale.LC_ALL, "C")
        try:
            img = make_img(tmp_path, "ä.png")
            md = make_md(tmp_path, "seed")
            rel = os.path.relpath(img, start=md.parent)
            md.write_bytes(f"Grüße\n![ü]({rel})\n".encode("utf-8"))

            changed, count = convert_file_to_absolute(md)
            assert changed and count == 1
            out = md.read_bytes().decode("utf-8")
            assert out == f"Grüße\n![ü]({img.resolve()})\n"
        finally:
            _locale.setlocale(_locale.LC_ALL, saved)
