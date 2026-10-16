import pytest

pytestmark = pytest.mark.unit

# tests/unit/test_generate_audiobook_pipeline.py
#
# The pipeline from an EPUB or a Markdown directory to the chapter MP3s, the
# merge through ffmpeg and the command line, without a TTS engine, a network
# or ffmpeg: a fake adapter records what it is asked to speak, subprocess.run
# is a stand-in whose command is asserted on, EPUBs are built with zipfile.

import subprocess
import sys
import zipfile
from pathlib import Path
from types import ModuleType

import ebooklib.epub
import yaml

from manuscripta.audiobook import generator
from manuscripta.audiobook.generator import (
    _clean_and_speak,
    _derive_book_title,
    _derive_voice_short_name,
    _path_or_none,
    _preview_merged_name,
    check_engine_dependencies,
    collect_files_in_order,
    extract_chapters_from_epub,
    generate_audio_from_epub,
    generate_audio_from_markdown,
    get_tts_adapter,
    list_chapters_from_epub,
    main,
    merge_audiobook,
)
from manuscripta.audiobook.tts.base import TTSAdapter

MP3_BYTES = b"ID3fake"


# --- Fakes and builders ------------------------------------------------------


class FakeTTS(TTSAdapter):
    """Records every synthesize call and writes MP3_BYTES in place of audio.

    The chapters named in ``fail_on`` raise after the partial file is written,
    the way an engine that drops the connection mid-chapter does.
    """

    def __init__(self, voice: str = "en-US-JennyNeural", fail_on=()):
        self.voice = voice
        self.fail_on = set(fail_on)
        self.calls: list[tuple[str, Path]] = []

    def synthesize(self, text: str, output_path: Path) -> None:
        output_path = Path(output_path)
        self.calls.append((text, output_path))
        output_path.write_bytes(MP3_BYTES)
        chapter = self._chapter(output_path)
        if chapter in self.fail_on:
            raise RuntimeError(f"engine down for {chapter}")

    @staticmethod
    def _chapter(output_path: Path) -> str:
        """The chapter name of a target MP3 or of the partial file the
        generator synthesizes into first (".<chapter>.part.mp3")."""
        name = output_path.name
        if name.startswith(".") and name.endswith(".part.mp3"):
            return name[1 : -len(".part.mp3")]
        return output_path.stem

    def list_voices(self, language_code=None):
        return []

    @property
    def texts(self) -> list[str]:
        return [text for text, _ in self.calls]


class FakeFfmpeg:
    """Stands in for subprocess.run: records the command, its keyword
    arguments and the file list ffmpeg would read, and writes the merged file
    the way a successful ffmpeg does."""

    def __init__(self, returncode: int = 0, stderr: str = ""):
        self.returncode = returncode
        self.stderr = stderr
        self.calls: list[tuple[list[str], dict, str]] = []

    def __call__(self, cmd, **kwargs):
        cwd = Path(kwargs["cwd"])
        listed = (cwd / cmd[cmd.index("-i") + 1]).read_text(encoding="utf-8")
        self.calls.append((list(cmd), kwargs, listed))
        if self.returncode == 0:
            (cwd / cmd[-1]).write_bytes(b"merged")
        return subprocess.CompletedProcess(cmd, self.returncode, "", self.stderr)


def _stub_ffmpeg(monkeypatch, present=True, returncode=0, stderr="") -> FakeFfmpeg:
    """ffmpeg on PATH (or not) and subprocess.run replaced by a FakeFfmpeg."""
    fake = FakeFfmpeg(returncode=returncode, stderr=stderr)
    monkeypatch.setattr(
        generator.shutil,
        "which",
        lambda name: "/usr/bin/ffmpeg" if present and name == "ffmpeg" else None,
    )
    monkeypatch.setattr(generator.subprocess, "run", fake)
    return fake


_CONTAINER_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<container version="1.0" '
    'xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
    '<rootfiles><rootfile full-path="OEBPS/content.opf" '
    'media-type="application/oebps-package+xml"/></rootfiles></container>'
)
_XHTML = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>t</title></head>'
    "<body>{body}</body></html>"
)


def write_epub(path: Path, docs: dict[str, str]) -> Path:
    """A minimal EPUB 3 at ``path``: one XHTML document per ``docs`` entry
    (file stem -> inner HTML of its body), in dict order as the spine."""
    manifest = "".join(
        f'<item id="{stem}" href="{stem}.xhtml" media-type="application/xhtml+xml"/>'
        for stem in docs
    )
    spine = "".join(f'<itemref idref="{stem}"/>' for stem in docs)
    opf = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" '
        'unique-identifier="uid">'
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
        '<dc:identifier id="uid">x</dc:identifier><dc:title>T</dc:title>'
        "<dc:language>en</dc:language></metadata>"
        f"<manifest>{manifest}</manifest><spine>{spine}</spine></package>"
    )
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        z.writestr("META-INF/container.xml", _CONTAINER_XML)
        z.writestr("OEBPS/content.opf", opf)
        for stem, body in docs.items():
            z.writestr(f"OEBPS/{stem}.xhtml", _XHTML.format(body=body))
    return path


# Two chapters, as EPUB documents; cleaned they read "One First." / "Two Second."
ONE_TWO = {
    "one": "<h1>One</h1><p>First.</p>",
    "two": "<h1>Two</h1><p>Second.</p>",
}
COVER_ONLY = {"cover": "<img src='c.png'/>"}


def _markdown_source(tmp_path: Path) -> Path:
    """A manuscript directory with the chapters 01-one and 02-two."""
    chapters = tmp_path / "manuscript" / "chapters"
    chapters.mkdir(parents=True)
    (chapters / "01-one.md").write_text("# One\n\nFirst.\n", encoding="utf-8")
    (chapters / "02-two.md").write_text("# Two\n\nSecond.\n", encoding="utf-8")
    return chapters.parent


