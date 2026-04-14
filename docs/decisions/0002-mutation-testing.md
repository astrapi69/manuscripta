# ADR-0002: Mutation testing scope and policy

- **Status:** Accepted
- **Date:** 2026-04-14
- **Author:** manuscripta maintainers

## Context

Through Phase 4 Priorities 1–3 the project reached a state where every
in-scope module sits at or above its configured coverage threshold and
the layered test pyramid (unit / integration / e2e / e2e_wheel) is
populated and enforced. Coverage tells us _whether code ran_; it
deliberately does not tell us _whether tests asserted on outcomes_. The
v0.7.0 image-embedding bug, which all unit tests passed cleanly, is
the canonical example of the gap: line coverage of the affected code
was 77 % but the tests didn't actually assert on the produced
artifact, so the bug shipped.

We need a quality signal _orthogonal_ to coverage. Mutation testing
fills this role: rewrite small fragments of the source ("mutants") and
check whether the test suite still passes. A mutant the tests fail to
distinguish is a mutant they didn't actually pin behaviour for; the
score is the fraction of mutants killed.

The policy questions are:

1. Which mutation tool, given Python 3.11+ and a small project budget
2. Which modules are in scope (mutation on subprocess-heavy code is
   near-useless because every mutant fails for the same external reason)
3. How to relate scope to the coverage debt mechanism from ADR-0001/0003
4. Whether to gate merges on mutation score
5. How to enforce per-module score thresholds without coupling them to
   the coverage threshold mechanism
6. How to handle surviving mutants (the response protocol)

## Decision

**Tool**: mutmut 3.5.x. Configuration in `[tool.mutmut]` and per-module
score thresholds in `[tool.manuscripta.mutation_thresholds]`, both in
`pyproject.toml`. Optional dependency group so consumers don't pull
mutmut by default.

**Scope rule (categorical)**:

> A module is in mutation scope if and only if (a) its category is
> CORE per ADR-0003, AND (b) it is **not currently in the debt table
> of TESTING.md §12**. Modules in CLI_WRAPPER and NETWORK_INTEGRATION
> categories are out of scope; mutation on subprocess-heavy or
> network-bound code produces near-no signal because every mutant
> fails for the same external reason.

**Debt-graduation rule**:

> Debt-tracked modules are excluded from the mutation scope until they
> reach their coverage target. Rationale: mutation testing measures
> test quality; debt modules have knowingly insufficient tests, so
> mutation scores would confirm what is already documented. Once a
> module exits the debt table, it is added to the mutation scope in
> the same commit that removes it from `baseline-coverage.json`.

**Current in-scope list (6 modules)**:

| Module path | Threshold | Inclusion criterion satisfied |
|---|---:|---|
| `src/manuscripta/exceptions.py` | 95 % | CORE; tiny surface; trivially testable |
| `src/manuscripta/paths/to_absolute.py` | 85 % | CORE pure path/text transform |
| `src/manuscripta/paths/to_relative.py` | 85 % | CORE pure path/text transform |
| `src/manuscripta/images/convert.py` | 85 % | CORE markdown→HTML transform |
| `src/manuscripta/markdown/normalize_toc.py` | 85 % | CORE pure text transform |
| `src/manuscripta/audiobook/tts/text_chunking.py` | 80 % | CORE pure string-splitting |

(The list was seven modules at ADR acceptance. `audiobook/tts/retry.py`
was removed during Phase 4b Pass 2 under the insufficient-surface
tier; see the Excluded table below.)

**Excluded with explicit rationale**:

