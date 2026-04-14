# Architecture Decision Records

Each ADR captures a single non-trivial decision: the context that forced
it, the options considered, the chosen option, and the consequences we
accept. Structure, not essay.

## Format

```
docs/decisions/NNNN-kebab-case-title.md
```

`NNNN` is a zero-padded sequence number starting at `0001`. Numbers are
assigned on write and never reused. Titles are short and descriptive.

## Template

```markdown
# ADR-NNNN: <title>

- **Status:** Proposed | Accepted | Superseded by ADR-MMMM | Deprecated
- **Date:** YYYY-MM-DD
- **Author:** <name>

## Context
<What problem forced this decision? What constraints are in play?>

## Decision
<What did we choose? One or two sentences.>

## Rationale
<Why this option over the others we considered?>

## Alternatives considered
<Options rejected, with reasons. Short.>

## Consequences
<What becomes easier? What becomes harder? What did we lock in?>

## Links
<PRs, issues, upstream docs.>
```

## Rules

- One decision per ADR. If you need to revise, write ADR-MMMM and set
  the old one's status to "Superseded by ADR-MMMM".
- ADRs are append-only. Never edit an Accepted ADR in place except to
  change its `Status` line.
- Link to the ADR from wherever it is enforced (TESTING.md,
  `.claude/rules/*.md`, code comments).
- Coverage-threshold exceptions below the 80 % wall require an ADR
  here before the merge lands.

## Index

| ID       | Title                                                            | Status   | Date       |
|----------|------------------------------------------------------------------|----------|------------|
| 0001     | Test pyramid and coverage policy                                 | Accepted | 2026-04-14 |
| 0002     | Mutation testing scope and policy                                | Accepted | 2026-04-14 |
| 0003     | Module categories for coverage threshold differentiation         | Accepted | 2026-04-14 |

ADR numbers are identifiers, not timestamps. ADR-0002 was reserved
during Phase 2 and filled in during Phase 4b, so its index entry's
date is later than ADR-0003's even though the number is lower. That is
correct.
