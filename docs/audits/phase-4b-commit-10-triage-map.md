# Phase 4b Commit 10 — `to_absolute.py` per-mutant triage map (reconstruction)

Date: 2026-08-14
Reconstructed from: fresh `poetry run mutmut run` at `d649089` (this
working tree), per-mutant diffs via `mutmut show <id>`. The non-dead
set (68 mutants: 43 survived + 25 timeout) matches the nightly audit
`docs/audits/current-mutation.md` @ run #123 and the function-set
recorded in `phase-4b-commit-10-blocked.md` §Preflight.

Replaces the unrecovered pre-pause map. Buckets land exactly on the
pause-doc estimate (~50 A / ~18 B): **47 A / 20 B / 1 C**.

Baseline: total=305 killed=237 survived=43 timeout=25 eq=0 → 77.7 %.
Post-response projection: eq=20, denom=285, survivors=1 (C) →
killed=284/285 = **99.6 %** (threshold 85 %).

Status legend: `s` = survived, `t` = timeout. Confidence: **H** =
mutant diff implies the behaviour directly; **M** = analytic argument
with one precondition — verified empirically before annotation lands
(B-candidates get a kill-attempt first; a kill demotes them to A).

## Summary by bucket

| Bucket | Count | Mutant IDs (function abbreviated) |
|---|---:|---|
| A — behavioural test | 22 | PS_8, IUL_1, FIT_22/24/25/27/29/53/66/71/83/90, SIP_3/8/29/30/50, SAB_4, CIT_24, CFA_2/12/14 |
| A — timeout kill via `pytest-timeout(5)` | 25 | FIT_1/6/8/12/13/16/18/52/60/61/69/70/88/92/93/95, SIP_34/35/46/69/70/74, CIT_11/28/37 |
| B — §14.8.5 opaque-token renaming | 9 | PS_3/9/10/17/22/23/26/31/32 |
| B — §14.8.1 print-None | 1 | CTA_18 |
| B — ad-hoc codec-alias | 2 | CFA_4/16 |
| B — ad-hoc early-return-converges | 5 | FIT_28/97, SIP_55/60/77 |
| B — ad-hoc None-falsiness | 3 | FIT_39/58, CIT_4 |
| C — specification gap | 1 | FIT_54 |

Function prefixes: PS = `_protect_segments`, IUL = `_is_url_like`,
FIT = `_find_image_tag`, SIP = `_split_inside_parens`,
SAB = `_strip_angle_brackets`, CIT = `_convert_images_in_text`,
CFA = `convert_file_to_absolute`, CTA = `convert_to_absolute`.

## `_protect_segments` (10)

| ID | St | Mutation | Cat | Rationale / planned kill | Conf |
|---|---|---|---|---|---|
| 3 | s | `idx = 0` → `idx = 1` | B §14.8.5 | Tokens start `{{FENCE_1}}`; monotonic, unique, non-colliding. Round-trip trace: `_restore_segments` replaces every mapping key mechanically. | H |
| 8 | s | `idx += 1` → `idx = 1` | **A** | Canonical §14.8.5 negative example: counter collapses after second token; two spans share `{{INLINE_1}}`, mapping last-write-wins, restore duplicates one span and loses another. Kill: text with 3 distinct inline-code spans + full-equality assert. | H |
| 9 | s | `idx += 1` → `idx -= 1` | B §14.8.5 | Counter 0, −1, −2 …: unique; `{{fence_-2}}` shape explicitly qualifies per policy. | H |
| 10 | s | `idx += 1` → `idx += 2` | B §14.8.5 | Counter 0, 2, 4 …: unique, monotonic. | H |
| 17 | s | prefix `"FENCE"` → `None` | B §14.8.5 | Token `{{None_N}}`; `{{None_0}}` explicitly qualifies per policy; shared counter keeps FENCE/None spellings disjoint. | H |
| 22 | s | prefix → `"XXFENCEXX"` | B §14.8.5 | `{{XXFENCEXX_N}}` explicitly qualifies. | H |
| 23 | s | prefix → `"fence"` | B §14.8.5 | Lowercase spelling; disjoint from `INLINE`, unique. | H |
| 26 | s | prefix `"INLINE"` → `None` | B §14.8.5 | Same as 17 with roles swapped. | H |
| 31 | s | prefix → `"XXINLINEXX"` | B §14.8.5 | As 22. | H |
| 32 | s | prefix → `"inline"` | B §14.8.5 | As 23. | H |

