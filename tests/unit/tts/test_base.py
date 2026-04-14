"""Tests for base.py: TTSAdapter ABC, VoiceInfo, QuotaInfo."""

import warnings

import pytest

from manuscripta.audiobook.tts.base import QuotaInfo, TTSAdapter, VoiceInfo


class TestVoiceInfo:
    def test_creation(self):
        v = VoiceInfo(
            engine="test",
            voice_id="v1",
            display_name="Voice One",
            language="en-US",
            gender="female",
        )
        assert v.engine == "test"
        assert v.voice_id == "v1"
        assert v.quality == "standard"

    def test_frozen(self):
        v = VoiceInfo(
            engine="test",
            voice_id="v1",
            display_name="V",
            language="en",
            gender="male",
        )
        with pytest.raises(AttributeError):
            v.engine = "other"

    def test_custom_quality(self):
        v = VoiceInfo(
            engine="gcp",
            voice_id="v1",
            display_name="V",
            language="de",
            gender="female",
            quality="neural2",
        )
        assert v.quality == "neural2"


class TestQuotaInfo:
    def test_creation(self):
        q = QuotaInfo(used=100, limit=1000)
        assert q.used == 100
        assert q.limit == 1000
        assert q.resets_at is None

    def test_with_reset(self):
        q = QuotaInfo(used=50, limit=500, resets_at="2026-05-01T00:00:00Z")
        assert q.resets_at == "2026-05-01T00:00:00Z"


class TestTTSAdapterABC:
    def test_cannot_instantiate_abstract(self):
        with pytest.raises(TypeError):
            TTSAdapter()

    def test_default_validate(self, stub_adapter):
        ok, msg = stub_adapter.validate()
        assert ok is True

    def test_default_estimate_cost(self, stub_adapter):
        assert stub_adapter.estimate_cost("hello") is None

    def test_default_check_quota(self, stub_adapter):
        assert stub_adapter.check_quota() is None

    def test_speak_alias_warns(self, stub_adapter, tmp_path):
        out = tmp_path / "test.mp3"
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            stub_adapter.speak("hello", out)
            assert len(w) == 1
            assert issubclass(w[0].category, DeprecationWarning)
            assert "synthesize" in str(w[0].message)

    def test_speak_alias_delegates_to_synthesize(self, stub_adapter, tmp_path):
        out = tmp_path / "test.mp3"
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            stub_adapter.speak("hello", out)
        assert len(stub_adapter.calls) == 1
        assert stub_adapter.calls[0][0] == "hello"
