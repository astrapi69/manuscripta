## Phase 4b Pass 2 — Commit 10 blocked

Date: 2026-08-14  \
Branch/worktree: `phase-4b/pass-2-resume`

### Status

Deferred Commit 10 for `src/manuscripta/paths/to_absolute.py` remains **blocked**. The required per-mutant triage map (A-test targets and B-annotation buckets) is not present in the repository. Implementing tests or B annotations without that map would violate the response protocol and corrupt the audit trail.

### Planned scope (unchanged)

- ~50 A-tests, including 25 timeout kills
- ~18 B annotations across buckets: 9× §14.8.5 token-renaming, 2–4 early-return-converges, 1 §14.8.1 print-None, 2 codec-alias, 1 falsiness

### Preflight evidence completed

- Full mutation rebuild: `poetry run mutmut run`
- Survivors recorded: `.local/mutation-results-full.txt`
- Targeted `to_absolute` tests pass:
  ```bash
  poetry run pytest -q \
    tests/unit/test_convert_to_absolute.py \
    tests/unit/test_convert_to_absolute_extra.py \
    tests/unit/test_convert_to_absolute_fuzz.py
  ```
- Current `to_absolute` survivors/timeouts align with the paused audit’s function set (e.g., `_protect_segments`, `_find_image_tag`, `_split_inside_parens`, `_convert_images_in_text`, `convert_file_to_absolute`, `convert_to_absolute`).

### Evidence missing

- No authoritative per-mutant triage map located despite searches across `docs/` and git history for Commit 10, bucket names (`§14.8.5`, token-renaming, early-return-converges, print-None, codec-alias, falsiness), and `to_absolute` symbols.

### Decision

- Do **not** land Commit 10 until the triage map is recovered or formally reconstructed and approved.

### Follow-up

- Open a reconstruction task: "Reconstruct Phase 4b Commit 10 to_absolute triage map" with a per-mutant table (ID, function, status, expected kill/timeout behavior, planned A-test, B bucket, evidence, confidence). Commit 10 may proceed only after that table is approved.
