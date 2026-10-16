#!/usr/bin/env python3
# tests/test_make_tag_message_test_ask_helpers.py
"""Tests for interactive ask_* helpers in scripts/make_tag_message.py."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.unit

# Import module under test
import manuscripta.project.tag_message as mtm


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def disable_questionary(monkeypatch):
    """Force fallback (no questionary) for all tests unless overridden."""
    monkeypatch.setattr(mtm, "questionary", None)


def make_questionary_mock():
    """Create a mock questionary module with chainable .ask() API."""
    mock = MagicMock()

    def _chain(return_value):
        chain = MagicMock()
        chain.ask.return_value = return_value
        return chain

    mock._chain = _chain
    return mock


# ===========================================================================
# ask_confirm
# ===========================================================================

# Each row: the answers typed at the input() fallback (the last one is
# accepted), the default, the result
CONFIRM_FALLBACK_CASES = [
    pytest.param(["y"], False, True, id="yes-y"),
    pytest.param(["yes"], False, True, id="yes-yes"),
    pytest.param(["Y"], False, True, id="yes-Y"),
    pytest.param(["YES"], False, True, id="yes-YES"),
    pytest.param(["Yes"], False, True, id="yes-Yes"),
    pytest.param(["j"], False, True, id="german-yes-j"),
    pytest.param(["ja"], False, True, id="german-yes-ja"),
    pytest.param(["J"], False, True, id="german-yes-J"),
    pytest.param(["JA"], False, True, id="german-yes-JA"),
    pytest.param(["Ja"], False, True, id="german-yes-Ja"),
    pytest.param(["n"], False, False, id="no-n"),
    pytest.param(["no"], False, False, id="no-no"),
    pytest.param(["N"], False, False, id="no-N"),
    pytest.param(["NO"], False, False, id="no-NO"),
    pytest.param(["No"], False, False, id="no-No"),
    pytest.param(["nein"], False, False, id="german-no-nein"),
    pytest.param(["NEIN"], False, False, id="german-no-NEIN"),
    pytest.param(["Nein"], False, False, id="german-no-Nein"),
    pytest.param([""], False, False, id="empty-returns-default-false"),
    pytest.param([""], True, True, id="empty-returns-default-true"),
    # Nonsense input loops, then accepts valid input.
    pytest.param(["x", "maybe", "y"], False, True, id="invalid-then-valid"),
    pytest.param(["abc", "n"], False, False, id="invalid-then-no"),
    pytest.param(["true"], False, True, id="true-string"),
    pytest.param(["false"], False, False, id="false-string"),
    pytest.param(["1"], False, True, id="numeric-1"),
    pytest.param(["0"], False, False, id="numeric-0"),
]


class TestAskConfirmFallback:
    """Tests for ask_confirm without questionary (input() fallback)."""

    @pytest.mark.parametrize("answers, default, expected", CONFIRM_FALLBACK_CASES)
    def test_fallback(self, answers, default, expected):
        with patch("builtins.input", side_effect=answers):
            assert mtm.ask_confirm("Continue?", default=default) is expected


# ===========================================================================
# ask_choice
# ===========================================================================

CHOICES = ["Alpha", "Beta", "Gamma"]

# Each row: the answers typed at the input() fallback (the last one is
# accepted), the default, the choice returned
CHOICE_FALLBACK_CASES = [
    pytest.param(["1"], None, "Alpha", id="select-by-number"),
    pytest.param(["3"], None, "Gamma", id="select-last-by-number"),
    pytest.param(["Beta"], None, "Beta", id="select-by-exact-text"),
    pytest.param([""], "Beta", "Beta", id="empty-returns-default"),
    pytest.param(["0", "5", "99", "2"], None, "Beta", id="out-of-range-then-valid"),
    pytest.param(["xyz", "2"], None, "Beta", id="nonsense-then-valid"),
    # Empty input without default should loop, not return.
    pytest.param(["", "1"], None, "Alpha", id="empty-without-default-loops"),
    pytest.param(["-1", "1"], None, "Alpha", id="negative-number-loops"),
]


class TestAskChoiceFallback:
    """Tests for ask_choice without questionary."""

    @pytest.mark.parametrize("answers, default, expected", CHOICE_FALLBACK_CASES)
    def test_fallback(self, answers, default, expected):
        with patch("builtins.input", side_effect=answers):
            assert mtm.ask_choice("Pick:", CHOICES, default=default) == expected


# ===========================================================================
# ask_text
# ===========================================================================

# Each row: the answer typed at the input() fallback, the default, the text
# returned
TEXT_FALLBACK_CASES = [
    pytest.param("hello", None, "hello", id="returns-user-input"),
    pytest.param("", "world", "world", id="empty-returns-default"),
    pytest.param("", None, "", id="empty-no-default-returns-empty"),
    pytest.param("  trimmed  ", None, "trimmed", id="strips-whitespace"),
]


class TestAskTextFallback:
    """Tests for ask_text without questionary."""

    @pytest.mark.parametrize("answer, default, expected", TEXT_FALLBACK_CASES)
    def test_fallback(self, answer, default, expected):
        with patch("builtins.input", return_value=answer):
            assert mtm.ask_text("Name:", default=default) == expected

    def test_validate_called(self):
        validator = MagicMock()
        with patch("builtins.input", return_value="ok"):
            mtm.ask_text("Name:", validate=validator)
        validator.assert_called_once_with("ok")

    def test_validate_raises_propagates(self):
        def bad_validator(val):
            raise SystemExit("Invalid tag")

        with patch("builtins.input", return_value="bad"):
            with pytest.raises(SystemExit, match="Invalid tag"):
                mtm.ask_text("Tag:", validate=bad_validator)


# ===========================================================================
# ask_* with questionary
# ===========================================================================

# Each row: the helper, the questionary method it calls, the helper's
# arguments, the answer questionary returns, the result
QUESTIONARY_ANSWERS = [
    pytest.param(
        mtm.ask_confirm, "confirm", ("Continue?",), True, True, id="confirm-true"
    ),
    pytest.param(
        mtm.ask_confirm, "confirm", ("Continue?",), False, False, id="confirm-false"
    ),
    pytest.param(
        mtm.ask_choice,
        "select",
        ("Pick:", CHOICES),
        "Beta",
        "Beta",
        id="choice-returns-value",
    ),
    pytest.param(
        mtm.ask_text, "text", ("Name:",), "answer", "answer", id="text-returns-value"
    ),
]

# Each row: the helper, the questionary method it calls, the helper's arguments;
# questionary answers None (Ctrl-C) and the helper aborts
QUESTIONARY_ABORTS = [
    pytest.param(mtm.ask_confirm, "confirm", ("Continue?",), id="confirm-none-aborts"),
    pytest.param(mtm.ask_choice, "select", ("Pick:", CHOICES), id="choice-none-aborts"),
    pytest.param(mtm.ask_text, "text", ("Name:",), id="text-none-aborts"),
]


class TestQuestionary:
    """Tests for ask_confirm, ask_choice and ask_text with questionary."""

    @pytest.mark.parametrize(
        "helper, method, args, answer, expected", QUESTIONARY_ANSWERS
    )
    def test_returns_answer(self, helper, method, args, answer, expected, monkeypatch):
        mock_q = make_questionary_mock()
        getattr(mock_q, method).return_value = mock_q._chain(answer)
        monkeypatch.setattr(mtm, "questionary", mock_q)
        result = helper(*args)
        assert result == expected
        assert type(result) is type(expected)

    @pytest.mark.parametrize("helper, method, args", QUESTIONARY_ABORTS)
    def test_none_aborts(self, helper, method, args, monkeypatch):
        mock_q = make_questionary_mock()
        getattr(mock_q, method).return_value = mock_q._chain(None)
        monkeypatch.setattr(mtm, "questionary", mock_q)
        with pytest.raises(SystemExit, match="Aborted"):
            helper(*args)


# ===========================================================================
# ask_int
# ===========================================================================

# Each row: the answers typed (the last one is accepted), the default, the
# minimum, the number returned
INT_CASES = [
    pytest.param(["42"], 10, 0, 42, id="valid-number"),
    pytest.param([""], 100, 0, 100, id="empty-returns-default"),
    pytest.param(["abc", "xyz", "50"], 10, 0, 50, id="non-numeric-then-valid"),
    pytest.param(["0", "-5", "3"], 10, 1, 3, id="below-minimum-then-valid"),
    pytest.param(["1"], 10, 1, 1, id="minimum-exact"),
    pytest.param(["3.14", "3"], 10, 0, 3, id="float-string-rejected"),
    pytest.param(["0"], 10, 0, 0, id="zero-accepted-when-minimum-zero"),
]


class TestAskInt:
    """Tests for ask_int (always uses ask_text internally)."""

    @pytest.mark.parametrize("answers, default, minimum, expected", INT_CASES)
    def test_ask_int(self, answers, default, minimum, expected):
        with patch("builtins.input", side_effect=answers):
            assert mtm.ask_int("Count:", default=default, minimum=minimum) == expected
