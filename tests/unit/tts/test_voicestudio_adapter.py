"""Tests for VoiceStudioAdapter (local OpenAI-compatible API, HTTP faked)."""

from unittest.mock import patch

import pytest
import requests

from manuscripta.audiobook.tts import create_adapter
from manuscripta.audiobook.tts.exceptions import (
    TTSCredentialsInvalidError,
    TTSInvalidInputError,
    TTSServiceUnavailableError,
)
from manuscripta.audiobook.tts.voicestudio_adapter import (
    DEFAULT_BASE_URL,
    VoiceStudioAdapter,
)

pytestmark = pytest.mark.unit


class FakeResponse:
    def __init__(self, status_code=200, content=b"", json_data=None, text=""):
        self.status_code = status_code
        self.content = content
        self._json = json_data
        self.text = text

    def json(self):
        return self._json


class FakeSession:
    """Records requests; answers from a queue per (method, path) or raises."""

    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    def request(self, method, url, headers=None, timeout=None, json=None):
        self.calls.append(
            {"method": method, "url": url, "headers": headers, "json": json}
        )
        path = url.split("3900", 1)[-1]
        answer = self.answers[(method, path)]
        if isinstance(answer, list):
            answer = answer.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


PROFILES = FakeResponse(
    json_data=[{"id": "p-42", "name": "Asterios", "language": "de"}]
)


def make(answers, voice="p-42", **kwargs):
    session = FakeSession(answers)
    return VoiceStudioAdapter(voice=voice, session=session, **kwargs), session


class TestInit:
    def test_voice_is_required(self):
        with pytest.raises(TTSInvalidInputError):
            VoiceStudioAdapter(voice="")

    def test_defaults(self, monkeypatch):
        monkeypatch.delenv("VOICESTUDIO_URL", raising=False)
        monkeypatch.delenv("VOICESTUDIO_API_KEY", raising=False)
        adapter = VoiceStudioAdapter(voice="p-42")
        assert adapter.base_url == DEFAULT_BASE_URL == "http://localhost:3900"
        assert adapter.api_key == "local"
        assert adapter.name == "voicestudio"
        assert adapter.requires_credentials is False
        assert adapter.max_chunk_chars == 1000

    def test_environment_overrides(self, monkeypatch):
        monkeypatch.setenv("VOICESTUDIO_URL", "http://gpu-box:3900/")
        monkeypatch.setenv("VOICESTUDIO_API_KEY", "secret")
        adapter = VoiceStudioAdapter(voice="p-42", max_chunk_chars=500)
        assert adapter.base_url == "http://gpu-box:3900"
        assert adapter.api_key == "secret"
        assert adapter.max_chunk_chars == 500

    def test_generator_selects_the_adapter(self):
        from manuscripta.audiobook.generator import get_tts_adapter

        adapter = get_tts_adapter("voicestudio", lang="de", voice="Asterios", rate=200)
        assert isinstance(adapter, VoiceStudioAdapter)
        assert (adapter.voice, adapter.lang) == ("Asterios", "de")

    def test_factory_knows_the_engine(self):
        assert isinstance(
            create_adapter("voicestudio", voice="p-42"), VoiceStudioAdapter
        )


