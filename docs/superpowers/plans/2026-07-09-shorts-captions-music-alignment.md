# Shorts: Whisper Alignment, Burned-In Captions, Music Bed, Log/Progress Cleanup

## Goal

Extend `docu_studio/shorts/` (built in the prior session) with:
1. Tier 2 Whisper-based forced alignment for word timestamps (currently a `NotImplementedError` stub).
2. Burned-in, word-level "pop" captions rendered via ASS + ffmpeg's `subtitles` filter.
3. An optional, ducked background-music bed sourced from a user-supplied manifest (no bundled copyrighted audio).
4. Two carried-over cleanups: a per-run `shorts_log.txt` (mirroring the documentary pipeline's `pipeline_log.txt`), and a full 7-stage progress bar for shorts runs (script → TTS → alignment → footage → assembly → captions/music → mux) instead of the current gappy 8-stage documentary map being reused.

The documentary pipeline path (`pipeline/`, `runner/`, `adapters/`, `history/`, `licensing.py`, existing tests) must remain byte-for-byte untouched. All new code lives in `docu_studio/shorts/`, plus targeted, additive edits to `docu_studio/gui/bridge.py`, `docu_studio/gui/web/{index.html,app.js}`, `docu_studio/gui/webview_app.py`, and `requirements.txt`.

## Architecture

```
ShortsRunner._execute()
  ├─ "Short Script"     generate_shorts_script()                    [unchanged]
  ├─ "Short TTS"        tts.synthesize()                             [renamed stage string only]
  ├─ "Short Alignment"  get_word_timestamps()                        [NEW stage event]
  │     Tier 1 native → Tier 2 shorts_alignment.run_tier2_alignment()  [NEW impl]
  │                        → Tier 3 estimate (unchanged fallback)
  └─ assemble_short()
        ├─ "Short Footage"            [unchanged]
        ├─ "Short Assembly"           [unchanged, per-segment loop]
        ├─ concat_segments_video_only [unchanged]
        ├─ "Short Captions & Music"   [NEW stage]
        │     shorts_captions.write_ass_file() → ffmpeg.burn_captions()   [NEW, guarded]
        │     music_library.select_music_track() → ffmpeg.mix_music_bed() [NEW, guarded]
        └─ "Short Mux"                ffmpeg.mux_shorts_audio()      [unchanged call, new args]

ShortsRunner.event_queue: ShortsTeeQueue (NEW, mirrors pipeline.runner._TeeQueue)
  + QueueLoggingHandler attached to logger "docu_studio.shorts" for the run's
    lifetime, so every _log.info()/_log.warning() in capability_resolvers,
    shorts_alignment, shorts_ffmpeg, shorts_assembly, music_library lands in
    shorts_log.txt and the GUI log panel without editing those call sites.

Bridge (gui/bridge.py)
  self._active_mode: "doc" | "shorts", set by start_run()/start_shorts_run()
  _STAGE_MAP (doc, 8 stages, unchanged) vs _SHORTS_STAGE_MAP (shorts, 7 stages, NEW)
  _to_js_event() picks the right map + final-stage index by self._active_mode

GUI (index.html / app.js)
  New shorts-stage-track (7 boxes), hidden unless short mode.
  New captions-row / music-row toggles (default checked), hidden unless short mode.
  _resetProgress()/_setStage()/_handleEvent() become mode-aware (stage-N vs
  short-stage-N ids, STAGES vs SHORT_STAGES, final index 7 vs 6).
```

## Tech Stack

- Python 3.11+, existing `docu_studio/shorts/` package conventions (dataclasses, `logging.getLogger(__name__)`, pure functions kept dependency-free where testable).
- **faster-whisper** (new dependency) — CPU, `int8` compute, `"tiny"` model — lazy-imported only inside the Tier 2 code path so it's never a hard import-time dependency.
- ffmpeg `subtitles` filter (ASS) for caption burn-in; `sidechaincompress` + `amix` for music ducking. Both via `subprocess.run`, following `ShortsFFmpeg`'s existing patterns exactly.
- pytest + `unittest.mock` / `monkeypatch`, matching existing `tests/unit/test_shorts_*.py` style.

## Global Constraints

- Do not modify `pipeline/`, `runner/`, `adapters/` (except adding new files — none needed here), `history/`, `licensing.py`, or any existing test file.
- Documentary (guided/full-auto) run path must be provably unchanged: `Bridge._STAGE_MAP`, `_to_js_event`'s doc behavior, and `STAGES`/`_setStage` for `stage-N` ids stay byte-identical in effect.
- Use `.venv/bin/python` for everything. **Note:** this repo's `.venv` currently has no `pip` module installed (`No module named pip`), so `faster-whisper` cannot actually be installed in this sandbox. This is fine and expected: Tier 2's `import faster_whisper` will raise `ImportError` in this environment, which the Tier 2 → Tier 3 fallback contract (item 1 below) is explicitly required to handle gracefully. Do not attempt to fix the venv's pip — out of scope.
- Bump `?v=N` in `webview_app.py` once, as the last step, after all HTML/JS edits land.
- Commit incrementally, one commit per task below.
- No placeholder code — every function in this plan is a complete, working implementation.

---

## Task 1: `shorts_log.py` — per-run log file + stdlib-logging bridge

### Files
- Create: `docu_studio/shorts/shorts_log.py`

### Interfaces
- Consumes: `docu_studio.pipeline.events.{ErrorEvent, LogEvent, LogLevel, ProgressEvent, sanitize_log_message}` (read-only reuse, not modified).
- Produces: `ShortsTeeQueue` (a `queue.Queue` subclass), `QueueLoggingHandler` (a `logging.Handler` subclass). Both consumed by Task 11 (`shorts_runner.py`).

### Steps

1. Create `docu_studio/shorts/shorts_log.py`:

```python
"""Per-run log-file teeing for Shorts runs, mirroring pipeline.runner._TeeQueue.

Kept as a separate module (not importing from pipeline.runner) per the Shorts
package's existing boundary of not depending on pipeline.runner internals — this
is a parallel implementation, not a reuse of the private _TeeQueue class.
"""
from __future__ import annotations

import logging
import queue
from datetime import datetime
from pathlib import Path
from typing import IO

from docu_studio.pipeline.events import (
    ErrorEvent,
    LogEvent,
    LogLevel,
    ProgressEvent,
    sanitize_log_message,
)


class ShortsTeeQueue(queue.Queue):
    """queue.Queue that mirrors every put() to an optional shorts_log.txt file.

    The log file is opened by open_log() once the project folder exists and
    closed by close_log() in the runner's finally block. Log writes are
    best-effort — an OSError never propagates to the caller.
    """

    def __init__(self) -> None:
        super().__init__()
        self._log_file: IO[str] | None = None
        self._sensitive_keys: list[str] = []

    def open_log(self, path: Path, sensitive_keys: list[str]) -> None:
        self._sensitive_keys = sensitive_keys
        self._log_file = path.open("w", encoding="utf-8")

    def close_log(self) -> None:
        if self._log_file is not None:
            try:
                self._log_file.flush()
                self._log_file.close()
            finally:
                self._log_file = None

    def put(self, item: object, block: bool = True, timeout: float | None = None) -> None:  # type: ignore[override]
        if self._log_file is not None and item is not None:
            self._tee(item)
        super().put(item, block, timeout)

    def _tee(self, event: object) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        if isinstance(event, LogEvent):
            msg = sanitize_log_message(event.message, self._sensitive_keys)
            line = f"[{ts}] {event.level.value.upper()}: {msg}"
        elif isinstance(event, ProgressEvent):
            line = f"[{ts}] PROGRESS: {event.stage}: {event.message}"
        elif isinstance(event, ErrorEvent):
            msg = sanitize_log_message(event.message, self._sensitive_keys)
            line = f"[{ts}] ERROR: {msg}"
        else:
            return
        try:
            self._log_file.write(line + "\n")  # type: ignore[union-attr]
            self._log_file.flush()
        except OSError:
            pass


class QueueLoggingHandler(logging.Handler):
    """Forwards stdlib `logging` records into a ShortsTeeQueue as LogEvents.

    Attached to the "docu_studio.shorts" logger for a run's lifetime so every
    module-level `_log.info()`/`_log.warning()` call made anywhere under
    docu_studio.shorts (capability_resolvers, shorts_alignment, shorts_ffmpeg,
    shorts_assembly, music_library, ...) lands in shorts_log.txt and the GUI
    log panel automatically, without editing any of those call sites.
    """

    _LEVEL_MAP = {
        logging.DEBUG: LogLevel.INFO,
        logging.INFO: LogLevel.INFO,
        logging.WARNING: LogLevel.WARNING,
        logging.ERROR: LogLevel.ERROR,
        logging.CRITICAL: LogLevel.ERROR,
    }

    def __init__(self, target_queue: "queue.Queue[object]") -> None:
        super().__init__()
        self._queue = target_queue

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = self._LEVEL_MAP.get(record.levelno, LogLevel.INFO)
            self._queue.put(LogEvent(message=record.getMessage(), level=level))
        except Exception:
            pass  # logging must never crash the run
```

No dedicated test file for this task — it's exercised end-to-end by Task 11's wiring and by the "shorts_log.txt from a dry run" item in the final report. `ShortsTeeQueue` is a direct structural mirror of `pipeline.runner._TeeQueue`, already covered by that class's own established correctness.

---

## Task 2: `shorts_alignment.py` — pure Whisper-output-to-script matcher

### Files
- Create: `docu_studio/shorts/shorts_alignment.py`
- Create: `tests/unit/test_shorts_alignment.py`

### Interfaces
- Consumes: `docu_studio.shorts.capability_resolvers.WordTiming` (read-only import).
- Produces: `align_words_to_script(script_words, whisper_words) -> tuple[list[WordTiming], float]`, consumed by `run_tier2_alignment` (added in this same file by Task 3) and directly by this task's tests.

### Steps

1. Create `docu_studio/shorts/shorts_alignment.py` with the matcher only (Task 3 appends the Whisper-driving code below the matcher in the same file):

```python
"""Sequence alignment: match Whisper's transcribed words against the known
script text, interpolating timing for any word Whisper missed or misheard.

The matcher (align_words_to_script / _interpolate) is pure — no faster-whisper
import here — so it's directly unit-testable against fake Whisper output.
"""
from __future__ import annotations

import re

from docu_studio.shorts.capability_resolvers import WordTiming


def _normalize_word(word: str) -> str:
    """Lowercase and strip surrounding punctuation for matching purposes."""
    return re.sub(r"^[^\w]+|[^\w]+$", "", word.lower())


def align_words_to_script(
    script_words: list[str],
    whisper_words: list[tuple[str, float, float]],
) -> tuple[list[WordTiming], float]:
    """Return (timings, fraction_matched) — one WordTiming per *script_words*
    entry, in order, aligned to *whisper_words* = [(word, start, end), ...].

    Forward-scans whisper_words for a normalized match to each script word in
    turn, never re-matching an earlier whisper word (so repeated words align
    positionally rather than all snapping to the first occurrence). Unmatched
    script words are filled in by _interpolate() using their matched neighbors.
    """
    n = len(script_words)
    matched: list[tuple[float, float] | None] = [None] * n
    whisper_cursor = 0
    match_count = 0

    for i, sw in enumerate(script_words):
        target = _normalize_word(sw)
        found = None
        for j in range(whisper_cursor, len(whisper_words)):
            w, start, end = whisper_words[j]
            if _normalize_word(w) == target:
                found = (start, end)
                whisper_cursor = j + 1
                break
        if found is not None:
            matched[i] = found
            match_count += 1

    fraction_matched = (match_count / n) if n else 0.0
    timings = _interpolate(script_words, matched)
    return timings, fraction_matched


def _interpolate(
    script_words: list[str], matched: list[tuple[float, float] | None]
) -> list[WordTiming]:
    """Fill in timing for unmatched words by linear interpolation between the
    nearest matched neighbors. Leading unmatched runs collapse to the first
    matched word's start; trailing runs collapse to the last matched word's
    end. If nothing matched at all, returns an all-zero-duration timeline —
    get_word_timestamps' caller is expected to fall back to Tier 3 rather than
    rely on this in practice, but it stays well-defined here regardless."""
    n = len(script_words)
    if n == 0:
        return []

    if not any(matched):
        return [WordTiming(word=w, start=0.0, end=0.0) for w in script_words]

    result: list[WordTiming | None] = [None] * n
    for i, m in enumerate(matched):
        if m is not None:
            result[i] = WordTiming(word=script_words[i], start=m[0], end=m[1])

    i = 0
    while i < n:
        if result[i] is not None:
            i += 1
            continue
        j = i
        while j < n and result[j] is None:
            j += 1
        left = result[i - 1] if i > 0 else None
        right = result[j] if j < n else None

        if left is None and right is None:
            span_start, span_end = 0.0, 0.0  # unreachable given the any(matched) guard
        elif left is None:
            span_start, span_end = right.start, right.start
        elif right is None:
            span_start, span_end = left.end, left.end
        else:
            span_start, span_end = left.end, right.start

        count = j - i
        span = max(0.0, span_end - span_start)
        step = span / count if count else 0.0
        for k in range(count):
            w_start = span_start + step * k
            w_end = span_start + step * (k + 1)
            result[i + k] = WordTiming(word=script_words[i + k], start=w_start, end=w_end)
        i = j

    return result  # type: ignore[return-value]
```

2. Create `tests/unit/test_shorts_alignment.py`:

```python
"""Unit tests for the pure Whisper-to-script word alignment matcher."""
from __future__ import annotations

import pytest

from docu_studio.shorts.capability_resolvers import WordTiming
from docu_studio.shorts.shorts_alignment import align_words_to_script


class TestAlignWordsToScript:
    def test_perfect_match_uses_whisper_timings_directly(self) -> None:
        script_words = ["the", "cat", "sat", "down"]
        whisper_words = [("the", 0.0, 0.3), ("cat", 0.3, 0.6), ("sat", 0.6, 0.9), ("down", 0.9, 1.2)]
        timings, fraction = align_words_to_script(script_words, whisper_words)
        assert fraction == pytest.approx(1.0)
        assert [t.word for t in timings] == script_words
        assert [(t.start, t.end) for t in timings] == [(0.0, 0.3), (0.3, 0.6), (0.6, 0.9), (0.9, 1.2)]

    def test_missing_middle_word_is_interpolated(self) -> None:
        script_words = ["the", "quick", "cat", "sat"]
        # whisper dropped "quick" entirely
        whisper_words = [("the", 0.0, 0.3), ("cat", 0.6, 0.9), ("sat", 0.9, 1.2)]
        timings, fraction = align_words_to_script(script_words, whisper_words)
        assert fraction == pytest.approx(0.75)
        assert timings[0].word == "the"
        assert (timings[0].start, timings[0].end) == (0.0, 0.3)
        # "quick" interpolated between "the".end (0.3) and "cat".start (0.6)
        assert timings[1].word == "quick"
        assert timings[1].start == pytest.approx(0.3)
        assert timings[1].end == pytest.approx(0.6)
        assert (timings[2].start, timings[2].end) == (0.6, 0.9)
        assert (timings[3].start, timings[3].end) == (0.9, 1.2)

    def test_mismatched_misheard_word_is_interpolated(self) -> None:
        script_words = ["the", "cat", "sat"]
        # whisper misheard "cat" as "bat"
        whisper_words = [("the", 0.0, 0.3), ("bat", 0.3, 0.6), ("sat", 0.6, 0.9)]
        timings, fraction = align_words_to_script(script_words, whisper_words)
        assert fraction == pytest.approx(2 / 3)
        assert timings[1].word == "cat"
        # interpolated between "the".end (0.3) and "sat".start (0.6)
        assert timings[1].start == pytest.approx(0.3)
        assert timings[1].end == pytest.approx(0.6)

    def test_leading_unmatched_run_collapses_to_first_match_start(self) -> None:
        script_words = ["um", "so", "hello"]
        whisper_words = [("hello", 1.0, 1.5)]
        timings, fraction = align_words_to_script(script_words, whisper_words)
        assert fraction == pytest.approx(1 / 3)
        assert timings[0].start == pytest.approx(1.0)
        assert timings[0].end == pytest.approx(1.0)
        assert timings[1].start == pytest.approx(1.0)
        assert timings[2].start == pytest.approx(1.0)
        assert timings[2].end == pytest.approx(1.5)

    def test_trailing_unmatched_run_collapses_to_last_match_end(self) -> None:
        script_words = ["hello", "there", "friend"]
        whisper_words = [("hello", 0.0, 0.5)]
        timings, fraction = align_words_to_script(script_words, whisper_words)
        assert fraction == pytest.approx(1 / 3)
        assert timings[-1].start == pytest.approx(0.5)
        assert timings[-1].end == pytest.approx(0.5)

    def test_empty_script_returns_empty_and_zero_fraction(self) -> None:
        timings, fraction = align_words_to_script([], [("hello", 0.0, 0.5)])
        assert timings == []
        assert fraction == 0.0

    def test_no_matches_at_all_returns_zero_duration_timeline(self) -> None:
        script_words = ["alpha", "beta"]
        whisper_words = [("gamma", 0.0, 0.3), ("delta", 0.3, 0.6)]
        timings, fraction = align_words_to_script(script_words, whisper_words)
        assert fraction == 0.0
        assert all(t.start == 0.0 and t.end == 0.0 for t in timings)

    def test_repeated_words_align_positionally_not_all_to_first_occurrence(self) -> None:
        script_words = ["go", "go", "go"]
        whisper_words = [("go", 0.0, 0.2), ("go", 0.2, 0.4), ("go", 0.4, 0.6)]
        timings, fraction = align_words_to_script(script_words, whisper_words)
        assert fraction == pytest.approx(1.0)
        assert [(t.start, t.end) for t in timings] == [(0.0, 0.2), (0.2, 0.4), (0.4, 0.6)]
```

3. Verify: `.venv/bin/python -m pytest tests/unit/test_shorts_alignment.py -v` — all pass.

---

## Task 3: Whisper Tier 2 wiring

### Files
- Modify: `docu_studio/shorts/shorts_alignment.py` (append `run_tier2_alignment` + helpers below the Task 2 matcher code)
- Modify: `docu_studio/shorts/capability_resolvers.py`
- Modify: `requirements.txt`
- Create: `tests/unit/test_capability_resolvers_tier2.py`

### Interfaces
- Consumes: `align_words_to_script` (Task 2), `platformdirs.user_cache_dir` (existing dependency), `faster_whisper.WhisperModel` (new dependency, lazily imported).
- Produces: `run_tier2_alignment(audio_path, script_text) -> tuple[list[WordTiming], float]`, consumed by `capability_resolvers._tier2_whisper_alignment`.

### Steps

1. Add `faster-whisper` to `requirements.txt` (append as a new line, alphabetical-ish placement doesn't matter — match existing file's unsorted style):

```
customtkinter>=5.2.0
pywebview>=4.4
anthropic>=0.25.0
edge-tts>=6.1.0
elevenlabs>=1.2.0
keyring>=25.0.0
imageio-ffmpeg>=0.4.9
requests>=2.31.0
platformdirs>=4.2.0
openai>=1.30
faster-whisper>=1.0.0
```

2. Append to `docu_studio/shorts/shorts_alignment.py` (after `_interpolate`, same file as Task 2):

```python
import threading
from pathlib import Path

_TIER2_TIMEOUT_SECONDS = 60.0


def _model_cache_dir() -> str:
    from platformdirs import user_cache_dir

    return str(Path(user_cache_dir("docu_studio")) / "whisper_models")


def _run_whisper(audio_path: str) -> list[tuple[str, float, float]]:
    from faster_whisper import WhisperModel  # lazy import — heavy optional dep

    import logging

    logging.getLogger(__name__).info(
        "Tier 2 alignment: loading Whisper model (first use downloads ~75MB)…"
    )
    model = WhisperModel(
        "tiny", device="cpu", compute_type="int8", download_root=_model_cache_dir(),
    )
    segments, _info = model.transcribe(audio_path, word_timestamps=True)
    words: list[tuple[str, float, float]] = []
    for segment in segments:
        for w in segment.words or []:
            words.append((w.word, w.start, w.end))
    return words


def run_tier2_alignment(audio_path: str, script_text: str) -> tuple[list[WordTiming], float]:
    """Run Whisper word-level transcription on *audio_path* and align it to the
    known *script_text*. Raises on any failure — missing dependency, model/
    transcription error, or a hard 60s timeout — callers must catch and fall
    back to Tier 3; a shorts run must never fail because of alignment."""
    result_box: dict[str, object] = {}

    def _worker() -> None:
        try:
            result_box["words"] = _run_whisper(audio_path)
        except Exception as exc:  # noqa: BLE001 - surfaced via result_box, not raised in-thread
            result_box["error"] = exc

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    thread.join(timeout=_TIER2_TIMEOUT_SECONDS)
    if thread.is_alive():
        raise TimeoutError(
            f"Tier 2 whisper alignment exceeded {_TIER2_TIMEOUT_SECONDS:.0f}s timeout"
        )
    if "error" in result_box:
        raise result_box["error"]  # type: ignore[misc]

    whisper_words = result_box.get("words", [])
    script_words = script_text.split()
    return align_words_to_script(script_words, whisper_words)  # type: ignore[arg-type]
```

Note: move the top-of-file `import re` and the `from docu_studio.shorts.capability_resolvers import WordTiming` from Task 2 stay as-is; this step only adds `import threading` and `from pathlib import Path` at module scope (add these to the existing top-of-file import block rather than mid-file, to match the rest of the codebase's style — i.e. the final file has all imports at the top: `from __future__ import annotations`, `import re`, `import threading`, `from pathlib import Path`, `from docu_studio.shorts.capability_resolvers import WordTiming`).

3. Edit `docu_studio/shorts/capability_resolvers.py` — replace the `_tier2_whisper_alignment` stub and `get_word_timestamps`'s tier-2 handling:

Replace:
```python
def _tier2_whisper_alignment(audio_path: str, script_text: str) -> list[WordTiming]:
    raise NotImplementedError(
        "Tier 2 (Whisper-based forced alignment) is not implemented yet — "
        "lands in a follow-up task."
    )


def get_word_timestamps(
    audio_path: str, script_text: str, tts_adapter: TTSProvider
) -> tuple[list[WordTiming], str]:
    """Return (timestamps, tier_used) for *script_text* aligned to *audio_path*."""
    tier1 = _tier1_native_timestamps(tts_adapter, script_text, audio_path)
    if tier1 is not None:
        _log.info("get_word_timestamps: using Tier 1 (native TTS timestamps)")
        return tier1, "tier1_native"

    try:
        return _tier2_whisper_alignment(audio_path, script_text), "tier2_whisper"
    except NotImplementedError:
        pass

    duration = FFmpegWrapper().get_duration(audio_path)
    _log.info("get_word_timestamps: using Tier 3 (estimated timing)")
    return estimate_word_timestamps(script_text, duration), "tier3_estimated"
```

With:
```python
def _tier2_whisper_alignment(audio_path: str, script_text: str) -> list[WordTiming]:
    from docu_studio.shorts.shorts_alignment import run_tier2_alignment

    timings, fraction_matched = run_tier2_alignment(audio_path, script_text)
    _log.info(
        "Tier 2 whisper alignment: %.0f%% of words matched directly, %.0f%% interpolated",
        fraction_matched * 100, (1 - fraction_matched) * 100,
    )
    return timings


def get_word_timestamps(
    audio_path: str, script_text: str, tts_adapter: TTSProvider
) -> tuple[list[WordTiming], str]:
    """Return (timestamps, tier_used) for *script_text* aligned to *audio_path*."""
    tier1 = _tier1_native_timestamps(tts_adapter, script_text, audio_path)
    if tier1 is not None:
        _log.info("get_word_timestamps: using Tier 1 (native TTS timestamps)")
        return tier1, "tier1_native"

    try:
        timings = _tier2_whisper_alignment(audio_path, script_text)
        _log.info("get_word_timestamps: using Tier 2 (Whisper forced alignment)")
        return timings, "tier2_whisper"
    except Exception as exc:
        _log.warning(
            "get_word_timestamps: Tier 2 failed (%s) — falling back to Tier 3", exc
        )

    duration = FFmpegWrapper().get_duration(audio_path)
    _log.info("get_word_timestamps: using Tier 3 (estimated timing)")
    return estimate_word_timestamps(script_text, duration), "tier3_estimated"
```

Also update the module's top docstring line `Tier 2: Whisper-based forced alignment — scaffolded, not implemented yet.` to `Tier 2: Whisper-based forced alignment (docu_studio.shorts.shorts_alignment).` — a one-line doc correction only, no other changes to that docstring.

4. Create `tests/unit/test_capability_resolvers_tier2.py` (new file — does not touch the existing `tests/unit/test_shorts_capability_resolvers.py`):

```python
"""Tests for the Tier 2 (Whisper) → Tier 3 fallback wiring added to
capability_resolvers.get_word_timestamps. Kept in a separate file from the
existing test_shorts_capability_resolvers.py per this task's file boundaries."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from docu_studio.shorts.capability_resolvers import WordTiming, get_word_timestamps


class TestTier2Fallthrough:
    def test_tier2_timeout_falls_back_to_tier3(self) -> None:
        tts = MagicMock(spec=["synthesize"])
        with patch(
            "docu_studio.shorts.shorts_alignment.run_tier2_alignment",
            side_effect=TimeoutError("Tier 2 whisper alignment exceeded 60s timeout"),
        ), patch(
            "docu_studio.shorts.capability_resolvers.FFmpegWrapper"
        ) as ffmpeg_cls:
            ffmpeg_cls.return_value.get_duration.return_value = 4.0
            timestamps, tier = get_word_timestamps("audio.mp3", "hello there world", tts)
        assert tier == "tier3_estimated"
        assert timestamps[-1].end == 4.0

    def test_tier2_import_error_falls_back_to_tier3(self) -> None:
        tts = MagicMock(spec=["synthesize"])
        with patch(
            "docu_studio.shorts.shorts_alignment.run_tier2_alignment",
            side_effect=ImportError("faster_whisper not installed"),
        ), patch(
            "docu_studio.shorts.capability_resolvers.FFmpegWrapper"
        ) as ffmpeg_cls:
            ffmpeg_cls.return_value.get_duration.return_value = 2.0
            timestamps, tier = get_word_timestamps("audio.mp3", "hi", tts)
        assert tier == "tier3_estimated"

    def test_tier2_success_returns_tier2_timings(self) -> None:
        tts = MagicMock(spec=["synthesize"])
        fake_timings = [
            WordTiming(word="hi", start=0.0, end=0.4),
            WordTiming(word="there", start=0.4, end=0.9),
        ]
        with patch(
            "docu_studio.shorts.shorts_alignment.run_tier2_alignment",
            return_value=(fake_timings, 1.0),
        ):
            timestamps, tier = get_word_timestamps("audio.mp3", "hi there", tts)
        assert tier == "tier2_whisper"
        assert timestamps == fake_timings

    def test_real_environment_without_faster_whisper_falls_back_cleanly(self) -> None:
        """No mocking at all: in this sandbox faster-whisper is not installed
        (and .venv has no pip), so this exercises the real ImportError path."""
        tts = MagicMock(spec=["synthesize"])
        with patch(
            "docu_studio.shorts.capability_resolvers.FFmpegWrapper"
        ) as ffmpeg_cls:
            ffmpeg_cls.return_value.get_duration.return_value = 3.0
            timestamps, tier = get_word_timestamps("audio.mp3", "hi there", tts)
        assert tier == "tier3_estimated"
```

5. Verify: `.venv/bin/python -m pytest tests/unit/test_capability_resolvers_tier2.py tests/unit/test_shorts_capability_resolvers.py tests/unit/test_shorts_alignment.py -v` — all pass, and the existing `test_shorts_capability_resolvers.py` file is unmodified and still green.

---

## Task 4: `shorts_captions.py` — ASS "pop caption" generation

### Files
- Create: `docu_studio/shorts/shorts_captions.py`
- Create: `tests/unit/test_shorts_captions.py`

### Interfaces
- Consumes: `WordTiming` (from `capability_resolvers`), `SHORTS_WIDTH`/`SHORTS_HEIGHT` (from `shorts_config`).
- Produces: `group_words`, `generate_ass`, `write_ass_file`, `SAFE_AREA_BOTTOM_MARGIN` — consumed by Task 10 (`shorts_assembly.py`).

### Steps

1. Create `docu_studio/shorts/shorts_captions.py`:

```python
"""Burned-in "pop" caption generation: groups word-level timings into 2-4 word
chunks and emits an ASS (Advanced SubStation Alpha) subtitle document with the
currently-spoken word bolded and briefly scaled up.

Pure text generation — no ffmpeg or subprocess calls here; ShortsFFmpeg.burn_captions
(Task 5) consumes the .ass file this module writes.
"""
from __future__ import annotations

from pathlib import Path

from docu_studio.shorts.capability_resolvers import WordTiming
from docu_studio.shorts.shorts_config import SHORTS_HEIGHT, SHORTS_WIDTH

_MIN_GROUP = 2
_MAX_GROUP = 4

# Platform UI (like/comment/share rail, captions toggle) covers the literal
# bottom 15% of a Short/Reel — 22% clears that with margin to spare while
# still reading as "lower-middle", not centered.
SAFE_AREA_BOTTOM_MARGIN = round(SHORTS_HEIGHT * 0.22)

# libass resolves this via fontconfig substitution if unavailable on the host,
# giving effectively a system-safe fallback without a literal comma-list (an
# ASS style line takes exactly one Fontname, unlike CSS font-family).
_FONT_NAME = "DejaVu Sans"

_MIN_WORD_DURATION = 0.05  # guards against zero-duration Dialogue lines

_ASS_HEADER_TEMPLATE = """[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.601

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Pop,{font},64,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,3,2,2,60,60,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"""


def group_words(timings: list[WordTiming]) -> list[list[WordTiming]]:
    """Split *timings* into 2-4 word "pop caption" chunks.

    Greedy 4-word chunking, with a borrow-fixup: if the final chunk would be a
    single leftover word, one word is moved over from the second-to-last chunk
    so both end chunks land at >=2 (e.g. n=13 -> [4,4,4,1] -> [4,4,3,2]). A
    single-word script is the only case returned below the 2-word floor, since
    there's nothing left to borrow from.
    """
    n = len(timings)
    if n == 0:
        return []
    if n == 1:
        return [list(timings)]

    groups: list[list[WordTiming]] = []
    i = 0
    while i < n:
        chunk = timings[i:i + _MAX_GROUP]
        groups.append(list(chunk))
        i += len(chunk)

    if len(groups[-1]) < _MIN_GROUP and len(groups) > 1:
        borrowed = groups[-2].pop()
        groups[-1].insert(0, borrowed)

    return groups


def _escape_ass_text(word: str) -> str:
    return word.replace("\\", "\\\\").replace("{", "(").replace("}", ")")


def _format_ass_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    total_cs = round(seconds * 100)
    hours, rem = divmod(total_cs, 360000)
    minutes, rem = divmod(rem, 6000)
    secs, cs = divmod(rem, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{cs:02d}"


def _render_group_text(group: list[WordTiming], active_index: int) -> str:
    parts = []
    for idx, w in enumerate(group):
        word_text = _escape_ass_text(w.word)
        if idx == active_index:
            parts.append(
                r"{\t(0,120,\fscx118\fscy118)\t(120,240,\fscx100\fscy100)\b1}"
                + word_text + r"{\r}"
            )
        else:
            parts.append(word_text)
    return " ".join(parts)


def generate_ass(timings: list[WordTiming]) -> str:
    """Build a full ASS subtitle document from word-level *timings*: words are
    grouped into 2-4 word "pop caption" chunks, the currently-spoken word in
    each chunk is bold and briefly scaled up via an ASS \\t transform, and
    every line sits inside the lower-middle safe area."""
    header = _ASS_HEADER_TEMPLATE.format(
        width=SHORTS_WIDTH, height=SHORTS_HEIGHT,
        font=_FONT_NAME, margin_v=SAFE_AREA_BOTTOM_MARGIN,
    )
    lines = [header]
    for group in group_words(timings):
        for active_index, word in enumerate(group):
            start = _format_ass_time(word.start)
            end_seconds = max(word.end, word.start + _MIN_WORD_DURATION)
            end = _format_ass_time(end_seconds)
            text = _render_group_text(group, active_index)
            lines.append(f"Dialogue: 0,{start},{end},Pop,,0,0,0,,{text}")
    return "\n".join(lines) + "\n"


def write_ass_file(timings: list[WordTiming], output_path: str) -> None:
    Path(output_path).write_text(generate_ass(timings), encoding="utf-8")
```

2. Create `tests/unit/test_shorts_captions.py`:

```python
"""Unit tests for shorts_captions: ASS subtitle generation for burned-in pop captions."""
from __future__ import annotations

import re

from docu_studio.shorts.capability_resolvers import WordTiming
from docu_studio.shorts.shorts_captions import (
    SAFE_AREA_BOTTOM_MARGIN,
    generate_ass,
    group_words,
    write_ass_file,
)
from docu_studio.shorts.shorts_config import SHORTS_HEIGHT


def _fake_timings(words: list[str], word_duration: float = 0.4) -> list[WordTiming]:
    timings = []
    cursor = 0.0
    for w in words:
        timings.append(WordTiming(word=w, start=cursor, end=cursor + word_duration))
        cursor += word_duration
    return timings


class TestGroupWords:
    def test_empty_returns_empty(self) -> None:
        assert group_words([]) == []

    def test_all_groups_within_bounds_for_various_lengths(self) -> None:
        for n in (2, 3, 4, 5, 6, 7, 9, 11, 13, 20):
            timings = _fake_timings([f"w{i}" for i in range(n)])
            groups = group_words(timings)
            assert sum(len(g) for g in groups) == n
            for g in groups:
                assert 2 <= len(g) <= 4

    def test_single_word_script_returns_single_group(self) -> None:
        groups = group_words(_fake_timings(["solo"]))
        assert len(groups) == 1
        assert len(groups[0]) == 1
        assert groups[0][0].word == "solo"

    def test_thirteen_words_borrows_to_avoid_trailing_singleton(self) -> None:
        groups = group_words(_fake_timings([f"w{i}" for i in range(13)]))
        assert [len(g) for g in groups] == [4, 4, 3, 2]


class TestGenerateAss:
    def test_contains_required_sections(self) -> None:
        ass = generate_ass(_fake_timings(["the", "quick", "brown", "fox", "jumps"]))
        assert "[Script Info]" in ass
        assert "[V4+ Styles]" in ass
        assert "[Events]" in ass
        assert "Style: Pop," in ass

    def test_dialogue_lines_are_word_level(self) -> None:
        timings = _fake_timings(["the", "quick", "brown", "fox", "jumps"])
        ass = generate_ass(timings)
        dialogue_lines = [l for l in ass.splitlines() if l.startswith("Dialogue:")]
        assert len(dialogue_lines) == len(timings)

    def test_times_are_monotonically_non_decreasing(self) -> None:
        timings = _fake_timings(["one", "two", "three", "four", "five", "six", "seven"])
        ass = generate_ass(timings)
        starts = []
        for line in ass.splitlines():
            if line.startswith("Dialogue:"):
                m = re.match(r"Dialogue: 0,([\d:.]+),", line)
                starts.append(m.group(1))
        assert starts == sorted(starts)

    def test_safe_area_margin_clears_bottom_15_percent(self) -> None:
        assert SAFE_AREA_BOTTOM_MARGIN >= round(SHORTS_HEIGHT * 0.15)

    def test_margin_v_is_embedded_in_style_line(self) -> None:
        ass = generate_ass(_fake_timings(["hi", "there"]))
        style_line = next(l for l in ass.splitlines() if l.startswith("Style: Pop,"))
        fields = style_line.split(",")
        assert int(fields[-2]) == SAFE_AREA_BOTTOM_MARGIN

    def test_active_word_gets_pop_transform(self) -> None:
        ass = generate_ass(_fake_timings(["hello", "world"]))
        assert r"\t(0,120" in ass

    def test_empty_timings_produces_header_only(self) -> None:
        ass = generate_ass([])
        assert "Dialogue:" not in ass

    def test_2_to_4_word_groups_present_in_a_longer_sentence(self) -> None:
        words = "a short burst of narration with several words in it total".split()
        timings = _fake_timings(words)
        groups = group_words(timings)
        assert all(2 <= len(g) <= 4 for g in groups)
        assert sum(len(g) for g in groups) == len(words)


class TestWriteAssFile:
    def test_writes_readable_utf8_file(self, tmp_path) -> None:
        out = tmp_path / "captions.ass"
        write_ass_file(_fake_timings(["hello", "world"]), str(out))
        content = out.read_text(encoding="utf-8")
        assert "[Script Info]" in content
        assert "Dialogue:" in content
```

3. Verify: `.venv/bin/python -m pytest tests/unit/test_shorts_captions.py -v` — all pass.

---

## Task 5: `ShortsFFmpeg.burn_captions`

### Files
- Modify: `docu_studio/shorts/shorts_ffmpeg.py`

### Interfaces
- Consumes: nothing new (plain ffmpeg subprocess call, following the file's existing patterns).
- Produces: `ShortsFFmpeg.burn_captions(input_path, ass_path, output_path) -> None`, consumed by Task 10.

### Steps

1. Add this method to the `ShortsFFmpeg` class in `docu_studio/shorts/shorts_ffmpeg.py`, placed after `concat_segments_video_only` and before `mux_shorts_audio` (do not touch either of those two methods):

```python
    def burn_captions(self, input_path: str, ass_path: str, output_path: str) -> None:
        """Burn *ass_path* (ASS pop-caption subtitles) into *input_path* via
        ffmpeg's subtitles filter. *input_path* here is the video-only concat
        output — no audio stream to preserve at this stage."""
        escaped_ass = ass_path.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
        cmd = [
            self._ffmpeg, "-y",
            "-i", input_path,
            "-vf", f"subtitles='{escaped_ass}'",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "22",
            output_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        self._check(result, f"burn_captions → {output_path!r}")
```

No dedicated test — consistent with the file's other subprocess-driving methods (`vertical_convert`, `apply_ken_burns`, `concat_segments_video_only`), none of which have direct unit tests; they're exercised through integration-style testing of `assemble_short` if any exists, and manually via the dry-run report.

---

## Task 6: `music_library.py` + manifest + README

### Files
- Create: `docu_studio/shorts/music_library.py`
- Create: `docu_studio/shorts/assets/music/manifest.json`
- Create: `docu_studio/shorts/assets/music/README.md`
- Create: `tests/unit/test_music_library.py`

### Interfaces
- Consumes: stdlib `json`, `random`, `pathlib`.
- Produces: `MusicTrack`, `load_manifest`, `select_music_track`, `MUSIC_DIR` — consumed by Task 10.

### Steps

1. Create `docu_studio/shorts/music_library.py`:

```python
"""Loader for the shorts music-bed manifest (assets/music/manifest.json).

Ships with a placeholder-only manifest — no copyrighted audio is bundled.
Users drop their own royalty-free tracks into assets/music/ per the README
there. Every failure mode here (missing dir, malformed JSON, entry pointing
at a file that was never dropped in) resolves to an empty track list, never
an exception — the music bed is always optional.
"""
from __future__ import annotations

import json
import logging
import random
from dataclasses import dataclass
from pathlib import Path

_log = logging.getLogger(__name__)

MUSIC_DIR = Path(__file__).parent / "assets" / "music"
MANIFEST_PATH = MUSIC_DIR / "manifest.json"


@dataclass(frozen=True)
class MusicTrack:
    filename: str
    mood: str
    bpm: int


def load_manifest(manifest_path: Path | None = None) -> list[MusicTrack]:
    """Return the MusicTrack entries whose backing audio file actually exists
    on disk. See module docstring for the graceful-empty-list contract."""
    path = manifest_path or MANIFEST_PATH
    if not path.exists():
        _log.info("Music manifest not found at %s — skipping music bed", path)
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        _log.warning(
            "Music manifest at %s is unreadable/malformed (%s) — skipping music bed",
            path, exc,
        )
        return []

    tracks: list[MusicTrack] = []
    for entry in raw.get("tracks", []):
        try:
            filename = entry["filename"]
            mood = entry["mood"]
            bpm = int(entry["bpm"])
        except (KeyError, TypeError, ValueError):
            _log.warning("Music manifest entry malformed, skipping: %s", entry)
            continue
        if not (path.parent / filename).exists():
            _log.info(
                "Music track %s listed in manifest but not found on disk — skipping",
                filename,
            )
            continue
        tracks.append(MusicTrack(filename=filename, mood=mood, bpm=bpm))
    return tracks


def select_music_track(seed: int, manifest_path: Path | None = None) -> MusicTrack | None:
    """Return a reproducible (seeded) track from the manifest, or None if no
    usable track exists — callers must skip the music bed gracefully then."""
    tracks = load_manifest(manifest_path)
    if not tracks:
        return None
    return random.Random(seed).choice(tracks)
```

2. Create `docu_studio/shorts/assets/music/manifest.json`:

```json
{
  "tracks": [
    {
      "filename": "PLACEHOLDER-drop-your-own-track-here.mp3",
      "mood": "uplifting",
      "bpm": 120
    }
  ]
}
```

(The placeholder's `filename` deliberately doesn't exist on disk, so `load_manifest` filters it out by design — a fresh checkout has zero usable tracks and the music bed is skipped automatically until the user drops in a real file.)

3. Create `docu_studio/shorts/assets/music/README.md`:

```markdown
# Shorts Music Bed

Drop royalty-free background tracks (mp3/wav) into this folder and add a
matching entry to `manifest.json`:

```json
{ "filename": "your-track.mp3", "mood": "uplifting", "bpm": 120 }
```

`bpm` is used by a future beat-sync feature — set it accurately even if
nothing consumes it yet.

**Do not commit copyrighted audio here.** Good sources for royalty-free
tracks: YouTube Audio Library, Pixabay Music, Free Music Archive — check
each track's license terms before use.

If `manifest.json` has no entries whose `filename` exists on disk, Shorts
runs skip the music bed automatically. No crash, no error — it's just quieter.
```

4. Create `tests/unit/test_music_library.py`:

```python
"""Unit tests for the shorts music-bed manifest loader."""
from __future__ import annotations

import json

from docu_studio.shorts.music_library import MusicTrack, load_manifest, select_music_track


class TestLoadManifest:
    def test_missing_directory_returns_empty(self, tmp_path) -> None:
        assert load_manifest(tmp_path / "does_not_exist" / "manifest.json") == []

    def test_malformed_json_returns_empty(self, tmp_path) -> None:
        manifest = tmp_path / "manifest.json"
        manifest.write_text("{not valid json", encoding="utf-8")
        assert load_manifest(manifest) == []

    def test_entry_pointing_at_missing_file_is_skipped(self, tmp_path) -> None:
        manifest = tmp_path / "manifest.json"
        manifest.write_text(
            json.dumps({"tracks": [{"filename": "ghost.mp3", "mood": "calm", "bpm": 90}]}),
            encoding="utf-8",
        )
        assert load_manifest(manifest) == []

    def test_valid_entry_with_file_present_is_returned(self, tmp_path) -> None:
        (tmp_path / "track.mp3").write_bytes(b"fake-audio")
        manifest = tmp_path / "manifest.json"
        manifest.write_text(
            json.dumps({"tracks": [{"filename": "track.mp3", "mood": "uplifting", "bpm": 120}]}),
            encoding="utf-8",
        )
        tracks = load_manifest(manifest)
        assert tracks == [MusicTrack(filename="track.mp3", mood="uplifting", bpm=120)]

    def test_malformed_entry_is_skipped_but_others_load(self, tmp_path) -> None:
        (tmp_path / "good.mp3").write_bytes(b"fake-audio")
        manifest = tmp_path / "manifest.json"
        manifest.write_text(
            json.dumps({"tracks": [
                {"filename": "good.mp3", "mood": "calm", "bpm": 100},
                {"mood": "missing-filename-key", "bpm": 80},
            ]}),
            encoding="utf-8",
        )
        tracks = load_manifest(manifest)
        assert len(tracks) == 1
        assert tracks[0].filename == "good.mp3"

    def test_real_shipped_manifest_has_no_usable_tracks_out_of_the_box(self) -> None:
        """The placeholder entry in the real manifest.json points at a file
        that isn't shipped — confirms the graceful empty-music-dir behavior
        on a fresh checkout without needing a test-only manifest."""
        assert load_manifest() == []


class TestSelectMusicTrack:
    def test_no_tracks_returns_none(self, tmp_path) -> None:
        assert select_music_track(seed=1, manifest_path=tmp_path / "missing.json") is None

    def test_reproducible_for_same_seed(self, tmp_path) -> None:
        for name in ("a.mp3", "b.mp3", "c.mp3"):
            (tmp_path / name).write_bytes(b"x")
        manifest = tmp_path / "manifest.json"
        manifest.write_text(
            json.dumps({"tracks": [
                {"filename": "a.mp3", "mood": "calm", "bpm": 90},
                {"filename": "b.mp3", "mood": "energetic", "bpm": 128},
                {"filename": "c.mp3", "mood": "uplifting", "bpm": 110},
            ]}),
            encoding="utf-8",
        )
        first = select_music_track(seed=42, manifest_path=manifest)
        second = select_music_track(seed=42, manifest_path=manifest)
        assert first == second
```

5. Verify: `.venv/bin/python -m pytest tests/unit/test_music_library.py -v` — all pass, including the real-manifest empty-tracks assertion.

---

## Task 7: `shorts_audio_mix.py` — ducking filtergraph construction

### Files
- Create: `docu_studio/shorts/shorts_audio_mix.py`
- Create: `tests/unit/test_shorts_audio_mix.py`

### Interfaces
- Consumes: nothing (pure string building).
- Produces: `build_ducking_filtergraph(video_duration) -> str`, consumed by Task 8.

### Steps

1. Create `docu_studio/shorts/shorts_audio_mix.py`:

```python
"""Pure ffmpeg filtergraph construction for shorts music-bed mixing.

Kept as pure string building (no subprocess) so the ducking graph is directly
unit-testable — ShortsFFmpeg.mix_music_bed (Task 8) is the only caller that
actually invokes ffmpeg with this string.
"""
from __future__ import annotations

_FADE_SECONDS = 1.0
# Combined with sidechaincompress ducking below, lands music around -18 to
# -22 dB under narration — voice always dominant.
_MUSIC_BASELINE_DB = -20


def build_ducking_filtergraph(video_duration: float) -> str:
    """Return a -filter_complex string that loops/trims a music input ([1:a])
    to *video_duration* seconds, fades it in/out, ducks it under a voice
    input ([0:a]) via sidechaincompress, and mixes the two with amix
    (normalize=0 so ffmpeg's default equal-weighting doesn't undermine "voice
    always dominant").

    Input stream order is fixed: [0:a] = voice (also the sidechain key),
    [1:a] = music (looped via -stream_loop -1 on the input args by the caller).
    """
    fade_out_start = max(0.0, video_duration - _FADE_SECONDS)
    return (
        f"[1:a]atrim=0:{video_duration:.3f},"
        f"afade=t=in:st=0:d={_FADE_SECONDS:.2f},"
        f"afade=t=out:st={fade_out_start:.3f}:d={_FADE_SECONDS:.2f},"
        f"volume={_MUSIC_BASELINE_DB}dB[music_faded];"
        f"[music_faded][0:a]sidechaincompress=threshold=0.05:ratio=8:attack=5:release=300[music_ducked];"
        f"[0:a][music_ducked]amix=inputs=2:duration=first:normalize=0[aout]"
    )
```

2. Create `tests/unit/test_shorts_audio_mix.py`:

```python
"""Unit tests for the shorts music-bed ducking filtergraph string construction."""
from __future__ import annotations

from docu_studio.shorts.shorts_audio_mix import build_ducking_filtergraph


class TestBuildDuckingFiltergraph:
    def test_references_both_input_streams(self) -> None:
        graph = build_ducking_filtergraph(30.0)
        assert "[0:a]" in graph
        assert "[1:a]" in graph

    def test_includes_sidechaincompress_keyed_by_voice(self) -> None:
        graph = build_ducking_filtergraph(30.0)
        assert "sidechaincompress" in graph
        assert "[music_faded][0:a]sidechaincompress" in graph

    def test_includes_fade_in_and_out(self) -> None:
        graph = build_ducking_filtergraph(30.0)
        assert "afade=t=in" in graph
        assert "afade=t=out" in graph

    def test_fade_out_starts_one_second_before_end(self) -> None:
        graph = build_ducking_filtergraph(30.0)
        assert "afade=t=out:st=29.000:d=1.00" in graph

    def test_short_clip_fade_out_start_clamped_to_zero(self) -> None:
        graph = build_ducking_filtergraph(0.5)
        assert "afade=t=out:st=0.000:d=1.00" in graph

    def test_final_output_label_is_aout(self) -> None:
        graph = build_ducking_filtergraph(30.0)
        assert graph.endswith("[aout]")

    def test_amix_does_not_auto_normalize(self) -> None:
        graph = build_ducking_filtergraph(30.0)
        assert "normalize=0" in graph

    def test_trims_music_to_exact_video_duration(self) -> None:
        graph = build_ducking_filtergraph(47.25)
        assert "atrim=0:47.250" in graph

    def test_baseline_volume_reduction_is_within_spec_range(self) -> None:
        graph = build_ducking_filtergraph(30.0)
        assert "volume=-20dB" in graph  # within the -18 to -22 dB spec range
```

3. Verify: `.venv/bin/python -m pytest tests/unit/test_shorts_audio_mix.py -v` — all pass.

---

## Task 8: `ShortsFFmpeg.mix_music_bed`

### Files
- Modify: `docu_studio/shorts/shorts_ffmpeg.py`

### Interfaces
- Consumes: `build_ducking_filtergraph` (Task 7, lazily imported to match the file's existing lazy-import style for cross-module ffmpeg helpers — see how `burn_captions` needs none, but this one pulls in a sibling module).
- Produces: `ShortsFFmpeg.mix_music_bed(voice_path, music_path, video_duration, output_path) -> None`, consumed by Task 10.

### Steps

1. Add this method to `ShortsFFmpeg`, placed after `burn_captions` (from Task 5) and before `mux_shorts_audio`:

```python
    def mix_music_bed(
        self, voice_path: str, music_path: str, video_duration: float, output_path: str
    ) -> None:
        """Loop/trim *music_path* to *video_duration*, duck it under
        *voice_path* via sidechaincompress, and write the mixed result to
        *output_path* as a standalone audio file — the caller (assemble_short)
        passes this into mux_shorts_audio exactly as it would the raw voice
        track, so that method's -map discipline never needs to change."""
        from docu_studio.shorts.shorts_audio_mix import build_ducking_filtergraph

        filter_complex = build_ducking_filtergraph(video_duration)
        cmd = [
            self._ffmpeg, "-y",
            "-i", voice_path,
            "-stream_loop", "-1", "-i", music_path,
            "-filter_complex", filter_complex,
            "-map", "[aout]",
            "-c:a", "aac",
            output_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        self._check(result, f"mix_music_bed → {output_path!r}")
```

No dedicated test — same rationale as Task 5's `burn_captions`.

---

## Task 9: `ShortsConfig` — captions/music toggles

### Files
- Modify: `docu_studio/shorts/shorts_config.py`
- Modify: `tests/unit/test_shorts_config.py` is NOT touched — verify the two new fields (both with defaults) don't break any existing construction call in that file.

### Steps

1. Edit `docu_studio/shorts/shorts_config.py`:

```python
@dataclass
class ShortsConfig:
    topic: str
    duration_seconds: int = SHORTS_DEFAULT_DURATION
    captions_enabled: bool = True
    music_enabled: bool = True

    def __post_init__(self) -> None:
        if not (SHORTS_MIN_DURATION <= self.duration_seconds <= SHORTS_MAX_DURATION):
            raise ValueError(
                f"duration_seconds must be between {SHORTS_MIN_DURATION} and "
                f"{SHORTS_MAX_DURATION}, got {self.duration_seconds}"
            )
```

2. Verify: `.venv/bin/python -m pytest tests/unit/test_shorts_config.py -v` — all pass unchanged (both new fields default, so every existing construction call — positional or keyword — keeps working).

---

## Task 10: Wire captions + music into `shorts_assembly.assemble_short`

### Files
- Modify: `docu_studio/shorts/shorts_assembly.py`

### Interfaces
- Consumes: `shorts_captions.write_ass_file` (Task 4), `music_library.{MUSIC_DIR, select_music_track}` (Task 6), `ShortsFFmpeg.{burn_captions, mix_music_bed}` (Tasks 5 & 8).
- Produces: `assemble_short(..., captions_enabled: bool = True, music_enabled: bool = True)` — consumed by Task 11.

### Steps

1. Add imports to `docu_studio/shorts/shorts_assembly.py` (alongside the existing `from docu_studio.shorts.shorts_ffmpeg import ShortsFFmpeg` line):

```python
from docu_studio.shorts.music_library import MUSIC_DIR, select_music_track
from docu_studio.shorts.shorts_captions import write_ass_file
```

2. Change the `assemble_short` signature to add the two new parameters (append after `event_queue`, both defaulted so any future direct caller without them keeps working):

```python
def assemble_short(
    script: ShortsScript,
    audio_path: str,
    audio_duration: float,
    timestamps: list[WordTiming],
    tier_used: str,
    providers: list[FootageProvider],
    ffmpeg: ShortsFFmpeg,
    project_folder: Path,
    output_path: Path,
    seed: int,
    event_queue: queue.Queue,
    captions_enabled: bool = True,
    music_enabled: bool = True,
) -> None:
```

3. Replace the final block of the function — currently:

```python
    event_queue.put(ProgressEvent(stage="Short Mux", message="Concatenating and muxing final short…"))
    concat_path = str(scene_dir / "short_concat.mp4")
    ffmpeg.concat_segments_video_only(segment_paths, concat_path)
    ffmpeg.mux_shorts_audio(concat_path, audio_path, str(output_path))

    event_queue.put(LogEvent(
        message=f"Short assembled: {len(segments)} segments → {output_path}",
        level=LogLevel.INFO,
    ))
```

With:

```python
    concat_path = str(scene_dir / "short_concat.mp4")
    ffmpeg.concat_segments_video_only(segment_paths, concat_path)

    event_queue.put(ProgressEvent(
        stage="Short Captions & Music", message="Adding captions and music bed…",
    ))
    video_for_mux = concat_path
    if captions_enabled:
        try:
            ass_path = str(scene_dir / "captions.ass")
            write_ass_file(timestamps, ass_path)
            captioned_path = str(scene_dir / "short_captioned.mp4")
            ffmpeg.burn_captions(video_for_mux, ass_path, captioned_path)
            video_for_mux = captioned_path
            event_queue.put(LogEvent(message="Captions burned in.", level=LogLevel.INFO))
        except Exception as exc:
            event_queue.put(LogEvent(
                message=f"Captions failed ({exc}) — continuing without captions.",
                level=LogLevel.WARNING,
            ))

    audio_for_mux = audio_path
    if music_enabled:
        try:
            track = select_music_track(seed=seed)
            if track is None:
                event_queue.put(LogEvent(
                    message="No usable music track found — skipping music bed.",
                    level=LogLevel.INFO,
                ))
            else:
                music_path = str(MUSIC_DIR / track.filename)
                mixed_audio = str(scene_dir / "audio_mixed.m4a")
                ffmpeg.mix_music_bed(audio_path, music_path, audio_duration, mixed_audio)
                audio_for_mux = mixed_audio
                event_queue.put(LogEvent(
                    message=f"Music bed mixed in ({track.mood}, {track.bpm} BPM).",
                    level=LogLevel.INFO,
                ))
        except Exception as exc:
            event_queue.put(LogEvent(
                message=f"Music mixing failed ({exc}) — continuing without music.",
                level=LogLevel.WARNING,
            ))

    event_queue.put(ProgressEvent(stage="Short Mux", message="Muxing final short…"))
    ffmpeg.mux_shorts_audio(video_for_mux, audio_for_mux, str(output_path))

    event_queue.put(LogEvent(
        message=f"Short assembled: {len(segments)} segments → {output_path}",
        level=LogLevel.INFO,
    ))
```

Note `mux_shorts_audio` itself is not touched at all — it just receives `video_for_mux`/`audio_for_mux` instead of the raw `concat_path`/`audio_path`, preserving its existing `-map` discipline unconditionally.

4. No new test file for this task (no existing `test_shorts_assembly.py` to extend, and the function is I/O-heavy/ffmpeg-driven — covered by the dry-run report instead, matching how the pre-existing per-segment loop in this same function has no direct unit test either).

---

## Task 11: Wire alignment stage, log file, and config into `shorts_runner.py`

### Files
- Modify: `docu_studio/shorts/shorts_runner.py`

### Interfaces
- Consumes: `ShortsTeeQueue`, `QueueLoggingHandler` (Task 1); `captions_enabled`/`music_enabled` on `ShortsConfig` (Task 9); `assemble_short`'s new params (Task 10).
- Produces: `ShortsRunner.__init__(..., captions_enabled: bool = True, music_enabled: bool = True)` — consumed by Task 12 (`bridge.py`).

### Steps

1. Replace the full contents of `docu_studio/shorts/shorts_runner.py`:

```python
"""ShortsRunner — background thread that orchestrates the Shorts/Reels pipeline.

Mirrors docu_studio.pipeline.runner.PipelineRunner's public shape (event_queue,
cancel_event, _final_video_path, _project_folder, run()) so the existing
Bridge._translate_events() works unmodified for both run types. Does not import
from pipeline.runner — ShortsTeeQueue (shorts_log.py) is a parallel
implementation of pipeline.runner._TeeQueue used here for per-run
shorts_log.txt teeing; project folder + history integration are reused.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime
from enum import Enum
from pathlib import Path

from docu_studio.adapters.footage.base import FootageProvider
from docu_studio.adapters.llm.base import LLMProvider
from docu_studio.adapters.tts.base import TTSProvider
from docu_studio.history.run_history import RunRecord, save_run
from docu_studio.output.project_folder import create_project_folder
from docu_studio.pipeline.events import ErrorEvent, LogEvent, LogLevel, ProgressEvent
from docu_studio.shorts.capability_resolvers import get_word_timestamps
from docu_studio.shorts.shorts_assembly import assemble_short
from docu_studio.shorts.shorts_config import ShortsConfig
from docu_studio.shorts.shorts_ffmpeg import ShortsFFmpeg
from docu_studio.shorts.shorts_log import QueueLoggingHandler, ShortsTeeQueue
from docu_studio.shorts.shorts_script_gen import generate_shorts_script


class ShortsRunStatus(str, Enum):
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class ShortsRunner(threading.Thread):
    def __init__(
        self,
        topic: str,
        duration_seconds: int,
        llm: LLMProvider,
        tts: TTSProvider,
        footage_providers: list[FootageProvider],
        output_base: Path,
        captions_enabled: bool = True,
        music_enabled: bool = True,
        sensitive_keys: list[str] | None = None,
        seed: int | None = None,
    ) -> None:
        super().__init__(daemon=True, name="ShortsRunner")
        self.config = ShortsConfig(
            topic=topic,
            duration_seconds=duration_seconds,
            captions_enabled=captions_enabled,
            music_enabled=music_enabled,
        )
        self.llm = llm
        self.tts = tts
        self.footage_providers = footage_providers
        self.output_base = output_base
        self._sensitive_keys: list[str] = sensitive_keys or []
        self._seed = seed if seed is not None else int(datetime.now().timestamp())

        self.event_queue: ShortsTeeQueue = ShortsTeeQueue()
        self.cancel_event = threading.Event()

        self._status = ShortsRunStatus.FAILED
        self._project_folder: Path | None = None
        self._final_video_path: Path | None = None
        self._started_at = datetime.now()

    def run(self) -> None:
        shorts_logger = logging.getLogger("docu_studio.shorts")
        handler = QueueLoggingHandler(self.event_queue)
        prev_level = shorts_logger.level
        shorts_logger.addHandler(handler)
        shorts_logger.setLevel(logging.INFO)
        try:
            self._execute()
        except Exception as exc:
            self.event_queue.put(ErrorEvent(message=str(exc), fatal=True))
            self._status = ShortsRunStatus.FAILED
        finally:
            shorts_logger.removeHandler(handler)
            shorts_logger.setLevel(prev_level)
            self._save_history()
            self.event_queue.close_log()  # flush log before sentinel
            self.event_queue.put(None)

    def _execute(self) -> None:
        if self._cancelled():
            return
        self._project_folder = create_project_folder(
            self.config.topic, self._started_at, self.output_base
        )
        self.event_queue.open_log(
            self._project_folder / "shorts_log.txt", self._sensitive_keys
        )
        ffmpeg = ShortsFFmpeg()

        self.event_queue.put(ProgressEvent(
            stage="Short Script", message=f"Writing short script for '{self.config.topic}'…",
        ))
        script = generate_shorts_script(self.config.topic, self.config.duration_seconds, self.llm)
        (self._project_folder / "script.md").write_text(script.text, encoding="utf-8")
        self.event_queue.put(LogEvent(
            message=f"Short script generated ({len(script.text.split())} words, "
                    f"{len(script.sentences)} sentences)",
            level=LogLevel.INFO,
        ))
        if self._cancelled():
            return

        self.event_queue.put(ProgressEvent(stage="Short TTS", message="Synthesizing voiceover…"))
        audio_path = str(self._project_folder / "audio" / "short.mp3")
        audio_duration = self.tts.synthesize(script.text, audio_path)
        self.event_queue.put(LogEvent(message=f"Voiceover: {audio_duration:.2f}s", level=LogLevel.INFO))
        if self._cancelled():
            return

        self.event_queue.put(ProgressEvent(
            stage="Short Alignment", message="Resolving word-level timing…",
        ))
        timestamps, tier_used = get_word_timestamps(audio_path, script.text, self.tts)
        self.event_queue.put(LogEvent(message=f"Word timing resolver: {tier_used}", level=LogLevel.INFO))
        if self._cancelled():
            return

        output_path = self._project_folder / "short_final.mp4"
        assemble_short(
            script=script,
            audio_path=audio_path,
            audio_duration=audio_duration,
            timestamps=timestamps,
            tier_used=tier_used,
            providers=self.footage_providers,
            ffmpeg=ffmpeg,
            project_folder=self._project_folder,
            output_path=output_path,
            seed=self._seed,
            event_queue=self.event_queue,
            captions_enabled=self.config.captions_enabled,
            music_enabled=self.config.music_enabled,
        )
        if self._cancelled():
            return

        self._final_video_path = output_path
        self._status = ShortsRunStatus.COMPLETED
        actual_duration = ffmpeg.get_duration(str(output_path))
        self.event_queue.put(ProgressEvent(
            stage="Done",
            message=(
                f"Short completed: {actual_duration:.1f}s actual vs "
                f"{self.config.duration_seconds}s requested."
            ),
        ))

    def _cancelled(self) -> bool:
        if self.cancel_event.is_set():
            self._status = ShortsRunStatus.CANCELLED
            self.event_queue.put(ProgressEvent(stage="Cancelled", message="Run cancelled by user."))
            return True
        return False

    def _save_history(self) -> None:
        try:
            record = RunRecord(
                topic=self.config.topic,
                mode="shorts",
                status=self._status.value,
                started_at=self._started_at,
                project_folder=self._project_folder or self.output_base,
                topic_source="user_supplied",
                fallback_triggered=False,
            )
            save_run(record)
        except Exception:
            pass  # history failure must never crash the runner
```

2. No new test file — `ShortsRunner` has no existing unit test to extend, and it's a thin thread-orchestration wrapper over already-tested pieces; verified end-to-end via the dry-run report.

---

## Task 12: `bridge.py` — mode-aware stage maps + config passthrough

### Files
- Modify: `docu_studio/gui/bridge.py`

### Interfaces
- Consumes: nothing new.
- Produces: `Bridge._SHORTS_STAGE_MAP`, `Bridge._active_mode` — consumed by Task 13's JS (indirectly, via the JSON event shape it already produces).

### Steps

1. Add the shorts stage map and mode-tracking as class/instance state, right after the existing `_STAGE_MAP`:

```python
    _STAGE_MAP = {
        "script":   0, "scene":    1, "audio":    2,
        "keyword":  3, "footage":  4, "sync":     5,
        "timeline": 6, "fcpxml":   6, "export":   6,
        "merge":    7, "done":     7, "complete": 7,
    }
    _SHORTS_STAGE_MAP = {
        "script": 0, "tts": 1, "alignment": 2, "footage": 3,
        "assembly": 4, "caption": 5, "music": 5,
        "mux": 6, "done": 6, "complete": 6,
    }
    _FINAL_STAGE_INDEX_BY_MODE = {"doc": 7, "shorts": 6}

    def __init__(self):
        self._window: webview.Window | None = None
        self._event_q: queue.Queue = queue.Queue()
        self._runner = None
        self._run_thread = None
        self._settings = Settings.load()
        self._active_mode = "doc"
```

2. In `start_run`, set the mode right after the initial "already running" guard (before the `try:` block's first line stays the same — insert as the first statement inside `try:`):

```python
    def start_run(self, config: dict) -> dict:
        if self._run_thread and self._run_thread.is_alive():
            return {"ok": False, "error": "A run is already in progress"}
        try:
            self._active_mode = "doc"
            from docu_studio.adapters.footage.factory import build_footage_providers
```

(Only the `self._active_mode = "doc"` line is new; everything else in `start_run` is unchanged.)

3. In `start_shorts_run`, set the mode and read the two new toggles, then pass them to `ShortsRunner`:

```python
    def start_shorts_run(self, config: dict) -> dict:
        if self._run_thread and self._run_thread.is_alive():
            return {"ok": False, "error": "A run is already in progress"}
        try:
            self._active_mode = "shorts"
            from docu_studio.adapters.footage.factory import build_footage_providers
```

And further down, where `duration_seconds` is parsed:

```python
            duration_seconds = int(config.get("duration_seconds", 30))
            captions_enabled = bool(config.get("captions_enabled", True))
            music_enabled = bool(config.get("music_enabled", True))

            self._runner = ShortsRunner(
                topic=config.get("topic", ""),
                duration_seconds=duration_seconds,
                llm=llm,
                tts=tts,
                footage_providers=footage_list,
                output_base=output_base,
                captions_enabled=captions_enabled,
                music_enabled=music_enabled,
                sensitive_keys=[
                    v for v in [llm_key, tts_key, pexels_key, pixabay_key, coverr_key] if v
                ],
            )
```

4. Replace `_to_js_event` to be mode-aware:

```python
    def _to_js_event(self, event: object) -> dict | None:
        stage_map = self._SHORTS_STAGE_MAP if self._active_mode == "shorts" else self._STAGE_MAP
        final_idx = self._FINAL_STAGE_INDEX_BY_MODE.get(self._active_mode, 7)
        cname = type(event).__name__.lower()

        if "log" in cname:
            msg = getattr(event, "message", str(event))
            lower = msg.lower()
            level = "info"
            if any(w in lower for w in ("error", "fail", "exception")):
                level = "error"
            elif "warn" in lower:
                level = "warning"
            elif any(w in lower for w in ("success", "complete", "done", "finished")):
                level = "success"
            for kw, idx in stage_map.items():
                if kw in lower:
                    self._event_q.put({"type": "stage", "index": idx, "state": "active"})
                    break
            return {"type": "log", "message": msg, "level": level}

        elif "progress" in cname:
            stage = (getattr(event, "stage", "") or "").lower()
            if stage == "done":
                return {"type": "stage", "index": final_idx, "state": "complete"}
            if stage == "cancelled":
                return {"type": "error", "message": "Run cancelled by user."}
            state = getattr(event, "state", "active")
            for kw, idx in stage_map.items():
                if kw in stage:
                    return {"type": "stage", "index": idx, "state": state}
            return None

        elif "error" in cname:
            return {"type": "error", "message": getattr(event, "message", str(event))}

        return {"type": "log", "message": str(event), "level": "info"}
```

5. No test file — `bridge.py` has no existing unit tests in this repo (it's a pywebview-bound GUI class); verified via the GUI smoke-check in Task 13's step 5 and the dry-run report.

---

## Task 13: GUI — shorts stage track, captions/music toggles, cache bust

### Files
- Modify: `docu_studio/gui/web/index.html`
- Modify: `docu_studio/gui/web/app.js`
- Modify: `docu_studio/gui/webview_app.py`

### Steps

1. In `index.html`, insert two new toggle rows right after the existing `aspect-row` block (before the `<!-- Start button -->` comment), inside the same `<div class="anim-card ...">` card:

```html
        <!-- Captions toggle (short/reel) -->
        <div id="captions-row" class="mt-6 flex items-center justify-between" style="display:none">
          <div>
            <label class="text-sm font-medium text-dim block">Burned-in captions</label>
            <p class="text-xs text-faint mt-0.5">Word-level pop captions in the safe area.</p>
          </div>
          <input id="captions-toggle" type="checkbox" checked class="w-5 h-5 accent-accent cursor-pointer">
        </div>

        <!-- Music toggle (short/reel) -->
        <div id="music-row" class="mt-4 flex items-center justify-between" style="display:none">
          <div>
            <label class="text-sm font-medium text-dim block">Background music</label>
            <p class="text-xs text-faint mt-0.5">Ducked under narration, only if a track is available.</p>
          </div>
          <input id="music-toggle" type="checkbox" checked class="w-5 h-5 accent-accent cursor-pointer">
        </div>
```

2. In `index.html`, insert a second stage-tracker `<div>` immediately after the closing `</div>` of the existing `id="stage-track"` block (before the `<!-- Log -->` comment):

```html
      <div class="flex flex-wrap gap-2" id="shorts-stage-track" style="display:none">
        <div id="short-stage-0" class="flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium bg-hover text-faint border border-border"><span class="stage-dot w-2 h-2 rounded-full bg-faint"></span>Script</div>
        <div id="short-stage-1" class="flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium bg-hover text-faint border border-border"><span class="stage-dot w-2 h-2 rounded-full bg-faint"></span>TTS</div>
        <div id="short-stage-2" class="flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium bg-hover text-faint border border-border"><span class="stage-dot w-2 h-2 rounded-full bg-faint"></span>Alignment</div>
        <div id="short-stage-3" class="flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium bg-hover text-faint border border-border"><span class="stage-dot w-2 h-2 rounded-full bg-faint"></span>Footage</div>
        <div id="short-stage-4" class="flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium bg-hover text-faint border border-border"><span class="stage-dot w-2 h-2 rounded-full bg-faint"></span>Assembly</div>
        <div id="short-stage-5" class="flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium bg-hover text-faint border border-border"><span class="stage-dot w-2 h-2 rounded-full bg-faint"></span>Captions & Music</div>
        <div id="short-stage-6" class="flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium bg-hover text-faint border border-border"><span class="stage-dot w-2 h-2 rounded-full bg-faint"></span>Mux</div>
      </div>
```

3. In `app.js`:

a) Add `SHORT_STAGES` right after the existing `STAGES` constant:

```javascript
const STAGES = ['Script','Scenes','Audio','Keywords','Footage','Sync','Timeline','Done'];
const SHORT_STAGES = ['Script','TTS','Alignment','Footage','Assembly','Captions & Music','Mux'];
```

b) In `startConfig(mode)`, add captions/music row toggling alongside the existing `aspect-row` line:

```javascript
  _q('doc-duration-row').style.display = mode === 'short' ? 'none' : '';
  _q('short-duration-row').style.display = mode === 'short' ? '' : 'none';
  _q('aspect-row').style.display = mode === 'short' ? '' : 'none';
  _q('captions-row').style.display = mode === 'short' ? '' : 'none';
  _q('music-row').style.display = mode === 'short' ? '' : 'none';
  showScreen('config');
```

c) In `startRun()`, add the two toggle values to the shorts payload:

```javascript
    const secs = parseInt(_q('shorts-duration-slider').value) || 30;
    showScreen('progress');
    _resetProgress();
    startPolling();
    const res = await window.pywebview.api.start_shorts_run({
      topic, duration_seconds: secs,
      captions_enabled: _q('captions-toggle').checked,
      music_enabled: _q('music-toggle').checked,
    });
    if (!res.ok) appendLog('Failed to start: ' + (res.error || ''), 'error');
    return;
```

d) Replace `_resetProgress()` to be mode-aware:

```javascript
function _resetProgress() {
  _q('progress-title').textContent = 'Generating…';
  _q('log-area').innerHTML = '';
  _q('open-folder-btn').style.display = 'none';
  const isShort = _runMode === 'short';
  _q('stage-track').style.display = isShort ? 'none' : '';
  _q('shorts-stage-track').style.display = isShort ? '' : 'none';
  const stages = isShort ? SHORT_STAGES : STAGES;
  stages.forEach((_, i) => _setStage(i, 'pending'));
}
```

e) Replace `_setStage()` to look up the right id prefix:

```javascript
function _setStage(i, state) {
  const prefix = _runMode === 'short' ? 'short-stage-' : 'stage-';
  const el = _q(prefix + i);
  if (!el) return;
  const base = 'flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium border ';
  const styles = {
    pending:  base + 'bg-[#2e313a] text-[#7a8099] border-[#383b45]',
    active:   base + 'bg-[#0c2d42] text-sky-400 border-sky-400',
    complete: base + 'bg-[#052e16] text-green-400 border-green-500',
    error:    base + 'bg-[#2d0a0a] text-red-400 border-red-500',
  };
  el.className = styles[state] || styles.pending;
  const dot = el.querySelector('.stage-dot');
  if (dot) {
    const dc = { pending:'bg-[#7a8099]', active:'bg-sky-400 animate-pulse',
                 complete:'bg-green-400', error:'bg-red-400' };
    dot.className = 'stage-dot w-2 h-2 rounded-full ' + (dc[state] || dc.pending);
  }
}
```

f) In `_handleEvent`'s `complete` branch, replace the hardcoded `_setStage(7, 'complete')` with a mode-aware index:

