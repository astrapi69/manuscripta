# ADR-0004: Exception string representation is not part of the public API

- **Status:** Accepted
- **Date:** 2026-04-14
- **Author:** manuscripta maintainers

## Context

Phase 4b mutation testing (ADR-0002) surfaced a cluster of surviving
mutants in `manuscripta.exceptions` that all mutate the **format** of
the string produced by `__str__()` on our exception classes — join
separators, line separators, snippet size, snippet direction. They
survive because the existing test suite asserts on **attribute access**
(`err.missing == ["config", "assets"]`, `err.unresolved[0] == "images/foo.png"`,
`err.source_dir`) and **substring presence** (`"config" in str(err)`),
never on the exact format of the rendered message.

Pass 1 of the mutation-response protocol categorised these five
mutants as C (specification gap): the docstrings document the
**attributes** but are silent on message format. Pass 2 needs a
decision: either declare a format contract and pin it with new tests
(Path β), or declare the format **not** a contract and mark the
mutants as B (Path α).

The question is broader than the five mutants. It is: **is the output
of a `manuscripta` exception's `__str__()` / `__repr__()` part of the
library's public API?** Answering once here prevents the same debate
every time a new exception class is added.

The decision generalises beyond those 5 mutants: any future
`ManuscriptaError` subclass inherits this policy automatically, and
any future mutation-testing run on the exceptions module will treat
format-only mutations as B by default rather than rediscovering the
question. That forward reach is why this lives in a standalone ADR
rather than as a Pass 2 commit note.

## Decision

**The output of `__str__()` and `__repr__()` on any
`manuscripta.exceptions.ManuscriptaError` subclass is diagnostic,
subject to change without a major-version bump, and must not be
parsed by consumers.**

The public API of a manuscripta exception is its **attributes**:

- `ManuscriptaLayoutError`: `source_dir`, `missing`, `reason`
- `ManuscriptaImageError`: `unresolved`
- `ManuscriptaPandocError`: `returncode`, `stderr`, `cmd`
- any future subclass: its documented `Attributes:` block

Consumers who want to react programmatically to an exception read its
attributes. Consumers who want to display the exception to a human
print `str(err)` / `repr(err)` and accept that the text may change
between versions.

## Rationale

### Why exception messages should not be a contract

Pinning `str(err)` output to a specific format looks like
belt-and-braces good practice and is actually the opposite. Three
concrete failure modes:

**1. Downstream parsing creates invited dependencies.** If the
current message happens to be
`"manuscripta: source_dir /path is missing required subdirectories: config, assets"`,
a sufficiently clever consumer may write
`missing = str(err).split("subdirectories: ")[1].split(", ")`.
The maintainer then cannot change the preposition, cannot add a
trailing hint ("did you run `manuscripta init`?"), cannot localise
the message, cannot switch to multi-line formatting for long lists —
all without a breaking change. The correct consumer code is
`err.missing`; the message-as-API framing invites consumers toward
the incorrect one.

**2. It locks out legitimate usability improvements.** A good
library iterates on error messages over time: adding correlation
IDs, suggesting remediation steps, prefixing with the library
version, embedding links to documentation. Every one of those
improvements breaks a message-format test. The test therefore either
gets updated alongside the change (meaningless ceremony) or blocks
the change entirely (meaningful damage).

**3. It does not prevent the bugs it looks like it prevents.** A
mutation that changes `", ".join(self.missing)` to `"XX, XX".join(...)`
produces a message like `"configXX, XXassets"` — ugly, but the
**attributes** are unchanged (`err.missing == ["config", "assets"]`).
A consumer that uses attributes is unaffected. A consumer that parses
messages was already broken by the mutation; also by any maintenance
change; also by any localisation effort. The message-format tests
only catch mutations that also happen to break a parser nobody
should have written in the first place.

### Why attributes are the right surface

Attributes are what the type system documents. They are introspectable
at the point of catch (`except ManuscriptaLayoutError as e: …e.missing…`),
they are picklable (ADR-0002's picklability tests pass because of the
`__reduce__` methods on attributes), and they are the natural unit of
test assertion (`assert e.missing == {"config", "assets"}`). A
library that publishes attributes as its API and messages as its
diagnostic output has two independent concerns that can evolve
independently.

### Why a short one-line docstring note is sufficient

The contract can be communicated in one sentence on each exception
class. Overdocumenting here would signal that the rule is
controversial; it is not. The rule is the default in every well-known
Python library (`requests.HTTPError`, `subprocess.CalledProcessError`,
`json.JSONDecodeError`) — none of them pin message format. Writing a
manual for the default is noise.

### What this means for mutation testing

