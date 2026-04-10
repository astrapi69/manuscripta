"""Central retry decorator for TTS adapters.

Uses tenacity for exponential backoff.  Adapters apply ``@with_retry()``
to their internal synthesis methods so that transient network/service
errors are retried transparently.
"""

from functools import wraps

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .exceptions import TTSTransientError


def with_retry(
    max_attempts: int = 3,
    min_wait: float = 1.0,
    max_wait: float = 8.0,
):
    """Decorator for retrying on transient TTS errors."""

    def decorator(func):
        @retry(
            retry=retry_if_exception_type(TTSTransientError),
            stop=stop_after_attempt(max_attempts),
            wait=wait_exponential(multiplier=1, min=min_wait, max=max_wait),
            reraise=True,
        )
        @wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)

        return wrapper

    return decorator
