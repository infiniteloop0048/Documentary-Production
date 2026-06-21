# Tasks: Documentary Pre-Production Studio

**Input**: Design documents from `specs/001-docu-preprod-studio/`

**Prerequisites**: plan.md ✅ spec.md ✅ research.md ✅ data-model.md ✅ contracts/ ✅ quickstart.md ✅

**Tests**: Included — spec explicitly requests unit tests for media processing and FCPXML generator, and HTTP-mocked integration tests for all provider adapters.

**Organization**: Tasks grouped by user story. US1 (Guided Mode) is the MVP; US2–US4 layer on top.

## Format: `[ID] [P?] [Story?] Description`

- **[P]**: Can run in parallel (different files, no blocking dependency)
- **[Story]**: Which user story ([US1]–[US4]) — omitted for Setup and Foundational phases

---

## Phase 1: Setup (Project Scaffold)

**Purpose**: Create the project skeleton so all subsequent tasks have a home.

- [ ] T001 Create full `docu_studio/` package tree with empty `__init__.py` files per plan.md directory structure
- [ ] T002 Create `pyproject.toml` declaring Python 3.11+, package name `docu_studio`, entry point `docu_studio.__main__:main`, and all runtime dependencies
- [ ] T003 [P] Create `requirements.txt` (customtkinter, anthropic, edge-tts, elevenlabs, keyring, imageio-ffmpeg, requests, platformdirs)
- [ ] T004 [P] Create `requirements-dev.txt` (pytest, pytest-asyncio, pytest-cov, responses, ruff)
- [ ] T005 [P] Create `tests/` directory with `tests/unit/`, `tests/integration/`, and `tests/conftest.py` stubs

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure every pipeline stage and GUI screen depends on. All user story work is blocked until this phase is complete.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [ ] T006 Implement `docu_studio/platform_layer.py` with `config_dir() -> Path`, `ffmpeg_exe() -> str`, `ffprobe_exe() -> str` — all OS branches isolated here only (no `platform.system()` elsewhere)
- [ ] T007 [P] Implement `docu_studio/licensing.py` with `check_license() -> bool: return True` and a comment marking it as the Phase 2 insertion point
- [ ] T008 [P] Implement `docu_studio/retry.py` with `@retry(max_attempts=3, backoff_factor=2.0, base_delay=1.0)` decorator — catches Exception, re-raises unchanged on final attempt
- [ ] T009 Implement `docu_studio/config/defaults.py` (DEFAULT_WPM=150, DEFAULT_LLM_MODEL_SCRIPT, DEFAULT_LLM_MODEL_KEYWORDS, DEFAULT_TTS_PROVIDER, DEFAULT_FOOTAGE_PROVIDERS list)
- [ ] T010 Implement `docu_studio/config/settings.py` — `Settings` dataclass with `load() / save()` for non-secret JSON fields via `platformdirs.user_config_dir()`, and `get_key(provider) / set_key(provider, value)` via `keyring`
- [ ] T011 [P] Implement `docu_studio/pipeline/events.py` — `ProgressEvent`, `LogEvent`, `ErrorEvent`, `LogLevel` as frozen dataclasses; define `PipelineEvent = Union[...]`
- [ ] T012 [P] Implement `docu_studio/output/project_folder.py` — `create_project_folder(topic: str, ts: datetime, base: Path) -> Path`; creates `{topic}_{timestamp}/`, `audio/`, `video/` subdirs; writes `script.md` and `scenes.json` placeholders
- [ ] T013 [P] Implement `docu_studio/history/run_history.py` — `RunRecord` dataclass with `to_dict/from_dict`; `load_history() -> List[RunRecord]`; `save_run(run: RunRecord)` with atomic write and max-100 pruning

**Checkpoint**: Foundation ready — user story implementation can now begin.

---

## Phase 3: User Story 1 — Guided Mode End-to-End Run (Priority: P1) 🎯 MVP

**Goal**: A user provides a topic and duration; the app runs the complete pipeline and produces a project folder with script, per-scene audio, per-scene synced video, FCPXML, and run log.