def _epub_source(tmp_path: Path) -> Path:
    """book.epub with the chapters One and Two."""
    return write_epub(tmp_path / "book.epub", ONE_TWO)


# --- extract_chapters_from_epub ---------------------------------------------

# Each row: the EPUB documents (file stem -> body HTML), the skip patterns and
# the chapter names extracted, in spine order
EXTRACTED_CHAPTERS = [
    pytest.param(
        {"intro": "<h1>Welcome: Home!</h1><p>Hi.</p>"},
        None,
        ["01_Welcome Home"],
        id="title-from-first-heading-without-punctuation",
    ),
    pytest.param(
        {"a": "<h2>Sub</h2><h1>Main</h1><p>x</p>"},
        None,
        ["01_Sub"],
        id="first-heading-in-document-order-wins",
    ),
    pytest.param(
        {"a": "<h3>Third</h3><p>x</p>"}, None, ["01_Third"], id="h3-counts-as-heading"
    ),
    pytest.param(
        {"a": "<h4>Fourth</h4><p>x</p>"}, None, ["01_axhtml"], id="h4-does-not-count"
    ),
    pytest.param(
        {"nohead": "<p>Just a paragraph.</p>"},
        None,
        ["01_noheadxhtml"],
        id="filename-when-no-heading",
    ),
    pytest.param(
        {"a": "<h1></h1><p>x</p>"},
        None,
        ["01_axhtml"],
        id="empty-heading-falls-back-to-filename",
    ),
    pytest.param(
        {**COVER_ONLY, **ONE_TWO},
        None,
        ["01_One", "02_Two"],
        id="textless-document-skipped-and-not-numbered",
    ),
    pytest.param(
        {"blank": "<p>... --- !!!</p>", "one": ONE_TWO["one"]},
        None,
        ["01_One"],
        id="wordless-document-skipped",
    ),
    pytest.param(
        {"a": "<h1>Table of Contents</h1><p>x</p>", **ONE_TWO},
        ["contents"],
        ["01_One", "02_Two"],
        id="skip-pattern-matches-title",
    ),
    pytest.param(
        {"toc": "<h1>Inhalt</h1><p>x</p>", **ONE_TWO},
        ["TOC"],
        ["01_One", "02_Two"],
        id="skip-pattern-matches-filename-case-insensitively",
    ),
    pytest.param(ONE_TWO, ["one", "two"], [], id="all-chapters-skipped"),
    pytest.param(
        {"a": "<h1>" + "A" * 70 + "</h1><p>x</p>"},
        None,
        ["01_" + "A" * 60],
        id="title-cut-at-sixty-characters",
    ),
    pytest.param(
        {"a": "<h1>§§§</h1><p>x</p>"},
        None,
        ["01_chapter"],
        id="symbol-only-title-becomes-chapter",
    ),
]


@pytest.mark.parametrize("docs, skip, names", EXTRACTED_CHAPTERS)
def test_extract_chapters_from_epub(docs, skip, names, tmp_path):
    chapters = extract_chapters_from_epub(write_epub(tmp_path / "b.epub", docs), skip)
    assert [name for name, _ in chapters] == names


def test_extract_chapters_hands_back_the_body_html(tmp_path):
    epub = write_epub(
        tmp_path / "b.epub", {"intro": "<h1>Welcome</h1><p>Hi &amp; bye.</p>"}
    )
    [(_, html)] = extract_chapters_from_epub(epub)
    assert "<h1>Welcome</h1>" in html and "<p>Hi &amp; bye.</p>" in html
    assert "<head>" not in html and "<body" not in html


class _Item:
    def __init__(self, name: str, body):
        self.name, self.body = name, body

    def get_body_content(self):
        return self.body

    def get_name(self):
        return self.name


class _Book:
    def __init__(self, items):
        self.items = items

    def get_items_of_type(self, item_type):
        return list(self.items)


def test_extract_chapters_skips_items_without_a_body(monkeypatch, tmp_path):
    # ebooklib itself answers b"" for a bodiless document; the None guard is
    # for readers that do not, so it is driven with a stand-in book
    book = _Book([_Item("blank.xhtml", None), _Item("one.xhtml", b"<h1>One</h1>")])
    monkeypatch.setattr(ebooklib.epub, "read_epub", lambda path, options=None: book)
    chapters = extract_chapters_from_epub(tmp_path / "b.epub")
    assert [name for name, _ in chapters] == ["01_One"]


# --- check_engine_dependencies ----------------------------------------------

# Each row: engine, the import name made unimportable, the package name and
# the install command the error message names
MISSING_DEPENDENCIES = [
    pytest.param("edge", "edge_tts", "edge-tts", "poetry install", id="edge"),
    pytest.param(
        "google",
        "gtts",
        "gTTS",
        "poetry install --with google-translate",
        id="google",
    ),
    pytest.param(
        "pyttsx3", "pyttsx3", "pyttsx3", "poetry install --with pyttsx3", id="pyttsx3"
    ),
    pytest.param(
        "elevenlabs",
        "elevenlabs",
        "elevenlabs",
        "poetry install --with elevenlabs",
        id="elevenlabs",
    ),
]


@pytest.mark.parametrize("engine, import_name, package, install", MISSING_DEPENDENCIES)
def test_check_engine_dependencies_exits_when_the_package_is_missing(
    engine, import_name, package, install, monkeypatch, capsys
):
    # None in sys.modules makes __import__ raise ModuleNotFoundError
    monkeypatch.setitem(sys.modules, import_name, None)
    with pytest.raises(SystemExit) as exc:
        check_engine_dependencies(engine)
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert f"Error: Required package '{package}' is not installed." in out
    assert f"The '{engine}' TTS engine needs it to work." in out
    assert f"Install it with:\n  {install}\n" in out


