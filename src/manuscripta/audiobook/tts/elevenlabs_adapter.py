"""ElevenLabs TTS adapter using the official client library.

Requires:
    poetry install --with elevenlabs

Needs an API key (constructor parameter or ``ELEVENLABS_API_KEY`` env var).
"""

from pathlib import Path
from typing import Optional

from manuscripta.audiobook.tts.base import TTSAdapter, QuotaInfo, VoiceInfo
from manuscripta.audiobook.tts.exceptions import (
    TTSCredentialsInvalidError,
    TTSCredentialsMissingError,
    TTSEngineNotInstalledError,
    TTSQuotaExceededError,
    TTSTransientError,
)
from manuscripta.audiobook.tts.retry import with_retry
from manuscripta.audiobook.tts.text_chunking import split_text_into_chunks

# ElevenLabs pricing per 1 000 characters (approximate, varies by plan)
_COST_PER_1K_CHARS = 0.30


class ElevenLabsAdapter(TTSAdapter):
    """TTS adapter backed by the ElevenLabs API.

    :param api_key: ElevenLabs API key.
    :param voice: Voice name *or* voice ID (default ``"Rachel"``).
    :param model: Model identifier (default ``"eleven_multilingual_v2"``).
    :param lang: Language hint (not used by API, kept for interface compat).
    """

    name = "elevenlabs"
    requires_credentials = True
    supports_chunking = True
    max_chunk_chars = 5000

    def __init__(
        self,
        api_key: str = "",
        voice: str = "Rachel",
        model: str = "eleven_multilingual_v2",
        lang: str = "en",
    ):
        try:
            from elevenlabs.client import ElevenLabs  # noqa: F811
        except ImportError as e:
            raise TTSEngineNotInstalledError(
                "elevenlabs is not installed. "
                "Install with: poetry install --with elevenlabs",
                engine=self.name,
                original=e,
            ) from e

        if not api_key:
            raise TTSCredentialsMissingError(
                "ElevenLabs API key must be provided",
                engine=self.name,
            )

        self._elevenlabs_cls = ElevenLabs
        self.api_key = api_key
        self.voice = voice
        self.model = model
        self.lang = lang
        self._client = None

    @property
    def client(self):
        if self._client is None:
            self._client = self._elevenlabs_cls(api_key=self.api_key)
        return self._client

    def synthesize(self, text: str, output_path: Path) -> None:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        chunks = split_text_into_chunks(text, max_chars=self.max_chunk_chars)

        with open(output_path, "wb") as f:
            for chunk in chunks:
                audio = self._synthesize_chunk(chunk)
                for audio_chunk in audio:
                    f.write(audio_chunk)

    @with_retry()
    def _synthesize_chunk(self, text: str):
        """Synthesize a single chunk via the ElevenLabs API."""
        try:
            return self.client.text_to_speech.convert(
                voice_id=self.voice,
                text=text,
                model_id=self.model,
                output_format="mp3_44100_128",
            )
        except Exception as exc:
            self._map_exception(exc)

    def list_voices(self, language_code: Optional[str] = None) -> list[VoiceInfo]:
        try:
            response = self.client.voices.get_all()
        except Exception as exc:
            self._map_exception(exc)

        result: list[VoiceInfo] = []
        for v in response.voices:
            labels = getattr(v, "labels", {}) or {}
            gender = labels.get("gender", "neutral")
            lang = labels.get("language", "en")

            if language_code and not lang.lower().startswith(language_code.lower()):
                continue

            result.append(
                VoiceInfo(
                    engine=self.name,
                    voice_id=v.voice_id,
                    display_name=v.name or v.voice_id,
                    language=lang,
                    gender=gender,
                    quality="premium",
                )
            )
        return result

    def validate(self) -> tuple[bool, str]:
        try:
            self.client.user.get()
            return True, "Credentials valid"
        except Exception as e:
            return False, str(e)

    def estimate_cost(self, text: str) -> float:
        return len(text) * _COST_PER_1K_CHARS / 1000

    def check_quota(self) -> Optional[QuotaInfo]:
        try:
            user = self.client.user.get()
            sub = getattr(user, "subscription", None)
            if sub:
                return QuotaInfo(
                    used=getattr(sub, "character_count", 0),
                    limit=getattr(sub, "character_limit", 0),
                )
        except Exception:
            pass
        return None

    def _map_exception(self, exc: Exception):
        """Map ElevenLabs exceptions to TTSError hierarchy."""
        msg = str(exc).lower()
        if "unauthorized" in msg or "invalid api key" in msg or "401" in msg:
            raise TTSCredentialsInvalidError(
                f"ElevenLabs credentials invalid: {exc}",
                engine=self.name,
                original=exc,
            ) from exc
        if "quota" in msg or "limit" in msg or "429" in msg:
            raise TTSQuotaExceededError(
                f"ElevenLabs quota exceeded: {exc}",
                engine=self.name,
                original=exc,
            ) from exc
        if "5" in str(getattr(exc, "status_code", "")) or "server" in msg:
            raise TTSTransientError(
                f"ElevenLabs service error: {exc}",
                engine=self.name,
                original=exc,
            ) from exc
        raise TTSTransientError(
            f"ElevenLabs error: {exc}",
            engine=self.name,
            original=exc,
        ) from exc
