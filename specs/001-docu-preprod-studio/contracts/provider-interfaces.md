# Provider Interface Contracts

**Date**: 2026-06-22 | **Plan**: [../plan.md](../plan.md)

All ABCs live in `docu_studio/adapters/<category>/base.py`. Pipeline code imports only
these ABCs — never a concrete adapter. Violations of this boundary are caught at code
review (Constitution Principle I).

---

## LLMProvider

**File**: `docu_studio/adapters/llm/base.py`

```python
from abc import ABC, abstractmethod
from typing import List

class LLMProvider(ABC):

    @abstractmethod
    def generate_script(self, topic: str, target_words: int) -> str:
        """
        Generate a documentary script for `topic` targeting `target_words` words.
        Returns the full script as plain text.
        Raises PipelineError after all retries exhausted.
        """

    @abstractmethod
    def break_into_scenes(self, script: str) -> List[dict]:
        """
        Break `script` into scenes.
        Returns list of dicts: [{"title": str, "narration": str}, ...]
        Scene order matches narrative order.
        Raises PipelineError after all retries exhausted.
        """

    @abstractmethod
    def extract_visual_keywords(self, scene_title: str, narration: str) -> List[str]:
        """
        Extract 3–7 visual search keywords for stock footage.
        Returns list of keyword strings (singular nouns or short phrases).
        Raises PipelineError after all retries exhausted.
        """

    @abstractmethod
    def suggest_topic(self) -> str:
        """
        Generate a single documentary topic suggestion from the model's knowledge.
        Used as the fallback in TopicDiscoveryProvider when web search fails.
        Returns a topic string suitable for a 20–45 min documentary.
        Raises PipelineError after all retries exhausted.
        """
```

**Concrete implementation**: `AnthropicAdapter` in `adapters/llm/anthropic_adapter.py`.
Uses `claude-sonnet-4-6` for `generate_script` and `break_into_scenes`;
`claude-haiku-4-5` for `extract_visual_keywords` and `suggest_topic` (configurable via Settings).

---

## TopicDiscoveryProvider

**File**: `docu_studio/adapters/topic_discovery/base.py`

```python
from abc import ABC, abstractmethod
from docu_studio.adapters.llm.base import LLMProvider

class TopicDiscoveryProvider(ABC):

    @abstractmethod
    def discover_topic(self, llm_fallback: LLMProvider) -> TopicResult:
        """
        Discover a currently trending/relevant documentary topic.

        Primary path: live web search.
        Fallback path: if web search fails or returns unusable result,
          call llm_fallback.suggest_topic() and set TopicResult.fallback_triggered=True.

        Returns TopicResult with topic, source, and fallback_triggered flag.
        Raises PipelineError only if both paths fail after all retries.
        """
```

**`llm_fallback` parameter**: The pipeline passes the configured `LLMProvider` instance;
the `TopicDiscoveryProvider` implementation must accept it and use it for fallback —
it MUST NOT import `AnthropicAdapter` directly. This satisfies Constitution Principle I.

**Concrete implementation**: `SerperAdapter` in `adapters/topic_discovery/serper_adapter.py`.

---

## TTSProvider

**File**: `docu_studio/adapters/tts/base.py`

```python
from abc import ABC, abstractmethod
from pathlib import Path

class TTSProvider(ABC):

    @abstractmethod
    def synthesize(self, text: str, output_path: Path) -> float:
        """
        Convert `text` to speech and write MP3 to `output_path`.
        Returns the duration of the generated audio in seconds (float).
        `output_path` parent directory is guaranteed to exist before call.
        Raises PipelineError after all retries exhausted.
        """
```

**Concrete implementations**:
- `EdgeTTSAdapter` in `adapters/tts/edge_tts_adapter.py` — free; no API key; uses
  `asyncio.run()` internally to call the async `edge_tts` library; default provider.
- `ElevenLabsAdapter` in `adapters/tts/elevenlabs_adapter.py` — paid; requires API key
  from keyring; uses the `elevenlabs` Python SDK.

**Duration measurement**: Each adapter measures the output file duration itself after
synthesis using `FFmpegWrapper.get_duration(output_path)` to return a verified float.

---

## FootageProvider

**File**: `docu_studio/adapters/footage/base.py`

