"""Abstract base class and data types for TTS adapters.

Every TTS engine implements :class:`TTSAdapter`.  The two dataclasses
:class:`VoiceInfo` and :class:`QuotaInfo` provide a uniform way to
describe voices and usage quotas across engines.
"""

import warnings
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class VoiceInfo:
    """Metadata about a TTS voice."""

    engine: str
    voice_id: str
    display_name: str
    language: str
    gender: str  # "male", "female", "neutral"
    quality: str = "standard"


@dataclass(frozen=True)
class QuotaInfo:
    """Current usage information for a TTS engine."""

    used: int
    limit: int
    resets_at: Optional[str] = None  # ISO datetime


class TTSAdapter(ABC):
    """Abstract base for all TTS engines."""

    name: str = ""
    requires_credentials: bool = False
    supports_chunking: bool = True
    max_chunk_chars: int = 4000

    @abstractmethod
    def synthesize(self, text: str, output_path: Path) -> None:
        """Generate speech audio from *text* and save to *output_path*."""

    @abstractmethod
    def list_voices(self, language_code: Optional[str] = None) -> list[VoiceInfo]:
        """List available voices, optionally filtered by language."""

    def validate(self) -> tuple[bool, str]:
        """Validate credentials / availability.  Returns ``(ok, message)``."""
        return True, "No validation needed"

    def estimate_cost(self, text: str) -> Optional[float]:
        """Estimate cost in USD for synthesizing *text*.  ``None`` = free."""
        return None

    def check_quota(self) -> Optional[QuotaInfo]:
        """Return current quota usage.  ``None`` = no quota info available."""
        return None

    # -- backward compatibility ------------------------------------------------

    def speak(self, text: str, output_path: Path) -> None:
        """Deprecated alias for :meth:`synthesize`."""
        warnings.warn(
            "TTSAdapter.speak() is deprecated, use synthesize() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        self.synthesize(text, output_path)
