# tests/test_convert_images.py
from pathlib import Path
import re
import pytest

pytestmark = pytest.mark.unit

from manuscripta.images.convert import (
    _parse_ref_defs,
    _replace_inline,
    _replace_reference,
    _split_outside_code,
    _unangle,
    convert_markdown_dir,
    convert_markdown_file,
)

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


# Each row: the Markdown written to the file and the src, alt and caption of
# the one figure it is converted into
FIGURE_CASES = [
    pytest.param(
        "Hello ![Alt](img/cat.png) world.\n",
        "img/cat.png",
        "Alt",
        "Alt",
        id="converts-simple-inline-image",
    ),
    pytest.param(
        '![Hund](pics/dog.jpg "Ein lieber Hund")\n',
        "pics/dog.jpg",
        "Hund",
        "Ein lieber Hund",
        id="uses-title-as-caption-when-present",
    ),
    pytest.param(
        "![A](x.png 'SQ')\n", "x.png", "A", "SQ", id="uses-single-quoted-title"
    ),
    pytest.param(
        "![A](x.png (Par))\n", "x.png", "A", "Par", id="uses-parenthesized-title"
    ),
    pytest.param(
        '![X](<pics/file with spaces.png> "T")\n',
        "pics/file with spaces.png",
        "X",
        "T",
        id="angle-bracket-url-and-spaces-supported",
    ),
    pytest.param(
        '![X](<../weird (1).png> "T")\n',
        "../weird (1).png",
        "X",
        "T",
        id="angle-bracket-url-with-parentheses-supported",
    ),
    pytest.param(
        'Here: ![Logo][app]\n[app]: assets/logo.svg "Brand"\n',
        "assets/logo.svg",
        "Logo",
        "Brand",
        id="reference-style-images-are-resolved",
    ),
    pytest.param(
        'An image: ![Foo][]\n[foo]: img/foo.png "Titel Foo"\n',
        "img/foo.png",
        "Foo",
        "Titel Foo",
        id="reference-empty-id-uses-alt-as-key",
    ),
    pytest.param(
        '![Logo][APP]\n[app]: assets/logo.svg "Brand"\n',
        "assets/logo.svg",
        "Logo",
        "Brand",
        id="reference-id-is-case-insensitive",
    ),
    pytest.param(
        '![L][app]\n[app]: <assets/my logo.svg> "Brand"\n',
        "assets/my logo.svg",
        "L",
        "Brand",
        id="reference-angle-bracket-url-supported",
    ),
]


@pytest.mark.parametrize("text, src, alt, caption", FIGURE_CASES)
def test_converts_to_figure(tmp_path: Path, text, src, alt, caption):
    md = tmp_path / "a.md"
    write(md, text)

    n = convert_markdown_file(md)
    assert n == 1

    out = read(md)
    m = FIG_RE.search(out)
    assert m is not None, f"no match in output:\n{out}"
    assert m.groups() == (src, alt, caption)


# Each row: Markdown that convert_markdown_file leaves untouched, returning 0
UNCHANGED_CASES = [
    pytest.param(
        'Before\n```\n![ALT](img/in_code.png "T")\n```\nAfter\n',
        id="skips-fenced-code-blocks",
    ),
    pytest.param(
        'Before\n~~~\n![ALT](img/in_code.png "T")\n~~~\nAfter\n',
        id="skips-tilde-fenced-code-blocks",
    ),
    pytest.param('Text `![ALT](path/x.png "T")` Text\n', id="skips-inline-code-spans"),
    pytest.param("Oops: ![Bar][missing]\n", id="unknown-reference-is-left-untouched"),
    pytest.param("No image here.\n", id="no-images-no-change"),
]


@pytest.mark.parametrize("text", UNCHANGED_CASES)
def test_leaves_file_unchanged(tmp_path: Path, text):
    md = tmp_path / "u.md"
    write(md, text)

    n = convert_markdown_file(md)
    assert n == 0
    assert read(md) == text


