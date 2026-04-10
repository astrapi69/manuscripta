# Migration Guide: v0.6.x to v0.7.0

## TL;DR

1. Replace `speak()` calls with `synthesize()`.
2. Replace `GoogleTTSAdapter` with `GoogleTranslateTTSAdapter`.
3. Install optional TTS engines explicitly: `poetry install --with elevenlabs,pyttsx3`.
4. Catch `TTSError` subclasses instead of `RuntimeError`/`ValueError`.

---

## 1. `speak()` renamed to `synthesize()`

**Old:**
```python
adapter.speak(text, output_path)
```

**New:**
```python
adapter.synthesize(text, output_path)
```

The old `speak()` method still works but emits a `DeprecationWarning`.
It will be removed in v0.8.0.

---

## 2. `GoogleTTSAdapter` renamed

**Old:**
```python
from manuscripta.audiobook.tts.gtts_adapter import GoogleTTSAdapter

adapter = GoogleTTSAdapter(lang="de")
```

**New:**
```python
from manuscripta.audiobook.tts.google_translate_adapter import GoogleTranslateTTSAdapter

adapter = GoogleTranslateTTSAdapter(lang="de")
```

The old class name `GoogleTTSAdapter` is still importable from
`google_translate_adapter` as a deprecated alias.

For production use, consider switching to the new `GoogleCloudTTSAdapter`
which uses the official Google Cloud Text-to-Speech API with higher
quality voices (Neural2, WaveNet, Journey).

---

## 3. Optional dependencies

TTS engines other than Edge TTS are now optional. Install the ones you
need via Poetry dependency groups:

```bash
# Edge TTS only (default, always installed)
poetry install

# Add specific engines
poetry install --with elevenlabs
poetry install --with google-cloud-tts
poetry install --with google-translate
poetry install --with pyttsx3

# All engines
poetry install --with elevenlabs,google-cloud-tts,google-translate,pyttsx3
```

If you try to use an adapter whose dependency is not installed, you get a
clear `TTSEngineNotInstalledError` with installation instructions.

---

## 4. Exception handling

**Old:**
```python
try:
    adapter.speak(text, path)
except RuntimeError as e:
    print(f"TTS failed: {e}")
```

**New:**
```python
from manuscripta.audiobook.tts.exceptions import (
    TTSError,
    TTSTransientError,
    TTSCredentialsError,
    TTSQuotaExceededError,
)

try:
    adapter.synthesize(text, path)
except TTSTransientError:
    # Temporary failure, retry may help (already retried internally)
    ...
except TTSCredentialsError:
    # Invalid or missing credentials
    ...
except TTSQuotaExceededError:
    # API quota exceeded
    ...
except TTSError:
    # Any other TTS-specific error
    ...
```

---

## 5. New features available

### Factory function
```python
from manuscripta.audiobook.tts import create_adapter

adapter = create_adapter("edge-tts", lang="de")
adapter = create_adapter("elevenlabs", api_key="...", voice="Rachel")
adapter = create_adapter("google-cloud-tts", credentials_path="creds.json", voice_id="de-DE-Neural2-B")
```

### Voice listing
```python
voices = adapter.list_voices(language_code="de")
for v in voices:
    print(f"{v.display_name} ({v.gender}, {v.quality})")
```

### Cost estimation
```python
cost = adapter.estimate_cost(text)
if cost is not None:
    print(f"Estimated cost: ${cost:.4f}")
```

### Credential validation
```python
ok, message = adapter.validate()
if not ok:
    print(f"Setup problem: {message}")
```

### Quota checking
```python
quota = adapter.check_quota()
if quota:
    print(f"Used {quota.used}/{quota.limit} characters")
```

---

## 6. ElevenLabs API update

The ElevenLabs adapter now uses the new client API (`elevenlabs>=1.0.0`).

**Old:**
```python
from elevenlabs import generate, save, set_api_key
set_api_key(api_key)
audio = generate(text=text, voice=voice, model=model)
save(audio, path)
```

**New (handled internally by the adapter):**
```python
from elevenlabs.client import ElevenLabs
client = ElevenLabs(api_key=api_key)
audio = client.text_to_speech.convert(voice_id=voice, text=text, model_id=model)
```

If you were using the adapter through the standard interface, no changes
are needed beyond the `speak()` -> `synthesize()` rename.
