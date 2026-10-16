import pytest

pytestmark = pytest.mark.unit

# tests/test_generate_audiobook.py

from functools import partial
from types import ModuleType
import sys
from manuscripta.audiobook.tts.base import TTSAdapter
from pathlib import Path

from manuscripta.audiobook.generator import (
    clean_markdown_for_tts,
    generate_audio_from_markdown,
    get_tts_adapter,
    normalize_single_newlines,
    strip_emphasis_markers,
)


class DummyTTS(TTSAdapter):
    def __init__(self) -> None:
        self.calls: list[tuple[str, Path]] = []

    def synthesize(self, text: str, output_path: Path) -> None:
        self.calls.append((text, output_path))
        output_path.write_bytes(b"\x00")

    def list_voices(self, language_code=None):
        return []


def write(p: Path, s: str):
    p.write_text(s, encoding="utf-8")


# Each row: the Markdown files of the source directory with their text, the
# output directory below tmp_path, the MP3 files generated (sorted) and the
# text each one was synthesized from, in that order
GENERATE_CASES = [
    pytest.param(
        {
            "01.md": "<figure><img src='x.png'/><figcaption>c</figcaption></figure>",
            "02.md": "Hello **world** [link](https://e.x)",
        },
        ("out",),
        ["02_02.mp3"],
        ["Hello world link"],
        id="skips-empty-after-cleanup",
    ),
    pytest.param(
        {"chapter.md": "# Title\nSome text."},
        ("nested", "audio"),
        ["01_chapter.mp3"],
        ["Title Some text."],
        id="output-directory-is-created",
    ),
    # After cleanup this is only punctuation/newlines → should skip
    pytest.param(
        {"x.md": "![i](a.png)\n<figure>...</figure>\n(**)**\n"},
        ("out",),
        [],
        [],
        id="skips-meaningless-text",
    ),
]


@pytest.mark.parametrize("sources, out_parts, mp3_names, texts", GENERATE_CASES)
def test_generate_audio_from_markdown(
    sources, out_parts, mp3_names, texts, tmp_path: Path
):
    src = tmp_path / "src"
    src.mkdir()
    for name, text in sources.items():
        write(src / name, text)
    out = tmp_path.joinpath(*out_parts)

    tts = DummyTTS()
    generate_audio_from_markdown(src, out, tts)

    assert sorted(p.name for p in out.glob("*.mp3")) == mp3_names
    assert [text for text, _ in tts.calls] == texts


# --- get_tts_adapter coverage: fake adapter modules so we don't need real deps


def _install_fake_adapter_module(
    monkeypatch, module_name: str, class_name: str, raises_on_kwargs=None
):
    """
    Install a minimal fake adapter module into sys.modules:
    module_name (e.g., 'scripts.tts.gtts_adapter') containing class_name
    (e.g., 'GoogleTTSAdapter') with .speak() that writes bytes.
    If raises_on_kwargs is provided (callable), it may raise in __init__.

    Uses ``monkeypatch.setitem`` so the sys.modules replacement is
    auto-undone at test teardown. Plain ``sys.modules[name] = mod`` is
    persistent across tests in the same process and was the root cause
    of the polluter incident documented in TESTING.md §12.
    """
    mod = ModuleType(module_name)

    class _FakeAdapter:
        def __init__(self, *args, **kwargs):
            if raises_on_kwargs and raises_on_kwargs(kwargs):
                raise ValueError("Missing API key")
            self.kwargs = kwargs

        def synthesize(self, text, output_path: Path):
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            Path(output_path).write_bytes(b"FAKE_MP3")

        def speak(self, text, output_path: Path):
            self.synthesize(text, output_path)

        def list_voices(self, language_code=None):
            return []

    setattr(mod, class_name, _FakeAdapter)
    monkeypatch.setitem(sys.modules, module_name, mod)


def _fake(module: str, class_name: str, raises_on_kwargs=None):
    """A builder installing the fake ``class_name`` as the tts.<module> adapter."""
    return partial(
        _install_fake_adapter_module,
        module_name=f"manuscripta.audiobook.tts.{module}",
        class_name=class_name,
        raises_on_kwargs=raises_on_kwargs,
    )


def _needs_api_key(kwargs) -> bool:
    """Fake ElevenLabs adapter that raises if api_key missing."""
    return not kwargs.get("api_key")