# Each row: engine and the module registered as importable (None: none)
SATISFIED_DEPENDENCIES = [
    pytest.param("google", "gtts", id="package-installed"),
    pytest.param("voicestudio", None, id="engine-without-python-package"),
    pytest.param("unknown", None, id="unknown-engine-not-checked"),
]


@pytest.mark.parametrize("engine, import_name", SATISFIED_DEPENDENCIES)
def test_check_engine_dependencies_stays_silent(
    engine, import_name, monkeypatch, capsys
):
    if import_name:
        monkeypatch.setitem(sys.modules, import_name, ModuleType(import_name))
    check_engine_dependencies(engine)
    assert capsys.readouterr().out == ""


# --- get_tts_adapter: the engines whose real classes touch no network -------

# Each row: engine, lang, voice, the adapter class name and the voice the
# adapter reports
ADAPTER_VOICES = [
    pytest.param(
        "edge",
        "de",
        None,
        "EdgeTTSAdapter",
        "de-DE-KatjaNeural",
        id="edge-default-voice-of-the-language",
    ),
    pytest.param(
        "edge",
        "en",
        "en-US-GuyNeural",
        "EdgeTTSAdapter",
        "en-US-GuyNeural",
        id="edge-explicit-voice",
    ),
    pytest.param(
        "voicestudio",
        "de",
        "my-clone",
        "VoiceStudioAdapter",
        "my-clone",
        id="voicestudio-profile",
    ),
]


@pytest.mark.parametrize("engine, lang, voice, class_name, reported", ADAPTER_VOICES)
def test_get_tts_adapter_builds_the_engine(engine, lang, voice, class_name, reported):
    adapter = get_tts_adapter(engine, lang=lang, voice=voice, rate=200)
    assert type(adapter).__name__ == class_name
    assert adapter.voice == reported


# --- _clean_and_speak --------------------------------------------------------

# Each row: the bytes of a pre-existing 01_a.mp3 (None: none), overwrite?,
# does the engine fail?, the return value, the texts synthesized, the bytes of
# 01_a.mp3 afterwards (None: no file) and fragments of the printed lines
SPEAK_DECISIONS = [
    pytest.param(
        None,
        False,
        False,
        True,
        ["Hello world"],
        MP3_BYTES,
        ["Generating: 01_a.mp3 (11 chars, ~2 words)", "Done in "],
        id="generates",
    ),
    pytest.param(
        b"old",
        False,
        False,
        True,
        [],
        b"old",
        ["Exists:     01_a.mp3 (0 KB, use --overwrite to regenerate)"],
        id="existing-kept",
    ),
    pytest.param(
        b"old",
        True,
        False,
        True,
        ["Hello world"],
        MP3_BYTES,
        ["Generating: 01_a.mp3"],
        id="existing-overwritten",
    ),
    pytest.param(
        None,
        False,
        True,
        False,
        ["Hello world"],
        None,
        ["FAILED: engine down for 01_a", "Continuing with next chapter..."],
        id="failure-removes-the-partial-file",
    ),
    pytest.param(
        b"old",
        True,
        True,
        False,
        ["Hello world"],
        b"old",
        ["FAILED: engine down for 01_a"],
        id="failure-while-overwriting-keeps-the-previous-file",
    ),
]


@pytest.mark.parametrize(
    "existing, overwrite, fails, result, texts, afterwards, fragments",
    SPEAK_DECISIONS,
)
def test_clean_and_speak(
    existing, overwrite, fails, result, texts, afterwards, fragments, tmp_path, capsys
):
    mp3 = tmp_path / "01_a.mp3"
    if existing is not None:
        mp3.write_bytes(existing)
    tts = FakeTTS(fail_on=["01_a"] if fails else [])

    assert (
        _clean_and_speak("01_a", "Hello **world**", tmp_path, tts, overwrite=overwrite)
        is result
    )

    assert tts.texts == texts
    assert (mp3.read_bytes() if mp3.exists() else None) == afterwards
    # no partial file stays behind, whichever way the engine went
    assert [p.name for p in tmp_path.iterdir() if p != mp3] == []
    out = capsys.readouterr().out
    for fragment in fragments:
        assert fragment in out


# Each row: index, total and the progress prefix of the status line
PROGRESS_PREFIXES = [
    pytest.param(2, 3, "[2/3] ", id="position-of-total"),
    pytest.param(0, 0, "", id="no-total-no-prefix"),
]


@pytest.mark.parametrize("index, total, prefix", PROGRESS_PREFIXES)
def test_clean_and_speak_progress_prefix(index, total, prefix, tmp_path, capsys):
    _clean_and_speak("01_a", "Hello", tmp_path, FakeTTS(), index=index, total=total)
    assert capsys.readouterr().out.startswith(f"  {prefix}Generating: 01_a.mp3")


def test_clean_and_speak_skips_text_that_is_empty_after_cleanup(tmp_path, capsys):
    tts = FakeTTS()
    raw = "<figure><img src='x.png'/><figcaption>c</figcaption></figure>"
    assert _clean_and_speak("01_a", raw, tmp_path, tts) is False
    assert tts.calls == [] and list(tmp_path.iterdir()) == []
    assert capsys.readouterr().out == "  Skipping 01_a (empty after cleanup)\n"


# --- collect_files_in_order --------------------------------------------------

