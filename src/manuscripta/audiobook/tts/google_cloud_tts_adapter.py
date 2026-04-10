"""Google Cloud Text-to-Speech adapter.

Uses the official ``google-cloud-texttospeech`` library.
Requires a Service Account JSON key file.

Quality tiers:
    - journey: highest quality, natural prosody (premium)
    - neural2: high quality, commercial grade
    - studio: professional voice-over quality
    - wavenet: DeepMind WaveNet technology
    - standard: basic parametric synthesis

Requires:
    poetry install --with google-cloud-tts
"""

from pathlib import Path
from typing import Optional

from manuscripta.audiobook.tts.base import TTSAdapter, VoiceInfo
from manuscripta.audiobook.tts.exceptions import (
    TTSCredentialsInvalidError,
    TTSEngineNotInstalledError,
    TTSError,
    TTSInvalidInputError,
    TTSQuotaExceededError,
    TTSTransientError,
)
from manuscripta.audiobook.tts.retry import with_retry
from manuscripta.audiobook.tts.text_chunking import split_text_into_chunks

# Pricing per 1M characters, USD
GOOGLE_CLOUD_TTS_PRICING = {
    "standard": 4.00,
    "wavenet": 16.00,
    "neural2": 16.00,
    "studio": 160.00,
    "journey": 30.00,
}


class GoogleCloudTTSAdapter(TTSAdapter):
    """TTS adapter using the official Google Cloud Text-to-Speech API.

    :param credentials_path: Path to a GCP service-account JSON key file.
    :param voice_id: Voice name, e.g. ``"de-DE-Neural2-B"``.
    :param language: BCP-47 language code, e.g. ``"de-DE"``.
    """

    name = "google-cloud-tts"
    requires_credentials = True
    supports_chunking = True
    max_chunk_chars = 5000

    def __init__(
        self,
        credentials_path: str | Path = "",
        voice_id: str = "",
        language: str = "de-DE",
    ):
        try:
            from google.cloud import texttospeech
            from google.oauth2 import service_account
        except ImportError as e:
            raise TTSEngineNotInstalledError(
                "google-cloud-texttospeech is not installed. "
                "Install with: poetry install --with google-cloud-tts",
                engine=self.name,
                original=e,
            ) from e

        self._texttospeech = texttospeech
        self._service_account = service_account
        self.credentials_path = Path(credentials_path) if credentials_path else None
        self.voice_id = voice_id
        self.language = language
        self._client = None

    @property
    def client(self):
        if self._client is None:
            if self.credentials_path:
                creds = self._service_account.Credentials.from_service_account_file(
                    str(self.credentials_path)
                )
                self._client = self._texttospeech.TextToSpeechClient(credentials=creds)
            else:
                self._client = self._texttospeech.TextToSpeechClient()
        return self._client

    @with_retry()
    def _synthesize_chunk(self, text: str) -> bytes:
        """Synthesize one chunk, with error mapping."""
        from google.api_core import exceptions as gexc

        try:
            response = self.client.synthesize_speech(
                input=self._texttospeech.SynthesisInput(text=text),
                voice=self._texttospeech.VoiceSelectionParams(
                    language_code=self.language,
                    name=self.voice_id,
                ),
                audio_config=self._texttospeech.AudioConfig(
                    audio_encoding=self._texttospeech.AudioEncoding.MP3,
                ),
            )
            return response.audio_content
        except gexc.PermissionDenied as e:
            raise TTSCredentialsInvalidError(
                "Service account lacks Cloud Text-to-Speech User role",
                engine=self.name,
                original=e,
            ) from e
        except gexc.ResourceExhausted as e:
            raise TTSQuotaExceededError(
                "Google Cloud TTS quota exceeded",
                engine=self.name,
                original=e,
            ) from e
        except gexc.InvalidArgument as e:
            raise TTSInvalidInputError(
                f"Invalid request: {e.message}",
                engine=self.name,
                original=e,
            ) from e
        except (gexc.DeadlineExceeded, gexc.ServiceUnavailable) as e:
            raise TTSTransientError(
                f"Google Cloud TTS temporarily unavailable: {e.message}",
                engine=self.name,
                original=e,
            ) from e

    def synthesize(self, text: str, output_path: Path) -> None:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        chunks = split_text_into_chunks(text, max_chars=self.max_chunk_chars)

        with open(output_path, "wb") as f:
            for chunk in chunks:
                audio = self._synthesize_chunk(chunk)
                f.write(audio)

    def list_voices(self, language_code: Optional[str] = None) -> list[VoiceInfo]:
        request = self._texttospeech.ListVoicesRequest()
        if language_code:
            request.language_code = language_code

        response = self.client.list_voices(request=request)

        voices: list[VoiceInfo] = []
        for voice in response.voices:
            quality = self._detect_quality(voice.name)
            gender = self._map_gender(voice.ssml_gender)
            display_name = self._format_display_name(voice.name)

            for lang in voice.language_codes:
                voices.append(
                    VoiceInfo(
                        engine=self.name,
                        voice_id=voice.name,
                        display_name=display_name,
                        language=lang,
                        gender=gender,
                        quality=quality,
                    )
                )
        return voices

    def validate(self) -> tuple[bool, str]:
        try:
            self.list_voices(language_code="en-US")
            return True, "Credentials valid"
        except TTSError as e:
            return False, str(e)

    def estimate_cost(self, text: str) -> float:
        quality = self._detect_quality(self.voice_id)
        rate = GOOGLE_CLOUD_TTS_PRICING.get(quality, 16.00)
        return len(text) * rate / 1_000_000

    @staticmethod
    def _detect_quality(voice_name: str) -> str:
        name_lower = voice_name.lower()
        for tier in ["journey", "neural2", "studio", "wavenet"]:
            if tier in name_lower:
                return tier
        return "standard"

    @staticmethod
    def _map_gender(ssml_gender) -> str:
        gender_name = (
            ssml_gender.name if hasattr(ssml_gender, "name") else str(ssml_gender)
        )
        mapping = {"MALE": "male", "FEMALE": "female", "NEUTRAL": "neutral"}
        return mapping.get(gender_name, "neutral")

    @staticmethod
    def _format_display_name(voice_name: str) -> str:
        parts = voice_name.split("-")
        if len(parts) >= 4:
            return "-".join(parts[2:])
        return voice_name
