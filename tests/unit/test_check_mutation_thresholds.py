"""Regression tests for scripts/check_mutation_thresholds.py.

Pin the score-formula semantics that landed in the
"fix(mutation): de-duplicate equivalent mutants from survived counts"
commit, after the bug surfaced during Phase 4b Pass 2 Commit 10
fresh-triage on paths/to_absolute.py.

The bug: mutants annotated in .mutmut/equivalent.yaml that ALSO appear
in mutmut's `survived` output were double-subtracted from `killed` —
once from `survived`, once from `equivalent`. The fix routes annotated
equivalents OUT of `survived` before scoring (`survived_live = survived
\\ equivalent`).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "check_mutation_thresholds.py"

# Skip cleanly under mutmut: mutmut mirrors src/ and tests/ into mutants/
# but not scripts/, so the script-under-test is absent from the mirrored
# tree at test-collection time. Adding scripts/ to [tool.mutmut].also_copy
# would also work, but the script is not under mutation — skipping the
# regression test from mutmut's runs costs nothing (the regression
# coverage is in normal `pytest -m unit`).
pytestmark = [
    pytest.mark.unit,
    pytest.mark.skipif(
        not SCRIPT_PATH.exists(),
        reason="scripts/check_mutation_thresholds.py not present in this tree "
        "(typical for mutmut-mirrored mutants/ runs); regression coverage "
        "lives in non-mutmut pytest -m unit invocations.",
    ),
]


def _load_module():
    """Import the script-under-test as a module."""
    spec = importlib.util.spec_from_file_location(
        "check_mutation_thresholds", SCRIPT_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def script_module():
    return _load_module()


# ---------------------------------------------------------------------------
# Score-formula semantics
# ---------------------------------------------------------------------------

# Each row: the total, the survived, timeout, suspicious and equivalent mutant
# names, the entries the score dict must carry (score None: undefined)
SCORE_CASES = [
    # 10 mutants: 5 killed, 3 survived, 2 timeout. 2 of the 3 survived are
    # annotated equivalent. Equivalents are removed from survived before
    # scoring: killed = total − survived_live − timeout − suspicious
    # − equivalent = 10 − 1 − 2 − 0 − 2 = 5. denom = 10 − 2 = 8.
    # score = 5/8 = 62.5 %.
    # The pre-fix bug would have computed killed = 10 − 3 − 2 − 0 − 2 = 3
    # (double-subtracting the 2 equivalents) and score = 3/8 = 37.5 %,
    # hiding 25 percentage points of legitimate response work.
    pytest.param(
        10,
        {"m_surv_a", "m_surv_b", "m_surv_c"},
        {"m_to_a", "m_to_b"},
        set(),
        {"m_surv_a", "m_surv_b"},
        {
            "killed": 5,
            "survived": 1,
            "timeout": 2,
            "equivalent": 2,
            "denom": 8,
            "score": pytest.approx(62.5),
            "orphan_equivalents": set(),
        },
        id="typical-module-with-mixed-statuses",
    ),
    # Regression pin for the specific bug: an equivalent mutant that is also
    # marked ``survived`` in mutmut output must be counted as equivalent
    # ONLY, not as both equivalent and survived.
    # Pre-fix: killed = total − survived − timeout − suspicious − eq
    #                 = 5 − 2 − 0 − 0 − 2 = 1.   (BUG: 2 ≠ 1)
    # Post-fix: survived_live = {survived} \ {equivalent} = ∅, so
    #           killed = 5 − 0 − 0 − 0 − 2 = 3.
    # Threshold 60 % would have falsely failed at 33 %; passes at 100 %.
    pytest.param(
        5,
        {"m_a", "m_b"},
        set(),
        set(),
        {"m_a", "m_b"},
        {
            "killed": 3,
            "survived": 0,
            "equivalent": 2,
            "denom": 3,
            "score": pytest.approx(100.0),
        },
        id="double-subtract-regression-pin",
    ),
    # Symmetric case: a YAML annotation for a mutant that no longer appears in
    # mutmut output (typical after a source change removes the mutant). The
    # orphan must not be counted into either ``survived`` or ``equivalent``
    # for scoring purposes — but it must surface in the orphan-warning channel
    # so a maintainer cleans it up. The equivalent count includes the stale
    # annotation (it IS in the YAML); the score formula uses that count, but
    # the score does not also penalise the live survived mutant for the
    # orphan: killed = total − survived_live − eq = 5 − 1 − 1.
    pytest.param(
        5,
        {"m_real_surv"},
        set(),
        set(),
        {"m_orphan_stale"},
        {
            "killed": 5 - 1 - 1,
            "survived": 1,
            "equivalent": 1,
            "orphan_equivalents": {"m_orphan_stale"},
        },
        id="orphan-equivalent-warns-does-not-double-subtract",
    ),
    # All mutants annotated equivalent → denom == 0 → score is undefined. The
    # script renders this as ``n/a`` with a ``?`` verdict, not as a failure.
    # Pinned because the §14.8.3 retry.py precedent depends on this branch.
    pytest.param(
        3,
        {"m_a", "m_b", "m_c"},
        set(),
        set(),
        {"m_a", "m_b", "m_c"},
        {"denom": 0, "score": None, "equivalent": 3},
        id="zero-denominator-returns-none-score",
    ),
    # A suspicious mutant is not killed either: killed = 4 − 0 − 0 − 1 − 0 = 3,
    # denom = 4, score = 75 %.
    pytest.param(
        4,
        set(),
        set(),
        {"m_sus"},
        set(),
        {
            "killed": 3,
            "survived": 0,
            "suspicious": 1,
            "denom": 4,
            "score": pytest.approx(75.0),
            "orphan_equivalents": set(),
        },
        id="suspicious-counts-like-survived",
    ),
]


class TestComputeModuleScore:
    @pytest.mark.parametrize(
        "total, survived, timeout, suspicious, equivalent, expected", SCORE_CASES
    )
    def test_compute_module_score(
        self, script_module, total, survived, timeout, suspicious, equivalent, expected
    ):
        result = script_module.compute_module_score(
            total=total,
            survived_names=survived,
            timeout_names=timeout,
            suspicious_names=suspicious,
            equivalent_names=equivalent,
        )
        for key, value in expected.items():
            if value is None:
                assert result[key] is None, key
            else:
                assert result[key] == value, key
