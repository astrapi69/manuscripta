"""TTS adapters for audiobook generation.

Public API
----------
- :func:`create_adapter` -- factory to instantiate an adapter by engine name.
- :class:`TTSAdapter` -- abstract base class all adapters implement.
- :class:`VoiceInfo`, :class:`QuotaInfo` -- data containers.
- Exception hierarchy rooted at :class:`TTSError`.

Adapter classes
---------------
- :class:`EdgeTTSAdapter` -- Microsoft Edge neural TTS (free, online).
- :class:`ElevenLabsAdapter` -- ElevenLabs API (paid, online).
- :class:`GoogleCloudTTSAdapter` -- Google Cloud TTS (paid, online).
- :class:`GoogleTranslateTTSAdapter` -- gTTS / Google Translate (free, online, deprecated).
- :class:`Pyttsx3Adapter` -- pyttsx3 system voices (free, offline).
"""

from .base import QuotaInfo, TTSAdapter, VoiceInfo
from .exceptions import (
    TTSCredentialsError,
    TTSCredentialsInvalidError,
    TTSCredentialsMissingError,
    TTSEngineNotInstalledError,
    TTSError,
    TTSInvalidInputError,
    TTSQuotaExceededError,
    TTSServiceUnavailableError,
    TTSTransientError,
)

# Adapters use lazy imports so optional deps don't break the package.
from .edge_tts_adapter import EdgeTTSAdapter


def _lazy_elevenlabs():
    from .elevenlabs_adapter import ElevenLabsAdapter

    return ElevenLabsAdapter


def _lazy_google_cloud():
    from .google_cloud_tts_adapter import GoogleCloudTTSAdapter

    return GoogleCloudTTSAdapter


def _lazy_google_translate():
    from .google_translate_adapter import GoogleTranslateTTSAdapter

    return GoogleTranslateTTSAdapter


def _lazy_google_translate_alias():
    from .google_translate_adapter import GoogleTTSAdapter

    return GoogleTTSAdapter


def _lazy_pyttsx3():
    from .pyttsx3_adapter import Pyttsx3Adapter

    return Pyttsx3Adapter


def create_adapter(engine_name: str, **kwargs) -> TTSAdapter:
    """Factory function to create a TTS adapter by name.

    :param engine_name: One of ``"edge-tts"``, ``"edge"``, ``"elevenlabs"``,
        ``"google-cloud-tts"``, ``"google-translate"``, ``"gtts"``,
        ``"pyttsx3"``.
    :param kwargs: Passed through to the adapter constructor.
    :raises ValueError: If *engine_name* is not recognised.
    """
    adapters = {
        "edge-tts": EdgeTTSAdapter,
        "edge": EdgeTTSAdapter,
        "elevenlabs": _lazy_elevenlabs(),
        "google-cloud-tts": _lazy_google_cloud(),
        "google-translate": _lazy_google_translate(),
        "gtts": _lazy_google_translate(),
        "pyttsx3": _lazy_pyttsx3(),
    }

    if engine_name not in adapters:
        raise ValueError(
            f"Unknown engine: {engine_name}. "
            f"Available: {', '.join(sorted(adapters.keys()))}"
        )

    return adapters[engine_name](**kwargs)


__all__ = [
    # Base
    "TTSAdapter",
    "VoiceInfo",
    "QuotaInfo",
    # Exceptions
    "TTSError",
    "TTSEngineNotInstalledError",
    "TTSCredentialsError",
    "TTSCredentialsMissingError",
    "TTSCredentialsInvalidError",
    "TTSQuotaExceededError",
    "TTSInvalidInputError",
    "TTSTransientError",
    "TTSServiceUnavailableError",
    # Adapters
    "EdgeTTSAdapter",
    # Factory
    "create_adapter",
]