| Module | Why excluded |
|---|---|
| `manuscripta.markdown.german_quotes` | CORE shape but currently debt-tracked at 84 % (target 85 %). Re-add when graduated. |
| `manuscripta.markdown.{unbold_headers,bullet_points,emojis,links_to_plain,strip_links}` | All eligible by category; not in initial scope to keep the baseline run time bounded. Add in a follow-up after the response protocol has been exercised. |
| `manuscripta.paths.img_tags` | CORE shape but debt-tracked at 72 %. |
| `manuscripta.config.loader` | CORE shape but debt-tracked at 0 % (no tests). |
| `manuscripta.utils.*` | Mix of debt and unrelated utilities. |
| `manuscripta.audiobook.tts.retry` | Insufficient mutable surface per §14.8.3 — all three mutmut-3.x mutants are trampoline-equivalent (default-value changes on `with_retry`'s signature; the wrapper forwards concrete args, so the mutant defaults are never consulted). Re-add when the module grows additional testable surface OR when a future mutmut release exposes default-argument mutations. Annotations retained in `.mutmut/equivalent.yaml` as audit history. |
| Everything CLI_WRAPPER or NETWORK_INTEGRATION (per ADR-0003) | Out of scope by category. |

**Inclusion criteria for future additions** (reviewers should consult
this list, not the module names alone):

1. Category is CORE in ADR-0003's classification.
2. Module is not in the §12 debt table.
3. Module's test surface does not require mocking >50 % of its
   imports (the mockability heuristic from Phase 4 Priority 1). If it
   does, the response work for survivors will be perpetual mock
   maintenance and the signal is noise.
4. Module exists in `paths_to_mutate` for fewer than 90 mutants per
   pre-graduation commit. Modules that explode mutmut runtime should
   be split or partially excluded; the initial seven-module set keeps
   nightly CI under the 45-minute Phase 4b budget.

A new entry adds:

- An entry in `[tool.mutmut].paths_to_mutate`
- An entry in `[tool.manuscripta.mutation_thresholds]`
- A row in this ADR's "Initial in-scope list" (replace the title with
  "Current in-scope list" once it grows)
- A row in TESTING.md §14

**Score definition**:

```
score = killed / (total - skipped - equivalent)
killed = total - survived - timeout - suspicious - skipped - equivalent - no_tests
```

Timeouts, no-tests, segfault, and suspicious mutants count against the
score. Conventional mutation testing literature is split on timeouts
(some treat them as killed because the test couldn't complete); we
take the strict reading because a timeout is not an assertion the test
suite made about the mutant's behaviour. Per ADR-0001's principle of
honest signals over flattering numbers.

**Threshold script**: separate `scripts/check_mutation_thresholds.py`
(not an extension of `scripts/check_coverage_thresholds.py`). See
§Alternatives considered.

**CI policy**: nightly, not per-PR. Mutmut takes 10+ minutes on the
seven-module scope; per-PR feedback would destroy iteration speed for
no merge-blocking benefit. The full results post to
`docs/audits/current-mutation.md` on every nightly run (success OR
regression) so the audit history shows the trend, not just the
incidents.

**Merge-blocking**: never. Mutation score is a quality _signal_, not a
gate. ADR-0001's coverage gate is what protects merges. Mutation
results inform the next sprint's test-writing priorities; they do not
fail builds.

**Local invocation**: `make mutation-fast` is the dev loop (only
modules changed vs `origin/main`). `make mutation` runs the full scope
and is documented as a "budget a coffee break" operation, not a
pre-commit check.

**Response protocol** (this is the expensive part of mutation
testing, where most projects lose discipline): every surviving mutant
falls into exactly one of A/B/C/D, recorded in the post-baseline
report:

- **A. Killed by new test.** Preferred. The new test asserts a
  specific behaviour that distinguishes the original from the mutant.
  Tests that re-pin the mutated literal without explaining _why_ that
  literal matters are not tests; they're hash checks. The assertion
  must trace to a specification, docstring, or inferable contract.
- **B. Documented equivalent.** The mutant produces identical
  observable behaviour to the original. Annotate on the mutated line:
  not "mutant is equivalent" but "both branches reach state X
  because Y." If the equivalence isn't visible from the comment, the
  comment is insufficient.
- **C. Documented specification gap.** The mutant survives because
  the specification is silent about the behaviour the mutation
  changes. Do _not_ pin current behaviour as correct (same rule as
  ADR-0001 §"normalize_toc.replace_extension ambiguity"). Add to
  TESTING.md's "Specification gaps surfaced by mutation testing"
  section.
- **D. Accepted below-threshold.** Module's score lands below
  threshold and the gap is composed of C-class mutants. Do _not_
  lower the threshold silently; document, ratchet down via ADR
  amendment if needed, track the spec work.

Forbidden: silently lowering thresholds, writing tests that pin
mutation-targeting literals, marking survivors B without verifiable
reason.

## Rationale

### Why mutmut (not cosmic-ray, not pytest-mutagen)

mutmut is maintained, integrates with `coverage.py` data
(`mutate_only_covered_lines = true` skips guaranteed-survivor
mutations), runs fast enough for a nightly cron, and configures from
`pyproject.toml`. Cosmic-ray is more thorough but its slowness pushes
nightly runtime past the budget. pytest-mutagen is small but its
mutation operator set is narrower than mutmut's.

mutmut 3.x has rough edges (subprocess-spawning tests interfere with
the runner; default mode mirrors only `paths_to_mutate` and breaks
unrelated imports without `also_copy`); these are workable with
inline configuration documented in `pyproject.toml`. Phase 4b Step 2
sanity-tested all of them.

### Why CORE-only scope

Mutating subprocess wrappers is near-useless: each mutant fails for the
same external reason (subprocess returns the wrong thing or doesn't
run at all), drowning the actual signal. This is empirically true for
every Pandoc-wrapper module in `manuscripta` (see ADR-0003's
NETWORK_INTEGRATION category). Mutation on those modules would
report low scores caused by the layer's nature, not by test quality.

### Why exclude debt modules

A module in `baseline-coverage.json` has knowingly insufficient tests.
Running mutation on it produces predictable low scores that confirm
what coverage already documents; the noise floor of the report goes
up; reviewers learn to ignore it. By tying mutation scope to debt
graduation, the mutation report stays informative and graduation gains
a structural reward: "your module just got mutation scoring."

### Why nightly, not per-PR

Mutmut on the initial 7-module scope estimates ~10–25 minutes wall
time on the project's hardware (extrapolated from the Step 2 sanity
run at 22.6 mutations/sec and ~1100 in-scope mutants; the actual
number measured in Step 7). Per-PR enforcement would either:

