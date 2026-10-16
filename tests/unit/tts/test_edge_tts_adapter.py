"""Tests for EdgeTTSAdapter."""

import asyncio
import re
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.unit

from manuscripta.audiobook.tts.base import VoiceInfo
import edge_tts

import manuscripta.audiobook.tts.edge_tts_adapter as mod
from manuscripta.audiobook.tts.edge_tts_adapter import EdgeTTSAdapter
from manuscripta.audiobook.tts.exceptions import (
    TTSInvalidInputError,
    TTSTransientError,
)
from manuscripta.audiobook.tts.text_chunking import split_text_into_chunks


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


# -- table-driven behaviour ---------------------------------------------------


def communicate_stub(outcomes):
    """A stand-in for edge_tts.Communicate. Its save() takes the next outcome:
    an exception to raise, or None to write the text as the file's bytes.
    Returns the class and the list recording every construction."""
    pending = list(outcomes)
    calls = []

    class Communicate:
        def __init__(self, text, voice, **options):
            calls.append((text, voice, options))
            self.text = text

        async def save(self, path):
            outcome = pending.pop(0) if pending else None
            if outcome is not None:
                raise outcome
            Path(path).write_bytes(self.text.encode("utf-8"))

    return Communicate, calls


def retry_lines(error: str, waits: list[int]) -> str:
    """The lines printed for the retries after ``error``, one per wait."""
    return "".join(
        f"    Retry {attempt}/3 after error: {error}\n"
        f"    Waiting {wait}s before next attempt...\n"
        for attempt, wait in enumerate(waits, 1)
    )


@pytest.fixture
def sleeps(monkeypatch):
    """Records the seconds asyncio.sleep is asked for instead of waiting."""
    slept = []

    async def record(seconds):
        slept.append(seconds)

    monkeypatch.setattr(mod.asyncio, "sleep", record)
    return slept


OPTIONS = {"rate": "+0%", "volume": "+0%", "pitch": "+0Hz"}

# Each row: what save() does per attempt (an exception; None: success), the
# seconds slept between attempts, the lines printed
RETRY_RECOVERIES = [
    pytest.param([None], [], "", id="first-attempt"),
    pytest.param(
        [Exception("boom"), None], [2], retry_lines("boom", [2]), id="second-attempt"
    ),
    pytest.param(
        [Exception("boom"), Exception("boom"), None],
        [2, 4],
        retry_lines("boom", [2, 4]),
        id="third-attempt",
    ),
]


@pytest.mark.parametrize("outcomes, waits, printed", RETRY_RECOVERIES)
def test_synthesize_recovers_within_three_attempts(
    outcomes, waits, printed, adapter, tmp_path, monkeypatch, sleeps, capsys
):
    Communicate, calls = communicate_stub(outcomes)
    monkeypatch.setattr(edge_tts, "Communicate", Communicate)
    out = tmp_path / "out.mp3"

    adapter.synthesize("Hallo Welt.", out)

    assert out.read_bytes() == b"Hallo Welt."
    assert calls == [("Hallo Welt.", "de-DE-KatjaNeural", OPTIONS)] * len(outcomes)
    assert sleeps == waits
    assert capsys.readouterr().out == printed


# Each row: the error every attempt fails with, the exception raised, its message
RETRY_FAILURES = [
    pytest.param(
        "timeout",
        TTSTransientError,
        "Edge TTS failed after 3 attempts: timeout",
        id="transient",
    ),
    pytest.param(
        "Invalid parameter: pitch",
        TTSInvalidInputError,
        "Edge TTS rejected input: Invalid parameter: pitch",
        id="invalid-input",
    ),
]