## `_is_url_like` (1)

| ID | St | Mutation | Cat | Rationale / planned kill | Conf |
|---|---|---|---|---|---|
| 1 | s | `bool(URLISH_RE.match(target))` → `bool(None)` | **A** | Survives because tests only use URL targets that don't exist as local files — skip and leave-untouched collapse. Kill: file literally named `data:image.png` beside the md; contract (module docstring: "Skips … URL-like targets") says it must stay unconverted; mutant converts it. | H |

## `_find_image_tag` (31)

| ID | St | Mutation | Cat | Rationale / planned kill | Conf |
|---|---|---|---|---|---|
| 1 | t | `pos = start` → `None` | A-timeout | `find("![", None)` rescans from 0; caller loops on first tag forever. Kill: basic conversion test under `timeout(5)`. | H |
| 6 | t | `find("![", pos)` → `find("![", None)` | A-timeout | Same shape as 1. | H |
| 8 | t | `find("![", pos)` → `find("![", )` | A-timeout | Same shape as 1. | H |
| 12 | t | `if i == -1` → `== +1` | A-timeout | End-of-scan −1 no longer returns None; loops. Any terminating test under timeout kills. | H |
| 13 | t | `if i == -1` → `== -2` | A-timeout | As 12. | H |
| 16 | t | `find("]", i+2)` → `find("]", None)` | A-timeout | Earlier `](` (e.g. a preceding `[link](u)`) hijacks alt-scan → `tag_end < tag_start` → caller loops. Kill: link-before-image test under timeout. | H |
| 18 | t | `find("]", i+2)` → `find("]", )` | A-timeout | As 16. | H |
| 22 | s | `find("]", i+2)` → `i+3` | **A** | Misses `]` at exactly i+2 = empty alt. Kill: `![](rel)` converts. | H |
| 24 | s | `if j == -1` → `== +1` | **A** | j==−1 falls through; with `(` at text index 0 a bogus tuple with `tag_end < tag_start` emerges → hang/corrupt. Kill: text `"(x) ![nope"` under timeout, assert unchanged. | H |
| 25 | s | `if j == -1` → `== -2` | **A** | Same trigger as 24; same test kills. | H |
| 27 | s | `j + 1 >= n` → `j - 1 >= n` | **A** | Guard for `]` as final char lost → `text[j+1]` IndexError. Kill: text ending exactly `![alt]`, assert unchanged & no exception. | H |
| 28 | s | `j + 1 >= n` → `j + 2 >= n` | B converges | Both the mutated guard and the `text[j+1] != "("` check it bypasses/enters execute the identical body (`pos = i+2; continue`). Fires-earlier cases: j+1==n−1 with `(` after `]` → scanner runs off the end → same malformed skip. All paths converge on identical state. | M |
| 29 | s | `j + 1 >= n` → `j + 1 > n` | **A** | Off-by-one admits j+1==n → `text[n]` IndexError. Same test as 27 kills. | H |
| 39 | s | `in_angle = False` (init) → `None` | B falsiness | `in_angle` only consumed via `not in_angle` / `if in_angle`; None and False are indistinguishable under both. | H |
| 52 | t | angle-enter `k += 1` → `k = 1` | A-timeout | Rescan from text index 1 in angle mode; with a `>` in the pre-tag prefix the close position shifts/hangs. Kill: `"a>b ![i](<rel>)"` under timeout + full equality. | H |
| 53 | s | angle-enter `k += 1` → `k -= 1` | **A** | `>` directly before `<` makes k oscillate `>`↔`<` forever. Kill: target `a><c>.png` under timeout, assert unchanged. | H |
| 54 | s | angle-enter `k += 1` → `k += 2` | **C** | Only distinguishable when the char after `<` is `>` — i.e. an empty `<>` target. Original then strips `<>` to `""` and resolves `md.parent / ""` = the containing directory, which exists → "converts" the image to a directory path. Spec is silent on empty angle targets; pinning either behaviour would freeze an accident. Recorded as specification gap below. | H |
| 58 | s | angle-exit `in_angle = False` → `None` | B falsiness | As 39. | H |
| 60 | t | angle-consume `k += 1` → `k = 1` | A-timeout | Every angle char resets scan → immediate loop. Kill: angled conversion test under timeout. | H |
| 61 | t | angle-consume `k += 1` → `k -= 1` | A-timeout | Scan walks backwards forever. Same test as 60. | H |
| 66 | s | `depth += 1` → `depth = 1` | **A** | Depth ≥2 lost: nested `((…))` closes early. Kill: file named `a((b)).png` converts (with depth intact) — mutant mis-parses and skips. | H |
| 69 | t | after `(`: `k += 1` → `k = 1` | A-timeout | Loop on paren-in-target inputs. Killed by nested-paren test under timeout. | H |
| 70 | t | after `(`: `k += 1` → `k -= 1` | A-timeout | As 69. | H |
| 71 | s | after `(`: `k += 1` → `k += 2` | **A** | Skips char after `(`; `()` empty parens lose their `)` → depth never closes → malformed → unchanged. Kill: file named `x().png` converts. | H |
| 83 | s | `return (i, k + 1, …)` → `(i, k - 1, …)` | **A** | `tag_end` short by 2. Convert path duplicates tail chars into output. Survives because existing tests assert `in out`, not equality. Kill: full-equality assertion on any conversion. | H |
| 88 | t | nested-close `k += 1` → `k = 1` | A-timeout | Loop after nested `)`. Killed by nested-paren test under timeout. | H |
| 90 | s | nested-close `k += 1` → `k += 2` | **A** | Skips char after nested `)`; when that char is the tag-close `)` the tag never closes. Kill: file named `x(y)` (target ends at nested close), tag `![a](x(y))` converts. | H |
| 92 | t | plain `k += 1` → `k = 1` | A-timeout | Loop on any bare target scan. Basic test under timeout. | H |
| 93 | t | plain `k += 1` → `k -= 1` | A-timeout | As 92. | H |
| 95 | t | malformed-skip `pos = i + 2` → `None` | A-timeout | Unclosed-paren candidate rescans from 0 forever. Kill: unclosed `![a](no-close` under timeout, assert unchanged. | H |
| 97 | s | malformed-skip `pos = i + 2` → `i + 3` | B converges | A candidate starting at i+2 shares the same `]`/`(`/`)` structure as the candidate at i (both alt-scans hit the same first `]`), so their parse outcomes are identical; the extra skipped position can never begin a candidate that parses differently. All reachable inputs converge. | M |