class TestSynthesize:
    def test_posts_openai_request_per_chunk_and_concatenates(self, tmp_path):
        adapter, session = make(
            {
                ("get", "/profiles"): PROFILES,
                ("post", "/v1/audio/speech"): [
                    FakeResponse(content=b"AAA"),
                    FakeResponse(content=b"BBB"),
                ],
            },
            max_chunk_chars=20,
        )
        out = tmp_path / "sub" / "chapter.mp3"
        adapter.synthesize("Erster Absatz hier.\n\nZweiter Absatz da.", out)

        assert out.read_bytes() == b"AAABBB"
        posts = [c for c in session.calls if c["method"] == "post"]
        assert [p["json"]["input"] for p in posts] == [
            "Erster Absatz hier.",
            "Zweiter Absatz da.",
        ]
        assert posts[0]["url"] == "http://localhost:3900/v1/audio/speech"
        assert posts[0]["json"] == {
            "model": "tts-1",
            "voice": "p-42",
            "input": "Erster Absatz hier.",
            "response_format": "mp3",
            "language": "de",
        }
        assert posts[0]["headers"] == {"Authorization": "Bearer local"}

    @pytest.mark.parametrize(
        "lang,expected", [("de-DE", "de"), ("EN", "en"), ("", None)]
    )
    def test_language_is_sent_as_iso_639_1(self, lang, expected):
        adapter, _ = make({}, lang=lang)
        assert adapter._speech_request("Hallo.", "p-42").get("language") == expected

    def test_profile_name_is_resolved_to_id(self, tmp_path):
        adapter, session = make(
            {
                ("get", "/profiles"): PROFILES,
                ("post", "/v1/audio/speech"): FakeResponse(content=b"X"),
            },
            voice="asterios",
        )
        adapter.synthesize("Hallo.", tmp_path / "a.mp3")
        assert session.calls[-1]["json"]["voice"] == "p-42"

    def test_unknown_profile_endpoint_passes_voice_through(self, tmp_path):
        adapter, session = make(
            {
                ("get", "/profiles"): FakeResponse(status_code=404, text="not found"),
                ("post", "/v1/audio/speech"): FakeResponse(content=b"X"),
            },
            voice="my-voice",
        )
        adapter.synthesize("Hallo.", tmp_path / "a.mp3")
        assert session.calls[-1]["json"]["voice"] == "my-voice"

    def test_empty_text_is_rejected(self, tmp_path):
        adapter, _ = make({("get", "/profiles"): PROFILES})
        with pytest.raises(TTSInvalidInputError):
            adapter.synthesize("  \n\n ", tmp_path / "a.mp3")


class TestErrors:
    def test_app_not_running_is_reported_clearly(self, tmp_path):
        adapter, _ = make({("get", "/profiles"): requests.ConnectionError("refused")})
        with pytest.raises(TTSServiceUnavailableError, match="not reachable"):
            adapter.synthesize("Hallo.", tmp_path / "a.mp3")

    def test_server_error_is_retried_then_succeeds(self, tmp_path):
        adapter, session = make(
            {
                ("get", "/profiles"): PROFILES,
                ("post", "/v1/audio/speech"): [
                    FakeResponse(status_code=503, text="busy"),
                    FakeResponse(content=b"OK"),
                ],
            }
        )
        with patch("time.sleep"):
            adapter.synthesize("Hallo.", tmp_path / "a.mp3")
        assert (tmp_path / "a.mp3").read_bytes() == b"OK"
        assert sum(1 for c in session.calls if c["method"] == "post") == 2

    @pytest.mark.parametrize(
        "status,exc", [(401, TTSCredentialsInvalidError), (422, TTSInvalidInputError)]
    )
    def test_client_errors_are_not_retried(self, tmp_path, status, exc):
        adapter, session = make(
            {
                ("get", "/profiles"): PROFILES,
                ("post", "/v1/audio/speech"): FakeResponse(
                    status_code=status, text="nope"
                ),
            }
        )
        with pytest.raises(exc):
            adapter.synthesize("Hallo.", tmp_path / "a.mp3")
        assert sum(1 for c in session.calls if c["method"] == "post") == 1


class TestVoicesAndHealth:
    def test_list_voices_maps_profiles_and_filters_language(self):
        adapter, _ = make(
            {
                ("get", "/profiles"): FakeResponse(
                    json_data={
                        "profiles": [
                            {"id": "p-42", "name": "Asterios", "language": "de"},
                            {"id": "p-7", "name": "Narrator EN", "language": "en"},
                        ]
                    }
                )
            }
        )
        voices = adapter.list_voices("de")
        assert [(v.voice_id, v.display_name, v.engine) for v in voices] == [
            ("p-42", "Asterios", "voicestudio")
        ]

    def test_validate_reports_health(self):
        adapter, _ = make(
            {("get", "/health"): FakeResponse(json_data={"status": "ok"})}
        )
        ok, msg = adapter.validate()
        assert ok and "ok" in msg

    def test_validate_never_raises(self):
        adapter, _ = make({("get", "/health"): requests.ConnectionError("refused")})
        ok, msg = adapter.validate()
        assert not ok and "not reachable" in msg