- block merges for 10–25 min of CI per PR (unacceptable iteration cost
  on a project where typical PRs are 100-line touch-ups), or
- run async and post results post-merge, at which point the signal
  arrives too late to act on.

Nightly preserves the signal and the audit trail without poisoning
the PR loop. The audit-on-success rule (see below) ensures _absence
of regression_ is also documented, so a quiet week is not confused
with a missing run.

### Why audit on success, not just on regression

Issue-comment-on-regression is the more common pattern but loses the
"everything is still fine" signal. The audit history must be
distinguishable from the absence of runs: a quiet week could mean no
regressions OR a broken cron, and the consumer of the audit shouldn't
have to debug CI to find out. Writing
`docs/audits/current-mutation.md` on every successful run with the
full per-module score table makes the trend visible at a glance.
Phylax's coverage-audit convention (see TESTING.md §3) uses the same
write-every-time pattern for the same reason.

### Why never merge-blocking

Mutation score is a quality SIGNAL, not a CONTRACT. A drop from 88 %
to 84 % may mean the test suite weakened, OR may mean a refactor
extracted a function whose new mutant operators happen to be easier
to survive than the inlined originals. The first warrants action; the
second is noise. Treating both as merge-blockers either creates a
chilling effect on legitimate refactors or trains reviewers to bypass
the gate. ADR-0001's coverage gate is the merge contract; mutation
informs but does not block.

### Why a separate threshold script

The two enforcement policies have already diverged:

- Coverage uses the baseline-ratchet on debt modules (ADR-0001 §3);
  mutation excludes debt modules entirely (this ADR).
- Coverage threshold violations are merge-blocking; mutation
  threshold violations are reportable, not blocking.
- Mutation gains the A/B/C/D survivor classification over time;
  coverage has no analog.

A single script would couple two policies that should evolve
independently, forcing every future change to touch both. The two
data sources are also structurally different (`coverage.json` is
file-keyed percentages; mutmut's state is per-mutant survival
status that needs aggregation). The script split keeps each one
small and single-purpose.

### Score formula treatment of trampoline-induced equivalence

mutmut 3.x wraps every mutated function in a trampoline that
resolves the original signature's defaults at the wrapper level and
forwards concrete arguments to the selected mutant. Mutations whose
only effect is to change a default parameter value in the mutation
target's own signature are therefore never exercised by the test
runner — the mutant receives the original's defaults and produces
identical behaviour by construction. TESTING.md §14.8.3 documents
this as a standing equivalence policy with its own citation tag
(`# B: TESTING.md §14.8.3 — trampoline forwards defaults; mutation
unreachable`).

From the score formula's perspective, §14.8.3-annotated mutants are
equivalents: they enter the `equivalent` bucket in the `killed /
(total - skipped - equivalent)` quotient, identical to §14.8.1 and
§14.8.2 / ADR-0004 B-annotations. The distinction between
behavioural equivalence (two reachable paths producing the same
state — §14.8.1, §14.8.2) and tool-artifact equivalence (the
mutation is unreachable because the framework short-circuits it —
§14.8.3) is preserved in audit output by counting the two
populations separately, so a rising §14.8.3 count signals "the
tool's instrumentation is hiding mutations" while a rising
§14.8.1 / §14.8.2 count signals "the codebase has grown more
policy-exempt wording" — two different maintenance prompts.