## `_split_inside_parens` (14)

| ID | St | Mutation | Cat | Rationale / planned kill | Conf |
|---|---|---|---|---|---|
| 3 | s | angle-target regex match → `m = None` | **A** | Bare-scan fallback rebuilds the same target but normalises inter-token whitespace: a double space before a quoted title collapses to one. Kill: `![x](<rel>  "T")` (two spaces) → converted output must keep both. | H |
| 8 | s | regex wrapped `XX…XX` | **A** | Never matches → same fallback as 3; same test kills. | H |
| 29 | s | `ch == "("` → `"XX(XX"` | **A** | Depth never rises → space-then-quote *inside* parens triggers bogus title split. Kill: file named `a(b "c").png` converts. | H |
| 30 | s | `depth += 1` → `depth = 1` | **A** | Depth ≥2 lost. Kill: file named `a((b) "c").png` converts. | H |
| 34 | t | after `(` append: `i += 1` → `i = 1` | A-timeout | Loop on paren targets. Killed by 29/30 tests under timeout. | H |
| 35 | t | after `(` append: `i += 1` → `i -= 1` | A-timeout | As 34. | H |
| 46 | t | nested-close append: `i += 1` → `i = 1` | A-timeout | Loop on nested parens. Killed by nested tests under timeout. | H |
| 50 | s | `depth == 0 and ch.isspace()` → `or` | **A** | Lookahead fires on every depth-0 char and on in-paren spaces; quote after in-paren space splits a bogus title. Same input as 29 kills; plus quote-at-depth-0 shape. | H |
| 55 | s | `while j < n` → `j <= n` | B converges | `s[n]` IndexError requires a space-run to end of `s`; `s = inside.strip()` guarantees the last char is non-space, so the run always stops early. Unreachable divergence. | M |
| 60 | s | `if j < n` → `j <= n` | B converges | Same precondition as 55 (j==n needs trailing spaces; stripped). | M |
| 69 | t | space-append: `i += 1` → `i = 1` | A-timeout | Loop on space-in-target inputs. Kill: file `has space.png` converts under timeout. | H |
| 70 | t | space-append: `i += 1` → `i -= 1` | A-timeout | As 69. | H |
| 74 | t | plain append: `i += 1` → `i = 1` | A-timeout | Loop on any bare target. Killed by any split test under timeout. | H |
| 77 | s | `.rstrip()` → `.lstrip()` | B converges | `s` is pre-stripped and the scanner never leaves a leading/trailing space in `target_chars` (title-break consumes the trailing-space case), so both strips are no-ops. | M |

