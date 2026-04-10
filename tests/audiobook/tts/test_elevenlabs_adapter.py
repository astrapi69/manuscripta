"""Tests for ElevenLabsAdapter."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from manuscripta.audiobook.tts.exceptions import (
    TTSCredentialsMissingError,
    TTSEngineNotInstalledError,
)


@pytest.fixture
def mock_elevenlabs():
    """Patch the elevenlabs import so the adapter can be instantiated."""
    mock_client_cls = MagicMock()
    mock_module = MagicMock()
    mock_module.ElevenLabs = mock_client_cls

    with patch.dict(
        "sys.modules", {"elevenlabs": MagicMock(), "elevenlabs.client": mock_module}
    ):
        from manuscripta.audiobook.tts.elevenlabs_adapter import ElevenLabsAdapter

        yield ElevenLabsAdapter, mock_client_cls


class TestElevenLabsInit:
    def test_missing_api_key_raises(self, mock_elevenlabs):
        ElevenLabsAdapter, _ = mock_elevenlabs
        with pytest.raises(TTSCredentialsMissingError):
            ElevenLabsAdapter(api_key="")

    def test_valid_api_key(self, mock_elevenlabs):
        ElevenLabsAdapter, _ = mock_elevenlabs
        adapter = ElevenLabsAdapter(api_key="test-key")
        assert adapter.api_key == "test-key"
        assert adapter.name == "elevenlabs"

    def test_import_error_raises(self):
        with patch.dict("sys.modules", {"elevenlabs": None, "elevenlabs.client": None}):
            # Force reimport to trigger ImportError
            import importlib
            import manuscripta.audiobook.tts.elevenlabs_adapter as mod

            with pytest.raises((TTSEngineNotInstalledError, ImportError)):
                importlib.reload(mod)
                mod.ElevenLabsAdapter(api_key="key")


class TestElevenLabsSynthesize:
    def test_synthesize_happy_path(self, mock_elevenlabs, tmp_path):
        ElevenLabsAdapter, mock_client_cls = mock_elevenlabs
        adapter = ElevenLabsAdapter(api_key="key", voice="Rachel")

        # Mock the client instance
        mock_client = MagicMock()
        mock_client.text_to_speech.convert.return_value = iter([b"AUDIO_DATA"])
        adapter._client = mock_client

        out = tmp_path / "out.mp3"
        adapter.synthesize("Hello world", out)

        assert out.exists()
        assert out.read_bytes() == b"AUDIO_DATA"
        mock_client.text_to_speech.convert.assert_called_once()


class TestElevenLabsListVoices:
    def test_list_voices(self, mock_elevenlabs):
        ElevenLabsAdapter, _ = mock_elevenlabs
        adapter = ElevenLabsAdapter(api_key="key")

        mock_voice = SimpleNamespace(
            voice_id="abc123",
            name="Rachel",
            labels={"gender": "female", "language": "en"},
        )
        mock_client = MagicMock()
        mock_client.voices.get_all.return_value = SimpleNamespace(voices=[mock_voice])
        adapter._client = mock_client

        voices = adapter.list_voices()
        assert len(voices) == 1
        assert voices[0].voice_id == "abc123"
        assert voices[0].gender == "female"

    def test_list_voices_with_language_filter(self, mock_elevenlabs):
        ElevenLabsAdapter, _ = mock_elevenlabs
        adapter = ElevenLabsAdapter(api_key="key")

        voices_data = [
            SimpleNamespace(
                voice_id="1", name="V1", labels={"gender": "female", "language": "en"}
            ),
            SimpleNamespace(
                voice_id="2", name="V2", labels={"gender": "male", "language": "de"}
            ),
        ]
        mock_client = MagicMock()
        mock_client.voices.get_all.return_value = SimpleNamespace(voices=voices_data)
        adapter._client = mock_client

        voices = adapter.list_voices(language_code="de")
        assert len(voices) == 1
        assert voices[0].language == "de"


class TestElevenLabsValidate:
    def test_validate_success(self, mock_elevenlabs):
        ElevenLabsAdapter, _ = mock_elevenlabs
        adapter = ElevenLabsAdapter(api_key="key")
        mock_client = MagicMock()
        mock_client.user.get.return_value = SimpleNamespace()
        adapter._client = mock_client

        ok, msg = adapter.validate()
        assert ok is True

    def test_validate_failure(self, mock_elevenlabs):
        ElevenLabsAdapter, _ = mock_elevenlabs
        adapter = ElevenLabsAdapter(api_key="key")
        mock_client = MagicMock()
        mock_client.user.get.side_effect = Exception("unauthorized")
        adapter._client = mock_client

        ok, msg = adapter.validate()
        assert ok is False


class TestElevenLabsCost:
    def test_estimate_cost(self, mock_elevenlabs):
        ElevenLabsAdapter, _ = mock_elevenlabs
        adapter = ElevenLabsAdapter(api_key="key")
        cost = adapter.estimate_cost("Hello" * 200)
        assert cost > 0
        assert isinstance(cost, float)

    def test_check_quota(self, mock_elevenlabs):
        ElevenLabsAdapter, _ = mock_elevenlabs
        adapter = ElevenLabsAdapter(api_key="key")
        mock_client = MagicMock()
        mock_client.user.get.return_value = SimpleNamespace(
            subscription=SimpleNamespace(character_count=500, character_limit=10000)
        )
        adapter._client = mock_client

        quota = adapter.check_quota()
        assert quota is not None
        assert quota.used == 500
        assert quota.limit == 10000
