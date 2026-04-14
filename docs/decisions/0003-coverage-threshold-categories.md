# ADR-0003: Module categories for coverage threshold differentiation

- **Status:** Accepted
- **Date:** 2026-04-14
- **Author:** manuscripta maintainers

## Context

ADR-0001 established a test pyramid and, in its §3 "Targets" table, a
small set of per-module coverage thresholds (`exceptions` 100 %,
`export.book` 95 %, `export.shortcuts` / `project` 90 %,
`audiobook.tts.*` 85 %, everything else 85 %). Those numbers were
reasonable as a first cut but deliberately left the *mechanism* for
categorising modules implicit.

During Phase 4 coverage measurement the weakness surfaced. Several
modules that ADR-0001 had nominally pinned at 90 % are, on inspection,
not shaped like their neighbours in the same threshold bucket:

- `manuscripta.project.tag_message` (441 statements, most of them wrapped
  around interactive git subprocess calls) and
  `manuscripta.audiobook.generator` (heavy TTS-adapter orchestration)
  look structurally different from `manuscripta.project.init` (pure
  filesystem scaffolding) or `manuscripta.project.metadata`
  (deterministic YAML manipulation), even though all four live under the
  same "`project` / `audiobook` subtree" in the original table.
- `manuscripta.translation.deepl`, `…lmstudio`, `…shortcuts`,
  `…shortcuts_lms` are almost entirely HTTP clients and dispatch.
  Pushing them to 90 % unit coverage buys mock scaffolding, not
  confidence.
- `manuscripta.export.shortcuts` looks like a CLI wrapper at 337
  statements, but it is also the surface that the v0.7.0 image-
  embedding bug traversed. Treating it as "just a wrapper" would be
  the wrong lesson.

A uniform floor forces one of two bad outcomes: either we water down
the top tier (CORE modules drift below their real target) or we drive
CLI/network modules above their natural ceiling with brittle mocks.
Neither serves quality.

We need a policy primitive that separates "what kind of module is this"
from "what number do we put on it", so the numbers fall out of the kind
rather than being bargained individually.

## Decision

Introduce three module categories as a first-class policy primitive.
Every module in `src/manuscripta/` belongs to exactly one:

| Category             | Floor | Shape |
|----------------------|------:|-------|
| **CORE**             | 85–100 % as configured | Pure logic, deterministic, fully testable without external dependencies. |
| **CLI_WRAPPER**      | 80 %  | Thin argv-parsing and dispatch. Behaviour is mostly "forward args to a core function". |
| **NETWORK_INTEGRATION** | 80 % | Fundamentally exists to talk to an external service (HTTP API, local daemon, subprocess with real external effects). |

The per-module threshold table in `docs/TESTING.md` §3 is the single
source of truth for which module lives in which category. The table and
the `[tool.manuscripta.coverage_thresholds]` block in `pyproject.toml`
are kept in sync mechanically by `scripts/check_coverage_thresholds.py`.

## Rationale

### Why three categories, not two or four

Two (CORE + carve-out) conflates CLI wrappers with network integrations
— they fail coverage for different reasons and deserve different
remediation ("extract testable logic" vs "add an integration test").