**Independent Test**: Enter topic "The Apollo 11 mission" and duration 20 minutes, start a Guided Mode run with all providers configured, and verify the project folder contains all required files with audio/video sync within 50 ms per scene.

### Tests for User Story 1

> **Write these tests FIRST; verify they FAIL before implementing the corresponding code**

- [ ] T014 [P] [US1] Write unit test for `FFmpegWrapper` in `tests/unit/test_ffmpeg_wrapper.py` — mock `subprocess.run`; assert correct command args for `get_duration`, `trim_clip`, `concat_clips`, `mux_audio_video`; assert `FFmpegError` on non-zero exit
- [ ] T015 [P] [US1] Write unit test for `fcpxml_generator` in `tests/unit/test_fcpxml_generator.py` — pass `List[FinalScene]` with known durations; assert FCPXML XML structure, scene marker count, sync gate raises `ExportSyncError` when invariant violated
- [ ] T016 [P] [US1] Write unit test for `retry.py` in `tests/unit/test_retry.py` — mock function that raises N times; assert retry count, backoff sleep calls, and that exception propagates after all attempts exhausted

### Implementation for User Story 1

**Provider ABCs** (must precede all adapter implementations):

- [ ] T017 [P] [US1] Implement `docu_studio/adapters/llm/base.py` — `LLMProvider` ABC with `generate_script`, `break_into_scenes`, `extract_visual_keywords`, `suggest_topic` abstract methods
- [ ] T018 [P] [US1] Implement `docu_studio/adapters/tts/base.py` — `TTSProvider` ABC with `synthesize(text, output_path) -> float` abstract method
- [ ] T019 [P] [US1] Implement `docu_studio/adapters/footage/base.py` — `FootageProvider` ABC with `search(keywords, min_duration) -> List[FootageClip]`; define `FootageClip` frozen dataclass

**Media layer** (depends on T006 for platform_layer):

- [ ] T020 [US1] Implement `docu_studio/media/ffmpeg_wrapper.py` — `FFmpegWrapper` with `get_duration`, `trim_clip`, `concat_clips`, `mux_audio_video`; uses `imageio_ffmpeg.get_ffmpeg_exe()` and `platform_layer.ffprobe_exe()`; raises `FFmpegError` on failure
- [ ] T021 [US1] Implement `docu_studio/media/fcpxml_generator.py` — `validate_sync(scenes, tolerance_s=0.050)` raises `ExportSyncError` on violation; `generate_fcpxml(scenes, project_folder, topic) -> str` pure function returning FCPXML 1.9 string with scene markers

**Concrete adapters** (depend on T017–T019 for base ABCs, T008 for retry):

- [ ] T022 [US1] Implement `docu_studio/adapters/llm/anthropic_adapter.py` — `AnthropicAdapter(LLMProvider)` with `@retry` on every API call; uses `anthropic` SDK; structured output via tool-use for `break_into_scenes` and `extract_visual_keywords`
- [ ] T023 [P] [US1] Implement `docu_studio/adapters/tts/edge_tts_adapter.py` — `EdgeTTSAdapter(TTSProvider)` wrapping async `edge_tts` with `asyncio.run()`; calls `FFmpegWrapper.get_duration()` to return verified float; no API key
- [ ] T024 [P] [US1] Implement `docu_studio/adapters/tts/elevenlabs_adapter.py` — `ElevenLabsAdapter(TTSProvider)` using `elevenlabs` SDK; key from `Settings.get_key("elevenlabs")`; `@retry` on API call
- [ ] T025 [P] [US1] Implement `docu_studio/adapters/footage/pexels_adapter.py` — `PexelsAdapter(FootageProvider)` using `requests`; key from `Settings.get_key("pexels")`; `@retry`; returns `List[FootageClip]` ordered by relevance
- [ ] T026 [P] [US1] Implement `docu_studio/adapters/footage/pixabay_adapter.py` — `PixabayAdapter(FootageProvider)` using `requests`; key from `Settings.get_key("pixabay")`; `@retry`; returns `List[FootageClip]`

