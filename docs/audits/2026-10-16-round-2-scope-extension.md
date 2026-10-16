# Round 2 (2026-10-16): the debt table empties, three more modules enter the mutation scope

Follow-up to #26 (line coverage 70 % → 94 %) and #30 (five debt graduates entered the
mutation scope). This round closes the last five entries of the TESTING.md §12 debt table and
triages the three graduates that measured below their tier on entry.

## Coverage: the last five debt modules

| Module | Before | After | Target | What the new rows assert |
|---|---:|---:|---:|---|
| `project/chapters.py` | 76 % | 98 % | 90 % | pattern detection, next start number, cwd fallback, parser values and rejects, exit status and files of `create-chapters`, `__main__` guard |
| `markdown/bullet_points.py` | 72 % | 100 % | 85 % | bullet and hard-break cases, files after processing, stdout/stderr, main runs |
| `markdown/emojis.py` | 79 % | 99 % | 85 % | mapping modules and rejects, mapping verdicts, default map is a copy, bundled table without `--map` |
| `utils/git_cache.py` | 74 % | 100 % | 85 % | the exact `git reflog` / `git gc` commands and their cwd, output forwarding, failure exit codes |
| `config/loader.py` | 0 % | 100 % | 90 % | YAML documents, the export and voice loaders, defaults below cwd, `!!python` tags rejected |

Left uncovered on purpose: `chapters.py` 74-75 (a `KeyError`/`ValueError` guard around
`int()` of a `\d+` match, dead) and `emojis.py` 26 (a second, identical import attempt that
cannot succeed after the first failed). `baseline-coverage.json` is empty from this round on.

## Mutation: survivor triage of init, metadata and pandoc_batch

Entered in #30's exclusion table with their measured scores; triaged per TESTING.md §14.5.

| Module | On entry (killed / survived / total) | After triage (killed / survived / equivalent) | Score | A | B | C | Threshold |
|---|---|---|---:|---:|---:|---:|---:|
| `project/init.py` | 516 / 273 / 789 (65.4 %) | 711 / 57 / 32 | 92.6 % | 191 | 32 | 57 | 85 % |
| `project/metadata.py` | 110 / 56 / 166 (66.3 %) | 161 / 0 / 5 | 100.0 % | 51 | 5 | 0 | 85 % |
| `utils/pandoc_batch.py` | 413 / 212 / 625 (66.1 %) | 548 / 9 / 68 | 98.4 % | 135 | 68 | 9 | 85 % |

A-rows assert what the mutant changed: the exact logged line, the file written and its content,
the settings dict resolved, the option parsed and its table fallback, the recorded pandoc
command, the resource-path separator per platform, the UTF-8 contract under `LC_ALL=C`, and the
presence (never the wording) of help text. B-annotations live in `.mutmut/equivalent.yaml` under
the two sections dated 2026-10-16, each with its §14.8 policy or an inline rationale; the four
§14.8.3 trampoline cases of `run_init_book_project` exceeded the stop-rule and the wrapper was
read and quoted.

## Specification gaps surfaced by mutation testing (C)

Per §14.5 these survivors count against the score and are not annotated. Each needs a decision,
not a test.

**`project/init.py`, `write_image_prompt_generation_template` (56 mutants).**
Mutation: wording and identifiers of the generated template (project name, description, author,
language placeholders; `source_format`, `output_formats`, `engine`, `style`, the four task names
and descriptions, notes; JSON indent 2 → 3).
Current behaviour: the template carries fixed placeholder text that no consumer reads back.
What a specification would need to say: whether the placeholders are filled from the run's
arguments (then the existing metadata assertions pin them), whether the format lists are drawn
from a canonical list in the export package, and whether placeholder prose in generated files
falls under §14.8.1 (which today excludes file output). An ADR extending §14.8.1 to generated
template prose would move 46 of these to B.

**`project/init.py`, `main` (1 mutant).** Mutation: the `format=` argument of
`logging.basicConfig` dropped. Current behaviour: lines carry the level tag; without the
argument logging's default format applies. What a specification would need to say: the operator
log format, which §14.8.1 reserves for its own ADR.

**`utils/pandoc_batch.py`, `parse_args` (1 mutant).** Mutation: `os.cpu_count() or 4` →
`or 5`. Current behaviour: four jobs when the CPU count is unknown. What a specification would
need to say: the job count in that case.

**`utils/pandoc_batch.py`, `run_one` (2 mutants).** Mutation: the stdout/stderr tail kept in the
log, 1000 / 2000 characters → ±1. Current behaviour: those lengths. What a specification would
need to say: how much output the log keeps.

**`utils/pandoc_batch.py`, `run_one` (6 mutants).** Mutation: `subprocess.run(capture_output=,
text=)` → None / False / dropped. Current behaviour: only the stubbed call sees the keyword
arguments (§14.2 wrapper noise). What would make them observable: a fake `pandoc` executable on
PATH in the integration layer, or an injectable runner whose captured and decoded output a unit
test can observe.

**`paths/img_tags.py`, `main` (3 mutants, from #30).** Mutation: the `--base-dir` default.
Current behaviour: `Path(__file__).resolve().parent.parent` is `src/manuscripta/`, the help says
repository root. Tracked as #28; a fix makes the three killable with one row.

## Findings that need a source change (not pinned by tests)

- `project/chapters.py`: `_ensure_valid_pattern` only checks for `{num`, so
  `--name-pattern {number}.md --start 1` dies with a `KeyError` traceback from `str.format`
  instead of exit 2; lines 74-75 are dead code.
- `markdown/emojis.py`: `_load_default_map` retries the same import (the "sibling import"
  comment is stale); line 26 is unreachable.
- `markdown/bullet_points.py`: `main()` exits 0 when the path is missing (only an `[ERROR]` on
  stderr); a `* * *` horizontal rule matches the bullet regex and becomes `• * *`.
- `config/loader.py`: `load_yaml` returns whatever the top-level node is (a list or a string for
  a non-mapping document) despite its `dict` signature.
- `utils/pandoc_batch.py`: with a `resource_path` list in `[tool.pandoc_batch]`, argparse's
  `append` extends the configured list with the CLI values instead of replacing it.

## Tooling findings

- `python -m mutmut run` fails deterministically at the stats phase with mutmut 3.5.0: the
  trampoline's `from mutmut.__main__ import record_trampoline_hit` re-executes the module (loaded
  as `__main__` under `-m`) inside the forked test process, and its module-level
  `set_start_method('fork')` raises "context has already been set". The console script
  `mutmut run` (what `poetry run mutmut` resolves to) works; `python -m mutmut results` is
  unaffected.
- A filtered `mutmut run 'manuscripta.project.init.*'` (fnmatch glob; a bare prefix matches
  nothing) resets every in-scope module's results before filtering and re-tests only the matched
  mutants; `scripts/check_mutation_thresholds.py` then counts the never-checked mutants as killed.
  Tracked as #29.
- Agent worktrees under the session scratchpad vanished with an editor crash; long-running
  work now lives under `~/dev/git/worktrees/` with WIP commits on its branch.

## Nightly expectations

Fourteen modules, about 4700 mutants. The badge in the README shows the global score the nightly
computes from the threshold table (killed / (total − equivalent) over all in-scope modules).
