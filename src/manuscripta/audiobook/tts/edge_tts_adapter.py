"""Edge TTS adapter using Microsoft Edge's online neural TTS service.

Requires:
    poetry add edge-tts

No API key needed.  Requires internet connection.

Splits long texts into chunks to avoid WebSocket timeouts on Microsoft's service.

German voices (examples):
    de-DE-KatjaNeural    (female, Germany)
    de-DE-ConradNeural   (male, Germany)
    de-AT-IngridNeural   (female, Austria)
    de-AT-JonasNeural    (male, Austria)
    de-CH-LeniNeural     (female, Switzerland)
    de-CH-JanNeural      (male, Switzerland)

English voices (examples):
    en-US-JennyNeural    (female, US)
    en-US-GuyNeural      (male, US)
    en-GB-SoniaNeural    (female, UK)
    en-GB-RyanNeural     (male, UK)

List all voices: edge-tts --list-voices
"""

import asyncio
import shutil
import tempfile
from pathlib import Path
from typing import Optional

from manuscripta.audiobook.tts.base import TTSAdapter, VoiceInfo
from manuscripta.audiobook.tts.exceptions import (
    TTSInvalidInputError,
    TTSTransientError,
)
from manuscripta.audiobook.tts.text_chunking import split_text_into_chunks

# Default voices per language code
_DEFAULT_VOICES = {
    "de": "de-DE-KatjaNeural",
    "de-de": "de-DE-KatjaNeural",
    "de-at": "de-AT-IngridNeural",
    "de-ch": "de-CH-LeniNeural",
    "en": "en-US-JennyNeural",
    "en-us": "en-US-JennyNeural",
    "en-gb": "en-GB-SoniaNeural",
    "es": "es-ES-ElviraNeural",
    "fr": "fr-FR-DeniseNeural",
    "el": "el-GR-AthinaNeural",
    "it": "it-IT-ElsaNeural",
    "pt": "pt-BR-FranciscaNeural",
    "ja": "ja-JP-NanamiNeural",
    "zh": "zh-CN-XiaoxiaoNeural",
}


class EdgeTTSAdapter(TTSAdapter):
    """TTS adapter backed by Microsoft Edge's neural TTS service (free, online).

    Automatically splits long texts into chunks to avoid WebSocket timeouts.

    :param lang: Language code (e.g. 'de', 'en', 'es', 'fr', 'el').
                 Used to pick a default voice if none is specified.
    :param voice: Full Edge TTS voice name, e.g. 'de-DE-ConradNeural'.
                  Overrides the language-based default.
    :param rate: Speech rate adjustment, e.g. '+0%', '-10%', '+20%'.
    :param volume: Volume adjustment, e.g. '+0%', '-20%'.
    :param pitch: Pitch adjustment, e.g. '+0Hz', '-5Hz'.
    """

    name = "edge-tts"
    requires_credentials = False
    supports_chunking = True
    max_chunk_chars = 4000

    def __init__(
        self,
        lang: str = "de",
        voice: Optional[str] = None,
        rate: str = "+0%",
        volume: str = "+0%",
        pitch: str = "+0Hz",
    ):
        self.lang = lang
        self.voice = voice or _DEFAULT_VOICES.get(lang.lower(), "en-US-JennyNeural")
        self.rate = rate
        self.volume = volume
        self.pitch = pitch

    def synthesize(self, text: str, output_path: Path) -> None:
        """Convert text to speech and save as MP3."""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        chunks = split_text_into_chunks(text, max_chars=self.max_chunk_chars)
        if not chunks:
            return

        if len(chunks) == 1:
            self._run_async(self._generate_single(chunks[0], output_path))
        else:
            self._run_async(self._generate_chunked(chunks, output_path))

    def list_voices(self, language_code: Optional[str] = None) -> list[VoiceInfo]:
        """List available Edge TTS voices via the edge-tts library."""
        voices_data = self._run_async(self._fetch_voices())
        result: list[VoiceInfo] = []
        for v in voices_data:
            lang = v.get("Locale", "")
            if language_code and not lang.lower().startswith(language_code.lower()):
                continue
            gender_raw = v.get("Gender", "neutral")
            gender = (
                gender_raw.lower()
                if gender_raw.lower() in ("male", "female")
                else "neutral"
            )
            result.append(
                VoiceInfo(
                    engine=self.name,
                    voice_id=v.get("ShortName", ""),
                    display_name=v.get("FriendlyName", v.get("ShortName", "")),
                    language=lang,
                    gender=gender,
                    quality="neural",
                )
            )
        return result

    def validate(self) -> tuple[bool, str]:
        """Check that Edge TTS is reachable."""
        try:
            voices = self.list_voices(language_code="en-US")
            if voices:
                return True, "Edge TTS reachable"
            return False, "No voices returned"
        except Exception as e:
            return False, str(e)

    # -- internals -------------------------------------------------------------

    @staticmethod
    def _run_async(coro):
        """Run an async coroutine, handling existing event loops gracefully."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            try:
                import nest_asyncio

                nest_asyncio.apply()
                loop.run_until_complete(coro)
            except ImportError:
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor() as pool:
                    return pool.submit(asyncio.run, coro).result()
        else:
            return asyncio.run(coro)

    @staticmethod
    async def _fetch_voices() -> list[dict]:
        """Fetch the list of available voices from the Edge TTS service."""
        import edge_tts

        return await edge_tts.list_voices()

    async def _generate_single(self, text: str, output_path: Path) -> None:
        await self._tts_with_retry(text, output_path)

    async def _tts_with_retry(
        self, text: str, output_path: Path, max_retries: int = 3
    ) -> None:
        """Call Edge TTS with retry on transient failure."""
        import edge_tts

        for attempt in range(1, max_retries + 1):
            try:
                communicate = edge_tts.Communicate(
                    text,
                    self.voice,
                    rate=self.rate,
                    volume=self.volume,
                    pitch=self.pitch,
                )
                await communicate.save(str(output_path))
                return
            except Exception as exc:
                if attempt < max_retries:
                    wait = attempt * 2
                    print(f"    Retry {attempt}/{max_retries} after error: {exc}")
                    print(f"    Waiting {wait}s before next attempt...")
                    await asyncio.sleep(wait)
                else:
                    exc_str = str(exc).lower()
                    if "invalid" in exc_str or "parameter" in exc_str:
                        raise TTSInvalidInputError(
                            f"Edge TTS rejected input: {exc}",
                            engine=self.name,
                            original=exc,
                        ) from exc
                    raise TTSTransientError(
                        f"Edge TTS failed after {max_retries} attempts: {exc}",
                        engine=self.name,
                        original=exc,
                    ) from exc

    async def _generate_chunked(self, chunks: list[str], output_path: Path) -> None:
        """Generate multiple chunks, concatenate into final MP3."""
        temp_dir = Path(tempfile.mkdtemp(prefix="edge_tts_"))

        try:
            temp_files: list[Path] = []
            for idx, chunk in enumerate(chunks):
                temp_path = temp_dir / f"chunk_{idx:04d}.mp3"
                print(f"    Chunk {idx + 1}/{len(chunks)} ({len(chunk)} chars)")
                await self._tts_with_retry(chunk, temp_path)
                temp_files.append(temp_path)

            with open(output_path, "wb") as outfile:
                for temp_file in temp_files:
                    outfile.write(temp_file.read_bytes())
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