**Pipeline stages** (each imports only ABCs, not concrete adapters):

- [ ] T027 [US1] Implement `docu_studio/pipeline/stages/script_gen.py` — Stage 1: call `LLMProvider.generate_script(topic, target_words)`, push `ProgressEvent` and `LogEvent`, write `script.md` to project folder
- [ ] T028 [US1] Implement `docu_studio/pipeline/stages/scene_break.py` — Stage 2: call `LLMProvider.break_into_scenes(script)`, construct `List[Scene]`, push progress, write `scenes.json`
- [ ] T029 [US1] Implement `docu_studio/pipeline/stages/tts_gen.py` — Stage 3: iterate scenes sequentially, call `TTSProvider.synthesize()`, set `scene.audio_path` and `scene.audio_duration`, push per-scene progress
- [ ] T030 [US1] Implement `docu_studio/pipeline/stages/keyword_extract.py` — Stage 4: per scene call `LLMProvider.extract_visual_keywords(title, narration)`, set `scene.visual_keywords`, push progress
- [ ] T031 [US1] Implement `docu_studio/pipeline/stages/footage_assembly.py` — Stages 5+6: per scene search enabled `FootageProvider` list, accumulate clips, trim/concat/mux via `FFmpegWrapper`, set `scene.video_path` and `scene.video_duration`; if clips exhausted push `ErrorEvent(fatal=False)` and set `scene.footage_shortage=True`
- [ ] T032 [US1] Implement `docu_studio/pipeline/stages/fcpxml_export.py` — Stage 7: collect `FinalScene` list, call `validate_sync()`, call `generate_fcpxml()`, write `timeline.fcpxml` to project folder, push completion events
- [ ] T033 [US1] Implement `docu_studio/pipeline/runner.py` — `PipelineRunner(threading.Thread)`: runs stages 1–7 sequentially, checks `cancel_event` between stages and between scenes, pushes all events to `queue.Queue`, calls `save_run()` with final `RunStatus` on exit (completed/cancelled/failed)

**GUI** (depends on T033 for runner interface):

- [ ] T034 [US1] Implement `docu_studio/gui/app.py` — `DocsStudioApp(CTk)`: screen stack navigation (`show_screen()`), `after(100, _poll_queue)` queue drainer that dispatches events to the active screen, call `check_license()` at startup
- [ ] T035 [US1] Implement `docu_studio/gui/screens/run_config_screen.py` — Guided Mode fields: topic entry, duration slider (5–120 min), Start Run button; wires to `PipelineRunner` and transitions to `ProgressScreen`
- [ ] T036 [US1] Implement `docu_studio/gui/screens/progress_screen.py` — shows stage name, "Scene N of M", scrollable log widget, Cancel button that sets `cancel_event`; renders `ProgressEvent`, `LogEvent`, `ErrorEvent` from queue
- [ ] T037 [US1] Implement `docu_studio/gui/screens/main_screen.py` — scrollable run history list (topic, date, status badge, Open Folder button per row); Start New Run button; loads `load_history()` at screen init
- [ ] T038 [US1] Wire end-to-end: `DocsStudioApp` launches `PipelineRunner` from `RunConfigScreen.start_run()`, queue drains to `ProgressScreen`, on run end navigate to `MainScreen` and refresh history

**Adapter integration tests** (all parallel; HTTP-mocked via `responses`):

- [ ] T039 [P] [US1] Write integration test for `AnthropicAdapter` in `tests/integration/test_anthropic_adapter.py` — mock HTTP; assert `generate_script` returns str, `break_into_scenes` returns list of scene dicts, `extract_visual_keywords` returns list of strings
- [ ] T040 [P] [US1] Write integration test for `EdgeTTSAdapter` in `tests/integration/test_edge_tts_adapter.py` — mock `edge_tts` library at boundary; assert `synthesize` writes file and returns duration float
- [ ] T041 [P] [US1] Write integration test for `ElevenLabsAdapter` in `tests/integration/test_elevenlabs_adapter.py` — mock HTTP; assert `synthesize` calls API with key and returns duration
- [ ] T042 [P] [US1] Write integration test for `PexelsAdapter` in `tests/integration/test_pexels_adapter.py` — mock HTTP; assert `search` returns `List[FootageClip]`; assert empty list on 404
- [ ] T043 [P] [US1] Write integration test for `PixabayAdapter` in `tests/integration/test_pixabay_adapter.py` — mock HTTP; assert `search` returns `List[FootageClip]`; assert empty list on API error

