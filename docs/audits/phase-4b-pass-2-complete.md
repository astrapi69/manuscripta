# Phase 4b Pass 2 — Completion report

Date: 2026-08-14
Status: **complete**. All six in-scope modules meet their thresholds;
the nightly threshold gate passes for the first time since it was
introduced.

## Final per-module state (fresh full run at `c38419a`)

```
Module                                          killed  surv  tout   eq  total  score   thr
src/manuscripta/exceptions.py                       29     0     0    6     35 100.0%   95%
src/manuscripta/paths/to_absolute.py               289     1     0   23    313  99.7%   85%
src/manuscripta/paths/to_relative.py               111     0     0   10    121 100.0%   85%
src/manuscripta/images/convert.py                  225     0     0   13    238 100.0%   85%
src/manuscripta/markdown/normalize_toc.py           92     0     0   14    106 100.0%   85%
src/manuscripta/audiobook/tts/text_chunking.py      44     0     0    6     50 100.0%   80%
```

The single surviving mutant is the C-category specification gap on
`to_absolute.py` (`_find_image_tag` mutant 62): an empty
angle-bracket target `![a](<>)` currently "converts" to the md file's
containing directory. Deliberately not pinned; see the triage map's
"Specification gap" section and §14.5's C-protocol. Phase 6 material.

## What Pass 2 Commits 10–12 added

- 35 A-category tests across three `*_mutation_pins.py` files, each
  docstring naming the mutant(s) it kills and the contract the
  assertion traces to.
- A unit-layer default `pytest.mark.timeout(10)`
  (tests/unit/conftest.py) — converts infinite-loop mutants from
  score-penalising `timeout` records into kills, per ADR-0002's
  strict-score reading. Explicit 60 s headroom for the hypothesis
  fuzz test to keep equivalent-kills deterministic.
- 47 B-annotations in `.mutmut/equivalent.yaml` with per-mutant
  traces: §14.8.5 (9), §14.8.1 (18), codec-alias (6), ad-hoc
  converges/falsiness/platform clusters (14).
- One C-category specification gap, documented, unpinned.

## Findings worth keeping (tooling)

1. **Coverage-driven mutant generation** (now TESTING.md §14.10):
   mutmut 3.5 only mutates covered lines, so the Commit 10 tests grew
   `to_absolute.py`'s mutant set 305 → 313 and renumbered ids.
   Response ordering rule: land tests → regenerate → annotate.
2. **Stale-state guard** (`98d7ab3`): a partially-run mutmut state
   store reads as vacuous kills; the threshold script now fails fast
   above 50 % unchecked mutants per module.
3. **Flaky equivalent-kills**: any unit test running near the default
   timeout ceiling under mutmut's instrumentation can spuriously
   fail and "kill" an annotated equivalent, making the nightly score
   flap. Give slow tests explicit timeout markers.
4. **mutmut pin promoted to exact** (`==3.5.0`), closing the drift
   between §14.9's table (which already claimed exact) and
   pyproject's caret pin. §14.8.3 and §14.10 are both statements
   about this version's internals.

## Nightly expectations

The next scheduled mutation-nightly run regenerates the mutant tree
with these tests present and must reproduce the table above. The
threshold gate exits 0, the audit rotates normally, and the standing
regression issue (#1) can close.
