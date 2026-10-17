# Scope-links (2026-10-17): links_to_plain and strip_links enter the mutation scope

Follow-up to round 3 (`2026-10-16-round-3-fixes-and-full-scope.md`), which left two modules
"eligible and not yet measured": `markdown/links_to_plain.py` (92 % coverage) and
`markdown/strip_links.py` (94 %). Both are CORE pure text transforms (ADR-0002's exclusion table
carried them with "add after a measured score and a survivor triage"). This round measures them,
triages every survivor per TESTING.md §14.5 and enters both at the 85 % tier. The scope is
twenty-one modules; no eligible module is left outside it.

## Mutation: the last two eligible modules enter

| Module | On entry (killed / survived / total) | After triage (killed / survived / equivalent / total) | Score | A | B | C | Threshold |
|---|---|---|---:|---:|---:|---:|---:|
| `markdown/links_to_plain.py` | 93 / 26 / 119 (78.2 %) | 111 / 1 / 13 / 125 | 99.1 % | 12 (+2) | 13 | 1 | 85 % |
| `markdown/strip_links.py` | 144 / 61 / 205 (70.2 %) | 186 / 0 / 27 / 213 | 100 % | 34 (+1) | 27 | 0 | 85 % |

The totals grew with the rows (119 → 125, 205 → 213): mutmut mutates covered lines only
(§14.10), and the new rows reach lines no test ran before — the counting branch and the
missing-file report of `convert_many`, the body of `_rep_ref` (no test had a reference link),
the no-links branch of `main`. The "+2" and "+1" are survivors among those new mutants, killed by
a further row each (two changed files add up to `(2, 3)`; two reference links both count). The
B-annotations were written against the tree regenerated after the A rows landed, in the §14.10
order.

**A rows, `links_to_plain`** (`tests/unit/test_convert_links_to_plain_text{,_extra}.py`): three
inline code spans each restored to their own text (the uniqueness-breaking `idx = 1`, the
§14.8.5 negative example); a space inside an angle-bracketed destination, a title behind one,
and a bare destination ending in `>` (the two `and`/`or` flips and the three bracket literals of
`_clean_target`); `convert_file` reading and writing UTF-8 under `LC_ALL=C` (the `encoding=None`
and dropped siblings); `(False, 0)` for an unchanged file; the status line naming the file. The
two ad-hoc tests of the base file became the tables `CONVERT_FILE_CASES` and `CONVERT_MANY_CASES`.

**A rows, `strip_links`** (`tests/unit/test_strip_links_{text,io,cli}.py`): an inline code span
starting exactly where a fence ends (the fence match swallows the line break, so `<` vs `<=` on
the overlap test is observable); the count across prose segments between code spans; reference
links `[text][id]` and `[text][]`, their definition lines removed, each counted, and the single
blank line a removed definition leaves; `process_file` and `main` reading and writing UTF-8
under `LC_ALL=C` with and without `--overwrite` (the `--encoding` default, the `encoding=None`
and dropped siblings in both branches); `manuscript/front-matter/toc.md` processed without
`--file`; the no-links run writing nothing; help PRESENCE for the six options and the
description paragraph (wording not asserted, §14.8.1).

**B clusters** (`.mutmut/equivalent.yaml`, two sections dated 2026-10-17): `links_to_plain` —
nine §14.8.5 opaque-token renamings of `_protect_segments` (the same encoder/decoder pair as
`to_absolute`, same nine mutants), two `split` maxsplit variants whose first element is the same,
two codec aliases. `strip_links` — twenty-two §14.8.1 wordings (parser description, six `help=`
strings, the dry-run status line), two §14.8.3 trampoline defaults of `process_file` (Σ = 2 for
one target, the wrapper binds `args = [src, overwrite, suffix, encoding]`), two §14.8.4 empty
slices of `strip_links_in_text` with their downstream trace
(`strip_links_in_text_no_code("") == ("", 0)`), one codec alias on the `--encoding` default.

## Specification gaps surfaced by mutation testing (C)

**`markdown/links_to_plain.py`, `_clean_target` (1 mutant).** Mutation: `t.split(" ", 1)` →
`t.split(None, 1)`. Current behaviour: the destination ends at the first space; a tab before
that space stays part of the destination (`[X](https://a.test\t "T")` → `X: https://a.test\t`),
and a title separated by a tab alone is not dropped at all (`[X](https://a.test\t"T")` →
`X: https://a.test\t"T"`, no space found). What a specification would need to say: what
separates a destination from its title — a single space, or any run of spaces and tabs as
CommonMark reads it. The second answer makes the mutant the intended behaviour and the tab-only
case a bug; neither is pinned.

## Source seams noticed, not changed

- `links_to_plain.MD_LINK_RE`: an angle-bracketed destination followed by a title falls back to
  the bare alternative and works only because the title split runs first; with parentheses in
  the URL it breaks: `[X](<https://host/a(b)> "T")` → `X: <https://host/a(b> "T")`.
- `links_to_plain.convert_many`: driven by the module-level `FILE_PATHS` list and the
  `__main__` block, no argparse; the status lines are its only report.
- `strip_links.strip_links_in_text_no_code`: the `\n{3,}` normalization applies to every prose
  segment, not only to the blank lines a removed definition leaves (`x\n\n\n\ny` → `x\n\ny`
  with no link in sight); the docstring says "that might result from removing definitions".
- `help_output` / `option_help_text` now live in a fourth test file (`test_strip_links_cli.py`),
  `c_locale` in an eighth; `tests/helpers/cli.py` would dedupe them (round-3 seam, grown).
- `tests/unit/test_pandoc_batch_cmd_and_paths.py::test_build_cmd_joins_resource_paths
  [windows-semicolon]` patches `os.name`. When a `pandoc_batch` mutant fails the row, pytest
  formats the failure report before teardown, `Path(os.getcwd())` in `_repr_failure_py` raises
  `NotImplementedError: cannot instantiate 'WindowsPath'`, and the session ends as INTERNALERROR
  (exit 3). The kill is legitimate — the assertion failed first — and the per-session basetemp is
  still removed in `pytest_unconfigure`, but the traceback lands in the mutmut log between 3 and
  33 times per run depending on which covering test fails first (mutmut sorts a mutant's tests by
  measured duration). `build_cmd` could use `os.pathsep` (`;` on Windows, `:` elsewhere) and the
  row would patch that instead of `os.name`.

## Tooling

- Three full gates on this branch: 5714 mutants on entry, 5728 after the rows, about five
  minutes each; `/tmp/pytest-of-<user>` stayed at four entries, so the per-child basetemp was in
  effect and the kills are assertions. Every other module reads exactly as in the nightlies of
  2026-10-16 and 2026-10-17.
- `poetry run` from inside `mutants/` resolves the copied `pyproject.toml` of the test book and
  creates a stray virtualenv (`test-book-…`); to replay a single mutant by hand, run the
  project's interpreter path with `MUTANT_UNDER_TEST=<id>` from `mutants/`.
