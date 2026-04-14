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