# Each row: the keyword arguments, whether a .bak sidecar exists afterwards,
# whether the file itself is rewritten
WRITE_CASES = [
    pytest.param({}, False, True, id="default-is-no-backup"),
    pytest.param({"backup": True}, True, True, id="backup-when-enabled"),
    pytest.param({"dry_run": True}, False, False, id="dry-run-writes-nothing"),
    # dry-run returns before the backup is taken
    pytest.param(
        {"backup": True, "dry_run": True}, False, False, id="dry-run-skips-backup"
    ),
]


@pytest.mark.parametrize("kwargs, expect_bak, written", WRITE_CASES)
def test_write_and_backup(tmp_path: Path, kwargs, expect_bak, written):
    md = tmp_path / "w.md"
    before = "Start ![A](x.png) End\n"
    write(md, before)
    bak = md.with_suffix(".md.bak")

    n = convert_markdown_file(md, **kwargs)
    assert n == 1
    assert bak.exists() is expect_bak
    if expect_bak:
        assert read(bak) == before  # original preserved in backup
    if written:
        assert FIG_RE.search(read(md))
    else:
        assert read(md) == before


def test_file_not_found_returns_zero(tmp_path: Path):
    missing = tmp_path / "nope.md"
    n = convert_markdown_file(missing)
    assert n == 0


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


# ---------------------------------------------------------------------------
# Phase 4b Pass 2 Commit 9 — mutation-survivor A-category kills.
# Companion B-annotations live in .mutmut/equivalent.yaml under the
# §14.8.1, §14.8.3, §14.8.4, and ad-hoc sections; this test block is the
# A side of the triage. Each row asserts a specific observable contract;
# the comment above it names the mutant(s) it kills.
# ---------------------------------------------------------------------------


# Each row: the raw URL and what _unangle returns. The angle brackets are
# stripped only when BOTH the leading ``<`` and the trailing ``>`` are
# present; a URL with only one of them is returned unchanged.
# Kills _unangle __mutmut_5 (``and`` → ``or`` on the bracket check).
UNANGLE_CASES = [
    pytest.param("<http://example.com>", "http://example.com", id="both-brackets"),
    pytest.param("<broken", "<broken", id="leading-bracket-only"),
    pytest.param("broken>", "broken>", id="trailing-bracket-only"),
    pytest.param("plain.png", "plain.png", id="no-brackets"),
    pytest.param(" <a.png> ", "a.png", id="surrounding-whitespace-stripped"),
]


class TestUnangleContract:
    @pytest.mark.parametrize("url, expected", UNANGLE_CASES)
    def test_unangle(self, url, expected):
        assert _unangle(url) == expected


# Each row: a reference definition, its id, src and title as parsed. Titles
# resolve through the ``title_dq``, ``title_sq`` and ``title_par`` named
# groups; the first match wins (``or or``, not ``or and``).
# Kills _parse_ref_defs __mutmut_18 (``m.group(None)`` raises), __mutmut_19
# (``m.group('XXtitle_sqXX')`` raises), __mutmut_20 (``m.group('TITLE_SQ')``
# raises), __mutmut_21 (``m.group(None)``), __mutmut_22 (``XXtitle_parXX``),
# __mutmut_23 (``TITLE_PAR``) and __mutmut_13 (``or or`` → ``or and``; with
# only title_par the ``and`` mutation collapses to ``None`` where the orig
# returns the parenthesised title).
REF_DEF_CASES = [
    pytest.param(
        "[logo]: img/x.png 'Single Title'\n",
        "logo",
        "img/x.png",
        "Single Title",
        id="single-quoted-title-parses",
    ),
    pytest.param(
        "[pic]: img/y.png (Par Title)\n",
        "pic",
        "img/y.png",
        "Par Title",
        id="parenthesized-title-parses",
    ),
    pytest.param(
        '[logo]: img/x.png "DQ Title"\n',
        "logo",
        "img/x.png",
        "DQ Title",
        id="double-quoted-title-parses",
    ),
    pytest.param("[logo]: img/x.png\n", "logo", "img/x.png", None, id="no-title"),
    pytest.param("[LOGO]: img/x.png\n", "logo", "img/x.png", None, id="id-lowercased"),
    pytest.param(
        '[logo]: <img/my pic.png> "T"\n',
        "logo",
        "img/my pic.png",
        "T",
        id="angle-bracket-src-unangled",
    ),
]


