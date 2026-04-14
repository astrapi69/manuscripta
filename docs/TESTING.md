# Testing manuscripta

This document defines the test pyramid, layer scopes, coverage policy, and
conventions for the `manuscripta` test suite. It is the source of truth;
README and inline comments should link back here rather than duplicating.

Modelled on [phylax's `.claude/rules/quality-checks.md`][phylax-rules],
adapted for a Python library that wraps external binaries (Pandoc, LaTeX,
TTS engines).

[phylax-rules]: https://github.com/astrapi69/phylax/blob/main/.claude/rules/quality-checks.md

---

## 1. The pyramid

```
          /\
         /wh\            e2e-wheel:   2–3 tests, real install, CI-only
        /----\
       / e2e  \          e2e:         5–10% of suite, real pandoc + LaTeX
      /--------\
     / integ.   \        integration: 20–30%, real subprocess, no LaTeX
    /------------\
   /    unit      \      unit:        60–70%, pure logic, no I/O
  /----------------\
```

Each test belongs to **exactly one** layer. When in doubt, it is an
integration test.

### Layer 1 — Unit (`tests/unit/`)

- **Scope.** Pure functions, path computation, argv assembly, config
  parsing, exception construction, markdown text transformations, YAML
  parsing, TOC normalization, validation helpers.
- **May use.** `tmp_path`, `monkeypatch`, `capsys`, `caplog`, tiny
  byte-level PNG generation, in-memory fakes.
- **May NOT use.** `subprocess`, real Pandoc, real LaTeX, network, writes
  outside `tmp_path`, import-time side effects on shared state.
- **Budget.** Each test < 50 ms. Whole layer < 5 s combined.
- **Count.** 60–70 % of the suite.
- **Marker.** `@pytest.mark.unit` (the default — tests with no marker are
  treated as unit).
- **Coverage.** Expected to carry the bulk of line / branch coverage for
  pure-logic modules.

### Layer 2 — Integration (`tests/integration/`)

- **Scope.** Seam between the library and Pandoc: subprocess wrapper,
  stderr parsing, exception propagation, resource-path construction,
  real file I/O on `tmp_path`. Tests that exercise the public API
  end-to-end but stop short of producing a bound artifact.
- **May use.** Pandoc binary (guarded by `@pytest.mark.requires_pandoc`),
  real subprocess calls, `tmp_path`-rooted file layouts, small
  markdown/YAML fixtures.
- **May NOT use.** LaTeX / `xelatex` / `pdflatex`. Integration tests must
  avoid the LaTeX toolchain; use `--to=html`, `--to=plain`, or
  `--to=markdown` where a produced format is needed.
- **Budget.** Each test < 2 s. Whole layer < 30 s combined.
- **Count.** 20–30 % of the suite.
- **Marker.** `@pytest.mark.integration` plus external-tool guards
  (`requires_pandoc`).

### Layer 3 — E2E (`tests/e2e/`)

- **Scope.** Full public-API → Pandoc → LaTeX → PDF on disk. Asset
  embedding verified with `pdfimages`. Text content verified with
  `pdftotext`. Realistic fixtures only — resembling
  [`der-selbststaendige-sklave`][dsk]: chapter ordering via
  `export-settings.yaml`, front/back-matter, cover assets, multilingual
  content.
- **May use.** Anything; this is the layer that proves the product works.
- **Budget.** Each test < 15 s. Whole layer < 90 s combined.
- **Count.** 5–10 % of the suite. **Quality over quantity.** Every E2E
  test must cover a user-visible scenario that lower layers cannot.
- **Marker.** `@pytest.mark.e2e`, `@pytest.mark.requires_pandoc`,
  `@pytest.mark.requires_latex`. Typically also `@pytest.mark.slow` if
  over 5 s.
- **Coverage.** **Not measured.** E2E line coverage is misleading; rely
  on unit + integration. `[tool.coverage.run] omit` will exclude
  `tests/e2e/` from the coverage run.

[dsk]: https://github.com/astrapi69/der-selbststaendige-sklave

### Layer 4 — E2E-wheel (`tests/e2e_wheel/`)

New tier motivated by the v0.7.0 image-embedding bug: the library worked
in-source but broke when installed as a dependency (extraction lost
implicit assumptions). This layer catches "works in source checkout,
broken when consumed" regressions.

- **Scope.** Build the wheel via `poetry build`, install into a fresh
  venv, and exercise it from outside the source tree. Three tests only:

  1. **Fresh-venv PDF build.** Install wheel; invoke the public API
     against a fixture from a cwd outside the repo; assert PDF produced
     and image embedded.
  2. **Package data audit.** Assert that every `importlib.resources`
     asset the library ships (templates, filters, anything declared in
     `pyproject.toml`) is actually present in the installed wheel.
  3. **CLI smoke test.** Invoke a Poetry-script entry point (e.g.
     `export-pdf`) from the wheel's venv; assert exit 0 and PDF
     produced.

- **Budget.** Each test < 60 s (the wheel build + venv install dominates
  the time). Whole layer < 3 min combined.
- **Marker.** `@pytest.mark.e2e_wheel`. **Excluded from the default
  `pytest` run.** Runs only in `make ci-local-full` and in CI on PR /
  main.

#### Isolation contract

Non-negotiable rules for this layer:

1. **Skip with a named-binary reason** when either `poetry` or `python
   -m venv` is unavailable. Use
   `pytest.skip("poetry binary not on PATH — cannot build wheel")`. No
   silent skips; no generic "skipped" reasons.
2. **Each test creates its own fresh, isolated venv under `tmp_path`**
   (via `python -m venv tmp_path / "venv"`; `uv venv` is acceptable if
   `uv` is on PATH and faster, but not required). The wheel is
   `pip install`ed into that venv only.
3. **The developer's active venv is never touched.** No test may invoke
   `pip install`, `poetry install`, or equivalent against the outer
   process's interpreter. If the interpreter running pytest is the only
   one available, skip — do not fall back.
4. **Tear-down happens automatically** because the venv lives under
   `tmp_path`. No explicit cleanup is required, but tests must not
   create processes that outlive the test function (background servers,
   etc.).

#### Helper fixture spec (implementation in Phase 4)

The shared invocation pattern lives at `tests/helpers/wheel_venv.py`.
**Specification only — not implemented yet:**

```python
# tests/helpers/wheel_venv.py
from __future__ import annotations
from pathlib import Path
from typing import Protocol

class WheelVenv(Protocol):
    """Fresh, isolated venv with the manuscripta wheel installed."""
    venv_dir: Path                       # tmp_path/venv
    python: Path                         # venv_dir/bin/python
    def run(self, *args: str,
            cwd: Path | None = None,
            check: bool = True) -> subprocess.CompletedProcess[str]:
        """Run a command inside the venv with its PATH prepended."""
    def run_python(self, *args: str, **kwargs) -> subprocess.CompletedProcess[str]:
        """Run ``venv/bin/python <args>`` (convenience wrapper)."""
    def run_script(self, entry_point: str, *args: str, **kwargs) -> subprocess.CompletedProcess[str]:
        """Run a console-script installed by the wheel (e.g. ``export-pdf``)."""

@pytest.fixture
def wheel_venv(tmp_path, built_wheel) -> WheelVenv:
    """Build (once per session via ``built_wheel``), install into fresh
    venv rooted at ``tmp_path``, yield handle. No cleanup — tmp_path
    autoremoves."""

@pytest.fixture(scope="session")
def built_wheel(tmp_path_factory) -> Path:
    """``poetry build`` once per test session; return wheel path. Skip
    the session's e2e_wheel layer if poetry is unavailable."""
```

This is the contract. Phase 4 implements it; Phase 3 does not touch it.

#### Case study: CLI short-circuit bug caught by this layer

In Phase 4, the first run of `tests/e2e_wheel/test_wheel_install.py::
test_wheel_cli_entry_point_smoke` failed with `ManuscriptaLayoutError`
when invoking `manuscripta-export --help` from a fresh venv whose cwd
was not a valid book project. The bug: `main()` called
`_validate_layout()` before `argparse` could handle `--help` / `-h`,
so every CLI short-circuit flag failed from any non-project cwd — the
exact path a new user takes on first install.

The bug had been live since the v0.8.0 CLI refactor. The unit suite
did not catch it because existing `main()` tests always ran against a
pre-built valid project; the integration layer did not catch it
because it does not invoke the installed console scripts. Only a test
that installs the wheel and runs its entry-points can surface this
class of packaging-boundary bug — which is the reason ADR-0001
introduced this tier.

Fix and pins: commit `5753983` moves `_validate_layout` from `main()`
into `_run_pipeline` (after `argparse.parse_args`) and pins the
contract with two unit tests in
`tests/unit/test_run_export_api.py`:

- `test_main_help_succeeds_outside_valid_project[--help|-h]`
- `test_main_build_fails_outside_valid_project`

Concrete evidence that the layer pays for itself.

---

## 2. Decision tree: which layer for my new test?

Work down the flowchart. First matching answer wins.

```
Does the test need a rendered PDF on disk or a full xelatex build?
├── YES → Does it also need to verify packaging / installed wheel behaviour?
│         ├── YES → tests/e2e_wheel/   @pytest.mark.e2e_wheel
│         └── NO  → tests/e2e/         @pytest.mark.e2e
│
└── NO  → Does it call pandoc (real subprocess, no mock)?
          ├── YES → tests/integration/ @pytest.mark.integration
          │                            + @pytest.mark.requires_pandoc
          │
          └── NO  → Does it write outside tmp_path, touch the network,
                     or depend on any external binary?
                     ├── YES → Stop. Rework to not need those; integration is
                     │         the only layer that may, and only for pandoc.
                     │
                     └── NO  → tests/unit/    (no marker needed)
```

Quick reference:

| Signal                                            | Layer       |
|---------------------------------------------------|-------------|
| Asserts on `pdfimages -list` / `pdftotext` output | e2e         |
| Builds a wheel / installs into a venv             | e2e-wheel   |
| `subprocess.run(["pandoc", ...])`, not mocked     | integration |
| `subprocess.run(...)` but mocked via monkeypatch  | unit        |
| Only touches Python objects, `tmp_path`, captured logs | unit   |
| `requires_latex` marker applies                   | e2e         |
| `requires_pandoc` marker applies, no `requires_latex` | integration |

### 2.1 Worked examples (canonical edge cases)

These three cases recur; make sure new tests land in the right layer.

**(a) Test that mocks `subprocess` entirely → `unit`.**
The test asserts on the argv that *would* have been passed to Pandoc, or on
the library's reaction to a fabricated `CompletedProcess`. No binary is
spawned; no file is produced that only Pandoc could produce.

```python
def test_resource_path_is_absolute(monkeypatch, minimal_book_fixture):
    seen = {}
    def fake(cmd, **kw):
        seen["argv"] = cmd
        class _CP: stdout = ""; stderr = ""
        return _CP()
    monkeypatch.setattr(book_mod.subprocess, "run", fake)
    ...  # → tests/unit/
```

**(b) Test that calls real Pandoc with `--to=plain` or `--to=html` → `integration`.**
Real subprocess, real stderr parsing, real file I/O — but no LaTeX
toolchain. These exercise the library-to-Pandoc seam without paying the
PDF build's 5–15 s cost.

```python
@pytest.mark.integration
@pytest.mark.requires_pandoc
def test_unresolved_image_warning_in_html_build(...):
    # pandoc --to=html  →  parse stderr  →  assert ManuscriptaImageError
    ...  # → tests/integration/
```

**(c) Test that produces a real PDF via `pandoc` + `xelatex` → `e2e`.**
The whole pipeline runs; a `.pdf` is written to disk; assertions use
`pdfimages` or `pdftotext`. This is the only layer where `xelatex` is
allowed.

```python
@pytest.mark.e2e
@pytest.mark.requires_pandoc
@pytest.mark.requires_latex
def test_image_is_embedded(...):
    pdf = _build_pdf(fixture)
    assert_pdf_has_images(pdf, 1)
    ...  # → tests/e2e/
```

---

## 3. Per-module coverage thresholds

Defined in `pyproject.toml` under `[tool.manuscripta.coverage_thresholds]`
(single source of truth). Enforcement is a 30–50 line Python script at
`scripts/check_coverage_thresholds.py` that reads `coverage.json` and
exits non-zero on any violation, printing every offending file with its
actual vs. required coverage. The script is itself unit-tested.

Why not `pytest-cov` alone? `pytest-cov`'s `fail_under` is a single global
floor. Per-path-glob thresholds are not supported without a third-party
plugin; option (b) from Phase 1 keeps us plugin-free and gives a clear
failure report.

### Granularity: per-file enforcement

`coverage.py` reports at **file** granularity (`coverage.json` keys are
source paths like `src/manuscripta/export/book.py`). The threshold
check script enforces thresholds **per file**, not per package. The
table below uses module-path notation (`manuscripta.export.book`) for
readability; the script translates each entry to the matching source
file(s) before comparing.

**Translation rule.** Let `ROOT = src/`. For a threshold entry keyed by
a module path `a.b.c`:

1. Let `P = ROOT + a/b/c` (with dots replaced by path separators).
2. If `P.py` exists, that single file is the target.
3. Else if `P/` is a package directory (contains `__init__.py`), the
   target is the set of `*.py` files **directly inside** `P/` —
   subpackages are resolved by their own entries or, failing that, by
   the global floor.
4. Otherwise, the threshold entry is a configuration error; the script
   exits non-zero with a "no matching source files" message.

Wildcards are not supported in threshold keys. To set a threshold on
a whole subtree, list each leaf module explicitly or rely on the global
floor. This mirrors `coverage.json`'s own granularity and keeps the
check script small.

### Module categories

Thresholds are not uniform. Each module is classified into one of three
categories; the category determines whether the strict Phase 2 target or
a carve-out floor applies.

| Category | Threshold | Description |
|---|---:|---|
| **CORE** | as configured (85–100 %) | Pure logic, deterministic, fully testable without external dependencies. Strict Phase 2 targets apply. |
| **CLI_WRAPPER** | **80 %** | Thin argv-parsing and dispatch layers whose behaviour is mostly "forward args to a core function". Beyond ~80 %, additional coverage is mock theatre; mutation testing on the underlying core catches dispatch bugs more reliably. |
| **NETWORK_INTEGRATION** | **80 %** | Modules that fundamentally exist to talk to external services (TTS APIs, DeepL, LMStudio, git-backed tag generation). Unit coverage is valuable up to the call-site seam; beyond that, integration-layer tests or live-service smoke tests are the right instrument. Every such module carries an inline rationale in the table. |

The 80 % carve-out floor is **not** a license to drift. It is a
recognition that for a well-defined subset of modules, the marginal cost
of unit-test coverage beyond 80 % exceeds the marginal value. Any
proposal to reduce a CORE threshold or re-classify a CORE module as
CLI_WRAPPER / NETWORK_INTEGRATION **requires an ADR** in
`docs/decisions/`. This entry gate is how the carve-out stays honest.

The category primitive itself is established and defended in
[ADR-0003](decisions/0003-coverage-threshold-categories.md) —
"Module categories for coverage threshold differentiation". Consult it
before proposing a fourth category or arguing a specific classification.

### Targets

| Category | Module path | Lines | Rationale |
|---|---|---:|---|
| CORE | `manuscripta.exceptions`                     | 100 % | Tiny surface. No excuse for gaps; picklability, repr, hierarchy are exhaustively testable. |
| CORE | `manuscripta.export.book`                    |  95 % | Critical path — `run_export`, pandoc invocation, strict-images logic, layout validation. |
| CLI_WRAPPER | `manuscripta.export.shortcuts`        |  90 % | Main CLI surface. **Exception to the CLI_WRAPPER 80 % floor** — the v0.7.0 image bug surfaced here, so the strict 90 % target stays. |
| CORE | `manuscripta.project.init`                   |  90 % | Project scaffolding is pure filesystem logic, fully testable. |
| CORE | `manuscripta.project.metadata`               |  90 % | Deterministic YAML/TOML manipulation. |
| CORE | `manuscripta.project.chapters`               |  90 % | File-layout helpers. |
| CORE | `manuscripta.project.reorder`                |  90 % | Chapter-ordering logic. |
| CORE | `manuscripta.project.shortcuts_init`         |  90 % | Thin wrapper around `project.init`, but still local-only. |
| NETWORK_INTEGRATION | `manuscripta.project.tag_message` | 80 % | Interactive git/tag message generation with external CLI calls; value plateaus at seam coverage. |
| CORE | `manuscripta.audiobook.tts.base`             |  85 % | Abstract base class, pure dataclasses. |
| CORE | `manuscripta.audiobook.tts.exceptions`       |  85 % | TTS exception hierarchy. |
| CORE | `manuscripta.audiobook.tts.text_chunking`    |  85 % | Pure text-splitting logic. |
| CORE | `manuscripta.audiobook.tts.retry`            |  85 % | `tenacity`-based retry decorator. |
| NETWORK_INTEGRATION | `manuscripta.audiobook.tts.edge_tts_adapter`           | 80 % | Microsoft Edge TTS HTTP wrapper. |
| NETWORK_INTEGRATION | `manuscripta.audiobook.tts.elevenlabs_adapter`         | 80 % | ElevenLabs SDK wrapper. |
| NETWORK_INTEGRATION | `manuscripta.audiobook.tts.google_cloud_tts_adapter`   | 80 % | Google Cloud TTS SDK wrapper. |
| NETWORK_INTEGRATION | `manuscripta.audiobook.tts.google_translate_adapter`   | 80 % | gTTS HTTP wrapper. |
| NETWORK_INTEGRATION | `manuscripta.audiobook.tts.pyttsx3_adapter`            | 80 % | Local `pyttsx3` engine wrapper; platform-bound. |
| NETWORK_INTEGRATION | `manuscripta.audiobook.generator` | 80 % | Book-to-audio orchestrator; most branches call into an adapter. |
| NETWORK_INTEGRATION | `manuscripta.translation.deepl`   | 80 % | DeepL HTTP client. |
| NETWORK_INTEGRATION | `manuscripta.translation.lmstudio`| 80 % | LMStudio local-API client. |
| CLI_WRAPPER | `manuscripta.translation.shortcuts`     | 80 % | Poetry-script dispatch to `deepl`. |
| CLI_WRAPPER | `manuscripta.translation.shortcuts_lms` | 80 % | Poetry-script dispatch to `lmstudio`. |
| CLI_WRAPPER | `manuscripta.export.shortcuts_comic`    | 80 % | Poetry-script dispatch to `export.comic`. |
| CORE | `manuscripta.config.loader`                  |  90 % | YAML parsing is deterministic. |
| CORE | _all `manuscripta.markdown.*` modules_       |  85 % | Pure string/markdown transforms. |
| CORE | _all `manuscripta.paths.*` modules_          |  85 % | Path rewriting; deterministic. |
| CORE | _everything else, global floor_              |  85 % | Project-wide default. |

Tracked future-work note: **CLI and config do not currently exist as
dedicated modules.** `main()` and `load_export_settings` both live inside
`manuscripta.export.book`. If a future task extracts them to
`manuscripta.cli` and `manuscripta.config`, add corresponding thresholds
(suggested: 90 % each for CORE extraction). Do not conflate "extract a
module" with "write tests" — extraction is its own decision.

### Tracked debt baseline (`baseline-coverage.json`)

Some CORE modules are currently below their threshold (Phase 4 starts
with a 59 % overall baseline). Rather than silently lowering the
targets, the threshold-check script supports a second mode for
**tracked-debt modules**:

1. A committed `baseline-coverage.json` file at the repo root captures
   the per-file coverage value for every module listed under the "debt"
   section (see §12).
2. For debt-tracked modules, the script enforces
   `actual_coverage >= max(baseline, 0)` — **coverage may not regress
   below the frozen baseline**, but is not required to meet the Phase 2
   target yet.
3. Whenever a debt module reaches its configured target, it is removed
   from `baseline-coverage.json` in the same commit. From that point on
   it is enforced at the full target, not the baseline.
4. Whenever a new test pushes a debt module higher, the baseline is
   **ratcheted up** (not left where it was) so the next test round can't
   regress to a previous "tolerated" level.

**Ratchet semantics: zero-buffer.** For a debt-tracked module with a
recorded baseline of `B`, the script passes if and only if
`actual >= B`. Any drop below the baseline — however small — fails the
build. There is no noise allowance. If coverage measurement is unstable
at the 0.1–1 pp level that would justify a buffer, that instability is a
separate problem worth exposing (typically a non-deterministic test or
an uninitialised coverage hook), not one to paper over with a tolerance.
A pure ratchet surfaces the instability; a buffered ratchet hides it.

The script's failure message:

```
FAIL manuscripta/project/init.py:
     actual 55.8 % < baseline 56.0 %
     (tracked debt; target 90 % — see docs/TESTING.md §12)
```

**Baseline timing.** Baselines are captured at the **end** of each
coverage-work session, not at its start, so they reflect the state we
commit to maintain, not the state we inherited. In practice: a session
that raises coverage from 56 % → 72 % records 72 % as the new baseline
in the same commit that lands the tests. The next session's floor is
72 %, and cannot slip.

This is how we avoid a "simplify the threshold, declare victory" trap:
debt stays visible and enforceable; reductions require an ADR; increases
ratchet automatically.

### Coverage-drop merge policy

**No module may fall below 80 % without an ADR in `docs/decisions/`
explaining why.** Drops to threshold but above 80 % require inline
rationale in the threshold table above. The CI gate enforces the
configured threshold; the 80 % wall is a human policy.

### Audit-file convention (adopted verbatim from phylax)

- `docs/audits/current-coverage.md` — the single canonical latest audit.
- `docs/audits/history/YYYY-MM-DD-coverage.md` — archived predecessors.
- On a new audit:
  1. Read the `Audit date:` header from existing `current-coverage.md`.
  2. Move it to `docs/audits/history/YYYY-MM-DD-coverage.md` using that
     date.
  3. Write the new audit to `current-coverage.md`.
- Never overwrite without archiving.
- `make audit-coverage` automates this rotation.

### Audit rotation triggers (WHO and WHEN)

An audit is not a background job; it has explicit triggers, and someone
is responsible each time. Without named triggers the history rots
within a quarter.

| Trigger                                                       | Who                        |
|---------------------------------------------------------------|----------------------------|
| Before cutting any release tag (`git tag vX.Y.Z`)             | Release author             |
| After any change to `[tool.manuscripta.coverage_thresholds]`  | Author of the config change |
| After any ADR in `docs/decisions/` that touches coverage      | ADR author                 |
| Quarterly calendar check (Jan 1, Apr 1, Jul 1, Oct 1)         | Project maintainer         |

The release-author trigger is the load-bearing one: if the release checklist
skips the audit, everything else drifts. `make publish` therefore depends
on `make audit-coverage` so the archive rotates as part of the release
flow and not as an optional follow-up.

CI does not auto-generate audits — running the coverage gate on every PR
would either spam the history directory or require write access to the
repo from CI, neither of which is desirable. CI enforces thresholds;
humans trigger audits.

---

## 4. pytest markers

All registered centrally in `tests/conftest.py` via
`pytest_configure(config)`; none in `pyproject.toml` (keeps the list
close to the skip-wiring logic).

| Marker                          | Meaning                                                  |
|---------------------------------|----------------------------------------------------------|
| `@pytest.mark.unit`             | Pure-logic test. Default; may be omitted.                |
| `@pytest.mark.integration`      | Uses real Pandoc subprocess, no LaTeX.                   |
| `@pytest.mark.e2e`              | Full pandoc + LaTeX → PDF pipeline.                      |
| `@pytest.mark.e2e_wheel`        | Built-wheel + fresh-venv install scenario.               |
| `@pytest.mark.requires_pandoc`  | Skipped if `pandoc` not on `PATH`. Auto-applied.         |
| `@pytest.mark.requires_latex`   | Skipped if `xelatex` not on `PATH`. Auto-applied.        |
| `@pytest.mark.slow`             | Cross-cutting. Any test > 5 s (visual diff, scale, etc.) |

Selection examples:
- `pytest -m unit` — fast local loop.
- `pytest -m "unit or integration"` — everything without LaTeX.
- `pytest -m "not slow"` — everything except long-runners.
- `pytest -m e2e_wheel` — only the install-from-wheel tier.

Skip behaviour: `requires_pandoc` and `requires_latex` are applied
**automatically** by a `pytest_collection_modifyitems` hook when the
corresponding binary is missing. The skip reason names the binary so
failures in CI produce an actionable message instead of a silent pass.

---

## 5. Layer boundary enforcement

Boundary rules are enforced by grep-style **lint tests** under
`tests/unit/test_layer_boundaries.py`, consistent with the existing
`test_no_chdir_lint.py`. They are heuristic guards, not formal proofs —
good enough to catch drift, cheap to maintain.

Current rules:

1. No `import subprocess` in any file under `tests/unit/`.
2. No string `"pandoc"` used as a literal argv under `tests/unit/`
   (mocks of `subprocess.run` are fine; the rule targets real invocations).
3. No writes outside `tmp_path` under `tests/unit/` — best-effort:
   reject `open(..., "w")` / `Path.write_text` / `Path.write_bytes` on
   paths not rooted at a fixture-provided `tmp_path`.

Same pattern applies if new rules are needed (e.g. "no `requests.get`
outside `tests/integration/`"). Add a single lint test per rule; do not
build a plugin.

This is explicitly **not static analysis**. A cleverly constructed test
can evade the grep. That is acceptable; the guards are there to prevent
accidental drift, not adversarial bypass.

---

## 6. Documented test patterns

### 6.1 Module-state reset

`manuscripta.export.book` carries module-level globals
(`BOOK_DIR`, `OUTPUT_DIR`, `METADATA_FILE`, etc.) that are anchored to a
`source_dir` by `_configure_paths(source_dir, resource_paths)`. For
tests, the **standard pattern** is:

```python
from manuscripta.export import book as book_mod

def test_something(tmp_path):
    # Anchor module-level globals to the tmp fixture.
    book_mod._configure_paths(tmp_path)
    ...
```

or, more surgically, patch one global with `monkeypatch.setattr`:

```python
def test_compile_book(monkeypatch, tmp_path):
    monkeypatch.setattr(book_mod, "BOOK_DIR", str(tmp_path / "manuscript"))
    monkeypatch.setattr(book_mod, "OUTPUT_DIR", str(tmp_path / "output"))
    ...
```

**Escape hatch: `importlib.reload(book_mod)`.** Available but
discouraged. If a test needs a full module reset to pass, that is a
smell pointing at inter-test coupling in the module. The correct fix is
to push the stateful surface toward dependency injection (pass
`source_dir` through, not through module globals). File an issue; use
`reload` as a stopgap.

### 6.2 Subprocess fixtures

Integration tests that invoke Pandoc use a small helper:

```python
def pandoc(argv, *, cwd=None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["pandoc", *argv],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
```

Captured stderr is parsed by `manuscripta.export.book._parse_unresolved_images`
(tested in isolation as a unit).

Unit tests that need to assert on argv without running Pandoc use the
`monkeypatch.setattr(book_mod.subprocess, "run", fake_run)` pattern
documented in `tests/unit/test_resource_path.py` (once Phase 3 lands).

### 6.3 Filesystem fixtures

Canonical fixtures live in `tests/conftest.py` and are available to
every layer. Each builds a `tmp_path`-rooted book skeleton:

- `minimal_book_fixture` — single chapter, single image.
- `multi_chapter_fixture` — three chapters, one image each.
- `broken_image_fixture` — markdown references missing image.
- `mixed_image_fixture` — one present, one missing.
- `nested_assets_fixture` — per-chapter asset subdirectories.
- `absolute_path_fixture` — image referenced by absolute path.
- `unicode_fixture` — non-ASCII filenames + content (Greek, German,
  French).

Realistic fixtures for E2E (resembling `der-selbststaendige-sklave`) live
under `tests/fixtures/` as static files, not generated programmatically.

### 6.4 PDF assertion helpers

Lives at `tests/helpers/pdf.py` (moves there in Phase 3 from the current
`tests/conftest.py`):

```python
def assert_pdf_has_images(pdf: Path, expected: int) -> None: ...
def assert_pdf_contains_text(pdf: Path, text: str) -> None: ...
def pdf_text(pdf: Path) -> str: ...
```

All three skip (not fail) when `pdftotext` / `pdfimages` are unavailable.

### 6.5 Skip conventions

Skips must always cite the missing tool in the reason:

```python
if shutil.which("pandoc") is None:
    pytest.skip("pandoc binary not on PATH")
```

Silent or generic skips (`pytest.skip("not supported")`) are forbidden —
they hide regressions in CI environments that should have all tools
installed.

`requires_pandoc` / `requires_latex` do this automatically via the
`pytest_collection_modifyitems` hook; they are the preferred form.

---

## 7. Directory layout (target after Phase 3)

```
tests/
  conftest.py              # shared fixtures, marker registration, auto-skip
  helpers/
    __init__.py
    pdf.py                 # assert_pdf_has_images, etc.
    png.py                 # write_png, _png_bytes
    project.py             # _scaffold, layout builders
  fixtures/
    dsk_like/              # realistic book fixture for e2e
    ...
  unit/
    conftest.py            # unit-local fixtures, if any
    test_exceptions.py
    test_layer_boundaries.py
    test_no_chdir_lint.py
    test_resource_path.py
    ...
  integration/
    conftest.py
    test_pandoc_stderr_parse.py
    test_compile_book_html.py
    ...
  e2e/
    conftest.py
    test_pdf_generation.py
    test_image_embedding.py
    ...
  e2e_wheel/
    conftest.py
    test_wheel_install.py
    test_package_data.py
    test_cli_from_wheel.py
```

Layer-local `conftest.py` files are allowed for narrow fixtures (e.g. a
wheel-builder fixture used only in `e2e_wheel`). Shared fixtures stay in
the top-level `tests/conftest.py`.

---

## 8. Make targets (target after Phase 5)

| Target                   | What it runs                                           | Budget       |
|--------------------------|--------------------------------------------------------|--------------|
| `make test`              | `pytest -m unit`                                       | < 5 s        |
| `make test-integration`  | `pytest -m "unit or integration"`                      | < 35 s       |
| `make test-e2e`          | `pytest -m e2e`                                        | < 90 s       |
| `make test-e2e-wheel`    | `pytest -m e2e_wheel`                                  | < 3 min      |
| `make test-all`          | `pytest -m "unit or integration or e2e"`               | < 2 min      |
| `make test-coverage`     | `pytest -m "unit or integration or e2e" --cov ...` + `scripts/check_coverage_thresholds.py` | < 3 min |
| `make audit-coverage`    | Archive current audit + generate new one               | < 3 min      |
| `make ci-local-fast`     | `lint format-check typecheck test`                     | < 30 s       |
| `make ci-local-full`     | `lint format-check typecheck test-coverage test-e2e-wheel` | < 6 min |

Default `pytest` (no marker filter) collects **unit + integration + e2e**
but **not** `e2e_wheel`. The wheel tier runs only when explicitly
selected or via `ci-local-full`.

---

## 9. CI wiring (target after Phase 5)

- **Push to any branch:** `make ci-local-fast`. Fast feedback, blocks
  merge on failure.
- **PR / push to `main`:** `make ci-local-full`. Full pyramid including
  `e2e_wheel` and coverage threshold enforcement.
- **Caching:** Poetry cache on `~/.cache/pypoetry`, pip cache, and
  Pandoc/TeX-Live apt packages cached by version key.
- **Budget:** CI full run under 5 minutes.

---

## 10. Manual smoke checklist

Before a release (mirrors phylax's manual-smoke pattern, adapted for
a book-production library):

1. Build `der-selbststaendige-sklave` end-to-end against the built wheel.
2. Open the PDF in a viewer and visually inspect:
   - Cover page renders correctly.
   - Chapter headings, TOC, front-matter, back-matter all present and in
     the expected order.
   - At least one image per chapter embeds and renders (not just
     `pdfimages`-listed).
   - Fonts look right, no `missing character` boxes.
3. Build `eternity-book` once it has migrated.
4. Check `export.log` for `[WARNING]` lines from Pandoc; every warning
   must either be expected and documented, or filed as an issue.

Automation does not replace a human reading the PDF before a release.

---

## 11. Cross-references

- Layer-boundary decision rationale and phylax translation: see
  [`docs/decisions/0001-test-pyramid.md`](decisions/0001-test-pyramid.md).
- Repository-wide quality policy and release workflow: see
  `.claude/rules/quality-checks.md`.
- Migration notes for the v0.8.0 image-resolution contract: see
  [`MIGRATION.md`](../MIGRATION.md).

---

## 12. Known limitations / planned follow-ups

Coverage thresholds for CLI and config are currently expressed against
their host modules (manuscripta.export.book, manuscripta.export.shortcuts,
manuscripta.project) because CLI and config logic is not yet extracted
into dedicated modules. Extraction is planned as a separate task once
the test pyramid is fully in place. At that point, dedicated thresholds
for manuscripta.cli (90%) and manuscripta.config (95%) will be added
and the host-module thresholds adjusted accordingly.

**Ordering is non-negotiable: pyramid first, refactor second.** The tests
built now must catch regressions from the future extraction. Do not
interleave the two.

### Coverage debt deferred to future task (post-Phase 6 cleanup)

The modules below are **not** carve-outs. They retain their Phase 2
CORE thresholds. They are explicitly tracked debt, to be closed in a
dedicated follow-up before any v1.0 release. Until closed, the
coverage-check script reports them as tracked-debt and enforces the
ratchet rule (§3) — current coverage may not drop below the baseline in
`baseline-coverage.json`.

| Module | Current | Target | Category |
|---|---:|---:|---|
| `manuscripta.project.init`            | 56 % | 90 % | CORE |
| `manuscripta.project.reorder`         | 68 % | 90 % | CORE |
| `manuscripta.project.chapters`        |  0 % | 90 % | CORE |
| `manuscripta.project.metadata`        |  0 % | 90 % | CORE |
| `manuscripta.project.shortcuts_init`  |  0 % | 90 % | CORE |
| `manuscripta.markdown.unbold_headers` | 52 % | 85 % | CORE |
| `manuscripta.markdown.bullet_points`  | 72 % | 85 % | CORE |
| `manuscripta.markdown.emojis`         | 79 % | 85 % | CORE |
| `manuscripta.markdown.german_quotes`  | 84 % | 85 % | CORE |
| `manuscripta.paths.img_tags`          | 72 % | 85 % | CORE |
| `manuscripta.utils.bulk_extension`    | 72 % | 85 % | CORE |
| `manuscripta.utils.pandoc_batch`      | 80 % | 85 % | CORE |
| `manuscripta.utils.git_cache`         | 74 % | 85 % | CORE |
| `manuscripta.images.generate`         |  0 % | 85 % | CORE |
| `manuscripta.config.loader`           |  0 % | 90 % | CORE |

CI policy on these modules:

- Coverage dropping below the recorded baseline **blocks merge**.
- Coverage rising above the baseline is written back into
  `baseline-coverage.json` in the same commit (the ratchet).
- Once a debt module hits its target, it is **removed** from the debt
  table (here) and from `baseline-coverage.json`, and the script
  enforces the full Phase 2 target from that commit forward.
- No merge may lower a module's recorded baseline. Only the target
  itself may be adjusted, and only via ADR.

### Known environmental test flakiness

Five tests under `tests/unit/tts/` fail **only in full-suite runs** and
pass in isolation. Root cause is test pollution from **two** files
that use plain `setattr(module, name, _LocalAdapter)` to inject a
stub adapter class into `manuscripta.audiobook.tts` without teardown:

- `tests/unit/test_generate_audiobook_use_cases.py:95–109`
- `tests/unit/test_generate_audiobook.py` (line numbers vary)

The plain `setattr` is not unwound after the test, so later tests in
the same Python process observe the stub `_Adapter` in place of the
real adapter (the stub is missing the real `.name` /
`.requires_credentials` / etc. class attributes).

> **Heuristic-detection note.** The original investigation found one
> polluter via `grep _Adapter`. The second one used a different
> identifier (`_FakeAdapter`) and was missed; Phase 4b's mutmut runs
> exposed it because mutmut keeps the same Python process across
> mutants. The class of problem is **`setattr`-based teardown-less
> injection**, not a specific identifier. When triaging similar
> regressions in the future, grep for `setattr(mod` (or
> `setattr(.*\.audiobook`, etc.), not for whatever stub class name
> happened to surface first.

Classification: **all five are environmental**, not regressions in
`manuscripta` source. The library code is healthy; the test files'
teardown is incomplete.

| Test ID | Symptom | Env where reproduces |
|---|---|---|
| `tests/unit/tts/test_elevenlabs_adapter.py::TestElevenLabsInit::test_missing_api_key_raises` | Wrong exception type because stub `_Adapter` replaces `ElevenLabsAdapter` | Full `pytest -m unit` runs only |
| `tests/unit/tts/test_elevenlabs_adapter.py::TestElevenLabsInit::test_valid_api_key` | Same as above | Full `pytest -m unit` runs only |
| `tests/unit/tts/test_factory.py::TestCreateAdapter::test_google_translate_warns` | Factory resolves the stub instead of the real `GoogleTranslateTTSAdapter` | Full `pytest -m unit` runs only |
| `tests/unit/tts/test_pyttsx3_adapter.py::TestPyttsx3Init::test_creation` | `AttributeError: '_Adapter' object has no attribute 'name'` | Full `pytest -m unit` runs only |
| `tests/unit/tts/test_google_translate_adapter.py::TestGoogleTranslateInit::test_deprecation_warning` | Collection error from the same cause | Full `pytest -m unit` runs only |

Fixing **both** `setattr` polluters is a Phase 6 cleanup item (swap
for `monkeypatch.setattr`, which auto-unwinds). Until then:

- **Mutation baseline:** the mutmut runner deselects both polluter
  files via `--deselect=` entries in `[tool.mutmut].pytest_add_cli_args`
  (see `pyproject.toml`). Inline comments there reference this
  subsection. Remove the deselects after the Phase 6 fix.
- **CI:** is unaffected because these tests pass in isolation and
  failing-only-in-full-suite is tolerable while the polluters are
  scoped and understood. If they start failing pre-merge, the Phase 6
  fix is promoted to unblock.

---

## 13. Transition: marker enforcement

During the Phase 3 reorganisation window, and permanently thereafter,
**every collected test must carry exactly one layer marker** from
`{unit, integration, e2e, e2e_wheel}`. Tests without a layer marker are
a policy violation, not a default to `unit`.

Enforcement lives in `tests/conftest.py` as a `pytest_collection_modifyitems`
hook that runs after the auto-skip pass and fails collection if any
item is missing a layer marker:

```python
_LAYER_MARKERS = {"unit", "integration", "e2e", "e2e_wheel"}

def pytest_collection_modifyitems(config, items):
    # ... existing auto-skip logic ...

    offenders = []
    for item in items:
        layers = _LAYER_MARKERS & set(m.name for m in item.iter_markers())
        if len(layers) != 1:
            offenders.append((item.nodeid, sorted(layers)))
    if offenders:
        msg = ["Every test must carry exactly one layer marker "
               f"({sorted(_LAYER_MARKERS)}). Offenders:"]
        for nodeid, layers in offenders:
            msg.append(f"  {nodeid}: markers={layers}")
        raise pytest.UsageError("\n".join(msg))
```

Consequences:

- The default `pytest` invocation **fails loudly** on an unmarked test;
  it does not silently include or silently skip it.
- CI therefore fails loudly on the same condition — no class of test can
  drift out of the pyramid unnoticed.
- During Phase 3 the hook is introduced in the same commit that assigns
  markers to existing tests, so the project never sits in an
  "unenforced" state.

The `requires_pandoc` / `requires_latex` / `slow` markers are orthogonal
(cross-cutting) and do not satisfy the layer requirement.

---

## 14. Mutation testing

Mutation testing is **orthogonal to the test pyramid** — a meta-test
that grades whether unit tests actually assert behaviour or just
exercise code paths. It is not a fifth layer; see ADR-0002
§"Alternatives considered" (rejected: fifth-pyramid-layer).

Tests prove code runs; mutation testing proves tests assert.

Policy is defined in [ADR-0002](decisions/0002-mutation-testing.md);
this section is the consumer-facing how-to.

### 14.1 Scope

Mutation runs over **CORE pure-logic modules only**, and only over
modules that are **not currently tracked as coverage debt** in §12.

The seven modules in scope at the start of Phase 4b:

| Module | Threshold | Why qualifies |
|---|---:|---|
| `src/manuscripta/exceptions.py` | 95 % | tiny surface; trivially testable |
| `src/manuscripta/paths/to_absolute.py` | 85 % | pure path/text transform |
| `src/manuscripta/paths/to_relative.py` | 85 % | pure path/text transform |
| `src/manuscripta/images/convert.py` | 85 % | markdown→HTML transform |
| `src/manuscripta/markdown/normalize_toc.py` | 85 % | pure text transform |
| `src/manuscripta/audiobook/tts/text_chunking.py` | 80 % | pure string-splitting |
| `src/manuscripta/audiobook/tts/retry.py` | 80 % | tenacity decorator |

The thresholds live in `[tool.manuscripta.mutation_thresholds]` in
`pyproject.toml` (single source of truth).

### 14.2 Why not all modules

CLI_WRAPPER and NETWORK_INTEGRATION modules (per ADR-0003) are
out of scope for two reasons:

- Mutation on subprocess-heavy code measures the subprocess wrapper,
  not the module under test. Every mutant fails for the same
  external reason; the signal drowns in noise.
- Mutation on mocked-network code measures the **mocks**, not the
  tests. A mutant that flips `status_code == 200` to `== 201`
  survives because the mock returned what the test configured.
  Adding NETWORK_INTEGRATION modules to mutation scope is
  pre-refuted in ADR-0002 §"Alternatives considered".

The right instrument for those modules is integration / e2e_wheel
testing against real services or replay fixtures.

### 14.3 How to run locally

| Command | What it does | Budget |
|---|---|---|
| `make mutation-fast` | Mutate only modules changed vs `origin/main` | seconds–minutes; the dev loop |
| `make mutation` | Full configured scope, no threshold enforcement | **budget a coffee break** (~10–25 min on the initial 7-module scope); for ad-hoc deep-dives, NOT a routine pre-commit check |
| `make mutation-check` | Full scope + threshold enforcement (CI gate equivalent) | same as `make mutation` plus a few seconds |
| `make mutation-report` | Print human-readable surviving-mutant list (no run) | < 2 s |

The dev loop is `make mutation-fast`. Running the full suite locally
is fine for one-off investigations but not as a pre-commit check; CI
runs the full scope nightly and posts results to the audit file.

### 14.4 Score formula

```
score = killed / (total - skipped - equivalent)
killed = total - survived - timeout - suspicious - skipped - equivalent - no_tests
```

Timeouts, no-tests, and suspicious mutants count **against** the
score (strict reading). Rationale in ADR-0002 §Decision: a timeout
is not an assertion the test made about the mutant's behaviour.

### 14.5 Response protocol for surviving mutants

Every survivor falls into exactly one of four categories. The Phase
4b baseline report and every nightly audit categorise survivors this
way; ad-hoc local triage should follow the same discipline.

**A — Killed by new test.** Preferred outcome. Add a test that
asserts a specific behaviour distinguishing the original from the
mutant. The assertion must trace to a specification, docstring, or
inferable contract — *not* to the code's current literal values.

> **Forbidden (A-class anti-pattern):** writing a test that re-pins
> the mutated literal without explaining *why*. `assert
> wait.multiplier == 2` is a hash check, not a test. The test that
> earns the kill says *why* the multiplier matters: "an exponential
> wait with multiplier 1 collapses to constant backoff and would
> retry too aggressively under the upstream rate limit."

**B — Documented equivalent.** The mutant produces identical
observable behaviour to the original. Annotate inline on the
mutated line:

```python
# mutmut: equivalent — both branches reach `return None` because
# the calling layer always discards the value when self.draft is
# truthy.
```

> **Forbidden (B-class anti-pattern):** marking equivalent without
> a verifiable reason. "mutant is equivalent" is not a comment; it's
> a label. Reviewer rule: if I cannot see the equivalence after
> reading the comment, the comment is insufficient.

Two classes of mutation are declared equivalent by **standing policy**
rather than per-mutant argument — see §14.8. Annotations citing
§14.8.1 (CLI help-text) or ADR-0004 (exception `__str__()` format)
are valid B-category references without a per-line equivalence
argument, because the argument lives in the cited document.

**C — Documented specification gap.** The mutant survives because
the specification itself is silent about the behaviour the mutation
changes. Add to the "Specification gaps surfaced by mutation
testing" subsection of the Phase 4b report (and any future audit)
listing: module, function, mutation, current behaviour, what a
specification would need to say to resolve it. **Do NOT pin current
behaviour as correct** — same rule as Phase 4 Priority 1's handling
of `normalize_toc.replace_extension` (see Phase 6 cleanup list).

> C is the highest-value output of mutation testing and the one most
> often lost when projects just chase scores. Treat it as the
> primary deliverable.

**D — Accepted below-threshold.** Module's mutation score lands
below its configured threshold, and the gap is composed of C-class
mutants. Do NOT lower the threshold silently. Do NOT write theatre
tests to compensate. Report the gap honestly; ratchet the threshold
DOWN temporarily via explicit ADR amendment if needed; track the
spec work as Phase 6 material.

> **Forbidden (D-class anti-pattern):** lowering a threshold without
> ADR amendment. Same rule as ADR-0001 / ADR-0003 for coverage
> thresholds.

### 14.6 Trade-off statement: nightly signal, not a merge gate

Mutation testing is a **quality signal**, not a **merge contract**.
ADR-0001's coverage gate is the merge contract.

Why not gate on mutation:

- Mutation runtime (~10–25 min on the initial 7-module scope) makes
  per-PR enforcement either prohibitive or async-and-too-late.
- A score drop from 88 % to 84 % may mean the test suite weakened OR
  it may mean a refactor extracted a function whose new mutants
  happen to be easier to survive than the inlined originals. The
  first warrants action; the second is noise. Treating both as
  merge-blockers either chills legitimate refactors or trains
  reviewers to bypass the gate.

What "nightly signal" looks like in practice:

- Cron runs `make mutation-check` on the configured scope.
- Result is written to `docs/audits/current-mutation.md` on **every
  successful run**, not only on regression. Previous current-* file
  is rotated to `docs/audits/history/YYYY-MM-DD-mutation.md` first.
- A regression below threshold also files a tracking issue via the
  CI workflow, but the merge isn't blocked. The regression is
  triaged the same way as any other quality signal: investigate,
  decide A/B/C/D, act.

Audit-on-success keeps the "everything is still fine" signal
distinguishable from "the cron broke and nobody noticed". This was
a deliberate design decision; see ADR-0002 §"Why audit on success".

### 14.7 Adding a module to mutation scope

When a debt-tracked module graduates (its line in §12 is removed),
the same commit that updates `baseline-coverage.json` should:

1. Add the module to `[tool.mutmut].paths_to_mutate` in
   `pyproject.toml`.
2. Add a threshold entry to `[tool.manuscripta.mutation_thresholds]`
   following the tier structure: 95 % for tiny exception-style
   modules, 85 % for pure transforms, 80 % for retry / chunking-style
   logic, 75 % default.
3. Update §14.1 above with a row in the in-scope table.
4. Update ADR-0002's "Initial in-scope list" header to "Current
   in-scope list" and add the row.

Do not skip step 4. The ADR documents the decision; if the table
drifts from the active configuration, the rationale becomes harder
to defend.

### 14.8 Standing equivalence policies (B-category shortcuts)

Two classes of mutation are declared equivalent by policy, not by
per-mutant annotation. A Pass 2 response that lands a B-annotation
citing one of these sections does **not** need a fresh equivalence
argument on the line — the policy is the argument.

#### 14.8.1 CLI help-text wording

> **Policy.** CLI help-text wording (argparse `description=`, `help=`,
> `--help` rendering, and status-line print strings) is considered
> incidental and not part of the API contract. Mutations that alter
> help-text literals — including case changes, `XX…XX` wrapping, and
> re-phrasings — without changing parser **behaviour** (defaults,
> choices, required flags, argument count / position) are documented
> as **equivalent**. Mutations that alter parser behaviour remain
> **A-category**.

The distinction is presence vs wording:

- Mutation that removes a `help="…"` kwarg entirely → `--help`
  output loses a line → **A** (observable presence change; a test
  can assert the line is there).
- Mutation that changes `help="Pfad zur TOC-Datei"` to
  `help="XXPfad zur TOC-DateiXX"` → `--help` wording differs but
  parser behaviour is unchanged → **B** per this policy.
- Mutation that changes `default="md"` to `default="MD"` → defaulted
  value differs, observable when the flag is omitted → **A**
  (behaviour change, not wording).

Rationale: CLI help text is consumed by humans reading `--help`,
not by parsers in downstream libraries. Pinning its exact wording
to tests would invite the same invited-dependency problem that
ADR-0004 rules out for exception messages, and would block
legitimate iteration (typo fixes, phrasing improvements,
translations).

Cross-links:

- This is the CLI analogue of [ADR-0004](decisions/0004-exception-strings-not-api.md)
  for exception `__str__()` output. The policies are parallel; the
  ADR carries the long-form reasoning that this footnote doesn't
  re-state.
- Status-line print strings in `if __name__ == "__main__":` /
  `main()` blocks (e.g. `print("🔄 All Markdown files reverted...")`)
  are covered by this section. They are operator-visible
  diagnostics, not API surfaces.

The narrow scope of this policy is deliberate. It covers
**help-text wording** only. It does **not** extend to:

- Logging format (log records may be consumed by log aggregators
  that parse them; not covered by this policy; would require its
  own ADR).
- HTTP response bodies (obvious API surface; out of scope for
  this library anyway).
- File output formats (PDF, EPUB, Markdown — the library's
  product, explicitly contractual).

If we later need a broader "user-facing text is incidental"
principle, it gets a proper ADR. This one-section policy is
intentionally narrow to close the 19 Pass 1 C-category gaps that
motivated it, without over-committing the project to a philosophy.

**Inline annotation format** for §14.8.1 B-category mutants is
shown side-by-side with the §14.8.2 (ADR-0004) format below.

#### 14.8.2 Exception `__str__()` format

Covered in full by [ADR-0004](decisions/0004-exception-strings-not-api.md).
Pass 2 B-annotations on `manuscripta.exceptions` format mutations
cite ADR-0004 directly. This subsection exists to surface the
cross-reference where response-protocol readers will look for it,
and to document the **inline annotation format** for both standing
policies together, because a reader who is about to annotate a
mutant is most often uncertain which of §14.8.1 / ADR-0004 applies.

Annotation format for exception-format mutants (§14.8.2 /
ADR-0004):

```python
# B: ADR-0004 — str() format is diagnostic, not contractual
```

Analogous annotation for CLI help-text mutants (§14.8.1):

```python
# B: TESTING.md §14.8.1 — CLI help-text wording is incidental
```

Both forms obey the same rule: one line, prefix `# B:`, citation
first, one-sentence summary of the policy second. No ad-hoc
rewordings — the grep target is the citation, not the summary.

#### 14.8.3 Trampoline-induced equivalence

> **Policy.** mutmut 3.x rewrites every mutated function into a thin
> wrapper that keeps the **original** signature, resolves the
> signature's default arguments at the wrapper level, and forwards
> the resulting concrete positional/keyword arguments to the
> selected mutant via an internal trampoline. Any mutation whose
> sole effect is to change a **default parameter value in the
> mutated function's own signature** is therefore structurally
> unreachable: the mutant function is invoked with the original's
> defaults, its own defaults are never consulted, and its runtime
> behaviour is identical to the original by construction. Such
> mutations are documented as **equivalent** by policy under this
> subsection.

This is not ordinary equivalence. The §14.8.1 and §14.8.2 / ADR-0004
policies describe **behavioural equivalence**: two distinct code
paths that produce the same observable state, where pinning the
distinction to a test would invite a dependency the project does
not intend to take on. §14.8.3 describes **tool-artifact
equivalence**: the mutation exists in the mutant source file but is
never exercised by the test runner, because the mutation-testing
framework short-circuits it before control reaches the mutated
expression. The distinction matters for audit readers: a B-annotation
under §14.8.3 says "the tool cannot reach this line", not "the
project has decided this line is not contractual". We preserve the
distinction with a separate citation tag so the two populations can
be counted and trended independently.

Worked example. [src/manuscripta/audiobook/tts/retry.py](../src/manuscripta/audiobook/tts/retry.py)
declares `with_retry(max_attempts=3, min_wait=1.0, max_wait=8.0)`.
mutmut generates three mutants — one per default — each changing a
single default to a different numeric constant. The corresponding
entry in `mutants/src/.../retry.py` rewrites the wrapper as:

```python
def with_retry(max_attempts: int = 3, min_wait: float = 1.0, max_wait: float = 8.0):
    args = [max_attempts, min_wait, max_wait]
    kwargs = {}
    return _mutmut_trampoline(x_with_retry__mutmut_orig,
                              x_with_retry__mutmut_mutants,
                              args, kwargs, None)
```

A test that calls `with_retry()` with no arguments binds the
**wrapper's** defaults (3, 1.0, 8.0) into `args`, then the
trampoline calls the selected mutant as
`x_with_retry__mutmut_N(3, 1.0, 8.0)`. The mutant's own default
annotation — e.g. `max_attempts: int = 4` in mutant 1 — is never
consulted. All three mutants are §14.8.3-equivalent.

Mutations that qualify under §14.8.3:

- Default value changes in the signature of a module-level or
  free-function mutation target, where the default is a literal
  constant (`int`, `float`, `str`, `bool`, `None`, tuple of same).

Mutations that do **not** qualify (still A- or B-category under
other policies):

- Mutations inside the function body that change how a bound
  argument is used (e.g. `max_attempts - 1` → `max_attempts + 1`).
  These run in the mutant; they are reachable and must be tested.
- Default value changes on class attributes, `__init__` parameters,
  or `dataclass` field defaults. mutmut handles method and
  dataclass mutations through different instrumentation paths; the
  trampoline argument-forwarding described above does not apply
  uniformly, and each case needs its own reachability analysis
  before a §14.8.3 citation is valid.
- Default value changes where the default is a mutable call
  expression (`list()`, `dict()`, `field(default_factory=…)`). These
  are evaluated per-call and the mutmut trampoline does not
  short-circuit the evaluation; they remain A-category.

Annotation format for §14.8.3 mutants:

```python
# B: TESTING.md §14.8.3 — trampoline forwards defaults; mutation unreachable
```

Same rules as §14.8.1 / §14.8.2: one line, `# B:` prefix, citation
first, summary second. The citation string is the grep target.

**Score-formula treatment.** §14.8.3-annotated mutants count as
equivalents in the score denominator, identical to §14.8.1 and
§14.8.2 B-annotations. They are reported under a separate tag in
audit output so the trampoline-equivalent population can be tracked
independently — useful for the version-pin review described below.
The full formula treatment lives in ADR-0002's score-formula section.

**Zero-denominator case.** A module whose entire mutant population
is §14.8.3-equivalent has an undefined mutation score
(`0 / (N − N) = 0 / 0`). This is **not** a threshold failure; it is
a signal that the module has insufficient testable mutation surface
for the tool to produce a meaningful measurement. The response is
documented in ADR-0002: such modules are removed from
`tool.mutmut.paths_to_mutate` and recorded as scope exclusions with
a `# reason: §14.8.3 — insufficient mutable surface` comment beside
their prior entry, pending either (i) the module growing additional
testable surface or (ii) a future mutmut release whose trampoline
semantics expose default-argument mutations.

**Version-pin dependency.** This policy is a statement about
mutmut's internal wrapper generation, not about Python semantics.
The trampoline shape was introduced in mutmut 3.x and may change in
future releases. mutmut is pinned in [pyproject.toml](../pyproject.toml)
under `[tool.poetry.group.mutation.dependencies]`; bumping the
pinned version requires re-reading this subsection and running a
one-off audit to confirm that default-argument mutations remain
structurally unreachable on the new version. If they do not, every
§14.8.3 annotation becomes unsound and must be re-categorised in
the same commit that bumps the pin.

This policy was added in response to a diagnostic finding during
Phase 4b Pass 2 Commit 3: all three `retry.py` surviving mutants,
which the Pass 1 report had categorised as A (killable by
behavioural test), were found to be structurally unreachable under
mutmut 3.5. The Pass 1 misclassification is the reason this
subsection exists and is the canonical example of the policy.
