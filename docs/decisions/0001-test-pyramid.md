# ADR-0001: Test pyramid and coverage policy

- **Status:** Accepted
- **Date:** 2026-04-14
- **Author:** manuscripta maintainers

## Context

Through v0.7.0 the test suite was a flat `tests/` directory of 567
tests with no layer distinction. The v0.7.0 image-embedding bug was a
direct consequence: a library extracted from `write-book-template` lost
an implicit cwd assumption, PDF builds silently produced
image-less output, and the test suite — which ran happily inside the
source checkout — never noticed. No layer existed to exercise the
library as its consumers would.

At the same time, a shared convention across the author's projects
(phylax in particular) had emerged: layered tests (unit / e2e /
production-e2e), per-module coverage thresholds, documented test
patterns, Makefile targets that match CI. manuscripta lacked all of
these.

We need a test architecture that:

1. Catches the v0.7.0-class bug before release (something that exercises
   the **installed wheel**, not the source tree).
2. Keeps fast feedback fast (< 5 s for unit tests).
3. Enforces coverage strictly where it matters (public-API / exceptions
   / critical paths) and more loosely where the cost of strictness
   outweighs the value (network-bound TTS adapters).
4. Stays consistent with phylax conventions where the translation from
   TypeScript / Vitest to Python / pytest is obvious, and deviates
   with explicit justification where it is not.

## Decision

Adopt a four-layer pyramid:

| Layer        | Directory              | Runners                                 |
|--------------|------------------------|-----------------------------------------|
| unit         | `tests/unit/`          | pytest, no subprocess, no Pandoc        |
| integration  | `tests/integration/`   | pytest + real Pandoc, **no LaTeX**      |
| e2e          | `tests/e2e/`           | pytest + Pandoc + LaTeX → PDF on disk   |
| e2e-wheel    | `tests/e2e_wheel/`     | Built wheel installed in a fresh venv   |

- **Every test carries exactly one layer marker.** A conftest hook fails
  collection on an unmarked test. No implicit-unit fallback.
- **Per-file coverage thresholds**, driven from a single source of truth
  in `pyproject.toml` and enforced by `scripts/check_coverage_thresholds.py`.
- **CLI and config remain inside their host modules for now;** thresholds
  are expressed against the hosts. Extraction is deferred — the pyramid
  must land first so the extraction does not happen without tests that
  catch regressions.

Full details are in [`docs/TESTING.md`](../TESTING.md).

## Rationale

### Why four layers and not three

A three-layer pyramid (unit / integration / e2e) is standard and
adequate for most libraries. We add the **e2e-wheel** tier specifically
because v0.7.0 demonstrated a class of failure — "works in source
checkout, broken when consumed as a dependency" — that lower layers
structurally cannot catch:

- Unit tests import from the source tree.
- Integration and e2e tests import from the source tree.
- Only a test that installs the built wheel into a clean interpreter
  exercises the packaging boundary (`importlib.resources`, declared
  package data, Poetry `include` / `packages`).

Three e2e-wheel tests (fresh-venv build, package-data audit, CLI smoke)
are cheap to maintain and would have caught v0.7.0 on the day it
shipped. The cost is a ~3 min CI step that runs on PR/main only; small
price.

### Why per-file, not per-directory, coverage thresholds

`coverage.json` reports file-granular. Re-aggregating to directory
granularity requires either a plugin or a custom aggregator. We chose
the file-granular enforcement script because:

- It mirrors `coverage.json`'s own granularity exactly — no aggregation
  bugs possible.
- It keeps the enforcement script tiny (30–50 lines) and itself
  unit-testable.
- It avoids a third-party plugin dependency whose semantics could drift.

The threshold table uses **module-path notation** (`manuscripta.exceptions`)
for human readability; the script translates module paths to file paths
at check time via the rule documented in `TESTING.md` §3.

### Why defer the CLI / config extraction

Extracting `manuscripta.cli` and `manuscripta.config` into dedicated
modules is a defensible refactor, but it carries migration risk that
the existing test suite is not positioned to catch. Ordering matters:

1. Land the pyramid (this ADR).
2. Populate every layer to its coverage threshold.
3. Only then extract CLI / config, with the full pyramid catching any
   behavioural drift.

