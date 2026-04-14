"""Tests for GoogleTranslateTTSAdapter and deprecated GoogleTTSAdapter alias."""

import warnings
from unittest.mock import MagicMock, patch

import pytest

from manuscripta.audiobook.tts.exceptions import TTSEngineNotInstalledError


@pytest.fixture
def mock_gtts():
    """Patch gtts so the adapter can be instantiated."""
    mock_module = MagicMock()
    mock_lang_module = MagicMock()
    mock_lang_module.tts_langs.return_value = {
        "en": "English",
        "de": "German",
        "es": "Spanish",
    }

    with patch.dict(
        "sys.modules",
        {"gtts": mock_module, "gtts.lang": mock_lang_module},
    ):
        from manuscripta.audiobook.tts.google_translate_adapter import (
            GoogleTranslateTTSAdapter,
            GoogleTTSAdapter,
        )

        yield GoogleTranslateTTSAdapter, GoogleTTSAdapter, mock_module


class TestGoogleTranslateInit:
    def test_deprecation_warning(self, mock_gtts):
        Cls, _, _ = mock_gtts
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            adapter = Cls(lang="de")
            assert any(issubclass(x.category, DeprecationWarning) for x in w)
        assert adapter.name == "google-translate"

    def test_import_error(self):
        with patch.dict("sys.modules", {"gtts": None}):
            import importlib
            import manuscripta.audiobook.tts.google_translate_adapter as mod

            with pytest.raises((TTSEngineNotInstalledError, ImportError)):
                importlib.reload(mod)
                mod.GoogleTranslateTTSAdapter(lang="en")


class TestGoogleTranslateSynthesize:
    def test_synthesize_happy_path(self, mock_gtts, tmp_path):
        Cls, _, mock_module = mock_gtts
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            adapter = Cls(lang="de")

        # Mock the gTTS class
        mock_tts_instance = MagicMock()
        mock_module.gTTS.return_value = mock_tts_instance

        out = tmp_path / "out.mp3"
        # We need to make save actually create the file
        mock_tts_instance.save.side_effect = lambda path: open(path, "wb").write(
            b"AUDIO"
        )

        adapter.synthesize("Hallo Welt", out)
        mock_module.gTTS.assert_called_once_with(text="Hallo Welt", lang="de")


class TestGoogleTranslateListVoices:
    def test_list_voices(self, mock_gtts):
        Cls, _, _ = mock_gtts
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            adapter = Cls(lang="en")

        voices = adapter.list_voices()
        assert len(voices) == 3
        assert all(v.engine == "google-translate" for v in voices)
        assert all(v.quality == "standard" for v in voices)

    def test_list_voices_filtered(self, mock_gtts):
        Cls, _, _ = mock_gtts
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            adapter = Cls(lang="en")

        voices = adapter.list_voices(language_code="de")
        assert len(voices) == 1
        assert voices[0].language == "de"


class TestGoogleTTSAlias:
    def test_alias_warns_deprecated(self, mock_gtts):
        _, AliasClass, _ = mock_gtts
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            AliasClass(lang="en")
            # Should get at least a deprecation warning about the alias
            dep_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
            assert len(dep_warnings) >= 1
            assert any("GoogleTTSAdapter" in str(x.message) for x in dep_warnings)
