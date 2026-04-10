"""TTS exception hierarchy.

All TTS adapters raise exceptions from this module instead of generic
RuntimeError or ValueError.  This allows callers to handle errors by
category (transient vs. permanent, credentials vs. quota, etc.).
"""


class TTSError(Exception):
    """Base exception for all TTS errors."""

    def __init__(
        self,
        message: str,
        engine: str = "",
        original: Exception | None = None,
    ):
        super().__init__(message)
        self.engine = engine
        self.original = original


class TTSEngineNotInstalledError(TTSError):
    """Engine dependency not installed (e.g. google-cloud-texttospeech missing)."""


class TTSCredentialsError(TTSError):
    """Base for credential-related errors."""


class TTSCredentialsMissingError(TTSCredentialsError):
    """No credentials provided for an engine that requires them."""


class TTSCredentialsInvalidError(TTSCredentialsError):
    """Credentials were rejected by the API."""


class TTSQuotaExceededError(TTSError):
    """API quota or rate limit exceeded."""


class TTSInvalidInputError(TTSError):
    """Input text or parameters rejected by the engine."""


class TTSTransientError(TTSError):
    """Temporary failure, retry may help."""

    def __init__(self, message: str, retryable: bool = True, **kwargs):
        super().__init__(message, **kwargs)
        self.retryable = retryable


class TTSServiceUnavailableError(TTSTransientError):
    """API is temporarily down."""
