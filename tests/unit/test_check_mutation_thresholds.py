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

Also pinned (#29): mutmut prints the never-checked mutants as
``name: not checked`` (with a space); they form their own bucket, count as
not killed, and make main() fail naming the modules and counts.
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

# Each row: the total, the survived, timeout, suspicious, not-checked and
# equivalent mutant names, the entries the score dict must carry (score None:
# undefined)
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
    # A mutant no test ever ran against is not a kill (#29): killed =
    # 4 − 0 − 0 − 0 − 1 − 0 = 3, denom = 4, score = 75 %. Before the fix it was
    # absent from every non-dead bucket and counted as killed (100 %).
    pytest.param(
        4,
        set(),
        set(),
        set(),
        {"m_nc"},
        set(),
        {
            "killed": 3,
            "survived": 0,
            "not_checked": 1,
            "denom": 4,
            "score": pytest.approx(75.0),
            "orphan_equivalents": set(),
        },
        id="not-checked-counts-as-not-killed",
    ),
    # An annotated equivalent that the stale state lists as not checked is
    # equivalent only (like a survived one) and no orphan: killed = 4 − 0 − 0
    # − 0 − 0 − 1 = 3, denom = 3, score = 100 %.
    pytest.param(
        4,
        set(),
        set(),
        set(),
        {"m_eq"},
        {"m_eq"},
        {
            "killed": 3,
            "not_checked": 0,
            "equivalent": 1,
            "denom": 3,
            "score": pytest.approx(100.0),
            "orphan_equivalents": set(),
        },
        id="not-checked-equivalent-is-equivalent-only",
    ),
]


class TestComputeModuleScore:
    @pytest.mark.parametrize(
        "total, survived, timeout, suspicious, not_checked, equivalent, expected",
        SCORE_CASES,
    )
    def test_compute_module_score(
        self,
        script_module,
        total,
        survived,
        timeout,
        suspicious,
        not_checked,
        equivalent,
        expected,
    ):
        result = script_module.compute_module_score(
            total=total,
            survived_names=survived,
            timeout_names=timeout,
            suspicious_names=suspicious,
            not_checked_names=not_checked,
            equivalent_names=equivalent,
        )
        for key, value in expected.items():
            if value is None:
                assert result[key] is None, key
            else:
                assert result[key] == value, key


# ---------------------------------------------------------------------------
# parse_results: the `mutmut results` lines
# ---------------------------------------------------------------------------

FOO = "src/manuscripta/foo.py"
M = "manuscripta.foo.x_bar__mutmut_"

# Each row: the lines `mutmut results` printed, the non-dead names per file
# and status, every status per file and status (spaces became underscores)
RESULT_LINES = [
    pytest.param(
        [f"    {M}1: survived", f"    {M}2: timeout", f"    {M}3: suspicious"],
        {FOO: {"survived": {M + "1"}, "timeout": {M + "2"}, "suspicious": {M + "3"}}},
        {FOO: {"survived": {M + "1"}, "timeout": {M + "2"}, "suspicious": {M + "3"}}},
        id="non-dead-statuses-land-in-both-views",
    ),
    pytest.param(
        [f"    {M}1: not checked"],
        {},
        {FOO: {"not_checked": {M + "1"}}},
        id="not-checked-is-parsed-with-its-space",
    ),
    pytest.param(
        [f"    {M}1: no tests", f"    {M}2: check was interrupted by user"],
        {},
        {FOO: {"no_tests": {M + "1"}, "check_was_interrupted_by_user": {M + "2"}}},
        id="multi-word-statuses-are-kept-apart",
    ),
    pytest.param(
        [f"    {M}1: killed"],
        {},
        {FOO: {"killed": {M + "1"}}},
        id="killed-is-not-non-dead",
    ),
    pytest.param(
        ["    manuscripta.foo.xǁBarǁbaz__mutmut_4: not checked"],
        {},
        {FOO: {"not_checked": {"manuscripta.foo.xǁBarǁbaz__mutmut_4"}}},
        id="class-method-names-map-to-their-file",
    ),
    pytest.param(
        ["Running...", "", "    x__mutmut_1: survived"],
        {},
        {},
        id="chatter-and-nameless-mutants-are-skipped",
    ),
]


