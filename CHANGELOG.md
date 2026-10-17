# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Changed
- **Nightly mutation testing** fails the workflow when a module sits below its threshold, after
  writing the audit and opening the issue (ADR-0002 amendment); pull requests still do not run
  it. The default threshold is 85 % (was 75 %) and `text_chunking` moves from 80 % to 85 %; no
  module in scope sits below 85 %.
- **Nightly mutation testing** keeps a `mutation-context.json` (tool and version, scope, the
  result breakdown, the equivalent count, mutmut's own score and the strict one) as the
  artifact `mutation-context` of every run, in the schema of awesome-well-tested's
  `docs/mutation-context.md`; `scripts/check_mutation_thresholds.py --equivalent-count` prints
  the number of annotated equivalents it feeds in.
- **Mutation scope**: `markdown/links_to_plain.py` and `markdown/strip_links.py`, the last two
  eligible CORE modules, enter the nightly mutation scope at the 85 % tier (78 % and 70 % on
  entry, 99 % and 100 % after the survivor triage per TESTING.md §14.5: case-table rows for
  token uniqueness, angle-bracketed destinations, the UTF-8 contract under `LC_ALL=C`, reference
  links and definition lines, the `toc.md` default and help presence; 40 equivalents annotated;
  one specification gap, the destination/title separator, documented). The scope is twenty-one
  modules, about 5700 mutants.

## [0.11.1] - 2026-10-16

### Fixed
- **`convert-img-tags`**: `--base-dir` defaults to the current working directory; it was the
  package directory `src/manuscripta/` left over from the `scripts/` era, while the help promised
  the repository root (#28).
- **`create-chapters`**: a `--name-pattern` that cannot be formatted (`{number}`, `{}`, a bad
  format spec) exits 2 with a clear error instead of a `KeyError` traceback (#31).
- **`replace-md-bullet-points`**: thematic breaks (`***`, `* * *`, `---`, `___`) are left
  untouched instead of becoming `• * *`; a missing path exits 1 (#31).
- **Config loader**: a YAML settings file whose top level is not a mapping raises `ValueError`
  naming the file instead of returning a list or a string (#31).
- **`pandoc-batch`**: `--resource-path` on the command line replaces the configured list instead
  of extending it (#31).
- **Mutation gate**: `scripts/check_mutation_thresholds.py` counts mutants that no test ever
  checked as not killed and fails naming the modules; `make mutation-fast` passes mutant-name
  globs instead of file paths and warns that a filtered run resets the other modules (#29).

## [0.11.0] - 2026-10-16

### Added
- **`--backup` / `--no-backup` for `fix-german-quotes`, `fix-english-quotes`, `fix-french-quotes` and
  `fix-spanish-quotes`**: a changed file gets its `.bak` copy only when Git does not track it
  (`git ls-files`); in a repository the copy is redundant and left 5 to 30 untracked files to delete
  after each run. `--backup` forces the copy, `--no-backup` skips it everywhere. The `Written:` line
  says which of the two happened (#17).

### Fixed
- **`export-*` shortcuts and `--help`**: `--help` / `-h` on every export shortcut (`export-epub`,
  `export-pdf-safe`, `export-print-version-hardcover`, ...) prints the usage of the shortcut and
  the options of `full-export` and `print-version-build` and exits without touching the
  manuscript or `output/`. Before, `--help` was dropped as an unknown option and a full export
  ran with the defaults. An unknown option now aborts with exit status 2 instead of being
  dropped silently; `--strict-opts` is still accepted and has no effect. The allow-list gained
  `--source-dir`, `--resource-path`, `--strict-images` and `--no-strict-images` (the README
  example `export-pdf --source-dir=...` was dropped before) and `--restore` / `--exact-name` for
  `print-version-build`; the stale `--scripts-dir` and `--no-restore` are gone (#18).
- **`fix-french-quotes` and `fix-spanish-quotes` convert English `“...”`**: a top-level English
  typographic pair becomes `« ... »` / `«...»` like a straight one; a pair nested inside
  guillemets stays as the second level. Before, every `“...”` was left as it was, so the Spanish
  edition of eternity-ebook kept three English pairs next to its guillemets (#16).
- **`make-tag-message`**: the built-in de/en prompts render the version label into the title line
  instead of the literal `{version_label}`; the JSON commit categories match keywords as whole
  words, so "texts" and "default" no longer land in content_style and imagery (plurals such as
  "images" no longer match either); the unreachable second "message file not found" guard is
  gone, the preflight check owns it (#25).
- **`generate-audiobook`**: a chapter whose synthesis fails with `--overwrite` keeps the previous
  MP3: audio goes to `.<chapter>.part.mp3` first and moves into place when complete, and an engine
  that produces no file counts as a failed chapter. The merged audiobook's title comes from the
  directory holding the input, not the process cwd, and ffmpeg runs in the resolved output
  directory, so a relative `--output` works from any cwd (#25).
- **`translate-book-deepl`**: `DEEPL_AUTH_KEY` is read on every request instead of once at import,
  `.skiplist` is read and written at the same path, and `--dry-run` no longer sleeps after every
  block (#25).
- **`translate-book` (LM Studio)**: a multi-paragraph answer is kept whole, only the `<think>`
  block and a leading label are stripped; the `translate-book-*` shortcuts forward the program
  name `translate-book-lmstudio` and their `translate` help names LM Studio, not DeepL (#25).
- **Translation, both engines**: a translated file keeps its final newline (#25).
- **`manuscripta-init --clean`**: an excluded item that is no longer on disk is reported as
  "Missing (nothing to delete)" instead of being listed as a file and announced as deleted; with
  nothing left on disk no deletion prompt appears (#25).
- **`generate-images`**: unknown names in a prompt's character list are skipped instead of
  leaving an empty `, ,` in the composed prompt (#25).
- **`reorder-chapters`**: the header/anchor update keeps the chapter file's trailing newline, and
  `--dry-run` previews the header change instead of warning "Header/anchor update failed" for
  the not-yet-renamed target (#25).
- **`unbold-md-headers`**: `main(argv)` honours the argv it is given (#25).
- **Edge TTS**: `_run_async` returns the coroutine's result on the nest_asyncio path, so
  `list_voices` and `validate` inside a running event loop no longer get `None` (#25).
- **`strip-links`**: a fenced block with an info string comes back verbatim; its fence lines were
  duplicated because the empty code span inside the fence line matched as inline code (#21).
- **Tests**: the wheel-install layer installs the built wheel with `uv pip install` when uv
  created the venv, so its two install tests run instead of skipping (#22).

## [0.10.0] - 2026-10-06

### Added
- **VoiceStudio TTS engine** (`voicestudio`): audiobooks with cloned or designed voices from the
  locally running VoiceStudio app via its OpenAI-compatible API. Voice profile by id or name,
  `VOICESTUDIO_URL` / `VOICESTUDIO_API_KEY` overrides, short chunks for stable long-form narration,
  retries on server errors, clear error when the app is not running. No new dependency.
- **Section order slot for `other-publications.md`**: the built-in ebook order includes
  `back-matter/other-publications.md` and the built-in paperback/hardcover order
  `back-matter/other-publications-print.md`, both between `about-the-author.md` and
  `bibliography.md`. A missing file is skipped as before. Every build now prints
  `⚠️  Not in section order, skipped: ...` for Markdown files under `manuscript/` that the
  resolved order does not include (the manual TOC files excepted), so an extra section no
  longer vanishes silently. Projects with their own sections set the order in
  `config/export-settings.yaml` (#10).
- **`fix-english-quotes`**: converts straight double and single quotes in Markdown files to
  English `“…”`, `‘…’` and the apostrophe `’`, with the per-paragraph pairing, protected regions
  (frontmatter, code, HTML attributes) and options of `fix-german-quotes`. An apostrophe inside
  or at the end of a word and before a decade (`'90s`) becomes `’`; an opening `'` needs a closing
  quote in the same paragraph, otherwise (`'tis`) the paragraph keeps its straight opening quotes
  and gets a warning. `process_file` and the stage functions take a `QuoteStyle` (`GERMAN`, the
  default, or `ENGLISH`) (#12).
- **`fix-french-quotes` and `fix-spanish-quotes`**: straight double quotes become guillemets,
  French `« … »` with a no-break space (U+00A0) inside, Spanish `«…»` without; the guillemets
  already in the text get the same spacing when they pair up in the paragraph (a lone `»` used as
  a heading marker keeps its space). Straight single quotes and apostrophes are converted
  as in `fix-english-quotes`. English `“…”` are left alone as the second level. New styles
  `FRENCH` and `SPANISH`.
- **`fix-french-quotes` sets the space before `; : ! ?`**: an ordinary space, a narrow no-break
  space or none before these marks becomes a no-break space (U+00A0, constant
  `FR_PUNCTUATION_SPACE`), so `Quoi ?` cannot break before the question mark. Marks that are
  markup or no punctuation keep their spacing: URLs, times, `:)`, footnote definitions and link
  references (`[^1]:`, `[id]:`), table alignment colons, HTML entities, `![image]`, `<!--` and a
  mark at the start of a line or after an opening bracket or quote. Checked on ai-for-everyone
  (French): 868 corrections, heading ids and link targets unchanged in pandoc.

### Changed
- **EPUB export uses `--split-level=1`** instead of the deprecated `--epub-chapter-level=1`
  (same behaviour: every H1 starts a new XHTML file). Pandoc 3.0 or newer is now the documented
  minimum (#6).
- **`fix-german-quotes` documentation** (module docstring and README) states which quotes the
  tool converts and that straight single quotes `'` are left alone on purpose, because they
  cannot be told apart from apostrophes (#9).

### Fixed
- **Export helper modules run with the current interpreter**: `run_script`, the TOC
  normalization step and `print-version-build` launch the `manuscripta.*` helper modules with
  `sys.executable` instead of a bare `python3`. An export started from a Poetry or virtualenv
  interpreter no longer falls back to the system Python (where manuscripta is not installed)
  and no longer logs "Error normalizing TOC" (#5).
- **`replace-emojis` maps 🌐 to ◯** (U+25EF, the same KDP-safe circle as 🌍) instead of the
  diameter sign ⌀ (#7).
- **`fix-german-quotes` pairs quotes per paragraph, not per line.** A quotation that a hard
  line wrap split across two lines used to produce two "Asymmetric straight quotation mark"
  warnings and stayed unconverted; it is now opened on the first line and closed on the second.
  Headings, list items and table rows are paired on their own, a blank line ends a paragraph,
  and frontmatter and fenced code blocks are still left untouched. A warning for a multi-line
  block names the line range (`Lines 7-8`) and shows the whole block as context (#8).
- **`fix-german-quotes` no longer gives a closed `„…“` the next straight quote.** In a paragraph
  such as `„Hallo“, sagte er, "und tschüss."` the opening straight quote was taken as a second
  closing quote of `„Hallo“`, which produced `“und tschüss."` and an "Asymmetric straight
  quotation mark" warning. Only an opening quote that is still open takes a straight closing
  quote now.

## [0.9.0] - 2026-04-16

### Changed
- **pillow** `^11.2.1` -> `^12.0` (unblocks Bibliogon downstream constraint)
- **pandas** `^2.3.2` -> `^3.0`
- **tenacity** `^8.2.3` -> `^9.0`
- **pytest** `^8.2` -> `^9.0`
- **pytest-cov** `^4.1.0` -> `^7.0`
- **ruff** `^0.14.0` -> `^0.15`

### Not upgraded (documented skips)
- **black** stays at `==25.12.0` — exact pin per TESTING.md §14.9 (formatter
  determinism). Bumping requires the procedure documented there.

## [0.8.1] - 2026-04-16

### Added
- `update-deps` Makefile target: runs `poetry update`, builds the project, and
  executes the test suite in one step to verify dependency upgrades.

### Changed
- Updated direct dependencies:
  - `edge-tts` 7.2.7 → 7.2.8
  - `hypothesis` 6.151.9 → 6.152.1
  - `mypy` 1.19.1 → 1.20.1
  - `pymupdf` 1.27.2 → 1.27.2.2
  - `requests` 2.32.5 → 2.33.1
  - `types-pyyaml` 6.0.12.20250915 → 6.0.12.20260408
  - `types-requests` 2.32.4.20260107 → 2.33.0.20260408
  - `types-toml` 0.10.8.20240310 → 0.10.8.20260408
- Updated transitive dependencies:
  aiohttp 3.13.3 → 3.13.5, attrs 25.4.0 → 26.1.0,
  charset-normalizer 3.4.6 → 3.4.7, filelock 3.25.2 → 3.28.0,
  librt 0.8.1 → 0.9.0, lxml 6.0.2 → 6.0.4, numpy 2.4.3 → 2.4.4,
  packaging 26.0 → 26.1, platformdirs 4.9.4 → 4.9.6,
  pygments 2.19.2 → 2.20.0, python-discovery 1.1.3 → 1.2.2,
  tzdata 2025.3 → 2026.1, virtualenv 21.2.0 → 21.2.4.

## [0.7.0] - 2026-04-10

### Breaking Changes
- `GoogleTTSAdapter` renamed to `GoogleTranslateTTSAdapter`.
  Old name available as alias with DeprecationWarning, will be removed in v0.8.0.
- `TTSAdapter.speak(text, path)` is deprecated. New method:
  `TTSAdapter.synthesize(text, path)`. Old name available as alias with
  DeprecationWarning.
- Optional dependencies: elevenlabs, google-cloud-texttospeech,
  gtts, and pyttsx3 are now optional. Install via Poetry groups:
  `poetry install --with google-cloud-tts,elevenlabs,pyttsx3,google-translate`
- All adapters now raise `TTSError` subclasses instead of `RuntimeError`/`ValueError`.
- New required dependency: `tenacity` (retry logic).

### Added
- `GoogleCloudTTSAdapter`: Official Google Cloud TTS integration
  with service account auth, quality detection (journey/neural2/wavenet/studio/standard).
- `TTSError` hierarchy with 8 specific exception types for granular error handling.
- Central retry decorator `with_retry()` with exponential backoff (tenacity).
- `VoiceInfo` and `QuotaInfo` dataclasses for uniform voice/quota metadata.
- `create_adapter()` factory function to instantiate adapters by engine name.
- `list_voices()`, `validate()`, `estimate_cost()`, `check_quota()` in all adapters.
- `text_chunking` module: reusable text splitting for all adapters.
- Comprehensive test suite for all TTS adapters (108 tests).

### Changed
- `EdgeTTSAdapter` uses extracted `text_chunking` module and maps errors to `TTSError` hierarchy.
- `ElevenLabsAdapter` updated to new client API (`elevenlabs>=1.0.0`).
  No more global state (`set_api_key`), uses per-instance client.
- `Pyttsx3Adapter` uses lazy initialization (engine created on first use).
- Text chunking extracted from `EdgeTTSAdapter` into reusable `text_chunking.py`.

### Deprecated
- `TTSAdapter.speak()` -- use `synthesize()` instead.
- `GoogleTTSAdapter` -- use `GoogleTranslateTTSAdapter` instead.
- `GoogleTranslateTTSAdapter` itself carries a deprecation warning recommending
  `GoogleCloudTTSAdapter` for production use.

## [0.6.2] - 2026-04-08

- Bump version to 0.6.2.

## [0.6.1] - 2026-04-07

- Add sensible defaults for input and output paths.

## [0.6.0] - 2026-04-06

- Add `remove_pandoc_attributes` to audiobook TTS cleaning pipeline.
- Restructure and optimize tasks in Makefile.