```javascript
  if (ev.type === 'complete') {
    stopPolling();
    _q('progress-title').textContent = '✓ Complete!';
    _q('progress-title').className = 'font-semibold text-green-400 ml-4';
    const btn = _q('open-folder-btn');
    btn.style.display = '';
    btn.onclick = () => window.pywebview.api.open_output_folder(ev.output_path);
    _setStage(_runMode === 'short' ? 6 : 7, 'complete');
    _q('cancel-btn').style.display = 'none';
    _q('back-btn').style.display = '';
  }
```

4. In `docu_studio/gui/webview_app.py`, bump the cache-buster on the line that currently reads:

```python
    the_url = str(WEB_DIR / "index.html") + "?v=8"
```

to:

```python
    the_url = str(WEB_DIR / "index.html") + "?v=9"
```

5. Verify (manual smoke check, not automated): `DISPLAY=:1 .venv/bin/python -m docu_studio`, click "Short / Reel Mode," confirm the Captions and Music toggle rows appear (checked by default) and the duration/aspect rows still behave as before; start a short run and confirm the new 7-box shorts stage tracker (Script/TTS/Alignment/Footage/Assembly/Captions & Music/Mux) advances instead of the old 8-box documentary tracker; separately start a guided documentary run and confirm its 8-box tracker and behavior are unchanged.