class TestRefDefParsing:
    @pytest.mark.parametrize("text, rid, src, title", REF_DEF_CASES)
    def test_ref_def_parses(self, text, rid, src, title):
        refs = _parse_ref_defs(text)
        assert rid in refs
        assert refs[rid]["src"] == src
        assert refs[rid]["title"] == title


# Each row: the chunk, the number of inline images replaced, fragments the
# result must carry, fragments it must not
INLINE_CASES = [
    # With only a single-quoted title the caption must be the sq title, not
    # None from an ``and``-collapse. Kills _replace_inline __mutmut_15
    # (``or`` → ``and`` on the middle link of the title precedence).
    pytest.param(
        "![A](img/pic.png 'SQ Caption')",
        1,
        ["SQ Caption"],
        [],
        id="single-quoted-title-caption",
    ),
    pytest.param(
        "![A](img/pic.png (Par Caption))",
        1,
        ["Par Caption"],
        [],
        id="parenthesized-title-caption",
    ),
    # ``![](src)`` yields ``alt=""`` in the rendered figure, not a sentinel.
    # Kills _replace_inline __mutmut_8 (``alt or ""`` → ``alt or "XXXX"``).
    pytest.param("![](img/a.png)", 1, ['alt=""'], ["XXXX"], id="empty-alt-preserved"),
    # The per-chunk count accumulates across matches (``count += 1``), it
    # does not reset to 1 per match. Kills _replace_inline __mutmut_31
    # (``count += 1`` → ``count = 1``).
    pytest.param(
        "![A](a.png) and ![B](b.png) and ![C](c.png)",
        3,
        [],
        [],
        id="count-sums-multiple",
    ),
]


class TestReplaceInlineMutationPins:
    @pytest.mark.parametrize("chunk, count, present, absent", INLINE_CASES)
    def test_replace_inline(self, chunk, count, present, absent):
        out, n = _replace_inline(chunk, figure_class=None)
        assert n == count
        for fragment in present:
            assert fragment in out
        for fragment in absent:
            assert fragment not in out


# Each row: the chunk, the reference definitions, the number of reference
# images replaced, fragments the result must carry, fragments it must not
REFERENCE_CASES = [
    # ``![][id]`` yields ``alt=""``, not a sentinel. Kills _replace_reference
    # __mutmut_8 (``alt or ""`` → ``alt or "XXXX"``).
    pytest.param(
        "![][pic]",
        {"pic": {"src": "img/x.png", "title": "T"}},
        1,
        ['alt=""'],
        ["XXXX"],
        id="empty-alt-preserved",
    ),
    # When the ref def carries no title the caption falls back to the alt
    # text, not to ``None``; the caption tag must not render literal "None".
    # Kills _replace_reference __mutmut_24 (``_caption(alt, …)`` →
    # ``_caption(None, …)``); with ``title=None``, _caption returns alt, and
    # the alt must be real, not None.
    pytest.param(
        "![MyAlt][pic]",
        {"pic": {"src": "img/x.png", "title": None}},
        1,
        ["MyAlt"],
        ["<em>None</em>"],
        id="no-title-uses-alt-as-caption",
    ),
    # The per-chunk count accumulates. Kills _replace_reference __mutmut_30
    # (``count += 1`` → ``count = 1``).
    pytest.param(
        "![x][a] ![y][b] ![z][c]",
        {
            "a": {"src": "a.png", "title": "A"},
            "b": {"src": "b.png", "title": "B"},
            "c": {"src": "c.png", "title": "C"},
        },
        3,
        [],
        [],
        id="count-sums-multiple",
    ),
]


