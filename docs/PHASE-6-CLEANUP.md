# Phase 6 cleanup list

Tracking file for deferred work surfaced during Phases 1–4b. Each item
is small enough to handle in a dedicated cleanup pass but not big enough
to stop current work. Close each with its own commit or ADR.

## Test suite hygiene

- **Rename `tests/unit/test_images_integration.py`** — filename lies, all
  I/O is faked; it is a unit test. Proposed new name:
  `test_images_pipeline.py`.
- **Delete or rename `tests/TEST_CREATE_CHAPTERS.PY`** — uppercase file,
  not collected by pytest's `test_*.py` pattern. Dead file.
- **Refactor `tests/unit/test_convert_round_trip.py` away from
  `importlib.util` hand-loading** — fragile under wheel installs; use
  plain imports.
- **Fix the plain `setattr` pollution in
  `tests/unit/test_generate_audiobook_use_cases.py:95–109`** — swap for
  `monkeypatch.setattr`. Unblocks the 5 TTS tests currently documented
  under TESTING.md §12 "Known environmental test flakiness".

## Specification ambiguities

- **`manuscripta.markdown.normalize_toc.replace_extension`** — docstring
  promises a general extension rewrite in link targets, but the inner
  regex only fires when the URL is followed by an anchor (`#…`). Either
  fix the regex (drop the `(?=…)` lookahead, match at URL end too) or
  narrow the docstring to "rewrites extensions only when followed by an
  anchor". Align the two, then convert the two `xfail` tests in
  `tests/unit/test_normalize_toc_direct.py` accordingly.

## Audit tooling hardening

- **[P2] Pre-commit guard against stale mutmut state in threshold-script
  runs.** Surfaced during Phase 4b Pass 2 Commit 10 fresh-triage on
  `paths/to_absolute.py`. The double-subtraction bug in
  `scripts/check_mutation_thresholds.py` (now fixed in `fix(mutation):
  de-duplicate equivalent mutants from survived counts`) existed for
  three response commits (7, 8, 9) before being caught, because each
  prior verification step ran the threshold script against a **narrow**
  mutmut sub-run state — narrow runs leave the equivalent mutants as
  `not_checked`, which is filtered out of `NON_DEAD_STATUSES`, so the
  double-subtract never triggered. Detection was structural (running
  against a module with pre-existing YAML annotations plus a full
  mutmut state), not accidental. Hardening proposals to evaluate:
  - Pre-commit hook that refuses to run `make mutation-check` when the
    `mutants/` directory contains a high proportion of `not_checked`
    entries (heuristic: > 50 % of in-scope mutants).
  - The threshold script itself emits a loud warning when it observes
    > 50 % `not_checked` and exits non-zero unless an explicit
    `--allow-stale-state` flag is passed.
  - The `mutation-check` Make target always invokes a clean `mutmut
    run` first (slowest, safest); leave the narrow-mode invocation as
    a separate `mutation-fast-check` target gated for dev-loop use only.
  Pick one. The orphan-equivalent warning added to the threshold script
  in the same fix is a partial mitigation, but does not catch the
  inverse case (full state + missing equivalents).

## Build / CI hygiene

- **[P1] Regenerate `poetry.lock` against the current `pyproject.toml`
  before Phase 6 completion.** Surfaced during Phase 4b Pass 2
  Commit 3: `poetry install` refuses with "pyproject.toml changed
  significantly since poetry.lock was last generated. Run `poetry
  lock` to fix the lock file." The nightly mutation workflow
  (`.github/workflows/…`) will hit exactly this wall. Lock
  regeneration was intentionally **not** done during Pass 2 —
  pulling dependency updates mid-mutation-stream would have muddied
  the diagnostic (a behaviour change attributable to a bumped
  tenacity or mutmut version would be indistinguishable from a
  response-to-survivor regression). Do it once, standalone, with
  a nightly-CI re-run to confirm green.

## Policy revisits

- **Integration-layer target range** — Phase 2 set 20–30 % of the
  suite; Phase 4 reached 2.3 % with full seam coverage. Evidence:
  Pandoc-wrapper libraries are structurally unit-heavy — most
  meaningful work is markdown / path / argv logic (unit) or a full PDF
  pipeline (e2e). The space between is naturally small. Propose an
  amendment after Phase 4b completes — ideally ADR-0004 citing Phase 4
  evidence — rather than mixing the change into active phase work.

## Refactor candidates

- **Extract `manuscripta.cli` and `manuscripta.config`** into dedicated
  modules. Noted in TESTING.md §12. Pyramid-first, refactor-second
  ordering is non-negotiable; schedule this only after the test
  pyramid, mutation baseline, and integration-target amendment have
  settled.
