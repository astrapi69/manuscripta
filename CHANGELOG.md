# Changelog

All notable changes to this project will be documented in this file.

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
