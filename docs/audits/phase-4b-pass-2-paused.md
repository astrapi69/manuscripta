# Phase 4b Pass 2 — Paused for v0.8.0 Release

**Status:** PAUSED at end of logical Commit 9 (HEAD = `1f123e0`).
**Pause date:** 2026-04-15.
**Reason:** the PDF-image-resolution bug that motivated the v0.8.0 work
is fixed, the public API contract is committed, and `MIGRATION.md` is
in place. The downstream consumer (`bibliogon`) needs a tagged release
to depend on, not a complete mutation-testing audit. Pass 2's remaining
work (Commits 10–13) is internal quality polishing that does not block
external consumers.

## Commits completed (1–9)

Pass 2 logical commits map to git commits as follows. Counting starts
at the first per-module mutation response after the §14.8 policy
framework was in place; framework-only commits (ADR-0004, §14.8 root,
§14.8.3 standing-policy text) are treated as pre-Commit-1 setup and
listed separately.

### Pre-Commit-1 setup (policy framework)

| SHA | Subject |
|---|---|
| `205fadf` | docs(adr): add ADR-0004 exception string representation not part of API |
| `cdec594` | docs(testing): add §14.8 standing equivalence policies |
| `5924842` | docs(testing): add §14.8.3 trampoline-induced equivalence |
| `3a09969` | docs(adr): amend ADR-0002 with trampoline-equivalent score treatment |

### Commit 1–3 — `audiobook/tts/retry.py` response

| SHA | Subject |
|---|---|
| `92238e6` | test(retry): pin public default parameters via behavioral assertions |
| `a575724` | test(mutation): annotate retry.py trampoline-equivalent mutants |
| `b478a9a` | build(mutation): remove retry.py from scope — §14.8.3 insufficient surface |

Resolution: all three retry.py survivors were §14.8.3 trampoline-
equivalents. Module removed from `tool.mutmut.paths_to_mutate` per
ADR-0002's zero-denominator clause.

### Commit 4–5 — v0.8.0 cut-over (out-of-band; required by exception-hierarchy work)

| SHA | Subject |
|---|---|
| `637ec89` | feat(exceptions)!: extract exception hierarchy into dedicated module |
| `5a8fa01` | chore(version): bump to 0.8.0 |
| `8cf339b` | docs(release): add MIGRATION.md and README notice for v0.8.0 |

Note: these are not strictly Pass 2 commits but are interleaved
because the exception-hierarchy refactor changed the mutation surface
of `manuscripta.exceptions` and had to land before Commit 6 could
respond to its survivors.

### Commit 6 — `exceptions.py` response

| SHA | Subject |
|---|---|
| `cd231e3` | test(mutation): kill exceptions.py A-survivors + annotate 6 B per ADR-0004 |

### Commit 7 — `audiobook/tts/text_chunking.py` response

| SHA | Subject |
|---|---|
| `30e4897` | test(mutation): kill text_chunking.py A-survivors + annotate 6 B (1 §14.8.3 + 5 ad-hoc) |

### Commit 8 — `images/convert.py` response + §14.8.4 elevation

| SHA | Subject |
|---|---|
| `cbc60b1` | docs(testing): amend §14.8.1 and §14.8.3, add §14.8.4 empty-slice equivalence |
| `d9e9ade` | test(mutation): kill convert.py A-survivors + annotate 13 B across 4 policy paths |

### Commit 9 — runner-level fixes + §14.8.5 elevation

| SHA | Subject |
|---|---|
| `9f0c7a5` | fix(mutation): de-duplicate equivalent mutants from survived counts |
| `d10b05e` | fix(test): skip threshold-script regression under mutmut mirroring |
| `aaad6f0` | docs(phase-6): record tests/fixtures deletion incident under working-tree hygiene |
| `1f123e0` | docs(testing): add §14.8.5 opaque-token renaming equivalence policy |

The §14.8.5 policy was elevated based on triage of `paths/to_absolute.py`
(the deferred Commit 10 module). The policy text is committed; the
9 B-annotations that will cite it are part of the deferred Commit 10.

