# Changelog

All notable changes to this project will be documented in this file.

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
