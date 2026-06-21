# Implementation Plan: Documentary Pre-Production Studio

**Branch**: `001-docu-preprod-studio` | **Date**: 2026-06-22 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/001-docu-preprod-studio/spec.md`

## Summary

Build a native desktop application (Python 3.11+, CustomTkinter) that automates the
research, scripting, voice-over, stock-footage, and FCPXML-export pipeline for documentary
pre-production. The app runs on Windows and macOS with identical features. Every external
service sits behind a swappable provider adapter. All pipeline stages run on a background
thread; the GUI stays responsive via a thread-safe event queue. See [research.md](research.md)
for technology decisions and [data-model.md](data-model.md) for entity definitions.

## Technical Context

**Language/Version**: Python 3.11+

**Primary Dependencies**:
- `customtkinter` — GUI framework
- `anthropic` — Anthropic Claude API SDK (LLM + topic fallback)
- `edge-tts` — Free async TTS (default, no key)
- `elevenlabs` — ElevenLabs TTS SDK (optional, paid)
- `keyring` — OS-native secrets (Windows Credential Manager / macOS Keychain)
- `imageio-ffmpeg` — Bundled FFmpeg binary (no user install required)
- `requests` — HTTP calls for Serper.dev, Pexels, Pixabay adapters
- `PyInstaller` — Native packaging per OS

**Storage**:
- API keys → `keyring` (OS-native, never plaintext)
- Non-secret settings (provider choices, output folder, WPM) → JSON config file in OS config dir
- Run history → JSON file in OS config dir
- Generated assets → per-run project folder chosen by user

**Testing**: `pytest`, `pytest-asyncio`, `responses` (HTTP mocking)

**Target Platform**: Windows 10+ and macOS 12+; identical feature set on both

**Project Type**: Desktop application

**Performance Goals**:
- GUI remains responsive at all times (pipeline on background thread)
- Per-scene sync invariant: video duration == audio duration ±50 ms (SC-002)
- Error displayed in GUI within 5 s of occurrence (SC-003)

**Constraints**:
- One active run at a time (FR assumption)
- No cross-compilation; PyInstaller builds run natively on each target OS
- Sequential scene processing in v1 (FR-031)
- No run resume in v1 (FR-033)
- `check_license()` always returns `True` (FR-028); no license logic

**Scale/Scope**: Single-user desktop tool; one pipeline run at a time; no server component

## Constitution Check

*GATE: Must pass before implementation begins. Re-checked after Phase 1 design.*

### I. Provider-Agnostic Design ✅

- `LLMProvider` ABC in `adapters/llm/base.py`; `AnthropicAdapter` is the only concrete class
- `TopicDiscoveryProvider` ABC in `adapters/topic_discovery/base.py`; `SerperAdapter` implements it and internally uses the `LLMProvider` for fallback — not by reaching into Anthropic directly
- `TTSProvider` ABC in `adapters/tts/base.py`; two implementations: `EdgeTTSAdapter`, `ElevenLabsAdapter`
- `FootageProvider` ABC in `adapters/footage/base.py`; two implementations: `PexelsAdapter`, `PixabayAdapter`
- Pipeline orchestrator (`pipeline/runner.py`) imports only the four ABCs; zero provider SDK imports in pipeline code
- Adding a new provider (e.g. Storyblocks) requires only a new `FootageProvider` subclass; zero pipeline changes

### II. Configuration-First ✅

- All provider selections, output folder path, and narration WPM live in `config/settings.py`
- Defaults in `config/defaults.py` (WPM=150, output=platform config dir)
- GUI Settings screen is the only interface for changing configuration
- No hardcoded provider names, paths, or tunable values anywhere in pipeline or adapter code

### III. Graceful Degradation ✅

- Retry decorator (`retry.py`): 3 attempts, exponential backoff, applied to every external API call (FR-030)
- After retries exhausted → `PipelineError` raised → runner catches → `ErrorEvent` pushed to queue → GUI displays within 5 s
- Serper failure → `SerperAdapter.discover_topic()` catches and delegates to `LLMProvider.suggest_topic()` (FR-005/FR-006)
- Footage shortage → flagged via `ErrorEvent` with `shortage=True`; run continues with remaining scenes (FR-014)
- Export gate checks sync invariant before writing FCPXML; export fails with clear error if invariant violated (Principle V)
- Run never sets status=`completed` when any stage produced incomplete output (FR-033)

### IV. Local-First, Secret-Safe ✅

- All API keys stored via `keyring.set_password()` / `keyring.get_password()` (FR-020)
- Keys never written to JSON config, log files, or any plaintext path
- Settings screen masks key fields after initial entry
- `LogEvent.message` strings are sanitized — no key interpolation allowed; adapters log only response metadata

### V. Deterministic Sync Contract ✅

- `media/ffmpeg_wrapper.py` measures exact audio and video durations via `ffprobe`
- `media/fcpxml_generator.py` is an export gate: `validate_sync(scenes)` runs before writing any file
- If any scene's `|video_duration − audio_duration| > 0.050 s` → export aborts with `ExportSyncError`
- `footage_assembly.py` enforces trim/concat logic: clips trimmed to exact audio duration; final clip trimmed to land on audio endpoint

### VI. Cross-Platform Parity ✅

- `platform_layer.py` is the single location of all `platform.system()` branches
- Provides: `config_dir()`, `ffmpeg_exe()`, `ffprobe_exe()`
- `imageio-ffmpeg` resolves the correct bundled binary per OS automatically
- `keyring` selects the correct backend (Windows Credential Manager / macOS Keychain) per OS automatically
- CustomTkinter renders natively on both platforms; look-and-feel differences are acceptable (Assumption in spec)
- PyInstaller builds are separate and native; `build/windows/` and `build/macos/` specs differ only in platform-specific paths

### VII. Observable Pipeline ✅

- `pipeline/events.py`: `ProgressEvent`, `LogEvent`, `ErrorEvent` dataclasses
- `PipelineRunner` pushes events to a `queue.Queue`; GUI polls via `CTk.after(100, poll_queue)`
- Every stage emits at least one `ProgressEvent` on start and one `LogEvent` on completion
- All events written to `pipeline_log.txt` inside the project folder (FR-018)
- `LogEvent.message` sanitized — no API keys, no raw response bodies with credentials

### VIII. Incremental Phases ✅

- `licensing.py` contains exactly one function: `check_license() -> bool: return True`
- Called once in `__main__.py` at startup; result checked but enforcement is a no-op in v1
- A comment marks it as the Phase 2 insertion point
- No license logic, server calls, MAC address checks, or trial counters anywhere in v1

## Project Structure

### Documentation (this feature)

```text
specs/001-docu-preprod-studio/
├── plan.md              # This file
├── research.md          # Phase 0: technology decisions
├── data-model.md        # Phase 1: entities and state
├── quickstart.md        # Phase 1: dev setup guide
├── contracts/
│   └── provider-interfaces.md  # Phase 1: ABC contracts
└── tasks.md             # Phase 2: generated by /speckit-tasks
```

### Source Code (repository root)

```text
docu_studio/                         # Python package
├── __main__.py                      # Entry point; check_license(); launch GUI
├── licensing.py                     # check_license() → True  [Phase 2 stub]
├── platform_layer.py                # config_dir(), ffmpeg_exe(), ffprobe_exe()
├── retry.py                         # @retry(max_attempts, backoff_factor) decorator
├── config/
│   ├── settings.py                  # Settings dataclass; load/save JSON + keyring
│   └── defaults.py                  # DEFAULT_WPM=150, default output folder constant
├── adapters/
│   ├── llm/
│   │   ├── base.py                  # LLMProvider ABC
│   │   └── anthropic_adapter.py     # AnthropicAdapter
│   ├── topic_discovery/
│   │   ├── base.py                  # TopicDiscoveryProvider ABC + TopicResult
│   │   └── serper_adapter.py        # SerperAdapter; Anthropic fallback via LLMProvider
│   ├── tts/
│   │   ├── base.py                  # TTSProvider ABC
│   │   ├── edge_tts_adapter.py      # EdgeTTSAdapter (free, default, async internally)
│   │   └── elevenlabs_adapter.py    # ElevenLabsAdapter (paid, optional)
│   └── footage/
│       ├── base.py                  # FootageProvider ABC + FootageClip
│       ├── pexels_adapter.py        # PexelsAdapter
│       └── pixabay_adapter.py       # PixabayAdapter
├── pipeline/
│   ├── events.py                    # ProgressEvent, LogEvent, ErrorEvent
│   ├── runner.py                    # PipelineRunner(Thread); Queue[PipelineEvent]
│   └── stages/
│       ├── topic_discovery.py       # Stage 0: Full Auto topic discovery
│       ├── script_gen.py            # Stage 1: script via LLMProvider
│       ├── scene_break.py           # Stage 2: scenes via LLMProvider
│       ├── tts_gen.py               # Stage 3: per-scene TTS via TTSProvider
│       ├── keyword_extract.py       # Stage 4: visual keywords via LLMProvider
│       ├── footage_assembly.py      # Stage 5+6: search + trim/concat/mux
│       └── fcpxml_export.py         # Stage 7: sync-gate + generate + write
├── media/
│   ├── ffmpeg_wrapper.py            # get_duration, trim, concat, mux (subprocess)
│   └── fcpxml_generator.py          # generate_fcpxml(scenes, folder) → str (pure)
├── history/
│   └── run_history.py               # RunRecord; load_history(), save_run()
├── output/
│   └── project_folder.py            # create_project_folder(topic, ts) → Path
└── gui/
    ├── app.py                       # DocsStudioApp(CTk); after()-based queue poll
    └── screens/
        ├── main_screen.py           # Run history list + Start Run button
        ├── run_config_screen.py     # Mode, topic, duration inputs
        ├── progress_screen.py       # Stage/scene progress + log + Cancel button
        └── settings_screen.py       # Keys (masked), providers, folder, WPM