## `_strip_angle_brackets` (1)

| ID | St | Mutation | Cat | Rationale / planned kill | Conf |
|---|---|---|---|---|---|
| 4 | s | `startswith("<") and endswith(">")` → `or` | **A** | One-sided bracket mis-strips. Kill: file named `<a>b` with tag `![x](<a>b)` — scanner closes angle at `>`, split yields target `<a>b`; original converts, mutant strips to `a>` and leaves unchanged. | H |

## `_convert_images_in_text` (5)

| ID | St | Mutation | Cat | Rationale / planned kill | Conf |
|---|---|---|---|---|---|
| 4 | s | `idx = 0` → `None` | B falsiness | `idx` used only as slice start (`text[None:x]` ≡ `text[0:x]`) and as `str.find` start (None ≡ 0) before first reassignment. Python-level equivalence. | H |
| 11 | t | `_find_image_tag(protected, idx)` → `(protected, None)` | A-timeout | Always re-finds first tag → caller loops. Basic test under timeout. | H |
| 24 | s | skip-guard `or` → `and` | **A** | URL-like non-abs target no longer skipped. Same `data:image.png`-file test as IUL_1 kills. | H |
| 28 | t | after skip: `idx = tag_end` → `None` | A-timeout | Post-skip rescan from 0 loops. Kill: URL image followed by convertible image, under timeout. | H |
| 37 | t | after convert: `idx = tag_end` → `None` | A-timeout | Post-convert rescan loops. Basic test under timeout. | H |

## `convert_file_to_absolute` (5)

| ID | St | Mutation | Cat | Rationale / planned kill | Conf |
|---|---|---|---|---|---|
| 2 | s | `read_text(encoding="utf-8")` → `None` | **A** | Locale-coupled read. Kill: LC_ALL=C + non-ASCII content (precedent: `convert.py` mutants 7/52/54, `TestConvertFileEncodingContract`). | H |
| 4 | s | `encoding="utf-8"` → `"UTF-8"` (read) | B codec-alias | Python codec lookup is case-insensitive (`codecs.lookup("UTF-8")` → utf-8); byte-identical behaviour on every input. | H |
| 12 | s | `write_text(encoding="utf-8")` → `None` | **A** | Same locale pin, write side — converted output containing umlauts fails ASCII encode under LC_ALL=C. | H |
| 14 | s | `write_text(updated, )` — kwarg dropped | **A** | Identical to 12 (default encoding=None). Same test kills. | H |
| 16 | s | `encoding="utf-8"` → `"UTF-8"` (write) | B codec-alias | As 4. | H |

## `convert_to_absolute` (1)

| ID | St | Mutation | Cat | Rationale / planned kill | Conf |
|---|---|---|---|---|---|
| 18 | s | summary `print(f"✅ Updated …")` → `print(None)` | B §14.8.1 | Operator-visible status line in the CLI walker; policy covers status-line prints verbatim. | H |

## Specification gap (C) — FIT_54

Module: `paths/to_absolute.py`, function `_find_image_tag` /
downstream `_convert_images_in_text`.
Mutation: angle-enter `k += 1` → `k += 2` (only observable on `<>`).
Current behaviour: an empty angle target `![a](<>)` is stripped to
`""`, `md.parent / ""` resolves to the containing **directory**, which
exists, so the image is "converted" to a directory path.
What a specification would need to say: whether an empty target (bare
or angle-bracketed) is malformed input to be left untouched, or an
error. Do **not** pin the current directory-conversion as correct.
Tracked as Phase 6 material per §14.5 C-protocol.

## Planned test inventory (one file: `tests/unit/test_convert_to_absolute_mutation_pins.py`)

All scanner/split tests carry `@pytest.mark.timeout(5)` (new dev-dep
`pytest-timeout`, per the pause-doc plan) and assert **full output
equality**, which is what converts the 25 timeout mutants into kills
and closes the `in out`-assertion gap (FIT_83).

