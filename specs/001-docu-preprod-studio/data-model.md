# Data Model: Documentary Pre-Production Studio

**Date**: 2026-06-22 | **Plan**: [plan.md](plan.md)

All entities use Python dataclasses (`@dataclass(frozen=True)` where noted; mutable where
state changes occur during pipeline execution).

---

## Run

```python
@dataclass
class Run:
    id: str                  # UUID4, generated at run creation
    topic: str               # User-supplied or discovered topic
    mode: RunMode            # RunMode.GUIDED | RunMode.FULL_AUTO
    target_duration_minutes: int
    status: RunStatus        # RunStatus.RUNNING | COMPLETED | CANCELLED | FAILED
    started_at: datetime
    completed_at: Optional[datetime]
    project_folder: Path     # Absolute path to the output project folder
    topic_source: TopicSource  # TopicSource.USER | WEB_SEARCH | AI_SUGGESTED
```

**Lifecycle**: Created when user starts a run (`status=RUNNING`). Status updated to
`COMPLETED`, `CANCELLED`, or `FAILED` when the pipeline ends. Written to `run_history.json`
at the end of every run regardless of outcome (FR-032, FR-029, FR-033).

**Persistence**: `RunRecord` is the JSON-serialisable dict form (all fields, datetime as
ISO-8601 string, Path as string). `run_history.json` is a list of `RunRecord` dicts.

---

## RunMode

```python
class RunMode(str, Enum):
    GUIDED = "guided"
    FULL_AUTO = "full_auto"
```

---

## RunStatus

```python
class RunStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"
```

---

## TopicSource

```python
class TopicSource(str, Enum):
    USER = "user"               # Guided Mode: user typed the topic
    WEB_SEARCH = "web_search"   # Full Auto: Serper.dev returned a topic
    AI_SUGGESTED = "ai_suggested"  # Full Auto: fallback to Anthropic suggestion
```

---

## Scene

```python
@dataclass
class Scene:
    index: int               # 0-based position in the documentary
    title: str               # Short title (used as FCPXML marker label)
    narration: str           # Full narration text for this scene
    visual_keywords: List[str]  # Extracted by LLMProvider.extract_visual_keywords()
    audio_path: Optional[Path]   # Set after TTSProvider.synthesize() completes
    audio_duration: Optional[float]  # Seconds, measured by FFmpegWrapper after TTS
    video_path: Optional[Path]   # Set after footage_assembly completes
    video_duration: Optional[float]  # Seconds, measured by FFmpegWrapper after mux
    footage_shortage: bool = False  # True if insufficient footage found (FR-014)
```

**Invariant** (checked at export gate): For every scene where `footage_shortage=False`,
`|video_duration − audio_duration| <= 0.050` seconds.

**Note**: `Scene` is mutable during pipeline execution (fields set progressively per stage).
It is frozen into a `FinalScene` snapshot for FCPXML generation (see below).

---

## FinalScene

```python
@dataclass(frozen=True)
class FinalScene:
    index: int
    title: str
    audio_path: Path
    audio_duration: float    # seconds
    video_path: Path
    video_duration: float    # seconds
```

Produced by `footage_assembly.py` after mux and duration measurement. Only scenes without
`footage_shortage` produce a `FinalScene`. Passed to `fcpxml_generator.generate_fcpxml()`.

---

## TopicResult

```python
@dataclass(frozen=True)
class TopicResult:
    topic: str
    source: TopicSource
    fallback_triggered: bool  # True when WEB_SEARCH failed and AI_SUGGESTED used
```

Returned by `TopicDiscoveryProvider.discover_topic()`. Stored on `Run.topic_source`.
Used to generate the fallback label in GUI and log (FR-006).

---

## FootageClip

```python
@dataclass(frozen=True)
class FootageClip:
    url: str              # Direct download URL for the video file
    duration: float       # Seconds, as reported by the footage API
    provider: str         # "pexels" | "pixabay" (for logging)
    clip_id: str          # Provider's clip ID (for deduplication)
```

Returned by `FootageProvider.search()`. Multiple clips are concatenated by
`footage_assembly.py` to cover `scene.audio_duration`.

---

## Settings

```python
@dataclass
class Settings:
    # Non-secret fields persisted to JSON config file
    tts_provider: str              # "edge_tts" | "elevenlabs"
    footage_providers: List[str]   # ["pexels", "pixabay"] or subset
    output_folder: Path            # Default output folder for project folders
    wpm: int                       # Words per minute for script length estimation
    llm_model_script: str          # Claude model for script gen + scene break
    llm_model_keywords: str        # Claude model for keyword extraction

    # Secret fields: NOT in JSON; loaded/saved via keyring
    # anthropic_api_key: str       # keyring.get_password("docu_studio", "anthropic")
    # serper_api_key: str          # keyring.get_password("docu_studio", "serper")
    # elevenlabs_api_key: str      # keyring.get_password("docu_studio", "elevenlabs")
    # pexels_api_key: str          # keyring.get_password("docu_studio", "pexels")
    # pixabay_api_key: str         # keyring.get_password("docu_studio", "pixabay")
```

`Settings.load()` reads JSON from config dir, fills defaults for missing keys.
`Settings.save()` writes only non-secret fields to JSON.
`Settings.get_key(provider)` calls `keyring.get_password()`.
`Settings.set_key(provider, value)` calls `keyring.set_password()`.

---

## Pipeline Events

```python
@dataclass(frozen=True)
class ProgressEvent:
    stage: str           # Stage name, e.g. "TTS Generation"
    scene_index: int     # -1 for pipeline-level events (not scene-specific)
    scene_count: int     # Total scene count (-1 if not yet known)
    message: str         # Human-readable progress message

@dataclass(frozen=True)
class LogEvent:
    level: LogLevel      # LogLevel.INFO | WARNING | ERROR
    message: str         # Must not contain API keys (sanitized by adapter)
    timestamp: datetime

@dataclass(frozen=True)
class ErrorEvent:
    stage: str
    scene_index: int     # -1 for pipeline-level errors
    message: str         # User-readable error message
    fatal: bool          # True → pipeline stops; False → scene flagged, run continues
    timestamp: datetime

class LogLevel(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
```

`PipelineEvent = Union[ProgressEvent, LogEvent, ErrorEvent]`

The pipeline runner puts `PipelineEvent` objects into `queue.Queue`; the GUI pops them
in `after(100, _poll_queue)` and dispatches to the appropriate screen widget.

---

## RunRecord (JSON persistence form)

```python
@dataclass
class RunRecord:
    id: str
    topic: str
    mode: str            # RunMode.value
    status: str          # RunStatus.value
    topic_source: str    # TopicSource.value
    started_at: str      # ISO-8601 datetime
    completed_at: Optional[str]
    project_folder: str  # str(Path)
```

`to_dict()` / `from_dict()` for JSON serialization. Stored in `run_history.json` as a
JSON array, newest first. Max 100 entries retained (oldest pruned on save).