**Checkpoint**: Guided Mode end-to-end run is fully functional and independently testable.

---

## Phase 4: User Story 2 — Full Automation Mode (Priority: P2)

**Goal**: User enters only a duration; app discovers a trending topic via Serper.dev (or Claude fallback) and runs the complete pipeline; run log shows topic source.

**Independent Test**: Select Full Auto Mode, enter 20 minutes, start run. Verify run log shows either `"topic_source": "web_search"` or `"topic_source": "ai_suggested"` plus `"fallback_triggered": true/false`. Verify GUI labels the source before the pipeline proceeds.

### Implementation for User Story 2

- [ ] T044 [US2] Implement `docu_studio/adapters/topic_discovery/base.py` — `TopicDiscoveryProvider` ABC with `discover_topic(llm_fallback: LLMProvider) -> TopicResult`; define `TopicResult` frozen dataclass (`topic`, `source`, `fallback_triggered`)
- [ ] T045 [US2] Implement `docu_studio/adapters/topic_discovery/serper_adapter.py` — `SerperAdapter(TopicDiscoveryProvider)`: call Serper.dev API with `@retry`; on failure or empty result call `llm_fallback.suggest_topic()` and set `fallback_triggered=True`; key from `Settings.get_key("serper")`
- [ ] T046 [US2] Implement `docu_studio/pipeline/stages/topic_discovery.py` — Stage 0: instantiate configured `TopicDiscoveryProvider`, call `discover_topic(llm_provider)`, push `ProgressEvent` with source label (`"web search"` or `"AI suggestion (search unavailable)"`), return `TopicResult`
- [ ] T047 [US2] Update `docu_studio/gui/screens/run_config_screen.py` — add Full Auto / Guided mode toggle; hide topic field in Full Auto mode; display discovered topic in `ProgressScreen` log before pipeline continues (FR-006)
- [ ] T048 [US2] Update `docu_studio/pipeline/runner.py` — run Stage 0 (`topic_discovery`) when `run.mode == RunMode.FULL_AUTO`; set `run.topic` and `run.topic_source` from `TopicResult` before Stage 1

### Tests for User Story 2

- [ ] T049 [P] [US2] Write integration test for `SerperAdapter` in `tests/integration/test_serper_adapter.py` — two cases: (1) successful search returns `TopicResult(source=WEB_SEARCH, fallback_triggered=False)`; (2) HTTP error triggers fallback to `LLMProvider.suggest_topic()` mock, returns `TopicResult(source=AI_SUGGESTED, fallback_triggered=True)`

**Checkpoint**: Full Automation Mode discovers a topic and logs its source; pipeline then completes identically to Guided Mode.

---

## Phase 5: User Story 3 — Per-Scene Footage Shortage Handling (Priority: P3)

**Goal**: When stock footage is exhausted for a scene, the shortage is flagged in GUI and log without crashing; remaining scenes complete normally.

**Independent Test**: Simulate footage shortage by providing API responses with insufficient clip durations for scene 2 of a 3-scene run. Verify GUI shows a shortage warning for scene 2, all other scenes complete, and run status is `completed` (not `failed`).

### Implementation for User Story 3

- [ ] T050 [US3] Audit `docu_studio/pipeline/stages/footage_assembly.py` (T031): confirm `ErrorEvent(fatal=False, shortage=True)` is pushed to queue and `scene.footage_shortage=True` is set; add `shortage` field to `ErrorEvent` if not yet present; run continues to next scene
- [ ] T051 [US3] Update `docu_studio/gui/screens/progress_screen.py` — render `ErrorEvent` with `fatal=False` as a yellow/warning row distinct from red fatal errors; show human-readable shortage message (FR-014)