Per ADR-0002 §"Response protocol", surviving mutants that change only
`str(err)` format (without altering any attribute value) are
**Category B — documented equivalent**. The inline annotation on
each B-marked line cites this ADR by number, so future readers find
the reason.

The 5 such mutants in `manuscripta.exceptions` at the Phase 4b
baseline move from C → B on the basis of this ADR.

## Alternatives considered

**Path β — pin message format to literals.** Rejected. Pinning would
either be shallow (substring presence, which mutations already
survive because attributes stay intact) or deep (exact equality with
literal strings, which creates the invited-dependency problem
above). Neither buys real protection against the class of mutation
that survives.

**Path γ — pin a structural format without literals.** Something
like "the message must contain each attribute's value as a substring."
This is where my instinct started. Rejected because it's still
susceptible to the invited-dependency pattern (consumers may rely
on *position* of the substrings, on the separator style, etc.) and
still blocks the legitimate usability improvements listed in
§Rationale ¶2. A weakly-pinned contract is worse than no contract:
it performs discipline without producing protection.

**Path δ — publish a separate machine-readable representation.**
A `to_dict()` method on every exception. Consumers who need structured
access use it; `str(err)` stays human-facing. **Deferred; revisit
only if a concrete structured-logging or telemetry consumer requires
it and attribute access proves insufficient.** YAGNI with a named
trigger — not "revisitable" (which invites speculative work) but
"revisit on concrete demand". Attribute access serves the same role
today with less API surface.

**Path ε — no policy, decide case by case.** Rejected. That leaves
every mutation-response cycle negotiating the same question, and
every new exception class argues from scratch. A blanket rule is
cheaper to maintain and harder to erode.

## Consequences

**Easier:**

- Exception messages can be improved freely (added context,
  localised strings, multi-line formatting) without breaking
  consumers.
- Mutation testing of message-format mutations closes cleanly via
  B-annotation citing this ADR.
- New exception classes inherit the policy; no per-class decision
  needed.
- Consumer code review can reject `str(err).split(...)` patterns
  with a concrete citation.

**Harder:**

- None identified. The message-format tests we would otherwise write
  provide no real protection; their absence is not a regression.

**Locked in:**

- `ManuscriptaError.__str__()` and `__repr__()` outputs are
  diagnostic, not contractual. Adding a format contract to any
  existing subclass requires a superseding ADR that engages with
  §Rationale above (specifically ¶1 on invited dependencies).
- Attribute names on each exception class **are** contractual —
  renaming is a breaking change, even though the message format is
  not.

  Concrete example of the distinction:

  > Renaming `ManuscriptaLayoutError.missing` to
  > `ManuscriptaLayoutError.missing_dirs` is a breaking change
  > requiring a major version bump. Changing the `str()` output
  > from `"source_dir X is missing required subdirectories: a, b"`
  > to `"Layout error at X: missing a, b"` is **not** a breaking
  > change and requires no version signal.

  Both sentences are necessary: the first rules out "the attributes
  are free to refactor because the message is diagnostic"; the
  second rules out "the current message is pinned because *something*
  about the exception must be stable". Neither reading is the
  policy.

**Explicitly rejected:**

- String equality tests on `str(err)` in the project's own test suite.
  Existing tests use `in` (substring presence) which is
  attribute-independent and tolerant of format change. Any new tests
  that assert on `str(err)` must follow the same pattern.

## Implementation

A follow-up commit (not this ADR) adds a one-line note to each
exception class's docstring:

```python
class ManuscriptaLayoutError(ManuscriptaError):
    """Raised when source_dir is missing expected subdirectories,
    does not exist, or is not a directory.

    Note:
        ``str(err)`` format is diagnostic and may change between
        versions. Consumers should use attribute access
        (``err.missing``, ``err.source_dir``, ``err.reason``).

    Attributes:
        source_dir: …
        missing: …
        reason: …
    """
```

The same note, copy-pasted, on every ManuscriptaError subclass.

Mutation-response annotations on the 5 currently-surviving
format mutants cite `ADR-0004` inline.

## Links

- [ADR-0001](0001-test-pyramid.md) — test pyramid and coverage policy (the
  parent decision ADR-0002 extends from).
- [ADR-0002](0002-mutation-testing.md) — mutation testing policy; this
  ADR resolves the Pass 1 C-category cluster in `exceptions`.
- [ADR-0003](0003-coverage-threshold-categories.md) — module categories;
  exceptions.py is CORE and sits at 100 % line coverage, which is
  orthogonal to the message-format question.
- `docs/TESTING.md` §14 — mutation testing how-to; response protocol
  cites this ADR for exception-message equivalences.
- `src/manuscripta/exceptions.py` — the module whose exception classes
  this ADR governs.
