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
pytestmark = [pytest.mark.unit, pytest.mark.skipif(
    not SCRIPT_PATH.exists(),
    reason="scripts/check_mutation_thresholds.py not present in this tree "
           "(typical for mutmut-mirrored mutants/ runs); regression coverage "
           "lives in non-mutmut pytest -m unit invocations.",
)]


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


class TestComputeModuleScore:
    def test_typical_module_with_mixed_statuses(self, script_module):
        """10 mutants: 5 killed, 3 survived, 2 timeout. 2 of the 3
        survived are annotated equivalent.

        Expected: equivalents are removed from survived before scoring;
        killed = 10 − 1 (live survived) − 2 (timeout) − 0 (suspicious)
                  − 2 (equivalent) = 5.
        Wait — that's the pre-fix arithmetic if we conflate. Actual
        post-fix: killed = total − survived_live − timeout − suspicious
                          − equivalent = 10 − 1 − 2 − 0 − 2 = 5.
        denom = 10 − 2 = 8. score = 5/8 = 62.5 %.

        The pre-fix bug would have computed killed = 10 − 3 − 2 − 0 − 2
        = 3 (double-subtracting the 2 equivalents) and score = 3/8 =
        37.5 %, hiding 25 percentage points of legitimate response work.
        """
        result = script_module.compute_module_score(
            total=10,
            survived_names={"m_surv_a", "m_surv_b", "m_surv_c"},
            timeout_names={"m_to_a", "m_to_b"},
            suspicious_names=set(),
            equivalent_names={"m_surv_a", "m_surv_b"},
        )
        assert result["killed"] == 5
        assert result["survived"] == 1
        assert result["timeout"] == 2
        assert result["equivalent"] == 2
        assert result["denom"] == 8
        assert result["score"] == pytest.approx(62.5)
        assert result["orphan_equivalents"] == set()

    def test_double_subtract_regression_pin(self, script_module):
        """Regression pin for the specific bug: an equivalent mutant
        that is also marked ``survived`` in mutmut output must be
        counted as equivalent ONLY, not as both equivalent and survived.

        Pre-fix: killed = total − survived − timeout − suspicious − eq
                        = 5 − 2 − 0 − 0 − 2 = 1.   (BUG: 2 ≠ 1)
        Post-fix: survived_live = {survived} \\ {equivalent} = ∅, so
                  killed = 5 − 0 − 0 − 0 − 2 = 3.
        Threshold 60 % would have falsely failed at 33 %; passes at 100 %.
        """
        result = script_module.compute_module_score(
            total=5,
            survived_names={"m_a", "m_b"},
            timeout_names=set(),
            suspicious_names=set(),
            equivalent_names={"m_a", "m_b"},
        )
        # Two annotated equivalents that mutmut also reports survived.
        # killed must be 3, not 1.
        assert result["killed"] == 3
        assert result["survived"] == 0
        assert result["equivalent"] == 2
        assert result["denom"] == 3
        assert result["score"] == pytest.approx(100.0)

    def test_orphan_equivalent_warns_does_not_double_subtract(
        self, script_module
    ):
        """Symmetric case: a YAML annotation for a mutant that no longer
        appears in mutmut output (typical after a source change removes
        the mutant). The orphan must not be counted into either
        ``survived`` or ``equivalent`` for scoring purposes — but it
        must surface in the orphan-warning channel so a maintainer
        cleans it up.
        """
        result = script_module.compute_module_score(
            total=5,
            survived_names={"m_real_surv"},
            timeout_names=set(),
            suspicious_names=set(),
            equivalent_names={"m_orphan_stale"},
        )
        # equivalent count includes the stale annotation (it IS in the
        # YAML); the score formula uses that count, but the score does
        # not also penalise the live survived mutant for the orphan.
        assert result["killed"] == 5 - 1 - 1  # total − survived_live − eq
        assert result["survived"] == 1
        assert result["equivalent"] == 1
        # Orphan surfaces for the maintainer.
        assert result["orphan_equivalents"] == {"m_orphan_stale"}

    def test_zero_denominator_returns_none_score(self, script_module):
        """All mutants annotated equivalent → denom == 0 → score is
        undefined. The script renders this as ``n/a`` with a ``?``
        verdict, not as a failure. Pinned because the §14.8.3 retry.py
        precedent depends on this branch.
        """
        result = script_module.compute_module_score(
            total=3,
            survived_names={"m_a", "m_b", "m_c"},
            timeout_names=set(),
            suspicious_names=set(),
            equivalent_names={"m_a", "m_b", "m_c"},
        )
        assert result["denom"] == 0
        assert result["score"] is None
        assert result["equivalent"] == 3
