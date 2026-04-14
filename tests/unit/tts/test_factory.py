"""Tests for the create_adapter factory function."""

import warnings
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.unit

from manuscripta.audiobook.tts import create_adapter
from manuscripta.audiobook.tts.edge_tts_adapter import EdgeTTSAdapter


class TestCreateAdapter:
    def test_edge_tts(self):
        adapter = create_adapter("edge-tts", lang="de")
        assert isinstance(adapter, EdgeTTSAdapter)

    def test_edge_alias(self):
        adapter = create_adapter("edge", lang="en")
        assert isinstance(adapter, EdgeTTSAdapter)

    def test_unknown_engine_raises(self):
        with pytest.raises(ValueError, match="Unknown engine"):
            create_adapter("nonexistent-engine")

    def test_elevenlabs_requires_key(self):
        mock_module = MagicMock()
        mock_module.ElevenLabs = MagicMock()
        with patch.dict(
            "sys.modules", {"elevenlabs": MagicMock(), "elevenlabs.client": mock_module}
        ):
            from manuscripta.audiobook.tts.exceptions import TTSCredentialsMissingError

            with pytest.raises(TTSCredentialsMissingError):
                create_adapter("elevenlabs", api_key="")

    def test_google_translate_warns(self):
        mock_module = MagicMock()
        with patch.dict("sys.modules", {"gtts": mock_module, "gtts.lang": MagicMock()}):
            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                create_adapter("gtts", lang="en")
                assert any(issubclass(x.category, DeprecationWarning) for x in w)