# Each row: the Markdown files below the input directory, the section order
# and the numbered names collected
COLLECTED_FILES = [
    pytest.param(
        ["b.md", "a.md"], ["b.md", "a.md"], ["01_b", "02_a"], id="files-as-listed"
    ),
    pytest.param(
        ["ch/z.md", "ch/a.md", "intro.md"],
        ["intro.md", "ch"],
        ["01_intro", "02_a", "03_z"],
        id="directory-entry-expands-sorted",
    ),
    pytest.param(
        ["ch/a.md"],
        ["front/toc.md", "ch", "back/x.md"],
        ["01_a"],
        id="missing-entries-skipped",
    ),
    pytest.param(
        ["x/b.md", "a.md"],
        ["nope.md"],
        ["01_a", "02_b"],
        id="nothing-matched-falls-back-to-every-file",
    ),
    pytest.param(["§§.md"], ["§§.md"], ["01_chapter"], id="symbol-only-stem"),
]


@pytest.mark.parametrize("files, order, names", COLLECTED_FILES)
def test_collect_files_in_order(files, order, names, tmp_path):
    for rel in files:
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("x", encoding="utf-8")
    collected = collect_files_in_order(tmp_path, order)
    assert [name for name, _ in collected] == names
    assert all(path.is_file() for _, path in collected)


# --- generate_audio_from_markdown / generate_audio_from_epub ----------------


def test_generate_audio_from_markdown_reports_a_directory_without_files(
    tmp_path, capsys
):
    src = tmp_path / "src"
    src.mkdir()
    out = tmp_path / "out"
    tts = FakeTTS()
    generate_audio_from_markdown(src, out, tts)
    assert capsys.readouterr().out == f"No *.md files found in {src}\n"
    assert out.is_dir() and list(out.iterdir()) == [] and tts.calls == []


# Each row: the source builder, the generator it feeds, the chapter whose
# synthesis fails (None: none), the "Finished:" line and the "Warning:" line
# (None: none)
GENERATION_SUMMARIES = [
    pytest.param(
        _markdown_source,
        generate_audio_from_markdown,
        None,
        "Finished: 2 file(s)",
        None,
        id="markdown-all-good",
    ),
    pytest.param(
        _markdown_source,
        generate_audio_from_markdown,
        "01_01-one",
        "Finished: 1 file(s)",
        "Warning:  1 chapter(s) failed to generate",
        id="markdown-one-failure",
    ),
    pytest.param(
        _epub_source,
        generate_audio_from_epub,
        None,
        "Finished: 2 file(s)",
        None,
        id="epub-all-good",
    ),
    pytest.param(
        _epub_source,
        generate_audio_from_epub,
        "02_Two",
        "Finished: 1 file(s)",
        "Warning:  1 chapter(s) failed to generate",
        id="epub-one-failure",
    ),
]


@pytest.mark.parametrize(
    "source, generate, failing, finished, warning", GENERATION_SUMMARIES
)
def test_generation_summary(
    source, generate, failing, finished, warning, tmp_path, capsys
):
    out = tmp_path / "out"
    tts = FakeTTS(fail_on=[failing] if failing else [])
    generate(source(tmp_path), out, tts)
    lines = capsys.readouterr().out.splitlines()
    finished_lines = [line for line in lines if line.startswith("Finished:")]
    warning_lines = [line for line in lines if line.startswith("Warning:")]
    assert [line[: len(finished)] for line in finished_lines] == [finished]
    assert warning_lines == ([warning] if warning else [])
    assert len(list(out.glob("*.mp3"))) == (1 if failing else 2)


# Each row: the EPUB documents, the skip patterns, the MP3 names written, the
# texts synthesized and fragments of the printed report
EPUB_GENERATION = [
    pytest.param(
        ONE_TWO,
        None,
        ["01_One.mp3", "02_Two.mp3"],
        ["One First.", "Two Second."],
        [
            "Chapters: 2",
            "[1/2] Generating: 01_One.mp3",
            "[2/2] Generating: 02_Two.mp3",
            "Finished: 2 file(s)",
        ],
        id="one-mp3-per-chapter",
    ),
    pytest.param(
        ONE_TWO,
        ["two"],
        ["01_One.mp3"],
        ["One First."],
        ["Chapters: 1", "Skipping: two", "Finished: 1 file(s)"],
        id="skip-patterns-applied-and-announced",
    ),
    pytest.param(
        COVER_ONLY,
        None,
        [],
        [],
        ["No readable chapters found in book.epub"],
        id="no-readable-chapters",
    ),
]


@pytest.mark.parametrize("docs, skip, mp3s, texts, fragments", EPUB_GENERATION)
def test_generate_audio_from_epub(docs, skip, mp3s, texts, fragments, tmp_path, capsys):
    epub = write_epub(tmp_path / "book.epub", docs)
    out = tmp_path / "nested" / "out"
    tts = FakeTTS()

    generate_audio_from_epub(epub, out, tts, skip)

    assert sorted(p.name for p in out.glob("*.mp3")) == mp3s
    assert tts.texts == texts
    out_text = capsys.readouterr().out
    for fragment in fragments:
        assert fragment in out_text


# --- list_chapters_from_epub -------------------------------------------------

# Each row: the EPUB documents and the lines printed
LISTINGS = [
    pytest.param(
        ONE_TWO,
        [
            "",
            "Chapters in book.epub:",
            "",
            "  01_One",
            "  02_Two",
            "",
            "Total: 2 chapter(s)",
            "Use --skip to exclude chapters by keyword, e.g. --skip toc,cover,imprint",
        ],
        id="numbered-names-and-skip-hint",
    ),
    pytest.param(
        COVER_ONLY, ["No readable chapters found in book.epub"], id="nothing-readable"
    ),
]


@pytest.mark.parametrize("docs, lines", LISTINGS)
def test_list_chapters_from_epub(docs, lines, tmp_path, capsys):
    list_chapters_from_epub(write_epub(tmp_path / "book.epub", docs))
    assert capsys.readouterr().out.splitlines() == lines


# --- Naming helpers ----------------------------------------------------------