# Each row: the fake adapter to install (None: none), ELEVENLABS_API_KEY (None:
# unset), engine, voice, rate, the ValueError message (None: an adapter with a
# synthesize method comes back)
GET_TTS_ADAPTER_CASES = [
    pytest.param(
        _fake("google_translate_adapter", "GoogleTranslateTTSAdapter"),
        None,
        "google",
        None,
        200,
        None,
        id="google",
    ),
    pytest.param(
        _fake("pyttsx3_adapter", "Pyttsx3Adapter"),
        None,
        "pyttsx3",
        "Alice",
        180,
        None,
        id="pyttsx3",
    ),
    # Without key -> should raise
    pytest.param(
        _fake("elevenlabs_adapter", "ElevenLabsAdapter", _needs_api_key),
        None,
        "elevenlabs",
        None,
        200,
        "Missing API key",
        id="elevenlabs-without-key",
    ),
    # With key -> should construct
    pytest.param(
        _fake("elevenlabs_adapter", "ElevenLabsAdapter", _needs_api_key),
        "XYZ",
        "elevenlabs",
        "Rachel",
        200,
        None,
        id="elevenlabs-with-key",
    ),
    pytest.param(
        None,
        None,
        "unknown",
        None,
        200,
        "Unsupported engine: unknown",
        id="invalid-engine",
    ),
]


@pytest.mark.parametrize(
    "install, api_key, engine, voice, rate, error", GET_TTS_ADAPTER_CASES
)
def test_get_tts_adapter(install, api_key, engine, voice, rate, error, monkeypatch):
    if install is not None:
        install(monkeypatch)
    if api_key is None:
        monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    else:
        monkeypatch.setenv("ELEVENLABS_API_KEY", api_key)

    if error is not None:
        with pytest.raises(ValueError, match=error):
            get_tts_adapter(engine, lang="en", voice=voice, rate=rate)
    else:
        adapter = get_tts_adapter(engine, lang="en", voice=voice, rate=rate)
        assert hasattr(adapter, "synthesize")


# --- Emphasis stripping tests ------------------------------------------------

# Each row: text and the text with its emphasis markers stripped
STRIP_EMPHASIS_CASES = [
    pytest.param("*hello*", "hello", id="single-line-italic"),
    pytest.param("**hello**", "hello", id="single-line-bold"),
    pytest.param("_hello_", "hello", id="single-line-underscore"),
    pytest.param("__hello__", "hello", id="single-line-double-underscore"),
    pytest.param("***hello***", "hello", id="bold-italic-combined"),
    pytest.param(
        "*Als Nächstes untersuchen wir,\nwas geschieht.*",
        "Als Nächstes untersuchen wir,\nwas geschieht.",
        id="multiline-italic",
    ),
    pytest.param(
        "**Dieser Text geht\nüber zwei Zeilen.**",
        "Dieser Text geht\nüber zwei Zeilen.",
        id="multiline-bold",
    ),
    pytest.param(
        "*eins* normal *zwei*", "eins normal zwei", id="multiple-emphasis-on-same-line"
    ),
    pytest.param(
        "Normal **bold** und *italic* text.",
        "Normal bold und italic text.",
        id="mixed-emphasis",
    ),
]


@pytest.mark.parametrize("text, expected", STRIP_EMPHASIS_CASES)
def test_strip_emphasis_markers(text, expected):
    assert strip_emphasis_markers(text) == expected


# --- Newline normalization tests ---------------------------------------------

# Each row: text and the text with its single newlines turned into spaces
NORMALIZE_NEWLINE_CASES = [
    pytest.param(
        "erste Zeile\nzweite Zeile",
        "erste Zeile zweite Zeile",
        id="single-newline-becomes-space",
    ),
    pytest.param(
        "Absatz eins.\n\nAbsatz zwei.",
        "Absatz eins.\nAbsatz zwei.",
        id="paragraph-break-preserved",
    ),
    pytest.param(
        "Satz geht\nweiter hier.\n\nNeuer Absatz mit\nUmbruch.",
        "Satz geht weiter hier.\nNeuer Absatz mit Umbruch.",
        id="mixed-newlines",
    ),
]


@pytest.mark.parametrize("text, expected", NORMALIZE_NEWLINE_CASES)
def test_normalize_single_newlines(text, expected):
    assert normalize_single_newlines(text) == expected


# Each row: text and what the full clean_markdown_for_tts pipeline makes of it
FULL_CLEANUP_CASES = [
    # Emphasis stripping works through the full pipeline
    pytest.param(
        "*Als Nächstes untersuchen wir, was geschieht, wenn dieser Prozess\n"
        "nicht bezeugt wird.*",
        "Als Nächstes untersuchen wir, was geschieht, wenn dieser Prozess "
        "nicht bezeugt wird.",
        id="strip-emphasis",
    ),
    # Soft-wrapped lines should not produce TTS pauses.
    pytest.param(
        "Das Bewusstsein steht\nder Ewigkeit gegenüber.",
        "Das Bewusstsein steht der Ewigkeit gegenüber.",
        id="single-newline-no-pause",
    ),
    # Real paragraph breaks should remain for natural TTS pauses.
    pytest.param(
        "Ende von Absatz eins.\n\nAnfang von Absatz zwei.",
        "Ende von Absatz eins.\nAnfang von Absatz zwei.",
        id="paragraph-break-kept",
    ),
]


@pytest.mark.parametrize("text, expected", FULL_CLEANUP_CASES)
def test_clean_markdown_for_tts(text, expected):
    assert clean_markdown_for_tts(text) == expected
