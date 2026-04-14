import pytest

pytestmark = pytest.mark.unit

"""Tests for the TTSError exception hierarchy."""

from manuscripta.audiobook.tts.exceptions import (
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


def test_tts_error_base():
    e = TTSError("boom", engine="test", original=ValueError("orig"))
    assert str(e) == "boom"
    assert e.engine == "test"
    assert isinstance(e.original, ValueError)


def test_engine_not_installed_is_tts_error():
    e = TTSEngineNotInstalledError("missing lib")
    assert isinstance(e, TTSError)


def test_credentials_hierarchy():
    assert issubclass(TTSCredentialsMissingError, TTSCredentialsError)
    assert issubclass(TTSCredentialsInvalidError, TTSCredentialsError)
    assert issubclass(TTSCredentialsError, TTSError)


def test_quota_exceeded():
    e = TTSQuotaExceededError("over limit", engine="el")
    assert isinstance(e, TTSError)
    assert e.engine == "el"


def test_invalid_input():
    e = TTSInvalidInputError("bad text")
    assert isinstance(e, TTSError)


def test_transient_error_retryable():
    e = TTSTransientError("timeout", retryable=True)
    assert e.retryable is True
    assert isinstance(e, TTSError)


def test_transient_error_not_retryable():
    e = TTSTransientError("permanent-ish", retryable=False)
    assert e.retryable is False


def test_service_unavailable_is_transient():
    e = TTSServiceUnavailableError("503")
    assert isinstance(e, TTSTransientError)
    assert isinstance(e, TTSError)
    assert e.retryable is True