# Each row: the voice id and its short name
VOICE_SHORT_NAMES = [
    pytest.param("de-DE-ConradNeural", "Conrad", id="neural-suffix-dropped"),
    pytest.param("en-US-AvaMultilingualNeural", "Ava", id="multilingual-dropped-too"),
    pytest.param("de-DE-Neural", "Neural", id="nothing-left-keeps-last-part"),
    pytest.param("Anna", "Anna", id="plain-name-unchanged"),
    pytest.param("my-clone", "my-clone", id="two-parts-unchanged"),
]


@pytest.mark.parametrize("voice, short", VOICE_SHORT_NAMES)
def test_derive_voice_short_name(voice, short):
    assert _derive_voice_short_name(voice) == short


# Each row: the project directory below tmp_path holding the input ("": the
# input sits directly under the file system root and is not created), the
# input name, is it a directory?, the title derived. The working directory is
# a decoy project throughout: the title comes from the input, not from cwd.
BOOK_TITLES = [
    pytest.param(
        "eternity-ebook", "manuscript", True, "eternity-audiobook", id="ebook-suffix"
    ),
    pytest.param("my_ebook", "book.epub", False, "my_audiobook", id="_ebook-suffix"),
    pytest.param("novel", "book.epub", False, "novel", id="other-names-unchanged"),
    pytest.param("", "book.epub", False, "book", id="under-root-the-file-stem"),
    pytest.param("", "manuscript", True, "manuscript", id="under-root-the-directory"),
]


@pytest.mark.parametrize("project_name, input_name, is_dir, title", BOOK_TITLES)
def test_derive_book_title(
    project_name, input_name, is_dir, title, tmp_path, monkeypatch
):
    decoy = tmp_path / "other-ebook"
    decoy.mkdir()
    monkeypatch.chdir(decoy)
    if not project_name:
        assert _derive_book_title(Path("/") / input_name) == title
        return
    input_path = tmp_path / project_name / input_name
    if is_dir:
        input_path.mkdir(parents=True)
    else:
        input_path.parent.mkdir()
        input_path.write_bytes(b"")
    assert _derive_book_title(input_path) == title


# Each row: voice, title (None: derived), is the manuscript folder of the
# project "eternity-ebook" given as input path?, the merged file name previewed
MERGED_NAMES = [
    pytest.param(
        "de-DE-ConradNeural",
        "Die Ewigkeit: Band 1!",
        False,
        "Conrad_Die_Ewigkeit_Band_1.mp3",
        id="title-sanitized",
    ),
    pytest.param(
        "en-US-JennyNeural", None, False, "Jenny_audiobook.mp3", id="no-title-no-input"
    ),
    pytest.param(
        "en-US-JennyNeural",
        None,
        True,
        "Jenny_eternity-audiobook.mp3",
        id="no-title-derived-from-project",
    ),
    pytest.param(
        "Anna",
        "  spaced  out  ",
        False,
        "Anna_spaced__out.mp3",
        id="spaces-kept-inside",
    ),
]