| Test | Kills |
|---|---|
| three distinct inline-code spans round-trip | PS_8 |
| URL-like target with matching local file stays untouched | IUL_1, CIT_24 |
| basic conversion, exact output | FIT_1/6/8/12/13/92/93, CIT_11/37, FIT_83 |
| empty alt `![](rel)` converts | FIT_22 |
| text ending `![alt]` unchanged, no exception | FIT_27/29 |
| `(x) ![nope` unchanged | FIT_24/25 |
| `[link](u)` before image, exact output | FIT_16/18 |
| `a>b` prefix before angle target, exact output | FIT_52 |
| target `a><c>.png` unchanged | FIT_53 |
| angle target converts, exact output | FIT_60/61 |
| file `a((b)).png` converts | FIT_66/69/70/88, SIP_46 |
| file `x().png` converts | FIT_71 |
| file `x(y)`, tag `![a](x(y))` converts | FIT_90 |
| unclosed `![a](no-close` unchanged | FIT_95 |
| double space before title preserved | SIP_3/8 |
| file `a(b "c").png` converts | SIP_29/50, SIP_34/35 |
| file `a((b) "c").png` converts | SIP_30 |
| file `has space.png` converts | SIP_69/70/74 |
| URL image then convertible image, exact output | CIT_28 |
| UTF-8 round-trip under LC_ALL=C | CFA_2/12/14 |
| file `<a>b` converts | SAB_4 |

## Verification protocol before landing

1. M-confidence B-candidates (FIT_28/97, SIP_55/60/77) get an
   explicit kill-attempt first; any kill demotes to A and the map is
   amended in the same commit.
2. Full targeted re-run of all 68 mutants after tests land; expected
   end state: 67 killed, 1 survivor (FIT_54, C).
3. `.mutmut/equivalent.yaml` entries carry per-mutant traces per
   §14.8.4/§14.8.5 discipline; ad-hoc buckets carry their argument
   inline (this map is the audit artefact they cite).

## Post-implementation amendment (2026-08-14, same day)

The map above is the pre-implementation plan, written against the
305-mutant tree. Implementation surfaced one tooling fact and four
bucket corrections; final verified state below.

**Coverage-driven mutant generation.** mutmut 3.5 only generates
mutants for lines the test suite covers. The Commit 10 A-tests grew
line coverage of `to_absolute.py` (malformed-scanner branches were
previously unexercised), which grew the mutant set 305 → 313 and
renumbered ids after each insertion point. All ids in the yaml and in
this amendment are from the post-Commit-10 tree; CI regenerates the
same tree from the same tests. Consequence for future responses:
land A-tests first, then re-run mutmut, then annotate against the
fresh numbering — never annotate against a pre-test tree.

**Bucket corrections vs the plan:**

1. Old FIT_27/29 (IndexError bound guards) killed as planned; the
   *new* branch-1/2/3 skip mutants generated by the coverage growth
   (`pos = i + 2` → `i + 3`, `continue` → `break`) triaged fresh:
   branch-2 `break` (new FIT_41) is **A** — killed by
   `test_malformed_candidate_then_valid_image_converts`; branch-1
   `break`/`pos` (new FIT_28/29), branch-2 `pos` (new FIT_40) and
   branch-3 `pos` (new FIT_105) are **B converges** (traces in the
   yaml).
2. The 25 planned per-mutant timeout kills landed as a structural
   fix instead: `tests/unit/conftest.py` applies a default
   `pytest.mark.timeout(10)` to every unit test without an explicit
   marker. Rationale: mutmut records a hang as `timeout` (not
   `killed`) whenever *any* unmarked test hangs first; marking only
   the new tests left 20 of 25 hang-mutants alive. With the
   unit-wide ceiling every hang becomes a fast test failure — final
   run shows **0 timeout mutants**.
3. `test_one_sided_angle_bracket_is_not_stripped` initially built
   its target with a directory prefix, so the target no longer began
   with `<` and SAB_4 survived; fixed by placing the `<a>b` file
   beside the md file.
4. Falsiness ids after renumbering: FIT_47 (init) / FIT_66
   (angle-exit) / CIT_4.

**Final verified state** (fresh full run, post-Commit-10 tree):

```
total=313  killed=289  survived=1  timeout=0  equivalent=23  score=99.7 %
```

The single survivor is FIT_62 (old FIT_54), the C-category
specification gap on empty `<>` targets documented above. 23
B-annotations live in `.mutmut/equivalent.yaml` with per-mutant
traces: 9 §14.8.5, 1 §14.8.1, 2 codec-alias, 8 converges, 3
falsiness.
