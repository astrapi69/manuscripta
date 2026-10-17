#!/usr/bin/env python3
"""Enforce per-module mutation-score thresholds.

Reads ``[tool.manuscripta.mutation_thresholds]`` from ``pyproject.toml``
and the most recent ``mutmut`` results, computes a per-file mutation
score, and exits non-zero if any in-scope module is below its
threshold.

Score formula (per ADR-0002 §"Score definition" and §"Score formula
treatment of trampoline-induced equivalence"):

    denom         = total − equivalent
    survived_live = |survived_from_mutmut \\ equivalent_yaml|
    killed        = total − survived_live − timeout − suspicious
                    − not_checked − equivalent
    score         = killed / denom

Equivalent mutants appear in mutmut's ``survived`` output because mutmut
has no intrinsic concept of equivalence; annotation via
``.mutmut/equivalent.yaml`` is manuscripta's mechanism for routing them
into the ``equivalent`` bucket. The script must subtract the overlap
once (out of ``survived``), not twice (out of both ``survived`` and
``equivalent``). The ``survived_live`` step is what enforces that
discipline; without it, a B-annotated mutant that genuinely survives
mutmut is counted against the score twice and the module FAILs even
when its response work is correct. See the regression test in
``tests/unit/test_check_mutation_thresholds.py``.

In mutmut 3.x, ``mutmut results`` lists every mutant that did NOT die:
``survived``, ``timeout``, ``suspicious`` and the ones never checked by a
test (``not checked``, ``no tests``, ``skipped``, ``check was interrupted
by user`` — statuses are printed with spaces). Killed mutants are those
mentioned nowhere in the results output. Total mutants per file are
counted by inspecting the mutmut-mirrored source under ``mutants/src/``
for ``def …__mutmut_<N>(…)`` definitions.

A mutant never checked by a test is not a kill. A filtered ``mutmut run
'manuscripta.foo.*'`` (or an interrupted one) resets every other in-scope
module to ``not checked``; the script counts those into their own bucket,
shows them in the table and fails, naming the modules and counts, so a
stale state can never report as fully killed.

Equivalent mutants must be marked with a sibling YAML file at
``.mutmut/equivalent.yaml`` (one entry per mutant id) — manual
annotation per the response protocol in TESTING.md §14.

Why a separate script and not an extension of
``check_coverage_thresholds.py``: the two enforcement policies have
already diverged (coverage has the baseline-ratchet on debt modules,
mutation does not — debt modules are excluded from mutation scope by
category) and will diverge further (mutation gains the A/B/C/D survivor
classification). Coupling them into a single parser would force every
future policy change to touch both. See ADR-0002 §"Alternatives
considered".

Exit codes:
    0   all modules at or above threshold, every in-scope mutant checked
    1   one or more modules below threshold, or in-scope mutants never
        checked by a test (build-failing)
    2   configuration or input error (no mutation results, malformed
        pyproject section, missing mutants/ dir, etc.)
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover -- Python <3.11 not supported by manuscripta
    import tomli as tomllib  # type: ignore[no-redef]


REPO_ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = REPO_ROOT / "pyproject.toml"
MUTANTS_DIR = REPO_ROOT / "mutants"
EQUIVALENT_FILE = REPO_ROOT / ".mutmut" / "equivalent.yaml"

# `mutmut results` (no flags) prints every mutant that DIDN'T die, one
# `    <name>: <status>` line each. Statuses carry spaces ("not checked",
# "no tests", "check was interrupted by user"); parse_results() lower-cases
# them and turns the spaces into underscores. Anything not in the results
# output but present in the mutated source is killed.
NON_DEAD_STATUSES = {"survived", "timeout", "suspicious"}
# Statuses meaning no test ever ran against the mutant: the state store is
# stale (a filtered or interrupted run) or the mutant was skipped. They are
# neither killed nor survived; main() fails when any in-scope mutant has
# one.
UNCHECKED_STATUSES = {
    "not_checked",
    "check_was_interrupted_by_user",
    "no_tests",
    "skipped",
}

MUTANT_DEF_RE = re.compile(
    # Class methods are indented (`    def xǁClassǁmethod__mutmut_N(...)`),
    # module-level functions are not. Match both.
    r"^\s*def\s+(x[\u01c0-\u01cfa-zA-Z0-9_]*__mutmut_\d+)\s*\(",
    re.MULTILINE,
)
MUTANT_NAME_PATTERN = re.compile(
    r"^\s*(?P<name>[\w.\u01c0-\u01cf]+__mutmut_\d+)\s*:\s*"
    r"(?P<status>\w+(?: \w+)*)\s*$"
)


def fail(msg: str, code: int = 2) -> "None":
    print(f"check_mutation_thresholds: {msg}", file=sys.stderr)
    sys.exit(code)


def load_thresholds() -> tuple[int, dict[str, int]]:
    """Return (default_threshold, {file_path: threshold}) from pyproject."""
    if not PYPROJECT.exists():
        fail(f"{PYPROJECT} not found")
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    try:
        section = data["tool"]["manuscripta"]["mutation_thresholds"]
    except KeyError:
        fail("[tool.manuscripta.mutation_thresholds] missing in pyproject.toml")
    default = int(section.get("default", 75))
    per_file = {k: int(v) for k, v in section.items() if k != "default"}
    return default, per_file


def in_scope_files() -> list[str]:
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    try:
        paths = data["tool"]["mutmut"]["paths_to_mutate"]
    except KeyError:
        fail("[tool.mutmut] paths_to_mutate missing in pyproject.toml")
    return list(paths)


def count_total_mutants() -> dict[str, int]:
    """Count def x…__mutmut_N(…) per mutated source file."""
    if not MUTANTS_DIR.exists():
        fail(
            f"{MUTANTS_DIR} not found — run `mutmut run` first to produce "
            f"the mutated source tree."
        )
    counts: dict[str, int] = {}
    src_root = MUTANTS_DIR / "src"
    for mutated in src_root.rglob("*.py"):
        text = mutated.read_text(encoding="utf-8", errors="replace")
        n = len(MUTANT_DEF_RE.findall(text))
        if n == 0:
            continue
        rel = mutated.relative_to(MUTANTS_DIR).as_posix()  # "src/manuscripta/…"
        counts[rel] = n
    return counts


PerFileStatuses = dict[str, dict[str, set[str]]]


def parse_results(raw: list[str]) -> tuple[PerFileStatuses, PerFileStatuses]:
    """Group the mutant **names** of ``mutmut results`` output per file and
    status — exposed for ``tests/unit/test_check_mutation_thresholds.py``.

    Returns (per_file_names, per_file_all_statuses) where per_file_names
    maps ``src/manuscripta/foo.py -> {"survived": {"…__mutmut_3", …},
    "timeout": {"…__mutmut_7"}}`` for the NON_DEAD_STATUSES only. Names
    (not just counts) are required so the caller can compute the overlap
    with ``.mutmut/equivalent.yaml`` and route annotated equivalents out
    of the ``survived`` bucket — see the module docstring's "score
    formula" block. ``per_file_all_statuses`` has the same shape but
    keeps every status, lower-cased with underscores for spaces
    (``not_checked``), feeding the unchecked bucket in ``main()``.
    """
    per_file: PerFileStatuses = defaultdict(lambda: defaultdict(set))
    per_file_all: PerFileStatuses = defaultdict(lambda: defaultdict(set))
    for line in raw:
        m = MUTANT_NAME_PATTERN.match(line)
        if not m:
            continue
        name = m.group("name")
        status = m.group("status").lower().replace(" ", "_")
        file_path = mutant_name_to_file(name)
        if file_path is None:
            continue
        per_file_all[file_path][status].add(name)
        if status not in NON_DEAD_STATUSES:
            continue
        per_file[file_path][status].add(name)
    return per_file, per_file_all


def collect_results() -> tuple[PerFileStatuses, list[str], PerFileStatuses]:
    """Run ``mutmut results`` and return ``parse_results()`` of its output
    as (per_file_names, raw_lines, per_file_all_statuses)."""
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "mutmut", "results"],
            check=True,
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
    except subprocess.CalledProcessError as e:
        fail(f"`mutmut results` failed (rc={e.returncode}).\n" f"stderr:\n{e.stderr}")
    raw = proc.stdout.splitlines()
    per_file, per_file_all = parse_results(raw)
    return per_file, raw, per_file_all


def unchecked_names(statuses: dict[str, set[str]]) -> set[str]:
    """The mutant names of ``statuses`` (one file's entry of
    ``per_file_all_statuses``) that no test ever ran against."""
    names: set[str] = set()
    for status in UNCHECKED_STATUSES:
        names |= statuses.get(status, set())
    return names


def compute_module_score(
    *,
    total: int,
    survived_names: set[str],
    timeout_names: set[str],
    suspicious_names: set[str],
    not_checked_names: set[str],
    equivalent_names: set[str],
) -> dict[str, "int | float | None | set[str]"]:
    """Pure scoring function — exposed for ``tests/unit/
    test_check_mutation_thresholds.py``.

    Implements the formula in the module docstring. A mutant in
    ``not_checked_names`` was never run against a test, so it is not a
    kill; one annotated equivalent counts as equivalent only, like a
    survived one. Returns a dict with the per-module counts that
    ``main()`` prints, plus the orphan-annotation set (equivalent ids in
    the YAML that do not appear in any non-dead status — usually a stale
    annotation left over from a refactor that removed the mutant).
    """
    survived_live = survived_names - equivalent_names
    timeout_live = timeout_names - equivalent_names
    suspicious_live = suspicious_names - equivalent_names
    not_checked_live = not_checked_names - equivalent_names
    orphans = equivalent_names - (
        survived_names | timeout_names | suspicious_names | not_checked_names
    )
    eq_count = len(equivalent_names)
    denom = total - eq_count
    killed = 0
    score: int | float | None = None
    if denom > 0:
        killed = (
            total
            - len(survived_live)
            - len(timeout_live)
            - len(suspicious_live)
            - len(not_checked_live)
            - eq_count
        )
        score = round(100.0 * killed / denom, 1)
    return {
        "total": total,
        "killed": killed,
        "survived": len(survived_live),
        "timeout": len(timeout_live),
        "suspicious": len(suspicious_live),
        "not_checked": len(not_checked_live),
        "equivalent": eq_count,
        "denom": denom,
        "score": score,
        "orphan_equivalents": orphans,
    }


def mutant_name_to_file(name: str) -> str | None:
    """Convert ``manuscripta.foo.bar.x_baz__mutmut_3`` -> ``src/manuscripta/foo/bar.py``.

    Mutmut adds the ``x`` prefix (or ``xǁ`` for class methods) right after
    the module path. Strip from the rightmost such delimiter onward.
    """
    candidates = [".x_", ".x\u01c1", ".x\u01c0"]
    idx = max((name.rfind(c) for c in candidates), default=-1)
    if idx < 0:
        # Some functions are named just `x__mutmut_N` (rare); fall back to module.
        return None
    module = name[:idx]
    return "src/" + module.replace(".", "/") + ".py"


def load_equivalents() -> dict[str, set[str]]:
    """Load operator-marked equivalent mutants, keyed by file path.

    Tiny YAML-ish parser: one ``- file/path.py: mutant_name`` per line.
    A real YAML dependency is not justified for this format.
    """
    equivalents: dict[str, set[str]] = defaultdict(set)
    if not EQUIVALENT_FILE.exists():
        return equivalents
    for line in EQUIVALENT_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # Expected form: "src/foo.py:manuscripta.foo.x_bar__mutmut_3"
        if ":" not in line:
            continue
        path, _, mutant = line.partition(":")
        equivalents[path.strip()].add(mutant.strip())
    return equivalents


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Enforce per-module mutation-score thresholds",
    )
    parser.add_argument(
        "--equivalent-count",
        action="store_true",
        help="print the number of in-scope mutants annotated as equivalent in "
        ".mutmut/equivalent.yaml and exit 0; the nightly passes it to the "
        "mutation-context converter of awesome-well-tested",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.equivalent_count:
        # Only the in-scope files: the score table counts the same set, and an
        # annotation for a module outside the scope must not shrink the
        # denominator of the context file.
        equivalents = load_equivalents()
        print(sum(len(equivalents.get(path, ())) for path in in_scope_files()))
        return 0
    default_threshold, per_file_thresholds = load_thresholds()
    in_scope = in_scope_files()
    totals = count_total_mutants()
    non_dead, _raw, all_statuses = collect_results()
    equivalents = load_equivalents()

    print("# Mutation threshold check")
    print()
    print(
        f"{'Module':<55} {'killed':>7} {'surv':>5} {'tout':>5} {'unchk':>5} "
        f"{'eq':>4} {'total':>6} {'score':>6} {'thr':>5} {'verdict'}"
    )
    print("-" * 116)

    failures: list[str] = []
    unchecked: list[tuple[str, int, int]] = []
    orphans_anywhere: list[tuple[str, str]] = []
    for path in in_scope:
        threshold = per_file_thresholds.get(path, default_threshold)
        total = totals.get(path, 0)
        non_dead_for_path = non_dead.get(path, {})
        result = compute_module_score(
            total=total,
            survived_names=set(non_dead_for_path.get("survived", set())),
            timeout_names=set(non_dead_for_path.get("timeout", set())),
            suspicious_names=set(non_dead_for_path.get("suspicious", set())),
            not_checked_names=unchecked_names(all_statuses.get(path, {})),
            equivalent_names=set(equivalents.get(path, set())),
        )
        for orph in sorted(result["orphan_equivalents"]):  # type: ignore[arg-type]
            orphans_anywhere.append((path, orph))

        eq = result["equivalent"]
        if result["score"] is None:
            print(
                f"{path:<55} {'-':>7} {'-':>5} {'-':>5} {'-':>5} {eq:>4} {total:>6} "
                f"{'n/a':>6} {threshold:>5} ?  no mutants"
            )
            continue

        killed = result["killed"]
        survived = result["survived"]
        timeout = result["timeout"]
        not_checked = result["not_checked"]
        score = result["score"]
        assert isinstance(score, (int, float))
        assert isinstance(not_checked, int)
        if not_checked > 0:
            verdict = "UNCHECKED"
            unchecked.append((path, not_checked, total))
        elif score >= threshold:
            verdict = "OK"
        else:
            verdict = "FAIL"
            failures.append(
                f"{path}: actual {score} % < threshold {threshold} % "
                f"(killed={killed}, survived={survived}, timeout={timeout}, "
                f"equivalent={eq}, total={total})"
            )
        print(
            f"{path:<55} {killed:>7} {survived:>5} {timeout:>5} {not_checked:>5} "
            f"{eq:>4} {total:>6} {score:>5}% {threshold:>4}% {verdict}"
        )

    print()
    if orphans_anywhere:
        print(
            "⚠  Orphan equivalent annotations (in .mutmut/equivalent.yaml "
            "but not in current mutmut output):"
        )
        for path, name in orphans_anywhere:
            print(f"  {path}: {name}")
        print(
            "  These were likely left behind when a source change removed "
            "the mutant. Clean up the YAML or re-run mutmut."
        )
        print()
    if unchecked:
        print(
            "FAIL — in-scope mutants were never checked by a test (status "
            '"not checked", "no tests", "skipped" or interrupted); a '
            "filtered or interrupted `mutmut run` leaves every other in-scope "
            "module unchecked:"
        )
        for path, count, total in unchecked:
            print(f"  {path}: {count} of {total} mutants not checked")
        print()
        print("Run `make mutation` (a full `mutmut run`) before the threshold check.")
        return 1
    if failures:
        print("FAIL — the following modules are below their mutation threshold:")
        for f in failures:
            print(f"  {f}")
        print()
        print("Response protocol: see docs/TESTING.md §14 (A/B/C/D categories).")
        print("Do not lower thresholds; do not pin mutation-targeting literals.")
        return 1
    print("OK — all in-scope modules meet their mutation thresholds.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
