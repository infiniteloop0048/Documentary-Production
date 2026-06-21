# Phase 0 Research: Documentary Pre-Production Studio

**Date**: 2026-06-22 | **Plan**: [plan.md](plan.md)

All technology decisions below are final. No NEEDS CLARIFICATION items remain.

---

## GUI Framework

**Decision**: CustomTkinter  
**Rationale**: Pure-Python, wraps Tk, supports dark/light themes, ships with no native
binary dependencies, and distributes cleanly with PyInstaller on both Windows and macOS.
Alternatives (PyQt6, wxPython) require separate LGPL/GPL compliance review and produce
larger bundles; Tkinter alone lacks modern styling.  
**Alternatives considered**: PyQt6, wxPython, Dear PyGui, Flet  

---

## Packaging

**Decision**: PyInstaller (one build per target OS, native)  
**Rationale**: Best-in-class Python-to-executable conversion; handles the `imageio-ffmpeg`
bundled binary correctly via `--add-binary` or `datas` in the spec file; supports
`--onefile` mode for Windows and `--windowed` for macOS app bundles. No cross-compilation;
each OS build runs on that OS natively.  
**Alternatives considered**: Nuitka (longer compile time, less ecosystem support), cx_Freeze
(more manual), Briefcase (less PyInstaller spec control for this use case)  

---

## LLM Provider

**Decision**: Anthropic Claude API via `anthropic` Python SDK  
**Rationale**: Required by spec. Used for four distinct operations: `generate_script`,
`break_into_scenes`, `extract_visual_keywords`, `suggest_topic`. Structured JSON output
available via tool-use or response format. SDK is actively maintained.  
**Model selection**: `claude-haiku-4-5` for keyword extraction (speed); `claude-sonnet-4-6`
for script generation and scene breakdown (quality). Both specified per-call, not hardcoded
in adapter — configurable via Settings.  
**Alternatives considered**: N/A (required by spec)  

---

## Topic Discovery

**Decision**: Serper.dev as primary; Anthropic Claude API as fallback  
**Rationale**: Serper.dev provides Google Search results via a simple REST API (no
Puppeteer, no scraping, stable JSON format). Free tier available. On Serper failure or
missing key, `AnthropicAdapter.suggest_topic()` is called — this is an LLM operation
already covered by the existing adapter, keeping the fallback zero-new-dependencies.  
**Fallback label**: `"AI-suggested topic (search unavailable)"` in GUI and log  
**Alternatives considered**: SerpAPI (paid only), DuckDuckGo scraping (fragile),
Brave Search API (requires separate key)  

---

## Text-to-Speech

**Decision**: Edge-TTS (default, free) + ElevenLabs (optional, paid)  
**Rationale**:
- `edge-tts`: Uses Microsoft Edge's TTS engine via WebSocket; no API key; async;
  produces high-quality MP3; widely used in the Python ecosystem. Wrapped with
  `asyncio.run()` inside `EdgeTTSAdapter.synthesize()` so callers see a sync interface.
- `elevenlabs`: Official SDK; supports many voices and voice cloning; API key required.
  Users who want higher quality voice can opt in from Settings.  
**Alternatives considered**: gTTS (Google TTS, lower quality, rate-limited), pyttsx3
(offline but robotic quality), Coqui TTS (heavy GPU model, out of scope for desktop)  

---

## Stock Footage

**Decision**: Pexels API + Pixabay API (both enabled by default, selectable/combinable)  
**Rationale**: Both are free with API keys; both return direct MP4 download URLs; both
have well-documented JSON APIs. Pexels consistently returns higher-quality curated footage;
Pixabay expands the pool. Architecture supports both simultaneously (search Pexels first,
extend with Pixabay clips if shortage), or either alone per user Settings toggle.  
**Provider addition path**: New `FootageProvider` subclass + registration in Settings;
zero pipeline changes.  
**Alternatives considered**: Storyblocks (paid, explicitly out of scope for v1 — flagged
as example future provider in spec), Unsplash (photos only, not video)  

---

## Media Processing

**Decision**: `imageio-ffmpeg` (bundled static binary) + `subprocess` calls  
**Rationale**: `imageio-ffmpeg.get_ffmpeg_exe()` returns the path to a platform-specific
static FFmpeg binary bundled with the package. No user install required. Operations
(`ffprobe` for duration, `ffmpeg` for trim/concat/mux) executed via `subprocess.run()` in
`FFmpegWrapper`. This keeps the wrapper as a thin shell around the binary — no FFmpeg
Python bindings to maintain.  
**FFprobe duration measurement**: `ffprobe -v error -show_entries format=duration -of
default=noprint_wrappers=1:nokey=1 <file>` → parse float seconds  
**Trim**: `-ss 0 -t <duration> -c copy` (stream copy; fast; no re-encode)  
**Concat**: concat demuxer via temporary file list (`-f concat -safe 0 -i list.txt`)  
**Mux**: `-i video.mp4 -i audio.mp3 -c copy -shortest output.mp4`  
**Alternatives considered**: `ffmpeg-python` (extra dependency layer, more complex), moviepy
(heavy; re-encodes by default)  