**Zero-denominator case.** A module whose entire mutant population
is §14.8.3-equivalent has `score = 0 / 0`. This is treated as
**insufficient mutable surface**, not as a threshold failure: the
tool's instrumentation cannot produce a meaningful measurement on
the module. The response is scope exclusion under a third,
distinct rationale tier alongside the two already established in
this ADR:

| Exclusion tier | Trigger | Re-entry condition |
|---|---|---|
| Category exclusion | Module is CLI_WRAPPER / NETWORK_INTEGRATION per ADR-0003 | Never (superseding ADR required) |
| Debt exclusion | Module is in TESTING.md §12 debt table | Graduates from debt table (ADR §Debt-graduation rule) |
| **Insufficient-surface exclusion (§14.8.3)** | Module's entire mutant population is §14.8.3-equivalent under current mutmut version | Module grows additional testable surface, OR a future mutmut release exposes default-argument mutations |

Insufficient-surface exclusions are recorded in the "Excluded with
explicit rationale" table with a `§14.8.3` citation in the "Why
excluded" column, and in the corresponding `[tool.mutmut]` config
block with a `# reason: §14.8.3 — insufficient mutable surface`
comment beside the prior entry. Re-entry is a normal scope
addition (four-surface update per the inclusion criteria above).

**Version-pin coupling.** The trampoline shape is an mutmut 3.x
internal, not a Python semantics guarantee. This ADR's treatment
of §14.8.3-equivalents is conditional on the pinned
`mutmut = "^3.5"` in `pyproject.toml`. Bumping the pin requires
re-verifying that default-argument mutations remain structurally
unreachable on the new version; if they do not, every §14.8.3
annotation and every insufficient-surface exclusion must be
re-categorised in the same commit that bumps the pin. The
version pin is therefore load-bearing and cannot be relaxed to a
bare `mutmut = "*"` without a superseding ADR.

### Why "100 % mutation score is not a goal"

Mutmut generates many mutants where the killed/survived distinction
is meaningless: the original `x = 1; if y: x = 2` produces a mutant
`x = 0; if y: x = 2` that survives if no test happens to sample the
`if y: False` path with `x` observable. Pursuing 100 % via test
additions creates scaffolding tests that pin incidental behaviour, and
those tests block legitimate refactors thereafter. The threshold
ladder (95 % for `exceptions`, 85 % for transforms, 80 % for retry /
chunking, 75 % default) reflects diminishing returns: the 90→100 % gap
on a 200-statement module is mostly C-class spec gaps, not real bugs.

## Alternatives considered

**cosmic-ray.** More thorough mutation operators; CLI is more flexible
in scope filtering. Rejected: slower (~2× mutmut on equivalent
scope), more complex configuration, harder to integrate with
`coverage.py`-based mutation gating. The thoroughness margin doesn't
buy enough for the budget cost on a Pandoc-wrapper library where
CORE modules are small.

**pytest-mutagen.** Smaller dependency surface, runs as a pytest
plugin so reuses the existing test runner exactly. Rejected: narrower
mutation operator set, less mature, and the runs-as-pytest model
loses the parallelism mutmut achieves with its fork-based runner. The
sanity check at 22.6 mutations/sec on a single module suggests
pytest-mutagen would be substantially slower at the same scope.

**Coverage-extension approach: extend `check_coverage_thresholds.py`
to also enforce mutation.** Rejected for the reasons in
§"Why a separate threshold script" above.

**Per-PR enforcement with async mode.** Run mutation in CI on every
PR but post results in a comment after merge. Rejected: signal
arrives too late to act on, and the data lands in PR-comment threads
that nobody trends. The audit-file-on-cron-schedule design surfaces
the trend in the repo itself.

**Tier mutation as a fifth pyramid layer.** Rejected emphatically.
Mutation testing is an _orthogonal_ meta-test, not a layer. A mutant
that fails to die is a unit-test problem. Calling it a "layer" would
imply mutation tests live in their own directory, with their own
markers, runnable independently — none of which is true. The pyramid
ADR (ADR-0001) explicitly rejects fifth layers without superseding
ADRs; this ADR confirms.