@pytest.mark.parametrize("voice, title, with_input, name", MERGED_NAMES)
def test_preview_merged_name(voice, title, with_input, name, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    input_path = tmp_path / "eternity-ebook" / "manuscript" if with_input else None
    assert _preview_merged_name(voice, title=title, input_path=input_path) == name


# Each row: a config value and the Path it becomes (None: none)
PATHS_OR_NONE = [
    pytest.param(None, None, id="missing"),
    pytest.param("", None, id="empty"),
    pytest.param("   ", None, id="blank"),
    pytest.param("out/dir", Path("out/dir"), id="relative-path"),
    pytest.param("  x.epub  ", Path("x.epub"), id="surrounding-space-stripped"),
    pytest.param(7, Path("7"), id="non-string-converted"),
]


@pytest.mark.parametrize("value, path", PATHS_OR_NONE)
def test_path_or_none(value, path):
    assert _path_or_none(value) == path


# --- merge_audiobook ---------------------------------------------------------

# Each row: the files in the output directory, voice, title, the merge file
# name given (None: auto name), the merged file name and the chapter files
# listed for ffmpeg, in order
MERGES = [
    pytest.param(
        ["01_a.mp3", "02_b.mp3"],
        "de-DE-ConradNeural",
        "Eternity",
        None,
        "Conrad_Eternity.mp3",
        ["01_a.mp3", "02_b.mp3"],
        id="auto-name-from-voice-and-title",
    ),
    pytest.param(
        ["01_a.mp3"],
        "en-US-JennyNeural",
        None,
        None,
        "Jenny_audiobook.mp3",
        ["01_a.mp3"],
        id="auto-name-without-title-or-input",
    ),
    pytest.param(
        ["01_a.mp3"],
        "en-US-JennyNeural",
        "ignored",
        "my-book.mp3",
        "my-book.mp3",
        ["01_a.mp3"],
        id="explicit-filename-wins",
    ),
    pytest.param(
        ["01_a.mp3"],
        "en-US-JennyNeural",
        None,
        "my-book",
        "my-book.mp3",
        ["01_a.mp3"],
        id="explicit-filename-gets-extension",
    ),
    pytest.param(
        ["02_b.mp3", "01_a.mp3", "Jenny_old.mp3", "notes.txt"],
        "en-US-JennyNeural",
        None,
        None,
        "Jenny_audiobook.mp3",
        ["01_a.mp3", "02_b.mp3"],
        id="only-numbered-chapters-in-order",
    ),
]


@pytest.mark.parametrize(
    "files, voice, title, merge_filename, merged_name, listed_files", MERGES
)
def test_merge_audiobook_runs_ffmpeg_concat(
    files,
    voice,
    title,
    merge_filename,
    merged_name,
    listed_files,
    tmp_path,
    monkeypatch,
    capsys,
):
    out = tmp_path / "out"
    out.mkdir()
    for name in files:
        (out / name).write_bytes(MP3_BYTES)
    ffmpeg = _stub_ffmpeg(monkeypatch)

    result = merge_audiobook(out, voice, title=title, merge_filename=merge_filename)

    assert result == out / merged_name and result.read_bytes() == b"merged"
    [(cmd, kwargs, listed)] = ffmpeg.calls
    assert cmd == [
        "ffmpeg",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        ".filelist.txt",
        "-c",
        "copy",
        merged_name,
    ]
    assert kwargs == {"capture_output": True, "text": True, "cwd": str(out.resolve())}
    assert listed == "".join(f"file '{name}'\n" for name in listed_files)
    assert not (out / ".filelist.txt").exists()
    out_text = capsys.readouterr().out
    assert f"Merging {len(listed_files)} chapter(s) into {merged_name}..." in out_text
    assert f"Merged:  {out / merged_name}" in out_text


# Each row: ffmpeg on PATH?, its return code, its stderr and the error text
# the output ends with
MERGE_FAILURES = [
    pytest.param(
        False,
        0,
        "",
        "Error: ffmpeg not found. Install it to merge chapters.\n"
        "  Ubuntu: sudo apt install ffmpeg\n",
        id="ffmpeg-missing",
    ),
    pytest.param(
        True,
        1,
        "version header\nl1\nl2\nl3\nl4\nl5\n",
        "Error: ffmpeg merge failed:\nl1\nl2\nl3\nl4\nl5\n",
        id="last-five-stderr-lines",
    ),
    pytest.param(
        True, 1, "", "Error: ffmpeg merge failed:\nUnknown error\n", id="empty-stderr"
    ),
]


@pytest.mark.parametrize("present, returncode, stderr, error", MERGE_FAILURES)
def test_merge_audiobook_failures(
    present, returncode, stderr, error, tmp_path, monkeypatch, capsys
):
    out = tmp_path / "out"
    out.mkdir()
    (out / "01_a.mp3").write_bytes(MP3_BYTES)
    ffmpeg = _stub_ffmpeg(
        monkeypatch, present=present, returncode=returncode, stderr=stderr
    )

    assert merge_audiobook(out, "en-US-JennyNeural") is None

    assert len(ffmpeg.calls) == (1 if present else 0)
    assert sorted(p.name for p in out.iterdir()) == ["01_a.mp3"]
    assert capsys.readouterr().out.endswith(error)


def test_merge_audiobook_without_chapter_files(tmp_path, monkeypatch, capsys):
    out = tmp_path / "out"
    out.mkdir()
    (out / "Jenny_old.mp3").write_bytes(MP3_BYTES)
    ffmpeg = _stub_ffmpeg(monkeypatch)
    assert merge_audiobook(out, "en-US-JennyNeural") is None
    assert ffmpeg.calls == []
    assert capsys.readouterr().out == "No chapter files found to merge.\n"


# --- main --------------------------------------------------------------------


class AdapterFactory:
    """Stands in for get_tts_adapter: records the engine arguments and hands
    out a FakeTTS whose voice falls back to the Edge default like the real
    adapter does."""

    def __init__(self):
        self.calls: list[tuple] = []
        self.adapters: list[FakeTTS] = []

    def __call__(self, engine, lang, voice, rate):
        self.calls.append((engine, lang, voice, rate))
        tts = FakeTTS(voice=voice or "en-US-JennyNeural")
        self.adapters.append(tts)
        return tts

    @property
    def texts(self) -> list[str]:
        return [text for tts in self.adapters for text in tts.texts]


def _project(tmp_path: Path, monkeypatch) -> Path:
    """The project directory "eternity-ebook" as working directory, with the
    two-chapter manuscript and the same two chapters as book.epub."""
    root = tmp_path / "eternity-ebook"
    root.mkdir()
    _markdown_source(root)
    _epub_source(root)
    monkeypatch.chdir(root)
    return root


def _settings(root: Path, mapping: dict, rel="config/voice-settings.yaml") -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(mapping), encoding="utf-8")
    return path


def _prepare_main(monkeypatch, argv: list[str]) -> AdapterFactory:
    """The command line set and the adapter factory replaced; main() is the
    caller's to run."""
    factory = AdapterFactory()
    monkeypatch.setattr(generator, "get_tts_adapter", factory)
    monkeypatch.setattr(sys, "argv", ["generate-audiobook", *argv])
    return factory


