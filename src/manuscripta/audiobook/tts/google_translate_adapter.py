"""Google Translate TTS adapter (gTTS).

Uses the unofficial ``gTTS`` library which scrapes Google Translate.
Quality is limited to standard voices.

For production use, consider :class:`GoogleCloudTTSAdapter` which uses
the official Google Cloud Text-to-Speech API with higher-quality voices.

Requires:
    poetry install --with google-translate
"""

import warnings
from pathlib import Path
from typing import Optional

from manuscripta.audiobook.tts.base import TTSAdapter, VoiceInfo
from manuscripta.audiobook.tts.exceptions import (
    TTSEngineNotInstalledError,
    TTSTransientError,
)
from manuscripta.audiobook.tts.retry import with_retry


class GoogleTranslateTTSAdapter(TTSAdapter):
    """TTS adapter using gTTS (Google Translate text-to-speech).

    .. deprecated::
        This adapter uses the unofficial gTTS library which scrapes
        Google Translate.  For production use, prefer
        :class:`GoogleCloudTTSAdapter`.
    """

    name = "google-translate"
    requires_credentials = False
    supports_chunking = False
    max_chunk_chars = 5000

    def __init__(self, lang: str = "en"):
        try:
            from gtts import gTTS  # noqa: F401
        except ImportError as e:
            raise TTSEngineNotInstalledError(
                "gTTS is not installed. "
                "Install with: poetry install --with google-translate",
                engine=self.name,
                original=e,
            ) from e

        warnings.warn(
            "GoogleTranslateTTSAdapter uses the unofficial gtts library which "
            "scrapes Google Translate. Quality is limited to standard voices. "
            "For production use, consider GoogleCloudTTSAdapter.",
            DeprecationWarning,
            stacklevel=2,
        )
        self.lang = lang

    @with_retry()
    def synthesize(self, text: str, output_path: Path) -> None:
        from gtts import gTTS

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            tts = gTTS(text=text, lang=self.lang)
            tts.save(str(output_path))
        except Exception as exc:
            msg = str(exc).lower()
            if "connection" in msg or "timeout" in msg or "503" in msg:
                raise TTSTransientError(
                    f"Google Translate TTS failed: {exc}",
                    engine=self.name,
                    original=exc,
                ) from exc
            raise

    def list_voices(self, language_code: Optional[str] = None) -> list[VoiceInfo]:
        from gtts.lang import tts_langs

        langs = tts_langs()
        result: list[VoiceInfo] = []
        for code, name in langs.items():
            if language_code and not code.lower().startswith(language_code.lower()):
                continue
            result.append(
                VoiceInfo(
                    engine=self.name,
                    voice_id=code,
                    display_name=name,
                    language=code,
                    gender="neutral",
                    quality="standard",
                )
            )
        return result


# Deprecated alias -- will be removed in v0.8.0
class GoogleTTSAdapter(GoogleTranslateTTSAdapter):
    """Deprecated: use :class:`GoogleTranslateTTSAdapter` instead."""

    def __init__(self, *args, **kwargs):
        warnings.warn(
            "GoogleTTSAdapter is deprecated, use GoogleTranslateTTSAdapter instead. "
            "Will be removed in v0.8.0.",
            DeprecationWarning,
            stacklevel=2,
        )
        super().__init__(*args, **kwargs)