class TestReplaceReferenceMutationPins:
    @pytest.mark.parametrize("chunk, refs, count, present, absent", REFERENCE_CASES)
    def test_replace_reference(self, chunk, refs, count, present, absent):
        out, n = _replace_reference(chunk, refs, figure_class=None)
        assert n == count
        for fragment in present:
            assert fragment in out
        for fragment in absent:
            assert fragment not in out

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


# Each row: the text, the code flag of the segments to look in, fragments
# that some segment carrying that flag must contain
SPLIT_CASES = [
    # Plain-text segments between code fences are labelled ``(False, …)``
    # (non-code), so the downstream loop runs image replacement on them.
    # Kills _split_outside_code __mutmut_7 (``(False, …)`` → ``(True, …)``).
    pytest.param(
        "intro text\n\n```\nfenced\n```\n\ntrailing text",
        False,
        ["intro text", "trailing text"],
        id="text-segments-marked-non-code",
    ),
    # A captured code fence carries the full matched text (``m.group(0)``),
    # not just the leading anchor capture group (``m.group(1)`` is
    # ``(^|\n)``, which is empty or a single newline).
    # Kills _split_outside_code __mutmut_11 (``m.group(0)`` → ``m.group(1)``).
    pytest.param(
        "pre\n```python\nprint('hi')\n```\npost",
        True,
        ["print('hi')"],
        id="full-code-fence-preserved-in-segment",
    ),
    # When inline code splits a non-code segment, the surrounding text keeps
    # its non-code label. Kills _split_outside_code __mutmut_24
    # (``(False, seg[...])`` → ``(True, seg[...])`` in the refinement path).
    pytest.param(
        "text before `inline` text after",
        False,
        ["text before", "text after"],
        id="inline-code-refinement-marks-surrounding-text-non-code",
    ),
    pytest.param(
        "text before `inline` text after",
        True,
        ["`inline`"],
        id="inline-code-marked-code",
    ),
]


class TestSplitOutsideCodeMutationPins:
    @pytest.mark.parametrize("text, is_code, fragments", SPLIT_CASES)
    def test_segment_labels(self, text, is_code, fragments):
        segments = [s for flag, s in _split_outside_code(text) if flag == is_code]
        for fragment in fragments:
            assert any(fragment in s for s in segments)


# Each row: the Markdown written to the file, the keyword arguments, the
# count convert_markdown_file returns, fragments the rewritten file must
# carry, fragments it must not
PIPELINE_CASES = [
    pytest.param(
        "![A](x.png)\n",
        {"figure_class": "img-figure"},
        1,
        ['<figure class="img-figure">'],
        [],
        id="applies-figure-class-when-provided",
    ),
    # A fenced code block's contents are written back unchanged: the
    # segment loop appends ``chunk``, not ``None``. Kills convert_markdown_file
    # __mutmut_17 (``converted.append(chunk)`` → ``converted.append(None)``).
    pytest.param(
        "pre ![A](a.png) mid\n\n```python\nx = 1\ny = 2\n```\n\npost",
        {},
        1,
        ["x = 1\ny = 2"],
        ["None"],
        id="code-segment-preserved-verbatim",
    ),
    # The per-segment loop uses ``continue`` to skip code fences without
    # aborting; images after a fence must still be processed.
    # Kills convert_markdown_file __mutmut_18 (``continue`` → ``break``).
    pytest.param(
        "```\ncode\n```\n\n![TailImg](img/tail.png)",
        {},
        1,
        ["TailImg"],
        [],
        id="processing-continues-past-code-fence",
    ),
    # ``figure_class`` is forwarded to _replace_reference, not dropped to
    # ``None``, so the CSS class lands on reference-image figures too.
    # Kills convert_markdown_file __mutmut_27
    # (``_replace_reference(chunk, refs, figure_class)`` →
    # ``_replace_reference(chunk, refs, None)``).
    pytest.param(
        '![Alt][pic]\n\n[pic]: img/x.png "T"\n',
        {"figure_class": "my-fig"},
        1,
        ['class="my-fig"'],
        [],
        id="figure-class-reaches-reference-images",
    ),
    # The per-file total sums image counts across every non-code segment,
    # not just the last one. Kills convert_markdown_file __mutmut_31
    # (``total += c1 + c2`` → ``total = c1 + c2``).
    pytest.param(
        "![A](a.png)\n\n```\ncode\n```\n\n![B](b.png)",
        {},
        2,
        [],
        [],
        id="total-accumulates-across-segments",
    ),
    # Per-segment strings are concatenated with ``""`` (empty) as joiner,
    # not a sentinel. Kills convert_markdown_file __mutmut_40
    # (``"".join(converted)`` → ``"XXXX".join(converted)``).
    pytest.param(
        "pre ![A](a.png)\n\n```\nfenced\n```\n\npost ![B](b.png)",
        {},
        2,
        [],
        ["XXXX"],
        id="segments-joined-without-sentinel-separator",
    ),
]


