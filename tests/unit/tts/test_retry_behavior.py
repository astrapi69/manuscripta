"""Behavioral tests for manuscripta.audiobook.tts.retry.with_retry.

These tests pin the **public default parameter values** of
``with_retry`` as a coverage-layer contract: a caller who omits
``max_attempts`` / ``min_wait`` / ``max_wait`` observes exactly
three attempts, a first-retry wait of 1.0 s, and a backoff cap at
8.0 s. Breaking any of those defaults is a user-visible change
and should fail these tests.

**These tests do NOT kill mutation-testing survivors.** The three
mutmut-3.x mutants on ``with_retry``'s default arguments
(`x_with_retry__mutmut_{1,2,3}`) are **structurally equivalent**
under the mutmut trampoline: see
[TESTING.md §14.8.3](../../../docs/TESTING.md#1483-trampoline-induced-equivalence).
The tests live here as general-purpose pinning of the public
contract, orthogonal to the mutation-response work tracked in
ADR-0002.

The tests patch ``time.sleep`` as the observation channel.
Tenacity's nap module calls ``time.sleep`` at module-level-attribute
lookup time, so a plain ``unittest.mock.patch("time.sleep", ...)``
within each test captures every retry wait without real time
elapsing.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

pytestmark = pytest.mark.unit

from manuscripta.audiobook.tts.exceptions import TTSTransientError
from manuscripta.audiobook.tts.retry import with_retry


# ---------------------------------------------------------------------------
# Mutant 1: max_attempts default
# ---------------------------------------------------------------------------


def test_max_attempts_defaults_to_three():
    """The ``with_retry()`` decorator with no arguments must retry a
    ``TTSTransientError``-raising callable exactly three times total
    (one original + two retries) before re-raising.

    Kills ``x_with_retry__mutmut_1`` which changes the default to 4.
    """
    calls = 0

    @with_retry()
    def always_fails():
        nonlocal calls
        calls += 1
        raise TTSTransientError("simulated upstream flake")

    with patch("time.sleep"):  # instant retries
        with pytest.raises(TTSTransientError):
            always_fails()

    assert calls == 3, (
        f"Expected 3 attempts (default max_attempts=3); got {calls}. "
        f"A higher count indicates the default was raised, which would "
        f"change user-visible retry-fatigue behaviour on persistently "
        f"broken upstream services."
    )


# ---------------------------------------------------------------------------
# Mutant 2: min_wait default
# ---------------------------------------------------------------------------


def test_min_wait_floor_defaults_to_one_second():
    """The first retry's wait, with ``with_retry()`` defaults, must be
    at the min_wait floor of 1.0 s.

    Rationale: tenacity's ``wait_exponential(multiplier=1, min=1, max=8)``
    on the first retry computes ``multiplier * 2**0 = 1.0``, which is
    exactly the floor. The value 1.0 is observable as the first
    ``time.sleep`` call argument.

    Kills ``x_with_retry__mutmut_2`` which raises the default floor
    to 2.0; the first sleep would then be 2.0, not 1.0.
    """
    sleeps: list[float] = []

    @with_retry()
    def always_fails():
        raise TTSTransientError("simulated")

    with patch("time.sleep", side_effect=sleeps.append):
        with pytest.raises(TTSTransientError):
            always_fails()

    # At least one retry wait should have occurred (since max_attempts=3
    # means 2 retry waits: after attempt 1 and after attempt 2).
    assert sleeps, "no time.sleep captured; tenacity call path changed?"
    assert sleeps[0] == pytest.approx(1.0, abs=0.01), (
        f"Expected first retry wait == 1.0 s (default min_wait); "
        f"got {sleeps[0]}. A higher value indicates min_wait was raised, "
        f"which makes first-retry latency noticeably slower on the happy "
        f"retry path."
    )


# ---------------------------------------------------------------------------
# Mutant 3: max_wait default
# ---------------------------------------------------------------------------


def test_max_wait_cap_defaults_to_eight_seconds():
    """With enough retries to saturate exponential backoff, the per-
    attempt wait must cap at 8.0 s under the default max_wait.

    Rationale: ``wait_exponential(multiplier=1, min=1, max=8)`` produces
    waits 1, 2, 4, 8, 8, 8 … — the fourth retry (attempt index 3)
    sits exactly at the cap, and every further retry stays at the cap.
    Driving at least five retries guarantees at least one cap-bound
    sleep.

    Kills ``x_with_retry__mutmut_3`` which raises max_wait to 9.0;
    the saturating sleep would then be 9.0, not 8.0.

    Note: ``max_attempts=7`` is passed explicitly so we get five
    retry sleeps (attempts 1–6 each produce a post-attempt wait
    before the 7th attempt is the final one). ``max_wait`` is left
    defaulted — that's the mutant we're targeting.
    """
    sleeps: list[float] = []

    @with_retry(max_attempts=7, min_wait=1.0)
    def always_fails():
        raise TTSTransientError("simulated")

    with patch("time.sleep", side_effect=sleeps.append):
        with pytest.raises(TTSTransientError):
            always_fails()

    assert sleeps, "no time.sleep captured"
    # By attempt 6, the computed wait is multiplier * 2**5 = 32, which
    # must be capped to max_wait (default 8). If the default was 9,
    # the cap would produce 9 here.
    assert max(sleeps) == pytest.approx(8.0, abs=0.01), (
        f"Expected maximum observed retry wait to cap at 8.0 s "
        f"(default max_wait); got {max(sleeps)}. A higher cap extends "
        f"tail latency on persistent-but-recoverable upstream outages."
    )