# Each row: the command line, the voice settings written (path, mapping; None:
# none), the MP3 files written relative to the project, the (engine, lang,
# voice, rate) the adapter was built with and fragments of the printed summary
MAIN_RUNS = [
    pytest.param(
        ["--input", "manuscript", "--output", "out"],
        None,
        ["out/01_01-one.mp3", "out/02_02-two.mp3"],
        ("edge", "en", None, 200),
        [
            "  Engine:   edge\n  Language: en\n  Voice:    en-US-JennyNeural\n",
            "Files to process (2):\n  01_01-one.mp3\n  02_02-two.mp3\n",
            "Finished: 2 file(s)",
        ],
        id="markdown-directory",
    ),
    pytest.param(
        ["--input", "book.epub", "--output", "out", "--skip", "two, ,"],
        None,
        ["out/01_One.mp3"],
        ("edge", "en", None, 200),
        [
            "Files to process (1):\n  01_One.mp3\n",
            "Skipping: two",
            "Finished: 1 file(s)",
        ],
        id="epub-with-cli-skip",
    ),
    pytest.param(
        [],
        (
            "config/voice-settings.yaml",
            {
                "input": "book.epub",
                "output": "out",
                "engine": "edge",
                "language": "de",
                "voice": "de-DE-ConradNeural",
                "rate": 150,
                "skip": ["one"],
            },
        ),
        ["out/01_Two.mp3"],
        ("edge", "de", "de-DE-ConradNeural", 150),
        [
            "  Loaded settings from: config/voice-settings.yaml",
            "  Settings: config/voice-settings.yaml",
            "  Voice:    de-DE-ConradNeural",
            "Skipping: one",
        ],
        id="settings-autodetected",
    ),
    pytest.param(
        [
            "--settings",
            "voices/custom.yaml",
            "--input",
            "manuscript",
            "--output",
            "out",
            "--lang",
            "el",
            "--voice",
            "el-GR-NestorasNeural",
            "--rate",
            "90",
        ],
        (
            "voices/custom.yaml",
            {"input": "book.epub", "language": "de", "voice": "x", "rate": 150},
        ),
        ["out/01_01-one.mp3", "out/02_02-two.mp3"],
        ("edge", "el", "el-GR-NestorasNeural", 90),
        ["  Loaded settings from: voices/custom.yaml", "  Language: el"],
        id="cli-overrides-settings",
    ),
    pytest.param(
        [],
        None,
        ["audiobook/output/01_01-one.mp3", "audiobook/output/02_02-two.mp3"],
        ("edge", "en", None, 200),
        ["Source:  manuscript", "Output:  audiobook/output"],
        id="defaults-manuscript-and-audiobook-output",
    ),
]


@pytest.mark.parametrize("argv, settings, mp3s, adapter_args, fragments", MAIN_RUNS)
def test_main_generates(
    argv, settings, mp3s, adapter_args, fragments, tmp_path, monkeypatch, capsys
):
    root = _project(tmp_path, monkeypatch)
    if settings:
        _settings(root, settings[1], settings[0])
    factory = _prepare_main(monkeypatch, argv)

    main()

    assert factory.calls == [adapter_args]
    assert sorted(str(p.relative_to(root)) for p in root.rglob("*.mp3")) == mp3s
    out = capsys.readouterr().out
    for fragment in fragments:
        assert fragment in out


# Each row: the extra command line, the voice settings (None: none), the
# "Merge to:" line of the summary (None: none), the merged file ffmpeg
# writes (None: no merge) and is main run from outside the project, with
# absolute --input and --output, instead of from the project with relative ones?
MAIN_MERGES = [
    pytest.param(
        ["--merge"],
        None,
        "  Merge to: Jenny_eternity-audiobook.mp3",
        "Jenny_eternity-audiobook.mp3",
        False,
        id="auto-name-from-voice-and-project",
    ),
    pytest.param(
        ["--merge"],
        None,
        "  Merge to: Jenny_eternity-audiobook.mp3",
        "Jenny_eternity-audiobook.mp3",
        True,
        id="auto-name-from-the-input-not-the-cwd",
    ),
    pytest.param(
        ["--merge", "--voice", "de-DE-ConradNeural", "--title", "Die Ewigkeit"],
        None,
        "  Merge to: Conrad_Die_Ewigkeit.mp3",
        "Conrad_Die_Ewigkeit.mp3",
        False,
        id="voice-and-title",
    ),
    pytest.param(
        ["--merge", "--merge-filename", "final"],
        None,
        "  Merge to: final.mp3",
        "final.mp3",
        False,
        id="merge-filename-gets-extension",
    ),
    pytest.param(
        [],
        {"merge": True, "merge_filename": "book.mp3"},
        "  Merge to: book.mp3",
        "book.mp3",
        False,
        id="merge-from-settings",
    ),
    pytest.param(
        [],
        {"merge": True, "title": "Config Title"},
        "  Merge to: Jenny_Config_Title.mp3",
        "Jenny_Config_Title.mp3",
        False,
        id="title-from-settings",
    ),
    pytest.param([], None, None, None, False, id="no-merge"),
]


@pytest.mark.parametrize("argv, settings, merge_line, merged, outside", MAIN_MERGES)
def test_main_merges(
    argv, settings, merge_line, merged, outside, tmp_path, monkeypatch, capsys
):
    root = _project(tmp_path, monkeypatch)
    if settings:
        _settings(root, settings)
    if outside:
        elsewhere = tmp_path / "other-ebook"
        elsewhere.mkdir()
        monkeypatch.chdir(elsewhere)
        paths = ["--input", str(root / "manuscript"), "--output", str(root / "out")]
    else:
        paths = ["--input", "manuscript", "--output", "out"]
    ffmpeg = _stub_ffmpeg(monkeypatch)
    _prepare_main(monkeypatch, [*paths, *argv])

    main()

    out_text = capsys.readouterr().out
    chapters = ["01_01-one.mp3", "02_02-two.mp3"]
    if merge_line is None:
        assert "Merge to:" not in out_text and ffmpeg.calls == []
        assert sorted(p.name for p in (root / "out").iterdir()) == chapters
        return
    assert merge_line in out_text
    [(cmd, kwargs, listed)] = ffmpeg.calls
    # ffmpeg runs inside the output directory, resolved to an absolute path
    assert cmd[-1] == merged and kwargs["cwd"] == str((root / "out").resolve())
    assert listed == "".join(f"file '{name}'\n" for name in chapters)
    assert (root / "out" / merged).read_bytes() == b"merged"


def _unimportable(name: str):
    """A preparation making ``name`` unimportable."""

    def prepare(monkeypatch, root: Path):
        monkeypatch.setitem(sys.modules, name, None)

    return prepare


def _plain_file(name: str):
    """A preparation writing a plain text file ``name`` into the project."""

    def prepare(monkeypatch, root: Path):
        (root / name).write_text("x", encoding="utf-8")

    return prepare