```python
from abc import ABC, abstractmethod
from typing import List

class FootageProvider(ABC):

    @abstractmethod
    def search(self, keywords: List[str], min_duration: float) -> List[FootageClip]:
        """
        Search for stock footage clips matching `keywords`.
        `min_duration`: minimum clip duration in seconds (clips shorter may be returned
          but the caller handles concatenation).
        Returns list of FootageClip ordered by relevance (best match first).
        Returns empty list (not raises) when no results found.
        Raises PipelineError after all retries exhausted on API failure.
        """
```

**Concrete implementations**:
- `PexelsAdapter` in `adapters/footage/pexels_adapter.py` — free; API key from keyring;
  HTTP via `requests`; enabled by default.
- `PixabayAdapter` in `adapters/footage/pixabay_adapter.py` — free; API key from keyring;
  HTTP via `requests`; enabled by default.

**Multi-provider aggregation**: `footage_assembly.py` iterates the user's enabled
`FootageProvider` list sequentially, accumulating clips until audio duration is covered.
No provider-specific logic in assembly stage.

**Extending**: A future `StoryblocksAdapter` implementing `FootageProvider` requires only:
1. Create `adapters/footage/storyblocks_adapter.py`
2. Add `"storyblocks"` to the Settings provider registry
3. Zero changes to pipeline or assembly code

---

## FFmpegWrapper

**File**: `docu_studio/media/ffmpeg_wrapper.py`

Not a provider ABC (single implementation, no substitution needed), but documented here
as a stable internal contract to protect the export gate and tests.

```python
class FFmpegWrapper:

    def get_duration(self, file_path: Path) -> float:
        """
        Measure duration of an audio or video file using ffprobe.
        Returns duration in seconds (float).
        Raises FFmpegError if file is unreadable or duration cannot be parsed.
        """

    def trim_clip(self, input_path: Path, output_path: Path, duration: float) -> None:
        """
        Trim input video to exactly `duration` seconds using stream copy.
        Output is written to `output_path`.
        Raises FFmpegError on non-zero exit code.
        """

    def concat_clips(self, clip_paths: List[Path], output_path: Path) -> None:
        """
        Concatenate `clip_paths` into a single video at `output_path`
        using the FFmpeg concat demuxer (stream copy; no re-encode).
        Raises FFmpegError on non-zero exit code.
        """

    def mux_audio_video(
        self, video_path: Path, audio_path: Path, output_path: Path
    ) -> None:
        """
        Combine `video_path` and `audio_path` into `output_path` (MP4).
        Uses stream copy with -shortest to terminate at the shorter track.
        Raises FFmpegError on non-zero exit code.
        """
```

**FFmpegError**: Raised with the full stderr from FFmpeg, truncated to 2000 chars.
Never leaks secrets (FFmpeg commands contain only file paths, not API keys).

---

## FCPXMLGenerator

**File**: `docu_studio/media/fcpxml_generator.py`

Pure function — no filesystem I/O inside, no network calls. Sync gate runs before
calling this function.

```python
def validate_sync(scenes: List[FinalScene], tolerance_s: float = 0.050) -> None:
    """
    Verify per-scene sync invariant: |video_duration - audio_duration| <= tolerance_s
    for every scene in `scenes`.
    Raises ExportSyncError listing all violating scenes if any fail.
    """

def generate_fcpxml(
    scenes: List[FinalScene],
    project_folder: Path,
    topic: str
) -> str:
    """
    Generate FCPXML 1.9 content as a string.
    `project_folder` is embedded as the base path for media references.
    Scene titles become <marker> elements.
    Returns the complete XML string (caller writes to disk).
    Does NOT call validate_sync — caller must call it first.
    """
```

**Usage contract**: `fcpxml_export.py` (Stage 7) always calls `validate_sync(scenes)`
before `generate_fcpxml(scenes, ...)`. Swapping or testing either function independently
is safe because they share no state.

---

## Error Types

```python
class PipelineError(Exception):
    """Raised by adapters after all retries exhausted. message is user-readable."""
    stage: str
    scene_index: int  # -1 for pipeline-level

class FFmpegError(Exception):
    """Raised by FFmpegWrapper on non-zero FFmpeg/ffprobe exit."""
    stderr: str  # truncated to 2000 chars

class ExportSyncError(Exception):
    """Raised by validate_sync when per-scene invariant is violated."""
    violations: List[tuple]  # [(scene_index, video_duration, audio_duration), ...]
```
