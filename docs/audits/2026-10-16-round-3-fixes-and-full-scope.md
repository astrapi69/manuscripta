# Round 3 (2026-10-16): the open findings fixed, every CORE module in the mutation scope

Follow-up to round 2 (`2026-10-16-round-2-scope-extension.md`). Three strands: the open issues
#28, #29 and #31 fixed with their pinned rows flipped; `unbold_headers` and `reorder` lifted from
the 75 % default tier to the 85 % pure-transform tier; the five modules that left the debt table
in round 2 measured and triaged into the scope.

## Fixes (#28, #29, #31)

| Issue | Module | Change | Rows |
|---|---|---|---|
| #28 | `paths/img_tags.py` | `--base-dir` defaults to the current working directory (it was `src/manuscripta/`); help says so | MAIN_RUNS gains a `project` column and the row `base-dir-defaults-to-the-working-directory`; the three C-class survivors on the default are killed, img_tags 100 % |
| #29 | `scripts/check_mutation_thresholds.py`, Makefile | `mutmut results` prints `name: not checked` with a space and the name pattern demanded `\w+` for the status, so unchecked mutants were invisible to the stale-state guard and counted as killed. Unchecked statuses form their own bucket, count as not killed, show in an `unchk` column and fail the check (exit 1) naming modules and counts; `--allow-stale-state` is gone. `make mutation-fast` maps files to `manuscripta.a.b.*` globs and warns that a filtered run resets the other modules | SCORE_CASES gains a `not_checked` column and two rows; new tables RESULT_LINES (6) and GUARD_RUNS (4) |
| #31.1 | `project/chapters.py` | `_ensure_valid_pattern` formats the pattern with `num=1` and `num=2`; anything that fails or ignores the placeholder exits 2 with a clear message; the dead `except` around `int()` is gone | REJECTED_PATTERNS (6 rows × with/without `--start`), MAIN_RUNS row `pattern-with-a-foreign-field-exits-2` |
| #31.2 | `markdown/emojis.py` | one import attempt in `_load_default_map`, stale comment removed | existing fallback test |
| #31.3 | `markdown/bullet_points.py` | thematic breaks (`***`, `* * *`, `---`, `___`) left verbatim and end the list; a missing path exits 1 | BULLET_CASES +5, PROCESS_PATHS gains `found`, MAIN_RUNS gains stderr and the row `missing-path-is-reported-and-exits-1` |
| #31.4 | `config/loader.py` | a non-mapping top level raises `ValueError` naming the file; an empty document stays `{}` | NON_MAPPING_DOCUMENTS (4 rows) |
| #31.5 | `utils/pandoc_batch.py` | `--resource-path` on the command line replaces the configured list | row `cli-resource-paths-replace-the-table-list`; pandoc_batch stays at 98.4 % |

## Mutation: the 75 % tier is gone

| Module | On entry | After triage (killed / survived / equivalent) | Score | A | B | C | Threshold |
|---|---:|---|---:|---:|---:|---:|---:|
| `markdown/unbold_headers.py` | 79.7 % | 264 / 0 / 32 | 100 % | 28 | 32 | 0 | 75 → 85 % |
| `project/reorder.py` | 79.2 % | 395 / 5 / 47 | 98.8 % | 41 | 47 | 5 | 75 → 85 % |

## Mutation: the round-2 graduates enter

| Module | On entry (killed / survived) | After triage (killed / survived / equivalent) | Score | A | B | Threshold |
|---|---|---|---:|---:|---:|---:|
| `project/chapters.py` | 163 / 42 (79.5 %) | 181 / 0 / 24 | 100 % | existing-directory runs, pattern rejected at detection, option presence | 24 | 85 % |
| `markdown/bullet_points.py` | 95 / 19 (83.3 %) | 102 / 0 / 12 | 100 % | indented first line, break ending a list, blank lines, C-locale encoding | 12 | 85 % |
| `markdown/emojis.py` | 208 / 92 (69.3 %) | 259 / 0 / 41 | 100 % | longest key wins, exact reject messages, multi-file CLI runs, default manuscript dir | 41 | 85 % |
| `config/loader.py` | 15 / 3 (83.3 %) | 17 / 0 / 1 | 100 % | UTF-8 under LC_ALL=C | 1 | 85 % |
| `utils/git_cache.py` | 65 / 7 (90.3 %) | 67 / 0 / 5 | 100 % | stdout pinned line by line | 5 | 85 % |