Doing the refactor first would mean the post-refactor coverage gap
becomes invisible until after the gap has opened.

### Why grep-style layer-boundary lint, not static analysis

The rules we need — "no `subprocess` under `tests/unit/`", "no `pandoc`
string literal under `tests/unit/`", "no writes outside `tmp_path`
under `tests/unit/`" — are heuristic by nature. Static analysis with
Ruff would require either a custom plugin or restrictive import rules
that generate false positives in non-test code.

The project already ships a grep-style lint test
(`test_no_chdir_lint.py`). The layer-boundary lint follows the same
pattern: a single `tests/unit/test_layer_boundaries.py` with three
explicit checks. False negatives are expected and acceptable; the
guards are there to prevent accidental drift, not adversarial bypass.

### Why an 80 % wall backed by ADRs, not a stricter universal floor

Phylax's "no module below 80 % without an ADR" rule correctly identifies
that below 80 % is architecturally suspect, not merely unfortunate. We
adopt it verbatim. A lower universal floor (e.g. 70 %) would quietly
normalise what should be escalated; a higher universal floor (e.g. 95 %)
would create pressure to write fake tests for uncovered error-handling
branches. 80 %-with-ADR makes the exception visible and reviewable.

## Alternatives considered

**Flat `tests/` with markers only, no directory reorganisation.**
Rejected. Directory structure is the load-bearing signal during code
review ("why is this file importing `subprocess` under `tests/unit/`?").
Markers alone are too easy to omit or mis-apply.

**Three-layer pyramid without e2e-wheel.** Rejected. See §"Why four
layers" above; the extraction-class bug requires the wheel tier.

**Global `fail_under` only, no per-file thresholds.** Rejected. The
exceptions module is trivially 100 %-coverable; a weak floor lets it
drift to 90 % without anyone noticing, which is a signal we want to
preserve.

**Third-party plugin for per-file thresholds**
(`pytest-cov-threshold`, `coverage-threshold`, etc.). Rejected. A
30-line script removes the dependency and gives a clearer error
report. The script is unit-tested; the plugin would not be.

**Source-colocated unit tests (phylax's idiom).** Rejected. Python
strongly prefers `tests/`; colocation would fight pytest's discovery
defaults and the Poetry wheel `include` rules. Consistency with the
broader Python ecosystem beats consistency with phylax on this one
axis.

**Playwright for e2e** (as phylax uses). Rejected. manuscripta is a
CLI-and-library, not a web app. pytest with external-binary guards is
the natural fit.

## Consequences

**Easier:**

- Running the fast loop (`make test` → unit only → < 5 s) without
  paying for pandoc/LaTeX setup.
- Catching packaging regressions before they ship (e2e-wheel tier).
- Reviewing a test PR — the directory tells you what's being tested.
- Enforcing per-module rigor where it matters (exceptions 100 %).
- Writing ADRs for coverage drops (forcing a visible justification
  instead of a silent slide).

**Harder:**

- Phase 3 reorganisation has to move 567 tests into the new tree and
  apply layer markers in the same commit so the marker-enforcement
  hook does not brown-out the suite.
- Per-file thresholds require the check script to be written and
  itself tested before CI can depend on it.
- The e2e-wheel tier introduces a hard dependency on `poetry` at test
  time; environments without poetry skip that tier cleanly but do not
  exercise it. CI must have poetry installed.

**Locked in:**

- Four-layer pyramid. A fifth layer (e.g. fuzzing, property-based) can
  be added, but no existing layer may be collapsed without a
  superseding ADR.
- The audit-file rotation convention (`docs/audits/current-coverage.md` +
  `history/YYYY-MM-DD-coverage.md`) — mirroring phylax.
- The marker-enforcement hook: any drift here is a merge-blocking CI
  failure, not a warning.

## Links

- [`docs/TESTING.md`](../TESTING.md) — the implementation contract.
- phylax `.claude/rules/quality-checks.md` — the TS/Vitest precedent.
- [`MIGRATION.md`](../../MIGRATION.md) — v0.8.0 contract change that
  motivated the e2e-wheel tier.
