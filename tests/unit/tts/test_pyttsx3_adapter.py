"""Tests for Pyttsx3Adapter."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from manuscripta.audiobook.tts.exceptions import (
    TTSCredentialsMissingError,
    TTSEngineNotInstalledError,
)


@pytest.fixture
def mock_pyttsx3():
    """Patch pyttsx3 so the adapter can be instantiated."""
    mock_module = MagicMock()
    mock_engine = MagicMock()
    mock_module.init.return_value = mock_engine
    mock_engine.getProperty.return_value = [
        SimpleNamespace(
            id="voice1", name="Alice", languages=["en-US"], gender="Female"
        ),
        SimpleNamespace(id="voice2", name="Bob", languages=["de-DE"], gender="Male"),
    ]

    with patch.dict("sys.modules", {"pyttsx3": mock_module}):
        from manuscripta.audiobook.tts.pyttsx3_adapter import Pyttsx3Adapter

        yield Pyttsx3Adapter, mock_module, mock_engine


class TestPyttsx3Init:
    def test_creation(self, mock_pyttsx3):
        Cls, _, _ = mock_pyttsx3
        adapter = Cls(voice="Alice", rate=200)
        assert adapter.name == "pyttsx3"
        assert adapter.requires_credentials is False
        assert adapter._engine is None  # lazy

    def test_import_error(self):
        with patch.dict("sys.modules", {"pyttsx3": None}):
            import importlib
            import manuscripta.audiobook.tts.pyttsx3_adapter as mod

            with pytest.raises((TTSEngineNotInstalledError, ImportError)):
                importlib.reload(mod)
                mod.Pyttsx3Adapter()


class TestPyttsx3LazyInit:
    def test_engine_created_on_first_access(self, mock_pyttsx3):
        Cls, mock_module, _ = mock_pyttsx3
        adapter = Cls()
        assert adapter._engine is None
        _ = adapter.engine  # triggers lazy init
        mock_module.init.assert_called_once()

    def test_engine_init_failure_raises(self, mock_pyttsx3):
        Cls, mock_module, _ = mock_pyttsx3
        mock_module.init.side_effect = RuntimeError("no speech engine")
        adapter = Cls()
        with pytest.raises(TTSCredentialsMissingError):
            _ = adapter.engine


class TestPyttsx3Synthesize:
    def test_synthesize_happy_path(self, mock_pyttsx3, tmp_path):
        Cls, _, mock_engine = mock_pyttsx3
        adapter = Cls()

        out = tmp_path / "out.mp3"
        adapter.synthesize("Hallo Welt", out)

        mock_engine.save_to_file.assert_called_once_with("Hallo Welt", str(out))
        mock_engine.runAndWait.assert_called_once()


class TestPyttsx3ListVoices:
    def test_list_voices(self, mock_pyttsx3):
        Cls, _, _ = mock_pyttsx3
        adapter = Cls()

        voices = adapter.list_voices()
        assert len(voices) == 2
        assert voices[0].voice_id == "voice1"
        assert voices[0].display_name == "Alice"
        assert voices[1].voice_id == "voice2"

    def test_list_voices_filtered(self, mock_pyttsx3):
        Cls, _, _ = mock_pyttsx3
        adapter = Cls()

        voices = adapter.list_voices(language_code="de")
        assert len(voices) == 1
        assert voices[0].display_name == "Bob"