@pytest.mark.parametrize("error, raised, message", RETRY_FAILURES)
def test_synthesize_gives_up_after_three_attempts(
    error, raised, message, adapter, tmp_path, monkeypatch, sleeps, capsys
):
    Communicate, calls = communicate_stub([Exception(error)] * 3)
    monkeypatch.setattr(edge_tts, "Communicate", Communicate)
    out = tmp_path / "out.mp3"

    with pytest.raises(raised, match=re.escape(message)) as ex:
        adapter.synthesize("Hallo Welt.", out)

    assert (ex.value.engine, str(ex.value.original)) == ("edge-tts", error)
    assert not out.exists()
    assert len(calls) == 3
    assert sleeps == [2, 4]
    assert capsys.readouterr().out == retry_lines(error, [2, 4])


def test_synthesize_long_text_joins_the_chunks(adapter, tmp_path, monkeypatch, capsys):
    text = "\n\n".join(f"Absatz {i}. " + "Wort " * 300 for i in range(4))
    chunks = split_text_into_chunks(text, max_chars=EdgeTTSAdapter.max_chunk_chars)
    assert len(chunks) == 2, "premise: the text needs two chunks"
    Communicate, calls = communicate_stub([])
    monkeypatch.setattr(edge_tts, "Communicate", Communicate)
    temp_dirs = []

    def mkdtemp(prefix):
        temp_dirs.append(Path(tempfile.mkdtemp(prefix=prefix, dir=tmp_path)))
        return str(temp_dirs[-1])

    monkeypatch.setattr(mod, "tempfile", SimpleNamespace(mkdtemp=mkdtemp))
    out = tmp_path / "book" / "out.mp3"

    adapter.synthesize(text, out)

    assert out.read_bytes() == "".join(chunks).encode("utf-8")
    assert [call[0] for call in calls] == chunks
    assert capsys.readouterr().out == "".join(
        f"    Chunk {n}/2 ({len(chunk)} chars)\n" for n, chunk in enumerate(chunks, 1)
    )
    # one scratch directory, named after the engine, gone afterwards
    assert [(d.name.startswith("edge_tts_"), d.exists()) for d in temp_dirs] == [
        (True, False)
    ]


def test_run_async_inside_a_running_loop_falls_back_to_a_thread(monkeypatch):
    monkeypatch.setitem(sys.modules, "nest_asyncio", None)

    async def payload():
        return "done"

    async def outer():
        return EdgeTTSAdapter._run_async(payload())

    assert asyncio.run(outer()) == "done"


def test_validate_reports_when_no_voices_come_back(adapter, monkeypatch):
    monkeypatch.setattr(edge_tts, "list_voices", AsyncMock(return_value=[]))
    assert adapter.validate() == (False, "No voices returned")


# Each row: a voice record as the service returns it, the VoiceInfo built
VOICE_RECORDS = [
    pytest.param(
        {
            "ShortName": "de-DE-ConradNeural",
            "FriendlyName": "Conrad",
            "Locale": "de-DE",
            "Gender": "Male",
        },
        VoiceInfo(
            engine="edge-tts",
            voice_id="de-DE-ConradNeural",
            display_name="Conrad",
            language="de-DE",
            gender="male",
            quality="neural",
        ),
        id="male",
    ),
    pytest.param(
        {"ShortName": "el-GR-AthinaNeural", "Locale": "el-GR", "Gender": "Unknown"},
        VoiceInfo(
            engine="edge-tts",
            voice_id="el-GR-AthinaNeural",
            display_name="el-GR-AthinaNeural",
            language="el-GR",
            gender="neutral",
            quality="neural",
        ),
        id="unknown-gender-falls-back-to-short-name",
    ),
    pytest.param(
        {},
        VoiceInfo(
            engine="edge-tts",
            voice_id="",
            display_name="",
            language="",
            gender="neutral",
            quality="neural",
        ),
        id="empty-record",
    ),
]


@pytest.mark.parametrize("record, voice", VOICE_RECORDS)
def test_list_voices_maps_records(record, voice, adapter, monkeypatch):
    monkeypatch.setattr(edge_tts, "list_voices", AsyncMock(return_value=[record]))
    assert adapter.list_voices() == [voice]