`git_cache` enters although 15 of its 72 mutants sit on the stubbed `subprocess.run` call (§14.2
noise, well under half): the command assembly, output forwarding, error path and exit code are
real logic. No C-class survivor among the five.

The scope is nineteen modules, about 5400 mutants; every CORE module of the package is in it.
Not in scope by category (ADR-0002 §14.2): `tag_message`, `generator`, `deepl`, `lmstudio`,
`edge_tts_adapter`, `images/generate`, the shortcut wrappers, `export/book` and friends.
Eligible and not yet measured: `markdown/links_to_plain`, `markdown/strip_links`.

## Specification gaps surfaced by mutation testing (C)

**`project/reorder.py`, `load_mapping_file` (2 mutants).** Mutation: `open(newline="")` for
the CSV mapping → `None` / dropped. Current behaviour: a line break inside a quoted field
survives verbatim. What a specification would need to say: whether a mapping entry may contain
a line break at all.

**`project/reorder.py`, `autodetect_lang_by_header` (1 mutant).** Mutation: `splitlines()[:5]`
→ `[:6]`. Current behaviour: the H1 is looked for in the first five lines. What a specification
would need to say: how far down the H1 may sit.

**`project/reorder.py`, `update_header_and_anchor` (2 mutants).** Mutation: `count=1` on the
anchor-only substitution → dropped / `2`. Current behaviour: only the first `{#-chapter-N}` on
the H1 is renumbered. What a specification would need to say: all, the first, or rejection when
there is more than one.

The round-2 gaps (init template prose and logging format, pandoc_batch job count, log tail and
stubbed subprocess keyword arguments) stand as listed there.

## Source seams noticed, not changed

- `reorder._repl_h1`: `re.sub(r"\s*\{#-chapter-\d+\}\s*$", "", rest or "").rstrip()` is dead
  (five B annotations vanish if it goes).
- `emojis.iter_md_files`: the `.md.bak` filter is dead, `glob("*.md")` never yields it; the two
  asserts after the spec guard in `load_mapping_from_module` are redundant.
- `chapters`: `{num!r}` passes `_ensure_valid_pattern` and is rejected at detection, after
  `mkdir` ran in a non-dry run.
- `tests/test_create_chapters.py` sits outside `tests/unit`, so its cases contribute nothing to
  mutation (mutmut's `tests_dir`); the round-3 rows under `tests/unit` cover them.
- `help_output` / `option_help_text` are duplicated in three test files; a `tests/helpers/cli.py`
  would dedupe them.

## Annotations that stopped being equivalent

The full gate after this round reported twelve to_absolute annotations as orphans: the mutants
(`_protect_segments` 10, 17, 22, 23; `_find_image_tag` 28, 29, 32, 40, 47, 66, 105;
`_convert_images_in_text` 4), judged equivalent under §14.8.4 and §14.8.5 against the
to_absolute tests, are killed once the round-3 unit tests drive the scanner through other callers
(the img_tags default base-dir runs among them). The entries are removed, the traces stay as
history; to_absolute reads 302 killed / 0 survived / 11 equivalent, 100 %.

## Tooling

- `python -m mutmut run` breaks on mutmut 3.5.0 (the trampoline re-imports `__main__`); the
  console script works. The threshold script's own `mutmut results` call via `-m` is unaffected.
- A filtered `mutmut run` resets every other in-scope module; the threshold script now fails on
  that state instead of reporting 100 % (#29).