### Tests for User Story 3

- [ ] T052 [P] [US3] Write integration test for footage shortage path in `tests/integration/test_footage_shortage.py` — mock both `PexelsAdapter.search` and `PixabayAdapter.search` to return clips shorter than audio duration with no further results; assert `ErrorEvent(fatal=False)` is in the event queue and subsequent scenes are processed

**Checkpoint**: Footage shortage is visible in GUI and run log; run completes with remaining scenes intact.

---

## Phase 6: User Story 4 — Settings Configuration (Priority: P4)

**Goal**: Non-technical user configures all API keys, provider selections, output folder, and narration pace through the Settings screen; all settings persist across restarts.

**Independent Test**: Open Settings, enter API keys for all providers, switch TTS to ElevenLabs, disable Pixabay, change output folder, set WPM to 130, save, restart app, open Settings — verify all values are restored correctly. Verify API key field shows masked text after save.

### Implementation for User Story 4

- [ ] T053 [US4] Implement `docu_studio/gui/screens/settings_screen.py` — sections: API Keys (masked entry fields per provider, show/hide toggle), TTS Provider (radio: Edge-TTS / ElevenLabs), Footage Providers (checkboxes: Pexels, Pixabay), Output Folder (path entry + Browse button via `tkinter.filedialog`), WPM (slider 80–250), Save button
- [ ] T054 [US4] Wire Settings screen save action: call `Settings.set_key(provider, value)` for each key field that changed, then `Settings.save()` for non-secret fields; reload `Settings` from disk on next app start to verify persistence
- [ ] T055 [US4] Add Settings button to `docu_studio/gui/screens/main_screen.py` and wire it to navigate to `SettingsScreen`; on first launch with no keys configured, open Settings automatically

**Checkpoint**: All Settings configurable and persisted; API keys never appear in plaintext files or logs.

---

## Phase 7: Polish & Packaging

**Purpose**: Cross-cutting quality checks, build specs, and coverage validation.

- [ ] T056 [P] Create `build/windows/docu_studio.spec` — PyInstaller one-file `.exe` spec: `datas` for imageio-ffmpeg binary, `--noconsole`, hiddenimports for keyring backends and customtkinter
- [ ] T057 [P] Create `build/macos/docu_studio.spec` — PyInstaller `.app` bundle spec: `datas` for imageio-ffmpeg binary, `--windowed`, correct macOS bundle metadata (CFBundleName, CFBundleIdentifier)
- [ ] T058 Run full test suite and verify 80%+ coverage: `pytest --cov=docu_studio --cov-report=term-missing`; identify and fill any gaps below threshold
- [ ] T059 [P] Verify no API key leaks: grep `LogEvent.message` construction sites across all adapters to confirm no key interpolation; check `pipeline_log.txt` output path is sanitized
- [ ] T060 [P] Validate `quickstart.md` dev-setup instructions on a clean virtualenv: follow steps end-to-end and confirm all commands succeed

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Depends on Phase 1 — **blocks all user stories**
- **US1 (Phase 3)**: Depends on Phase 2 — MVP; blocks nothing downstream but US2–US4 can start in parallel once Phase 2 is done
- **US2 (Phase 4)**: Depends on Phase 2 + US1 pipeline runner (`runner.py`) being stable (T033)
- **US3 (Phase 5)**: Depends on footage_assembly.py (T031) from Phase 3
- **US4 (Phase 6)**: Depends on Phase 2 (Settings) and GUI app.py (T034) from Phase 3
- **Polish (Phase 7)**: Depends on all desired user story phases being complete

### User Story Dependencies

- **US1 (P1)**: After Phase 2 — no dependency on other stories; this is the MVP
- **US2 (P2)**: After Phase 2 + T033 (runner) from US1 — integrates as Stage 0 in the runner
- **US3 (P3)**: After T031 (footage_assembly) from US1 — audit + extend existing code
- **US4 (P4)**: After Phase 2 + T034 (gui/app.py) from US1 — pure GUI layer addition

