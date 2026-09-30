"""VoiceStudio TTS adapter (local, OpenAI-compatible API).

VoiceStudio (https://voicestudio.sh) runs speech models such as OmniVoice on
this machine and serves an OpenAI-compatible API while the app is running.
No cloud, no quota, no per-character cost. Voices are VoiceStudio voice
profiles (cloned from a short sample or designed), referenced by profile id
or by profile name.

Environment:
    VOICESTUDIO_URL      API base URL (default ``http://localhost:3900``)
    VOICESTUDIO_API_KEY  any non-empty string on localhost (default ``"local"``)
"""

import os
from pathlib import Path
from typing import Optional

import requests

from manuscripta.audiobook.tts.base import TTSAdapter, VoiceInfo
from manuscripta.audiobook.tts.exceptions import (
    TTSCredentialsInvalidError,
    TTSInvalidInputError,
    TTSQuotaExceededError,
    TTSServiceUnavailableError,
    TTSTransientError,
)
from manuscripta.audiobook.tts.retry import with_retry
from manuscripta.audiobook.tts.text_chunking import split_text_into_chunks

DEFAULT_BASE_URL = "http://localhost:3900"


class VoiceStudioAdapter(TTSAdapter):
    """TTS adapter backed by a locally running VoiceStudio app.

    :param voice: Voice profile id or profile name (required).
    :param lang: Language of the text, sent as ISO 639-1 ``language`` (``"de-DE"``
        becomes ``"de"``) so the model pronounces it in that language.
    :param base_url: API base URL, default ``$VOICESTUDIO_URL`` or
        ``http://localhost:3900``.
    :param api_key: Bearer token, default ``$VOICESTUDIO_API_KEY`` or ``"local"``.
    :param model: Value of the OpenAI ``model`` field. ``"tts-1"`` (default) is
        VoiceStudio's alias for the engine active in the app; an engine id such as
        ``"omnivoice"`` or ``"omnivoice-gguf"`` pins one.
    :param max_chunk_chars: Characters per request. Short chunks keep
        long-form narration stable on local models.
    :param timeout: Seconds per request; local synthesis on CPU can be slow.
    :param session: Optional ``requests.Session`` (injected in tests).
    """

    name = "voicestudio"
    requires_credentials = False
    supports_chunking = True
    max_chunk_chars = 1000

    def __init__(
        self,
        voice: str = "",
        lang: str = "de",
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        model: str = "tts-1",
        max_chunk_chars: Optional[int] = None,
        timeout: float = 600.0,
        session: Optional[requests.Session] = None,
    ):
        if not voice:
            raise TTSInvalidInputError(
                "VoiceStudio needs a voice profile (id or name). "
                "Create one in the app (Voice Clone or Voice Design) and set "
                "'voice' in voice-settings.yaml or pass --voice.",
                engine=self.name,
            )
        self.voice = voice
        self.lang = lang
        self.base_url = (
            base_url or os.getenv("VOICESTUDIO_URL") or DEFAULT_BASE_URL
        ).rstrip("/")
        self.api_key = api_key or os.getenv("VOICESTUDIO_API_KEY") or "local"
        self.model = model
        if max_chunk_chars:
            self.max_chunk_chars = max_chunk_chars
        self.timeout = timeout
        self._session = session or requests.Session()
        self._voice_id: Optional[str] = None

    # -- synthesis ----------------------------------------------------------------

    def synthesize(self, text: str, output_path: Path) -> None:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        chunks = split_text_into_chunks(text, max_chars=self.max_chunk_chars)
        if not chunks:
            raise TTSInvalidInputError("Nothing to synthesize", engine=self.name)
        voice_id = self.voice_id
        with open(output_path, "wb") as f:
            for chunk in chunks:
                f.write(self._synthesize_chunk(chunk, voice_id))

    @with_retry()
    def _synthesize_chunk(self, text: str, voice_id: str) -> bytes:
        response = self._request(
            "post",
            "/v1/audio/speech",
            json=self._speech_request(text, voice_id),
        )
        if not response.content:
            raise TTSTransientError(
                "VoiceStudio returned empty audio", engine=self.name
            )
        return response.content

    def _speech_request(self, text: str, voice_id: str) -> dict:
        body = {
            "model": self.model,
            "voice": voice_id,
            "input": text,
            "response_format": "mp3",
        }
        if self.lang:
            body["language"] = self.lang.split("-")[0].lower()
        return body

    # -- voices -------------------------------------------------------------------

    @property
    def voice_id(self) -> str:
        """Profile id for :attr:`voice`; a profile *name* is resolved via ``/profiles``."""
        if self._voice_id is None:
            self._voice_id = self._resolve_voice(self.voice)
        return self._voice_id

    def _resolve_voice(self, voice: str) -> str:
        try:
            profiles = self._profiles()
        except TTSInvalidInputError:
            return voice  # older app without /profiles: pass the value through
        for p in profiles:
            if str(p.get("id")) == voice:
                return voice
        for p in profiles:
            if str(p.get("name", "")).casefold() == voice.casefold():
                return str(p["id"])
        return voice

    def _profiles(self) -> list[dict]:
        data = self._request("get", "/profiles").json()
        if isinstance(data, dict):
            data = data.get("profiles") or data.get("items") or data.get("data") or []
        return [p for p in data if isinstance(p, dict) and p.get("id") is not None]

    def list_voices(self, language_code: Optional[str] = None) -> list[VoiceInfo]:
        result = []
        for p in self._profiles():
            lang = str(p.get("language") or "")
            if (
                language_code
                and lang
                and not lang.lower().startswith(language_code.lower())
            ):
                continue
            result.append(
                VoiceInfo(
                    engine=self.name,
                    voice_id=str(p["id"]),
                    display_name=str(p.get("name") or p["id"]),
                    language=lang or "multilingual",
                    gender=str(p.get("gender") or "neutral"),
                    quality="local",
                )
            )
        return result

    def validate(self) -> tuple[bool, str]:
        try:
            info = self._request("get", "/health").json()
        except Exception as exc:  # noqa: BLE001 - validate() reports, never raises
            return False, str(exc)
        return True, f"VoiceStudio reachable at {self.base_url}: {info}"

    # -- HTTP ---------------------------------------------------------------------

    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        url = f"{self.base_url}{path}"
        try:
            response = self._session.request(
                method,
                url,
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=self.timeout,
                **kwargs,
            )
        except requests.ConnectionError as exc:
            raise TTSServiceUnavailableError(
                f"VoiceStudio is not reachable at {self.base_url}. Start the app "
                "(the API runs while it is open) or set VOICESTUDIO_URL.",
                engine=self.name,
                original=exc,
            ) from exc
        except requests.Timeout as exc:
            raise TTSTransientError(
                f"VoiceStudio timed out after {self.timeout:.0f}s",
                engine=self.name,
                original=exc,
            ) from exc
        self._raise_for_status(response)
        return response

    def _raise_for_status(self, response: requests.Response) -> None:
        status = response.status_code
        if status < 400:
            return
        detail = f"VoiceStudio HTTP {status}: {response.text[:300]}"
        if status in (401, 403):
            raise TTSCredentialsInvalidError(detail, engine=self.name)
        if status == 429:
            raise TTSQuotaExceededError(detail, engine=self.name)
        if status >= 500:
            raise TTSServiceUnavailableError(detail, engine=self.name)
        raise TTSInvalidInputError(detail, engine=self.name)