def plain(view) -> dict:
    """The defaultdict view as plain dicts (for equality with a literal)."""
    return {path: dict(statuses) for path, statuses in view.items()}


@pytest.mark.parametrize("lines, non_dead, all_statuses", RESULT_LINES)
def test_parse_results(script_module, lines, non_dead, all_statuses):
    parsed_non_dead, parsed_all = script_module.parse_results(lines)
    assert plain(parsed_non_dead) == non_dead
    assert plain(parsed_all) == all_statuses


# ---------------------------------------------------------------------------
# main: the unchecked guard
# ---------------------------------------------------------------------------

BAR = "src/manuscripta/bar.py"
N = "manuscripta.bar.x_baz__mutmut_"


def run_main(script_module, monkeypatch, lines: list[str]) -> tuple[int, str]:
    """main() over two in-scope modules of four mutants each (threshold
    75 %), with `mutmut results` printing ``lines``; its exit status and
    stdout."""
    import contextlib
    import io

    monkeypatch.setattr(script_module, "load_thresholds", lambda: (75, {}))
    monkeypatch.setattr(script_module, "in_scope_files", lambda: [FOO, BAR])
    monkeypatch.setattr(script_module, "count_total_mutants", lambda: {FOO: 4, BAR: 4})

    def collect_results():
        non_dead, all_statuses = script_module.parse_results(lines)
        return non_dead, lines, all_statuses

    monkeypatch.setattr(script_module, "collect_results", collect_results)
    monkeypatch.setattr(script_module, "load_equivalents", lambda: {})
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = script_module.main([])
    return code, out.getvalue()


# Each row: the lines `mutmut results` printed, the exit status, the lines
# the output must carry
GUARD_RUNS = [
    pytest.param(
        [f"    {M}1: survived"],
        0,
        ["OK — all in-scope modules meet their mutation thresholds."],
        id="complete-state-passes",
    ),
    pytest.param(
        [f"    {M}1: not checked", f"    {N}1: not checked", f"    {N}2: not checked"],
        1,
        [
            f"  {FOO}: 1 of 4 mutants not checked",
            f"  {BAR}: 2 of 4 mutants not checked",
            "Run `make mutation` (a full `mutmut run`) before the threshold check.",
        ],
        id="unchecked-mutants-fail-naming-modules-and-counts",
    ),
    pytest.param(
        [f"    {N}1: no tests"],
        1,
        [f"  {BAR}: 1 of 4 mutants not checked"],
        id="no-tests-is-unchecked-too",
    ),
    pytest.param(
        [f"    {M}1: survived", f"    {M}2: survived"],
        1,
        [f"  {FOO}: actual 50.0 % < threshold 75 % (killed=2, survived=2, "],
        id="threshold-failure-still-fails",
    ),
]


@pytest.mark.parametrize("lines, code, printed", GUARD_RUNS)
def test_main_guard(script_module, monkeypatch, lines, code, printed):
    exit_code, out = run_main(script_module, monkeypatch, lines)
    assert exit_code == code
    for line in printed:
        assert any(line in out_line for out_line in out.splitlines()), line


def test_table_shows_the_unchecked_count(script_module, monkeypatch):
    _, out = run_main(script_module, monkeypatch, [f"    {N}1: not checked"])
    rows = {
        line.split()[0]: line.split()
        for line in out.splitlines()
        if line.startswith("src/")
    }
    # killed surv tout unchk eq total score thr verdict
    assert rows[FOO][1:] == ["4", "0", "0", "0", "0", "4", "100.0%", "75%", "OK"]
    assert rows[BAR][1:] == ["3", "0", "0", "1", "0", "4", "75.0%", "75%", "UNCHECKED"]