### Within Each User Story

- Test stubs written FIRST (fail before implementation)
- ABCs implemented before concrete adapters
- Media layer before pipeline stages (stages call media layer)
- Pipeline stages before runner (runner orchestrates stages)
- GUI screens before wiring (wiring connects them)

### Parallel Opportunities

- All `[P]`-marked tasks share no files and can run simultaneously
- T014, T015, T016 (unit test stubs) can all be written in parallel
- T017, T018, T019 (ABCs) can be written in parallel
- T023, T024, T025, T026 (concrete adapters after ABCs) can be written in parallel
- T039–T043 (adapter integration tests) can all be written in parallel
- T056, T057 (PyInstaller specs) can be written in parallel

---

## Parallel Example: User Story 1 (Phase 3)

```bash
# Round 1 — Tests (all parallel):
Task: "T014 Unit test for FFmpegWrapper in tests/unit/test_ffmpeg_wrapper.py"
Task: "T015 Unit test for fcpxml_generator in tests/unit/test_fcpxml_generator.py"
Task: "T016 Unit test for retry.py in tests/unit/test_retry.py"

# Round 2 — ABCs (all parallel, no deps on each other):
Task: "T017 LLMProvider ABC in docu_studio/adapters/llm/base.py"
Task: "T018 TTSProvider ABC in docu_studio/adapters/tts/base.py"
Task: "T019 FootageProvider ABC + FootageClip in docu_studio/adapters/footage/base.py"

# Round 3 — After ABCs complete, concrete adapters in parallel:
Task: "T023 EdgeTTSAdapter in docu_studio/adapters/tts/edge_tts_adapter.py"
Task: "T024 ElevenLabsAdapter in docu_studio/adapters/tts/elevenlabs_adapter.py"
Task: "T025 PexelsAdapter in docu_studio/adapters/footage/pexels_adapter.py"
Task: "T026 PixabayAdapter in docu_studio/adapters/footage/pixabay_adapter.py"
# Note: T022 AnthropicAdapter is NOT parallel here because it also implements suggest_topic
# used by topic discovery — implement it serially after ABCs

# Round 4 — Adapter integration tests (all parallel):
Task: "T039 test_anthropic_adapter.py"
Task: "T040 test_edge_tts_adapter.py"
Task: "T041 test_elevenlabs_adapter.py"
Task: "T042 test_pexels_adapter.py"
Task: "T043 test_pixabay_adapter.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (**CRITICAL** — blocks all stories)
3. Complete Phase 3: User Story 1 (Guided Mode end-to-end)
4. **STOP and VALIDATE**: Run end-to-end with real API keys; verify project folder contents
5. Ship MVP or demo

### Incremental Delivery

1. Setup + Foundational → skeleton running
2. US1 → Guided Mode → project folder delivered (**demo-able MVP**)
3. US2 → Full Auto Mode → autonomous runs
4. US3 → Shortage handling → robust failure modes
5. US4 → Settings screen → non-technical users can configure
6. Polish → packaging → distributable binaries

### Parallel Team Strategy

With two developers after Phase 2 is complete:
- Developer A: US1 (core pipeline + GUI)
- Developer B: US4 (Settings screen) — Settings layer is done in Phase 2; screen is pure GUI

---

## Notes

- `[P]` tasks touch different files and have no blocking dependency — safe to parallelize
- `[USN]` label maps every task to its user story for traceability and incremental delivery
- Pipeline code (`pipeline/`) MUST import only ABCs (`adapters/*/base.py`) — never concrete adapters
- All OS-specific branches (`platform.system()`, `os.startfile`) stay in `platform_layer.py` only
- API keys must never appear in `LogEvent.message` strings — sanitize before logging
- `validate_sync()` MUST be called before `generate_fcpxml()` — never skip (Constitution Principle V)
- `check_license()` always returns `True` — do not add logic here (Constitution Principle VIII)
- Commit after each completed task or logical group
- Stop at each Checkpoint to validate the user story independently before proceeding
