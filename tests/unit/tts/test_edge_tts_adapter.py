"""Tests for EdgeTTSAdapter."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.unit

from manuscripta.audiobook.tts.base import VoiceInfo
from manuscripta.audiobook.tts.edge_tts_adapter import EdgeTTSAdapter


@pytest.fixture
def adapter():
    return EdgeTTSAdapter(lang="de", voice="de-DE-KatjaNeural")


class TestEdgeTTSSynthesize:
    def test_synthesize_single_chunk(self, adapter, tmp_path):
        out = tmp_path / "out.mp3"

        async def fake_save(path):
            Path(path).write_bytes(b"AUDIO")

        with patch("edge_tts.Communicate") as mock_comm:
            instance = MagicMock()
            instance.save = fake_save
            mock_comm.return_value = instance

            adapter.synthesize("Short text", out)

        assert out.exists()
        assert out.read_bytes() == b"AUDIO"

    def test_synthesize_creates_parent_dirs(self, adapter, tmp_path):
        out = tmp_path / "deep" / "nested" / "out.mp3"

        async def fake_save(path):
            Path(path).write_bytes(b"AUDIO")

        with patch("edge_tts.Communicate") as mock_comm:
            instance = MagicMock()
            instance.save = fake_save
            mock_comm.return_value = instance

            adapter.synthesize("text", out)

        assert out.exists()

    def test_synthesize_empty_text_noop(self, adapter, tmp_path):
        out = tmp_path / "out.mp3"
        adapter.synthesize("", out)
        assert not out.exists()


class TestEdgeTTSListVoices:
    def test_list_voices_returns_voice_info(self, adapter):
        fake_voices = [
            {
                "ShortName": "de-DE-KatjaNeural",
                "FriendlyName": "Katja",
                "Locale": "de-DE",
                "Gender": "Female",
            },
            {
                "ShortName": "en-US-JennyNeural",
                "FriendlyName": "Jenny",
                "Locale": "en-US",
                "Gender": "Female",
            },
        ]

        with patch(
            "edge_tts.list_voices", new_callable=AsyncMock, return_value=fake_voices
        ):
            voices = adapter.list_voices()

        assert len(voices) == 2
        assert all(isinstance(v, VoiceInfo) for v in voices)
        assert voices[0].engine == "edge-tts"
        assert voices[0].voice_id == "de-DE-KatjaNeural"

    def test_list_voices_filters_by_language(self, adapter):
        fake_voices = [
            {
                "ShortName": "de-DE-KatjaNeural",
                "FriendlyName": "Katja",
                "Locale": "de-DE",
                "Gender": "Female",
            },
            {
                "ShortName": "en-US-JennyNeural",
                "FriendlyName": "Jenny",
                "Locale": "en-US",
                "Gender": "Female",
            },
        ]

        with patch(
            "edge_tts.list_voices", new_callable=AsyncMock, return_value=fake_voices
        ):
            voices = adapter.list_voices(language_code="de")

        assert len(voices) == 1
        assert voices[0].language == "de-DE"


class TestEdgeTTSValidate:
    def test_validate_success(self, adapter):
        fake_voices = [
            {
                "ShortName": "en-US-JennyNeural",
                "FriendlyName": "Jenny",
                "Locale": "en-US",
                "Gender": "Female",
            },
        ]
        with patch(
            "edge_tts.list_voices", new_callable=AsyncMock, return_value=fake_voices
        ):
            ok, msg = adapter.validate()
        assert ok is True

    def test_validate_failure(self, adapter):
        with patch(
            "edge_tts.list_voices",
            new_callable=AsyncMock,
            side_effect=Exception("network"),
        ):
            ok, msg = adapter.validate()
        assert ok is False


class TestEdgeTTSDefaultVoice:
    def test_default_voice_de(self):
        a = EdgeTTSAdapter(lang="de")
        assert a.voice == "de-DE-KatjaNeural"

    def test_default_voice_en(self):
        a = EdgeTTSAdapter(lang="en")
        assert a.voice == "en-US-JennyNeural"

    def test_explicit_voice_overrides(self):
        a = EdgeTTSAdapter(lang="de", voice="de-DE-ConradNeural")
        assert a.voice == "de-DE-ConradNeural"

    def test_estimate_cost_is_none(self, adapter):
        assert adapter.estimate_cost("any text") is None
