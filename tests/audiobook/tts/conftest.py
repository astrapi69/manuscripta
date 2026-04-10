"""Shared fixtures for TTS adapter tests."""

import pytest
from pathlib import Path
from manuscripta.audiobook.tts.base import TTSAdapter, VoiceInfo


SAMPLE_TEXT = (
    "Dies ist ein Testtext. Er hat mehrere Sätze. Damit können wir die Synthese testen."
)
LONG_TEXT = "A" * 5000  # exceeds typical chunk limits


class StubTTSAdapter(TTSAdapter):
    """Minimal concrete adapter for testing the ABC."""

    name = "stub"

    def __init__(self):
        self.calls = []

    def synthesize(self, text: str, output_path: Path) -> None:
        self.calls.append((text, output_path))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"\x00FAKE_MP3")

    def list_voices(self, language_code=None) -> list[VoiceInfo]:
        return [
            VoiceInfo(
                engine="stub",
                voice_id="stub-voice",
                display_name="Stub Voice",
                language="en-US",
                gender="neutral",
            )
        ]


@pytest.fixture
def stub_adapter():
    return StubTTSAdapter()


@pytest.fixture
def output_path(tmp_path):
    return tmp_path / "output.mp3"