Four or more (separating e.g. `CLI_WRAPPER_THIN` from
`CLI_WRAPPER_FAT`, or carving out "config parsers" from "pure
transforms") is category proliferation. We would never agree on the
boundaries; every borderline case would trigger a bikeshed.

Three matches the three forces we actually face: (a) strictness where
logic is testable, (b) realism where unit coverage is mock theatre,
(c) realism where unit coverage stops at a network seam.

### Why 80 % as the carve-out floor

- Phylax's quality-checks rule that "no module falls below 80 % without
  an ADR-documented exception" already anchors 80 % as the policy wall.
  The carve-out lands at that wall, not beneath it.
- 80 % is high enough to force real tests (you cannot reach it by
  exercising happy-path only), low enough that the last ~15 % does not
  require mocking an entire external API.
- Symmetric with the pyramid's boundary: below 80 %, the ADR gate
  engages for any module regardless of category. The carve-out widens
  the allowed range, it does not lower the floor.

### Why `manuscripta.export.shortcuts` is a documented exception

`export.shortcuts` fits the CLI_WRAPPER shape on paper: it is ~337
statements of argv validation and dispatch. In principle its category
floor would be 80 %.

We hold it at 90 % for one specific historical reason: **the v0.7.0
image-embedding bug surfaced through this file.** The CLI layer is
where extraction-class regressions manifest first and where users
observe them. Weakening its threshold would be accepting a known blind
spot on a known-sharp edge.

This is the only intentional exception. Future exceptions must meet an
equivalent bar — a specific historical bug or a specific architectural
role — and be noted inline in the threshold table. No silent overrides.

### Why categories, not "just adjust the numbers"

A policy consisting only of per-module numbers becomes unreadable after
a dozen entries. Every new module requires a fresh argument about what
number to pick. A policy consisting of three categories with one
default each reduces new-module triage to a classification question
(CORE / CLI_WRAPPER / NETWORK_INTEGRATION) that almost always has a
clear answer from the module's first file of source.

The categories also give mutation-testing scope (ADR-0002) a natural
partition: mutate CORE modules aggressively, skip NETWORK_INTEGRATION
modules, spot-check CLI_WRAPPER modules.

### What prevents category-drift misuse

Four deliberate frictions:

1. **ADR gate on CORE → carve-out reclassification.** Moving a module
   from CORE to CLI_WRAPPER or NETWORK_INTEGRATION requires a fresh
   ADR. Reclassification is the primary abuse vector ("this module got
   hard to cover, let's call it NETWORK_INTEGRATION and lower the
   floor"). An ADR makes the rationale visible and reviewable.
2. **Inline rationale required for every NETWORK_INTEGRATION entry.**
   The threshold table in TESTING.md §3 carries a one-line reason for
   every NI classification ("Edge TTS HTTP wrapper", "gTTS HTTP",
   "DeepL HTTP client"). A reviewer can sanity-check in seconds.
3. **Debt tracking is separate from category.** A CORE module that is
   below its target goes into the §12 debt table with a baseline; it
   does **not** get reclassified. Debt is temporary; category is the
   module's nature.
4. **Ratchet on debt modules** (§3 baseline subsection). Once a CORE
   module's coverage rises, the new level locks in. The easy path of
   "accept regression because it's hard" is closed.

### Why mutation testing (ADR-0002) makes the carve-out safer

ADR-0002 directs mutmut at CORE modules only. NETWORK_INTEGRATION
modules are explicitly out of scope ("mutation testing on
subprocess-heavy code is near-useless"). This means lowering
NETWORK_INTEGRATION coverage to 80 % does **not** silently weaken the
mutation signal — those modules were never going to be mutation-tested
anyway. The carve-out and the mutation scope decision fit together.

## Alternatives considered

**Keep ADR-0001's uniform table; adjust individual numbers case-by-case.**
Rejected. Leads to n per-module debates, each without a reusable
framework. Today's reviewer accepts a lower number for Module X;
tomorrow's reviewer finds a similar Module Y and argues from inconsistency.

**Single carve-out category ("carved out", 80 %).** Rejected. Loses the
CLI_WRAPPER / NETWORK_INTEGRATION distinction, which actually matters
for how to close the remaining gap (refactor vs integration test).

**Fourth category for "config / parsers".** Rejected. Config parsers
are either deterministic (CORE) or they are talking to a live service
(NETWORK_INTEGRATION). A separate category gains nothing.

**Mandatory ADR on every threshold change, regardless of direction.**
Rejected as too heavy. Increases (tightening a target) should be
frictionless. The ADR gate belongs on reductions and reclassifications,
where the risk of silent weakening lives.

## Consequences

**Easier:**

- New-module triage: pick a category; the threshold follows.
- Review conversations on coverage: argue about the category (a
  structural question with a fact-based answer), not the number (a
  negotiation).
- Mutation testing scope: "CORE only" is a one-line policy that aligns
  with this ADR's categories.
- Reading the §3 table: a category column makes the pattern visible at
  a glance.

**Harder:**

- The threshold table is longer (we now list every module individually,
  not just the outliers). The trade-off is visibility: a reader can
  verify they agree with every classification.
- Reclassification requires an ADR, which is friction. That friction
  is load-bearing; see §Rationale ¶"category-drift misuse".

**Locked in:**

- The three-category structure. A fourth category requires a superseding
  ADR.
- The CORE → carve-out ADR gate.
- The `export.shortcuts` 90 % exception. Relaxing it requires an ADR
  that engages with the v0.7.0 rationale.
- The 80 % wall regardless of category. Dropping below 80 % requires an
  ADR per the phylax-inherited policy, independent of this one.

**Explicitly rejected goals:**

- 100 % coverage in any category. CORE modules aim at the table's
  configured target, which caps at 100 % only for `exceptions` (tiny
  surface, exhaustively testable). Elsewhere, pushing above the target
  through mock-heavy paths is anti-goal; see ADR-0002 on why the
  pressure to inflate numbers for its own sake corrupts the signal.

## Links

- ADR-0001 (test pyramid and coverage policy) — parent decision.
- ADR-0002 (mutation testing) — aligned via CORE-only mutation scope.
- `docs/TESTING.md` §3 — the threshold table and the baseline-ratchet
  mechanism that this ADR constrains.
- `docs/TESTING.md` §12 — the debt table. Debt is separate from
  category.
