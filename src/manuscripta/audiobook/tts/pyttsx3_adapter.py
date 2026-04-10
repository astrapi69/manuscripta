"""Pyttsx3 offline TTS adapter.

Uses the system's built-in speech synthesis (SAPI5 on Windows, NSSpeech
on macOS, espeak on Linux).  No internet connection required.

Requires:
    poetry install --with pyttsx3
"""

from pathlib import Path
from typing import Optional

from manuscripta.audiobook.tts.base import TTSAdapter, VoiceInfo
from manuscripta.audiobook.tts.exceptions import (
    TTSCredentialsMissingError,
    TTSEngineNotInstalledError,
)


class Pyttsx3Adapter(TTSAdapter):
    """Offline TTS adapter using pyttsx3 (system voices).

    The pyttsx3 engine is initialized lazily on first use.

    :param voice: System voice ID (platform-specific).  ``None`` = default.
    :param rate: Speech rate in words-per-minute (default 180).
    """

    name = "pyttsx3"
    requires_credentials = False
    supports_chunking = False

    def __init__(self, voice: Optional[str] = None, rate: int = 180):
        try:
            import pyttsx3  # noqa: F401
        except ImportError as e:
            raise TTSEngineNotInstalledError(
                "pyttsx3 is not installed. "
                "Install with: poetry install --with pyttsx3",
                engine=self.name,
                original=e,
            ) from e

        self._voice = voice
        self._rate = rate
        self._engine = None

    @property
    def engine(self):
        """Lazily initialize the pyttsx3 engine."""
        if self._engine is None:
            import pyttsx3

            try:
                self._engine = pyttsx3.init()
            except Exception as e:
                raise TTSCredentialsMissingError(
                    "No system speech engine available. "
                    "On Linux, install espeak: sudo apt install espeak",
                    engine=self.name,
                    original=e,
                ) from e
            if self._voice:
                self._engine.setProperty("voice", self._voice)
            self._engine.setProperty("rate", self._rate)
        return self._engine

    def synthesize(self, text: str, output_path: Path) -> None:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        self.engine.save_to_file(text, str(output_path))
        self.engine.runAndWait()

    def list_voices(self, language_code: Optional[str] = None) -> list[VoiceInfo]:
        voices = self.engine.getProperty("voices") or []
        result: list[VoiceInfo] = []
        for v in voices:
            # pyttsx3 voice objects have .id, .name, .languages, .gender
            langs = getattr(v, "languages", []) or []
            lang = langs[0] if langs else ""
            if isinstance(lang, bytes):
                lang = lang.decode("utf-8", errors="replace")

            if (
                language_code
                and lang
                and not str(lang).lower().startswith(language_code.lower())
            ):
                continue

            gender_raw = getattr(v, "gender", None)
            if isinstance(gender_raw, str):
                gender = (
                    gender_raw.lower()
                    if gender_raw.lower() in ("male", "female")
                    else "neutral"
                )
            else:
                gender = "neutral"

            result.append(
                VoiceInfo(
                    engine=self.name,
                    voice_id=v.id,
                    display_name=getattr(v, "name", v.id),
                    language=str(lang),
                    gender=gender,
                    quality="standard",
                )
            )
        return result