## Commits deferred (10–13)

| # | Module / artefact | Triage status |
|---|---|---|
| 10 | `src/manuscripta/paths/to_absolute.py` | Triaged but not committed. Plan: ~50 A-tests (25 timeout-as-A infinite-loop kills using `pytest-timeout(5)` + ~25 regular survivors) + ~18 B-annotations (9 §14.8.5, 2–4 ad-hoc early-return-converges, 1 §14.8.1 print-None, 2 ad-hoc codec-alias, 1 falsiness). Target: 100% kill on `to_absolute.py`. |
| 11 | `src/manuscripta/paths/to_relative.py` | Untriaged. Baseline survivors retained. |
| 12 | `src/manuscripta/markdown/normalize_toc.py` | Untriaged. Baseline survivors retained. |
| 13 | Audit publication | Per-module audit YAML aggregation + the post-Pass-2 publication step (the artefact this very document partially substitutes for). |

## Per-module mutation status as of pause

Modules that have received a Pass 2 response (A-tests landed, B
mutants annotated, threshold script passes for the module):

- `manuscripta.audiobook.tts.retry` — removed from scope (§14.8.3).
- `manuscripta.exceptions` — responded (commit `cd231e3`).
- `manuscripta.audiobook.tts.text_chunking` — responded (commit `30e4897`).
- `manuscripta.images.convert` — responded (commit `d9e9ade`).

Modules that retain their baseline survivor population (no Pass 2
response yet; thresholds pass only because the module-level floor in
`scripts/check_mutation_thresholds.py` admits the baseline):

- `manuscripta.paths.to_absolute` — survivors triaged, response not committed.
- `manuscripta.paths.to_relative` — un-triaged.
- `manuscripta.markdown.normalize_toc` — un-triaged.
- Any other module currently in `tool.mutmut.paths_to_mutate` not
  named above — un-triaged.

## Triage decisions made but not committed

- **§14.8.5 elevation** (token-renaming-invisible, opaque-token round-
  trip). The standing-policy text is committed (`1f123e0`); the 9
  B-annotations on `_protect_segments` survivors that cite it are not.
- **Ad-hoc pattern: early-return-bypass-converges.** Surfaced in the
  `to_absolute.py` triage. Applied to 2–4 mutants where the mutated
  early return short-circuits to the same observable state the
  unmutated path would have reached on the next iteration. Treated as
  ad-hoc per-mutant equivalence, not elevated to a §14.8 standing
  policy — the recurrence rate was below the §14.8.4 elevation bar.
- **Partial `to_absolute.py` categorization.** Survivors split into
  the buckets enumerated in the Commit 10 row above. Not committed.

## Resume condition

When Pass 2 resumes, the entry point is unchanged from the
pre-pause direction:

1. Confirm the §14.8.5 amendment direction in the prior session is
   still applicable (re-read [docs/TESTING.md §14.8.5](../TESTING.md#L1418-L1535);
   it is already landed in full by `1f123e0` and may need no
   amendment).
2. Land Commit 10: the A-tests + 18 B-annotations on
   `paths/to_absolute.py` per the triage breakdown above.
3. Continue with Commits 11–13.

Stop-rules from the pre-pause session remain in force: stop on
threshold fail, stop on sixth ad-hoc pattern, stop on more than
`(free-functions × 2)` §14.8.3 candidates.

## Cross-link to git log range

There is no `v0.7.0` git tag in this repository. `v0.7.0` exists as a
documented release in `CHANGELOG` (commit `439e0ae`, *"docs(audiobook):
CHANGELOG and migration guide for v0.7.0"*) but was never tagged. The
last tag before the v0.8.0 cut is `v0.6.2`.

The Pass 2 commit set is therefore best identified by the range:

```
git log 439e0ae..1f123e0 --oneline
```

(35 commits total; the four pre-Commit-1 setup commits plus Commits
1–9 are listed in the table above.)

The corresponding tagged range will be `v0.6.2..v0.8.0` once `v0.8.0`
is cut as part of the release this pause document accompanies.
