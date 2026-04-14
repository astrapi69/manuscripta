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
    killed        = total − survived_live − timeout − suspicious − equivalent
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

In mutmut 3.x, ``mutmut results`` lists the mutants that did NOT die
(``survived`` and ``timeout`` only). Killed mutants are those mentioned
nowhere in the results output. Total mutants per file are counted by
inspecting the mutmut-mirrored source under ``mutants/src/`` for
``def …__mutmut_<N>(…)`` definitions.

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
    0   all modules at or above threshold
    1   one or more modules below threshold (build-failing)
    2   configuration or input error (no mutation results, malformed
        pyproject section, missing mutants/ dir, etc.)
"""

from __future__ import annotations

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

# Mutmut emits one of: survived | timeout | killed | no_tests | skipped | segfault.
# `mutmut results` (no flags) prints survived + timeout + suspicious — i.e. the
# ones that DIDN'T die. Anything not in the results output but present in the
# mutated source is killed.
NON_DEAD_STATUSES = {"survived", "timeout", "suspicious"}

MUTANT_DEF_RE = re.compile(
    # Class methods are indented (`    def xǁClassǁmethod__mutmut_N(...)`),
    # module-level functions are not. Match both.
    r"^\s*def\s+(x[\u01c0-\u01cfa-zA-Z0-9_]*__mutmut_\d+)\s*\(",
    re.MULTILINE,
)
MUTANT_NAME_PATTERN = re.compile(
    r"^\s*(?P<name>[\w.\u01c0-\u01cf]+__mutmut_\d+)\s*:\s*(?P<status>\w+)\s*$"
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


def collect_results() -> tuple[
    dict[str, dict[str, set[str]]], list[str]
]:
    """Run ``mutmut results`` and group non-dead mutant **names** per file
    and status.

    Returns (per_file_names, raw_lines) where per_file_names maps
    ``src/manuscripta/foo.py -> {"survived": {"…__mutmut_3", …}, "timeout":
    {"…__mutmut_7"}}``. Names (not just counts) are required so the caller
    can compute the overlap with ``.mutmut/equivalent.yaml`` and route
    annotated equivalents out of the ``survived`` bucket — see the module
    docstring's "score formula" block.
    """
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "mutmut", "results"],
            check=True,
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
    except subprocess.CalledProcessError as e:
        fail(
            f"`mutmut results` failed (rc={e.returncode}).\n"
            f"stderr:\n{e.stderr}"
        )
    raw = proc.stdout.splitlines()
    per_file: dict[str, dict[str, set[str]]] = defaultdict(
        lambda: defaultdict(set)
    )
    for line in raw:
        m = MUTANT_NAME_PATTERN.match(line)
        if not m:
            continue
        name = m.group("name")
        status = m.group("status")
        if status not in NON_DEAD_STATUSES:
            continue
        file_path = mutant_name_to_file(name)
        if file_path is None:
            continue
        per_file[file_path][status].add(name)
    return per_file, raw


def compute_module_score(
    *,
    total: int,
    survived_names: set[str],
    timeout_names: set[str],
    suspicious_names: set[str],
    equivalent_names: set[str],
) -> dict[str, "int | float | set[str]"]:
    """Pure scoring function — exposed for ``tests/unit/
    test_check_mutation_thresholds.py``.

    Implements the formula in the module docstring. Returns a dict with
    the per-module counts that ``main()`` prints, plus the orphan-
    annotation set (equivalent ids in the YAML that do not appear in any
    non-dead status — usually a stale annotation left over from a
    refactor that removed the mutant).
    """
    survived_live = survived_names - equivalent_names
    timeout_live = timeout_names - equivalent_names
    suspicious_live = suspicious_names - equivalent_names
    orphans = equivalent_names - (
        survived_names | timeout_names | suspicious_names
    )
    eq_count = len(equivalent_names)
    denom = total - eq_count
    if denom <= 0:
        score: int | float | None = None
    else:
        killed = (
            total
            - len(survived_live)
            - len(timeout_live)
            - len(suspicious_live)
            - eq_count
        )
        score = round(100.0 * killed / denom, 1)
    return {
        "total": total,
        "killed": (total - len(survived_live) - len(timeout_live)
                   - len(suspicious_live) - eq_count) if denom > 0 else 0,
        "survived": len(survived_live),
        "timeout": len(timeout_live),
        "suspicious": len(suspicious_live),
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


def main() -> int:
    default_threshold, per_file_thresholds = load_thresholds()
    in_scope = in_scope_files()
    totals = count_total_mutants()
    non_dead, _raw = collect_results()
    equivalents = load_equivalents()

    print("# Mutation threshold check")
    print()
    print(f"{'Module':<55} {'killed':>7} {'surv':>5} {'tout':>5} "
          f"{'eq':>4} {'total':>6} {'score':>6} {'thr':>5} {'verdict'}")
    print("-" * 110)

    failures: list[str] = []
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
            equivalent_names=set(equivalents.get(path, set())),
        )
        for orph in sorted(result["orphan_equivalents"]):  # type: ignore[arg-type]
            orphans_anywhere.append((path, orph))

        eq = result["equivalent"]
        if result["score"] is None:
            print(f"{path:<55} {'-':>7} {'-':>5} {'-':>5} {eq:>4} {total:>6} "
                  f"{'n/a':>6} {threshold:>5} ?  no mutants")
            continue

        killed = result["killed"]
        survived = result["survived"]
        timeout = result["timeout"]
        score = result["score"]
        assert isinstance(score, (int, float))
        if score >= threshold:
            verdict = "OK"
        else:
            verdict = "FAIL"
            failures.append(
                f"{path}: actual {score} % < threshold {threshold} % "
                f"(killed={killed}, survived={survived}, timeout={timeout}, "
                f"equivalent={eq}, total={total})"
            )
        print(f"{path:<55} {killed:>7} {survived:>5} {timeout:>5} {eq:>4} "
              f"{total:>6} {score:>5}% {threshold:>4}% {verdict}")

    print()
    if orphans_anywhere:
        print("⚠  Orphan equivalent annotations (in .mutmut/equivalent.yaml "
              "but not in current mutmut output):")
        for path, name in orphans_anywhere:
            print(f"  {path}: {name}")
        print("  These were likely left behind when a source change removed "
              "the mutant. Clean up the YAML or re-run mutmut.")
        print()
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
