import pytest

pytestmark = pytest.mark.unit

# tests/test_generate_audiobook_use_cases.py
from pathlib import Path
from types import ModuleType
import sys
import textwrap
from manuscripta.audiobook.tts.base import TTSAdapter

from manuscripta.audiobook.generator import (
    generate_audio_from_markdown,
    get_tts_adapter,
)


class RecordingTTS(TTSAdapter):
    """TTS stub that records calls and writes fake MP3s."""

    def __init__(self):
        self.calls = []

    def synthesize(self, text, out_path: Path):
        self.calls.append((text, Path(out_path)))
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_bytes(b"FAKE_MP3")

    def list_voices(self, language_code=None):
        return []


def w(p: Path, s: str):
    p.write_text(s, encoding="utf-8")


def test_generation_orders_by_filename_and_skips_empty(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir()
    out = tmp_path / "out"

    # Will be emptied by cleaner (figure+image only)
    w(src / "02.md", "<figure><img src='x.png'/><figcaption>c</figcaption></figure>")
    # Minimal but meaningful after cleanup (heading retained without #)
    w(src / "01.md", "# Hello **world** [link](https://e.x)")
    # Becomes only punctuation after cleanup -> skip
    w(src / "03.md", "![i](a.png)\n(**)**\n<em></em>")

    tts = RecordingTTS()
    generate_audio_from_markdown(src, out, tts)

    # Only 01.md should be synthesized; filenames are sorted
    files = sorted(p.name for p in out.glob("*.mp3"))
    assert files == ["01_01.mp3"]
    assert len(tts.calls) == 1
    # Cleaned text should have no markdown noise
    assert tts.calls[0][0].startswith("Hello world link")


def test_nested_output_dir_creation_and_text_content(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir()
    out = tmp_path / "audio" / "book"
    w(
        src / "chapter.md",
        textwrap.dedent(
            """
    ---
    title: meta
    ---
    # Título &amp; Überblick
    ¡Hola&nbsp;mundo! `code ok`
    """
        ),
    )
    tts = RecordingTTS()
    generate_audio_from_markdown(src, out, tts)

    mp3 = out / "01_chapter.mp3"
    assert mp3.exists()
    # Verify content seen by TTS is cleaned
    cleaned = tts.calls[0][0]
    assert "Título & Überblick" in cleaned
    assert "Hola mundo" in cleaned  # nbsp normalized
    assert "`" not in cleaned


# ---------- Engine selection coverage with fakes (no real deps) --------------


def _install_fake(monkeypatch, module_name: str, class_name: str, fail_on_kwargs=None):
    """Install a minimal fake adapter module under sys.modules.

    Uses ``monkeypatch.setitem`` so the sys.modules replacement is
    auto-undone at test teardown — otherwise the fake adapter persists
    across subsequent tests in the same Python process. See TESTING.md
    §12 for the polluter incident this protects against.
    """
    mod = ModuleType(module_name)

    class _Adapter:
        def __init__(self, *a, **kw):
            if callable(fail_on_kwargs) and fail_on_kwargs(kw):
                raise ValueError("Missing API key")

        def synthesize(self, text, out_path: Path):
            Path(out_path).write_bytes(b"FAKE")

        def speak(self, text, out_path: Path):
            self.synthesize(text, out_path)

        def list_voices(self, language_code=None):
            return []

    setattr(mod, class_name, _Adapter)
    monkeypatch.setitem(sys.modules, module_name, mod)


def test_get_tts_adapter_paths(monkeypatch):
    _install_fake(
        monkeypatch,
        "manuscripta.audiobook.tts.google_translate_adapter",
        "GoogleTranslateTTSAdapter",
    )
    _install_fake(
        monkeypatch, "manuscripta.audiobook.tts.pyttsx3_adapter", "Pyttsx3Adapter"
    )

    a = get_tts_adapter("google", lang="en", voice=None, rate=200)
    b = get_tts_adapter("pyttsx3", lang="de", voice="Anna", rate=170)
    assert hasattr(a, "synthesize") and hasattr(b, "synthesize")


def test_get_tts_adapter_elevenlabs_key_required(monkeypatch):
    # Fake module that fails if api_key not passed
    _install_fake(
        monkeypatch,
        "manuscripta.audiobook.tts.elevenlabs_adapter",
        "ElevenLabsAdapter",
        fail_on_kwargs=lambda kw: not kw.get("api_key"),
    )

    # No key -> should raise
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    raised = False
    try:
        get_tts_adapter("elevenlabs", lang="en", voice=None, rate=200)
    except ValueError:
        raised = True
    assert raised

    # With key -> ok
    monkeypatch.setenv("ELEVENLABS_API_KEY", "XYZ")
    adapter = get_tts_adapter("elevenlabs", lang="en", voice="Rachel", rate=200)
    assert hasattr(adapter, "synthesize")


def test_invalid_engine_raises():
    try:
        get_tts_adapter("nope", lang="en", voice=None, rate=200)
        assert False, "Expected ValueError"
    except ValueError:
        pass
