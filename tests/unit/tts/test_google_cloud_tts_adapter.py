"""Tests for GoogleCloudTTSAdapter."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.unit

from manuscripta.audiobook.tts.exceptions import (
    TTSEngineNotInstalledError,
)


def _make_mock_modules():
    """Create mock google.cloud.texttospeech and google.oauth2 modules."""
    mock_tts = MagicMock()
    mock_tts.AudioEncoding.MP3 = "MP3"
    mock_oauth2 = MagicMock()

    modules = {
        "google": MagicMock(),
        "google.cloud": MagicMock(),
        "google.cloud.texttospeech": mock_tts,
        "google.oauth2": mock_oauth2,
        "google.oauth2.service_account": mock_oauth2,
        "google.api_core": MagicMock(),
        "google.api_core.exceptions": MagicMock(),
    }
    return modules, mock_tts, mock_oauth2


@pytest.fixture
def mock_google():
    modules, mock_tts, mock_oauth2 = _make_mock_modules()
    with patch.dict("sys.modules", modules):
        from manuscripta.audiobook.tts.google_cloud_tts_adapter import (
            GoogleCloudTTSAdapter,
        )

        yield GoogleCloudTTSAdapter, mock_tts, mock_oauth2


class TestGoogleCloudInit:
    def test_creation(self, mock_google):
        Cls, _, _ = mock_google
        adapter = Cls(credentials_path="/fake/creds.json", voice_id="de-DE-Neural2-B")
        assert adapter.name == "google-cloud-tts"
        assert adapter.requires_credentials is True

    def test_import_error(self):
        with patch.dict(
            "sys.modules",
            {
                "google": None,
                "google.cloud": None,
                "google.cloud.texttospeech": None,
                "google.oauth2": None,
                "google.oauth2.service_account": None,
            },
        ):
            import importlib
            import manuscripta.audiobook.tts.google_cloud_tts_adapter as mod

            with pytest.raises((TTSEngineNotInstalledError, ImportError)):
                importlib.reload(mod)
                mod.GoogleCloudTTSAdapter(credentials_path="/fake.json", voice_id="v1")


class TestGoogleCloudSynthesize:
    def test_synthesize_happy_path(self, mock_google, tmp_path):
        Cls, mock_tts, mock_oauth2 = mock_google
        adapter = Cls(credentials_path="/fake/creds.json", voice_id="de-DE-Neural2-B")

        # Mock the client
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.audio_content = b"MP3_AUDIO"
        mock_client.synthesize_speech.return_value = mock_response
        adapter._client = mock_client

        out = tmp_path / "output.mp3"
        adapter.synthesize("Hallo Welt", out)

        assert out.exists()
        assert out.read_bytes() == b"MP3_AUDIO"

    def test_synthesize_creates_dirs(self, mock_google, tmp_path):
        Cls, _, _ = mock_google
        adapter = Cls(credentials_path="/fake.json", voice_id="v1")

        mock_client = MagicMock()
        mock_client.synthesize_speech.return_value = MagicMock(audio_content=b"A")
        adapter._client = mock_client

        out = tmp_path / "deep" / "nested" / "out.mp3"
        adapter.synthesize("text", out)
        assert out.exists()


class TestGoogleCloudListVoices:
    def test_list_voices(self, mock_google):
        Cls, mock_tts, _ = mock_google
        adapter = Cls(credentials_path="/fake.json", voice_id="v1")

        mock_voice = MagicMock()
        mock_voice.name = "de-DE-Neural2-B"
        mock_voice.language_codes = ["de-DE"]
        mock_voice.ssml_gender = SimpleNamespace(name="MALE")

        mock_client = MagicMock()
        mock_client.list_voices.return_value = MagicMock(voices=[mock_voice])
        adapter._client = mock_client

        voices = adapter.list_voices()
        assert len(voices) == 1
        assert voices[0].voice_id == "de-DE-Neural2-B"
        assert voices[0].quality == "neural2"
        assert voices[0].gender == "male"


class TestGoogleCloudCost:
    def test_estimate_cost_neural2(self, mock_google):
        Cls, _, _ = mock_google
        adapter = Cls(credentials_path="/f.json", voice_id="de-DE-Neural2-B")
        cost = adapter.estimate_cost("A" * 1_000_000)
        assert cost == pytest.approx(16.00)

    def test_estimate_cost_standard(self, mock_google):
        Cls, _, _ = mock_google
        adapter = Cls(credentials_path="/f.json", voice_id="de-DE-Standard-A")
        cost = adapter.estimate_cost("A" * 1_000_000)
        assert cost == pytest.approx(4.00)

    def test_estimate_cost_journey(self, mock_google):
        Cls, _, _ = mock_google
        adapter = Cls(credentials_path="/f.json", voice_id="de-DE-Journey-B")
        cost = adapter.estimate_cost("A" * 1_000_000)
        assert cost == pytest.approx(30.00)


class TestGoogleCloudHelpers:
    def test_detect_quality(self, mock_google):
        Cls, _, _ = mock_google
        assert Cls._detect_quality("de-DE-Neural2-B") == "neural2"
        assert Cls._detect_quality("de-DE-Wavenet-A") == "wavenet"
        assert Cls._detect_quality("de-DE-Journey-C") == "journey"
        assert Cls._detect_quality("de-DE-Studio-A") == "studio"
        assert Cls._detect_quality("de-DE-Standard-A") == "standard"

    def test_format_display_name(self, mock_google):
        Cls, _, _ = mock_google
        assert Cls._format_display_name("de-DE-Neural2-B") == "Neural2-B"
        assert Cls._format_display_name("ShortName") == "ShortName"