# Each row: the command line, a preparation of the project (None: none), the
# exception raised (type, message pattern; None: main returns), was an adapter
# built?, fragments of what was printed. No MP3 is written in any row.
MAIN_STOPS = [
    pytest.param(
        ["--input", "book.epub", "--list-chapters"],
        None,
        None,
        False,
        ["Chapters in book.epub:", "  01_One\n  02_Two\n", "Total: 2 chapter(s)"],
        id="list-chapters",
    ),
    pytest.param(
        ["--input", "manuscript", "--list-chapters"],
        None,
        None,
        False,
        ["--list-chapters is only supported for .epub files"],
        id="list-chapters-needs-an-epub",
    ),
    pytest.param(
        ["--engine", "google"],
        _unimportable("gtts"),
        (SystemExit, "1"),
        False,
        ["Error: Required package 'gTTS' is not installed."],
        id="engine-package-missing",
    ),
    pytest.param(
        ["--input", "book.epub"],
        _unimportable("bs4"),
        None,
        False,
        [
            "Error: EPUB support requires 'ebooklib' and 'beautifulsoup4'.",
            "poetry add ebooklib beautifulsoup4",
        ],
        id="epub-support-missing",
    ),
    pytest.param(
        ["--input", "nowhere"],
        None,
        (
            ValueError,
            r"--input must be a directory with \*\.md files or a \.epub file, "
            r"got: nowhere",
        ),
        True,
        ["  Audiobook Generator"],
        id="input-does-not-exist",
    ),
    pytest.param(
        ["--input", "notes.txt"],
        _plain_file("notes.txt"),
        (ValueError, r"got: notes\.txt"),
        True,
        ["  Audiobook Generator"],
        id="input-is-neither-directory-nor-epub",
    ),
]


@pytest.mark.parametrize("argv, prepare, raises, adapter_built, fragments", MAIN_STOPS)
def test_main_stops(
    argv, prepare, raises, adapter_built, fragments, tmp_path, monkeypatch, capsys
):
    root = _project(tmp_path, monkeypatch)
    if prepare:
        prepare(monkeypatch, root)
    factory = _prepare_main(monkeypatch, argv)

    if raises is None:
        main()
    else:
        with pytest.raises(raises[0], match=raises[1]):
            main()

    assert bool(factory.calls) is adapter_built
    assert factory.texts == [] and list(root.rglob("*.mp3")) == []
    assert not (root / "audiobook").exists()
    out = capsys.readouterr().out
    for fragment in fragments:
        assert fragment in out


# Each row: the extra command line, the section_order of the settings (None:
# none) and the files previewed and written. order.yaml lists 02-two before
# 01-one.
MAIN_SECTION_ORDERS = [
    pytest.param([], None, ["01_01-one.mp3", "02_02-two.mp3"], id="default-order"),
    pytest.param(
        ["--section-order", "order.yaml"],
        None,
        ["01_02-two.mp3", "02_01-one.mp3"],
        id="order-file",
    ),
    pytest.param([], ["chapters/02-two.md"], ["01_02-two.mp3"], id="settings-order"),
    pytest.param(
        ["--section-order", "order.yaml"],
        ["chapters/02-two.md"],
        ["01_02-two.mp3", "02_01-one.mp3"],
        id="order-file-wins-over-settings",
    ),
    pytest.param(
        ["--section-order", "missing.yaml"],
        ["chapters/02-two.md"],
        ["01_02-two.mp3"],
        id="missing-order-file-falls-back-to-settings",
    ),
]


@pytest.mark.parametrize("argv, section_order, names", MAIN_SECTION_ORDERS)
def test_main_section_order(argv, section_order, names, tmp_path, monkeypatch, capsys):
    root = _project(tmp_path, monkeypatch)
    (root / "order.yaml").write_text(
        yaml.safe_dump(["chapters/02-two.md", "chapters/01-one.md"]), encoding="utf-8"
    )
    if section_order:
        _settings(root, {"section_order": section_order})
    _prepare_main(monkeypatch, ["--input", "manuscript", "--output", "out", *argv])

    main()

    preview = f"Files to process ({len(names)}):\n" + "".join(
        f"  {name}\n" for name in names
    )
    assert preview in capsys.readouterr().out
    assert sorted(p.name for p in (root / "out").iterdir()) == sorted(names)


# Each row: --overwrite given?, overwrite in the settings?, the status line of
# the existing 01_01-one.mp3 and the texts synthesized
MAIN_OVERWRITES = [
    pytest.param(
        False,
        False,
        "[1/2] Exists:     01_01-one.mp3 (0 KB, use --overwrite to regenerate)",
        ["Two\nSecond."],
        id="existing-kept",
    ),
    pytest.param(
        True,
        False,
        "[1/2] Generating: 01_01-one.mp3",
        ["One\nFirst.", "Two\nSecond."],
        id="cli-overwrite",
    ),
    pytest.param(
        False,
        True,
        "[1/2] Generating: 01_01-one.mp3",
        ["One\nFirst.", "Two\nSecond."],
        id="settings-overwrite",
    ),
]


@pytest.mark.parametrize("cli, settings, status, texts", MAIN_OVERWRITES)
def test_main_overwrite(cli, settings, status, texts, tmp_path, monkeypatch, capsys):
    root = _project(tmp_path, monkeypatch)
    (root / "out").mkdir()
    (root / "out" / "01_01-one.mp3").write_bytes(b"old")
    if settings:
        _settings(root, {"overwrite": True})
    argv = ["--input", "manuscript", "--output", "out"] + (
        ["--overwrite"] if cli else []
    )
    factory = _prepare_main(monkeypatch, argv)

    main()

    out = capsys.readouterr().out
    assert "  01_01-one.mp3 [exists]\n  02_02-two.mp3\n" in out
    assert status in out
    assert factory.texts == texts
