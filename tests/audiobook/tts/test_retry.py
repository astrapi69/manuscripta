"""Tests for the retry decorator."""

import pytest

from manuscripta.audiobook.tts.exceptions import TTSError, TTSTransientError
from manuscripta.audiobook.tts.retry import with_retry


class TestWithRetry:
    def test_succeeds_on_first_attempt(self):
        call_count = 0

        @with_retry(max_attempts=3, min_wait=0.01, max_wait=0.02)
        def fn():
            nonlocal call_count
            call_count += 1
            return "ok"

        assert fn() == "ok"
        assert call_count == 1

    def test_retries_on_transient_error(self):
        call_count = 0

        @with_retry(max_attempts=3, min_wait=0.01, max_wait=0.02)
        def fn():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise TTSTransientError("transient")
            return "recovered"

        assert fn() == "recovered"
        assert call_count == 3

    def test_raises_after_max_attempts(self):
        @with_retry(max_attempts=2, min_wait=0.01, max_wait=0.02)
        def fn():
            raise TTSTransientError("always fails")

        with pytest.raises(TTSTransientError, match="always fails"):
            fn()

    def test_does_not_retry_non_transient_error(self):
        call_count = 0

        @with_retry(max_attempts=3, min_wait=0.01, max_wait=0.02)
        def fn():
            nonlocal call_count
            call_count += 1
            raise TTSError("permanent")

        with pytest.raises(TTSError, match="permanent"):
            fn()
        assert call_count == 1

    def test_does_not_retry_generic_exception(self):
        call_count = 0

        @with_retry(max_attempts=3, min_wait=0.01, max_wait=0.02)
        def fn():
            nonlocal call_count
            call_count += 1
            raise ValueError("not a TTS error")

        with pytest.raises(ValueError):
            fn()
        assert call_count == 1