---

## Secrets Storage

**Decision**: `keyring` library (Windows Credential Manager / macOS Keychain)  
**Rationale**: One-line read/write; automatically selects the OS-native backend; encrypted
at rest by the OS; no plaintext file needed. Service name: `"docu_studio"`, username =
provider name (e.g., `"anthropic"`, `"pexels"`).  
**Alternatives considered**: `python-dotenv` + `.env` file (plaintext, violates Principle IV),
custom AES encryption (requires key management, not better than OS keystore)  

---

## Non-Secret Settings Storage

**Decision**: JSON file in platform config dir  
**Rationale**: Simple, human-inspectable, Python-native (`json` stdlib). Config dir:
`platformdirs.user_config_dir("docu_studio", "DocsStudio")` — returns the correct
platform-standard path on each OS.  
**Fields stored in JSON**: `tts_provider`, `footage_providers`, `output_folder`, `wpm`,
`llm_model_script`, `llm_model_keywords`  
**Fields stored in keyring only**: All API keys  
**Alternatives considered**: TOML (extra dependency), SQLite (overkill for flat settings),
Windows Registry (platform-locked)  

---

## Concurrency

**Decision**: `threading.Thread` for pipeline; `queue.Queue` for GUI events;
`customtkinter.CTk.after()` for GUI poll  
**Rationale**: CustomTkinter (and Tkinter) require all GUI mutations on the main thread.
Running the pipeline on a `Thread` with a `Queue` is the standard Tk pattern.
`asyncio` would require wrapping Tk's event loop, which is complex and fragile. The pipeline
has no concurrent-scene logic in v1 (FR-031), so one thread is sufficient.  
**Cancellation**: `threading.Event` — pipeline checks `cancel_event.is_set()` between
stages and between scenes. Cancel is cooperative (checked at stage boundaries), not preemptive.  
**GUI poll interval**: 100 ms via `after(100, _poll_queue)` — responsive without busy-loop  
**Alternatives considered**: `asyncio` + Tk integration (fragile), `multiprocessing` (IPC
complexity not justified by v1 scope)  

---

## Retry Policy

**Decision**: Decorator `@retry(max_attempts=3, backoff_factor=2.0, base_delay=1.0)`  
**Behavior**: Attempt 1 → fail → sleep 1 s → Attempt 2 → fail → sleep 2 s → Attempt 3 →
fail → raise `PipelineError`. Applied to every method in every adapter that makes a network
call.  
**Implementation**: Simple decorator in `retry.py`; catches `Exception` (or a configurable
exception type); re-raises unchanged on final attempt.  
**Alternatives considered**: `tenacity` library (heavier dependency, API surface larger
than needed)  

---

## Run History Persistence

**Decision**: JSON file in platform config dir (`run_history.json`)  
**Schema**: List of `RunRecord` dicts, newest first. Written atomically (write to temp file,
rename). Loaded at app startup; updated after each run ends (completed/cancelled/failed).  
**Open Folder**: `os.startfile(path)` on Windows, `subprocess.run(["open", path])` on macOS  
**Alternatives considered**: SQLite (correct but more infra than needed for a flat list),
no persistence (rejected — FR-032 requires it)  

---

## FCPXML Format

**Decision**: FCPXML 1.9 with Filmora-compatible structure  
**Rationale**: Filmora uses Final Cut Pro XML for import. The file contains one `<sequence>`
with one `<video>` track and one `<audio>` track. Scene titles are `<marker>` elements on
the sequence. Per-scene clips reference absolute file paths to the synced `.mp4` files.  
**Sync gate**: Before writing FCPXML, `validate_sync(scenes)` checks
`|scene.video_duration − scene.audio_duration| <= 0.050` for every scene; raises
`ExportSyncError` on any violation.  
**Alternatives considered**: EDL (less Filmora-friendly), CSV timeline (no marker support)  

---

## Testing

**Decision**: `pytest` + `pytest-asyncio` + `responses` (HTTP mocking)  
**Unit tests** (no network, no filesystem side effects):
- `test_ffmpeg_wrapper.py`: mock `subprocess.run`; assert correct command args and duration parsing
- `test_fcpxml_generator.py`: pure function; pass in `List[Scene]` with known durations; assert XML structure and sync gate behavior
- `test_retry.py`: mock a function that raises N times; assert retry count and backoff timing  
**Integration tests** (HTTP-mocked at request layer):
- Each adapter module has its own test file; `responses` intercepts `requests.get/post`
- Edge-TTS adapter: mock the underlying WebSocket at the `edge_tts` library boundary
- `test_serper_adapter.py` covers both success path and fallback-to-Anthropic path  
**Alternatives considered**: `httpretty` (less actively maintained than `responses`), `vcrpy`
(cassette-based; harder to cover fallback paths intentionally)  