**Universal threshold (e.g. all modules at 80 %).** Rejected. Phylax's
"strict where it matters, loose where it doesn't" precedent (also
codified in ADR-0003 for coverage) applies here equally. `exceptions`
is small, hand-testable, and benefits from 95 % strictness.
`audiobook.tts.retry` is a tenacity wrapper whose mutants are
dominated by retry-count and backoff-multiplier changes that need
specific tests to distinguish — 80 % is the right floor.

**Relaxing CORE-only scope to include NETWORK_INTEGRATION modules
with mocked network calls.** Rejected, and named here explicitly
because the temptation to "expand mutation coverage to the TTS
adapters, they're important modules" will recur and needs a standing
refutation.

NETWORK_INTEGRATION modules (TTS adapters, translation clients,
`project.tag_message`) reach their 80 % coverage threshold through
heavy mocking — the unit tests stub out `edge_tts.Communicate`, the
ElevenLabs SDK, the gTTS HTTP client, etc. Running mutation testing
on them would measure the quality of the **mocks**, not the quality
of the tests against real behaviour:

- A mutant that flips `response.status_code == 200` to `== 201`
  survives not because the test is weak, but because the mock returns
  whatever the test configured it to. The "kill" requires the mock to
  reject 201 specifically — which the mock has no reason to do.
- A mutant that changes `wait_exponential(multiplier=2)` to
  `multiplier=3` survives because the mocked transient-error sequence
  doesn't run long enough for the difference to matter.
- A mutant that drops a header from an HTTP request survives because
  the mock isn't asserting on header presence — it's just recording
  the call.

The result would be uniformly low mutation scores on
NETWORK_INTEGRATION modules that diagnose nothing. The signal would
be "network code is hard to mutation-test", which is already known
(it is the foundation of ADR-0003's NETWORK_INTEGRATION category).
Reviewers would learn to ignore the report; the threshold ladder
above would need a new "mocked-network" tier with floors so low they
have no enforcement value.

The right instrument for this class of module is integration or
e2e_wheel testing against real services (or realistic replay
fixtures) — a separate tier with its own cost profile, not something
to retrofit onto the mutation scope. Adding NETWORK_INTEGRATION
modules to mutation scope therefore requires a superseding ADR that
either (a) defines a coherent mocked-network mutation policy with
real signal, or (b) introduces a real-service test tier that
generates the necessary observable contracts. Pre-refuted.

## Consequences

**Easier:**

- The integration with the debt mechanism creates a structural
  reward: "your module just hit its coverage target — now it's in
  mutation scope too." Carrots, not sticks.
- The categorical scope rule (CORE-only) keeps the report
  high-signal. Reviewers see five lines per module per nightly run,
  not 50.
- Separating mutation enforcement from coverage enforcement means
  policy changes on either side don't ripple into the other.
- The A/B/C/D protocol pre-commits the team to a discipline before
  the survivors arrive. Without that, every survivor becomes its own
  bike-shed.

**Harder:**

- Maintaining the `[tool.mutmut]` configuration alongside the
  `[tool.manuscripta.mutation_thresholds]` table (two surfaces
  changed per scope addition).
- Onboarding new contributors who don't know mutation testing
  vocabulary. Mitigated by TESTING.md §14, which is the
  consumer-facing entry point.
- Inline `noqa: equivalence` annotations on B-marked mutants will
  accumulate over time. ADR amendment may eventually be needed if
  they exceed the 30 % stop-rule for any module.

**Locked in:**

- mutmut as the tool. Switching tools requires a superseding ADR.
- CORE-only scope. Adding NETWORK_INTEGRATION modules requires an
  ADR.
- Nightly cadence. Per-PR enforcement requires an ADR.
- Audit-on-success rule. Issue-comments-on-regression-only requires
  an ADR.
- Never merge-blocking. Gating mutation requires an ADR.

**Explicitly rejected goals:**

- 100 % mutation score on any module. The threshold ladder is the
  ceiling, not the floor's complement.
- Mutation as a fifth pyramid layer. Mutation is orthogonal.
- Threshold reduction without ADR.

## Links

- [ADR-0001](0001-test-pyramid.md) — parent decision (test pyramid + coverage policy)
- [ADR-0003](0003-coverage-threshold-categories.md) — module categories that determine mutation scope
- `docs/TESTING.md` §14 — consumer-facing how-to for mutation testing
- `docs/TESTING.md` §12 — debt table that drives the debt-exclusion rule
- `pyproject.toml` `[tool.mutmut]` and `[tool.manuscripta.mutation_thresholds]` — configuration surface
- `scripts/check_mutation_thresholds.py` — the enforcement script