---

## Final Verification (after all 13 tasks)

1. `.venv/bin/python -m pytest -q --ignore=tests/integration/test_edge_tts_adapter.py` — expect **24 pre-existing failures + the same 195+N passed** (N = new tests added across Tasks 2/3/4/6/7), zero new failures. (The `test_edge_tts_adapter.py` collection error is pre-existing/unrelated — same `--ignore` used to establish the baseline in this planning session; if the actual project's baseline command doesn't ignore it, run without `--ignore` and confirm the same single collection error plus 24 failures, all pre-existing.)
2. Confirm baseline command without ignore also still shows exactly 1 collection error (`test_edge_tts_adapter.py`, pre-existing, unrelated to this work) + 24 pre-existing failures, no new ones.
3. Deliver the REPORT BACK: observed tier-chain behavior (Tier 2 forced via mocking since faster-whisper isn't installed in this `.venv`; document the real-environment fallback test's result too), a sample of `generate_ass()` output for one test sentence, confirmation of graceful empty-music-dir behavior (from `test_real_shipped_manifest_has_no_usable_tracks_out_of_the_box`), the `shorts_log.txt` contents from a dry run (if a live run is feasible in this environment — otherwise the file format is demonstrated via `ShortsTeeQueue._tee`'s line format), and the final 7-stage shorts progress list.

## Self-Review Checklist

- [x] Every requirement in the user's spec (0: log file + stage cleanup, 1: Whisper Tier 2, 2: captions, 3: music bed, 4: tests) maps to at least one task above.
- [x] No task touches `pipeline/`, `runner/`, `adapters/`, `history/`, `licensing.py`, or an existing test file.
- [x] No placeholder code — every function shown is complete and directly copy-pasteable.
- [x] `mux_shorts_audio` and `concat_segments_video_only` (pre-existing, tested-by-the-prior-session methods) are never modified — only called with different arguments.
- [x] Tier 2 failure (import error, model error, timeout) always falls through to Tier 3 — verified by 4 distinct tests in Task 3.
- [x] Caption/music failures are independently try/except-guarded in `assemble_short` — a failure in either never fails the run.
- [x] `?v=8` → `?v=9` bump happens exactly once, last, in Task 13.
- [x] Type consistency: `ShortsTeeQueue` is a `queue.Queue` subclass so it satisfies every existing `queue.Queue` type hint (`assemble_short`'s `event_queue: queue.Queue` parameter, `Bridge._translate_events`'s `self._runner.event_queue`) without any signature changes elsewhere.

## Execution Handoff

Recommended: **Subagent-Driven** — one fresh implementer subagent per task above (13 tasks, each with a clear file boundary), with a task-level code-review gate after each, mirroring the process used for the original shorts-mode build. This keeps each subagent's context small and lets review catch integration issues (e.g. Task 10's imports matching Task 4/6's actual exports) before they compound.

Alternative: Inline Execution — I implement all 13 tasks directly in this session, running `pytest` after each and doing a final whole-diff self-review at the end. Faster to start, no subagent-dispatch overhead, but the whole implementation rides in one long context.