class TestConvertFilePipelineMutationPins:
    @pytest.mark.parametrize("text, kwargs, count, present, absent", PIPELINE_CASES)
    def test_pipeline(self, tmp_path: Path, text, kwargs, count, present, absent):
        md = tmp_path / "a.md"
        write(md, text)
        n = convert_markdown_file(md, **kwargs)
        assert n == count
        out = read(md)
        for fragment in present:
            assert fragment in out
        for fragment in absent:
            assert fragment not in out

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


# Each row: the keyword arguments of convert_markdown_dir, the total it
# returns for one file holding one image, whether file.md.bak exists
# afterwards, a fragment the file must carry
DIR_CASES = [
    # the file is left as it was
    pytest.param({"dry_run": True}, 1, False, "![A](", id="dry-run-directory"),
    # ``backup=True`` propagates through the dir wrapper to each file call,
    # producing a ``.bak`` sidecar. Kills convert_markdown_dir __mutmut_11
    # (``backup=backup`` → ``backup=None`` in the per-file call).
    pytest.param({"backup": True}, 1, True, "<figure>", id="passes-backup-kwarg"),
    # ``figure_class`` propagates through the dir wrapper to each file call.
    # Kills convert_markdown_dir __mutmut_13 (``figure_class=figure_class``
    # → ``figure_class=None``).
    pytest.param(
        {"figure_class": "dir-fig"},
        1,
        False,
        'class="dir-fig"',
        id="passes-figure-class-kwarg",
    ),
    # The per-file call in the dir wrapper includes every forwarded kwarg
    # explicitly; dropping any of them makes the per-file call use
    # convert_markdown_file's own default for that parameter, silently
    # losing the caller's value. Kills convert_markdown_dir __mutmut_15
    # (``backup=backup`` entry dropped; per-file default ``backup=False``
    # overrides the dir-call's ``backup=True``).
    pytest.param(
        {"backup": True},
        1,
        True,
        "<figure>",
        id="kwarg-drop-silently-uses-per-file-default",
    ),
    # The last forwarded kwarg (``figure_class=``) is present in the
    # per-file call; a trailing-comma-only variant that drops it would
    # silently make every per-file call use the per-file default of
    # ``None``. Kills convert_markdown_dir __mutmut_17 (the last kwarg in
    # the per-file call signature dropped).
    pytest.param(
        {"figure_class": "dir-fig2"},
        1,
        False,
        'class="dir-fig2"',
        id="last-positional-kwarg-forwarded",
    ),
]


class TestConvertDirKwargForwardingMutationPins:
    @pytest.mark.parametrize("kwargs, total, expect_bak, fragment", DIR_CASES)
    def test_forwards_kwargs(self, tmp_path: Path, kwargs, total, expect_bak, fragment):
        f = tmp_path / "file.md"
        write(f, "![A](a.png)")
        assert convert_markdown_dir(tmp_path, **kwargs) == total
        assert (tmp_path / "file.md.bak").exists() is expect_bak
        assert fragment in read(f)