tests/
├── conftest.py
├── unit/
│   ├── test_ffmpeg_wrapper.py       # trim/concat/mux logic; subprocess mocked
│   ├── test_fcpxml_generator.py     # pure function; no I/O; sync-gate assertions
│   └── test_retry.py               # retry + backoff behavior
└── integration/
    ├── test_anthropic_adapter.py    # HTTP-mocked via responses
    ├── test_serper_adapter.py       # HTTP-mocked; fallback path covered
    ├── test_edge_tts_adapter.py     # async; edge-tts network mocked
    ├── test_elevenlabs_adapter.py   # HTTP-mocked
    ├── test_pexels_adapter.py       # HTTP-mocked
    └── test_pixabay_adapter.py      # HTTP-mocked

build/
├── windows/
│   └── docu_studio.spec            # PyInstaller spec (.exe); ffmpeg data file included
└── macos/
    └── docu_studio.spec            # PyInstaller spec (.app/.dmg); ffmpeg data file included

requirements.txt
requirements-dev.txt                # pytest, pytest-asyncio, responses
```

**Structure Decision**: Single-package layout (`docu_studio/`). The adapter, pipeline,
media, history, output, and GUI sub-packages map 1:1 to the four architecture boundaries
defined in the constitution (Adapter, Settings, Platform, Export Gate).

## Implementation Phases

### Phase 0: Foundation

**Goal**: Runnable skeleton with all boundaries in place; no provider calls yet.

| Task | File(s) | Notes |
|------|---------|-------|
| Python project scaffold | `pyproject.toml`, `requirements.txt`, `requirements-dev.txt` | Python 3.11+, editable install |
| Platform layer | `platform_layer.py` | `config_dir()`, `ffmpeg_exe()`, `ffprobe_exe()` — all OS branches here only |
| License stub | `licensing.py` | `check_license() -> bool: return True` + Phase 2 comment |
| Entry point | `__main__.py` | `check_license()`; start GUI; nothing else |
| Retry decorator | `retry.py` | `@retry(max_attempts=3, backoff_factor=2.0)`; raises after all attempts |
| Settings layer | `config/settings.py`, `config/defaults.py` | `Settings` dataclass; `load()` / `save()`; keyring for keys, JSON for rest |

### Phase 1: Provider Adapters

**Goal**: All four provider categories implemented and individually testable.

| Task | File(s) | Notes |
|------|---------|-------|
| LLM interface | `adapters/llm/base.py` | `generate_script`, `break_into_scenes`, `extract_visual_keywords`, `suggest_topic` |
| Anthropic adapter | `adapters/llm/anthropic_adapter.py` | `@retry` on every API call; structured output via Claude |
| Topic discovery interface | `adapters/topic_discovery/base.py` | Returns `TopicResult(topic, source, fallback_triggered)` |
| Serper adapter | `adapters/topic_discovery/serper_adapter.py` | Calls Serper.dev; on failure delegates to `LLMProvider.suggest_topic()` |
| TTS interface | `adapters/tts/base.py` | `synthesize(text, output_path) -> float` (returns duration seconds) |
| Edge-TTS adapter | `adapters/tts/edge_tts_adapter.py` | `asyncio.run()` wraps async edge-tts call; no API key |
| ElevenLabs adapter | `adapters/tts/elevenlabs_adapter.py` | Key from keyring; `@retry` on API call |
| Footage interface | `adapters/footage/base.py` | `search(keywords, min_duration) -> List[FootageClip]` |
| Pexels adapter | `adapters/footage/pexels_adapter.py` | Key from keyring; `requests`; `@retry` |
| Pixabay adapter | `adapters/footage/pixabay_adapter.py` | Key from keyring; `requests`; `@retry` |

### Phase 2: Media Processing

**Goal**: FFmpeg wrapper and FCPXML generator fully tested as pure/isolated units.

| Task | File(s) | Notes |
|------|---------|-------|
| FFmpeg wrapper | `media/ffmpeg_wrapper.py` | `get_duration`, `trim_clip`, `concat_clips`, `mux_audio_video`; uses `imageio_ffmpeg.get_ffmpeg_exe()` and `ffprobe_exe()` |
| FCPXML generator | `media/fcpxml_generator.py` | `generate_fcpxml(scenes, project_folder) -> str`; pure function; sync-gate runs before any file write |
| Unit tests | `tests/unit/test_ffmpeg_wrapper.py`, `tests/unit/test_fcpxml_generator.py` | No network; subprocess mocked for ffmpeg tests |

### Phase 3: Pipeline

**Goal**: End-to-end pipeline runnable in tests with all providers mocked.

| Task | File(s) | Notes |
|------|---------|-------|
| Event types | `pipeline/events.py` | `ProgressEvent`, `LogEvent`, `ErrorEvent` frozen dataclasses |
| Stage 0 | `pipeline/stages/topic_discovery.py` | Full Auto only; returns `TopicResult` |
| Stage 1 | `pipeline/stages/script_gen.py` | `LLMProvider.generate_script(topic, target_words)` |
| Stage 2 | `pipeline/stages/scene_break.py` | `LLMProvider.break_into_scenes(script)` → `List[Scene]` |
| Stage 3 | `pipeline/stages/tts_gen.py` | Sequential per-scene; `TTSProvider.synthesize()`; emits per-scene progress |
| Stage 4 | `pipeline/stages/keyword_extract.py` | `LLMProvider.extract_visual_keywords()` per scene |
| Stage 5+6 | `pipeline/stages/footage_assembly.py` | Search → trim/concat → mux per scene; shortage flag on exhaustion |
| Stage 7 | `pipeline/stages/fcpxml_export.py` | Sync gate → `generate_fcpxml` → write `timeline.fcpxml` |
| Pipeline runner | `pipeline/runner.py` | `PipelineRunner(Thread)`; cancellation via `threading.Event`; pushes to `queue.Queue` |
| Run history | `history/run_history.py` | `load_history() -> List[RunRecord]`; `save_run(run)` |
| Project folder | `output/project_folder.py` | Creates `{topic}_{timestamp}/`; writes `script.md`, `scenes.json`; returns `Path` |

### Phase 4: GUI

**Goal**: Fully interactive GUI connected to the live pipeline runner.

| Task | File(s) | Notes |
|------|---------|-------|
| App root | `gui/app.py` | `DocsStudioApp(CTk)`; `after(100, _poll_queue)`; screen navigation |
| Main screen | `gui/screens/main_screen.py` | Scrollable run history list; each row shows topic, date, status, Open Folder button |
| Run config screen | `gui/screens/run_config_screen.py` | Mode toggle (Guided/Full Auto), topic entry (hidden in Full Auto), duration slider |
| Progress screen | `gui/screens/progress_screen.py` | Stage name, scene N of M, scrollable log, Cancel button |
| Settings screen | `gui/screens/settings_screen.py` | Masked key fields, TTS radio, footage checkboxes, folder picker, WPM slider |

### Phase 5: Integration Tests

**Goal**: 80%+ coverage of adapter logic via HTTP-mocked tests.

| Task | File(s) |
|------|---------|
| Anthropic adapter tests | `tests/integration/test_anthropic_adapter.py` |
| Serper adapter tests (success + fallback) | `tests/integration/test_serper_adapter.py` |
| Edge-TTS adapter tests | `tests/integration/test_edge_tts_adapter.py` |
| ElevenLabs adapter tests | `tests/integration/test_elevenlabs_adapter.py` |
| Pexels adapter tests | `tests/integration/test_pexels_adapter.py` |
| Pixabay adapter tests | `tests/integration/test_pixabay_adapter.py` |

### Phase 6: Packaging

**Goal**: Distributable single-file executables on each target OS.

| Task | File(s) | Notes |
|------|---------|-------|
| Windows PyInstaller spec | `build/windows/docu_studio.spec` | One-file `.exe`; ffmpeg binary as data; `--noconsole` |
| macOS PyInstaller spec | `build/macos/docu_studio.spec` | `.app` bundle; ffmpeg binary as data; `--windowed` |
| Build docs | `quickstart.md` (packaging section) | Native build steps per OS; no cross-compile |

## Complexity Tracking

No constitution violations. No complexity exceptions required.
