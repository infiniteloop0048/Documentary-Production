# Clip Story Phase 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add captions, background music + ducking, and crossfade transitions to Clip
Story, all additive/default-off on top of Phase 1's uploaded-video/duration-authoritative
pipeline. Captions and ducking are thin reuses of `docu_studio/common/`; crossfade is new
engineering (chained `xfade`+`acrossfade` on already-narration-muxed segments, per the
design spec's resolved fork); music's local-folder provider is a Clip-Story-owned copy of
Slideshow's, per the already-made shared-core decision not to unify "local" music.

**Architecture:** All changes live in `docu_studio/clipstory/` (existing package from
Phase 1) plus one new module `clipstory_music.py`, plus additive GUI wiring in
`bridge.py`/`webview_app.py`/`web/app.js`/`web/index.html`. Every new code path defaults
to Phase 1's exact prior behavior when untouched.

**Tech Stack:** Python 3.11+, ffmpeg (via `imageio_ffmpeg`), pytest, pywebview/JS frontend.

**Spec reference:** `docs/superpowers/specs/2026-07-13-clipstory-phase2-design.md` — every
task below implements a specific section of that spec; consult it for full rationale
behind any decision that seems surprising, especially the crossfade design fork (§
"The real design fork" in Investigation findings).

## Global Constraints

- Do not touch `pipeline/`, `runner/`, `adapters/` (existing files — new adapter files are
  fine), `history/`, `licensing.py`, or existing test files unless fixing an actual bug in
  them.
- Correct venv is `.venv/`, never `venv/`. Restart before testing any GUI change:
  `pkill -f docu_studio 2>/dev/null; DISPLAY=:1 .venv/bin/python -m docu_studio`.
- Work happens on branch/worktree `clipstory-phase2`. Commit incrementally. Do not push
  without explicit go-ahead.
- Bump the cache-busting `?v=N` in `docu_studio/gui/webview_app.py:33` from `?v=13` to
  `?v=14` after the HTML/JS task (Task 6).
- Baseline reconfirmed fresh before Task 1 (2026-07-13): **640 passed, 24 failed** (plus
  one pre-existing collection error in `tests/integration/test_edge_tts_adapter.py`,
  unrelated — exclude it via `--ignore` to get a clean pass/fail count). Every task's "no
  new failures" check compares against this.
- `.m4a`, not `.mp3`, for `mix_music_bed`'s output filename — ffmpeg's mp3 muxer rejects
  the AAC-encoded audio this method produces (a real bug Slideshow Phase 3 already hit and
  documented; do not rediscover it).

---

### Task 0: Baseline check and worktree setup

**Files:** none (verification only).

- [ ] **Step 1: Create the worktree/branch**

Use `superpowers:using-git-worktrees` to create a worktree for branch `clipstory-phase2`
off `main`. Confirm with `git worktree list`.

- [ ] **Step 2: Run the full test suite fresh, record the baseline**

Run: `cd <worktree-path> && .venv/bin/python -m pytest tests/ -q --ignore=tests/integration/test_edge_tts_adapter.py 2>&1 | tail -30`
Expected: `640 passed, 24 failed` (re-confirm — do not assume; read the actual output).

---

### Task 1: `clipstory_config.py` — add Phase 2 fields

**Files:**
- Modify: `docu_studio/clipstory/clipstory_config.py`
- Modify: `tests/unit/test_clipstory_config.py`

**Interfaces:**
- Produces: `ClipStoryConfig` gains `transition: str = "cut"` (`"cut"`|`"crossfade"`),
  `captions: bool = False`, `music_enabled: bool = False`, `music_provider: str =
  "jamendo"` (`"jamendo"`|`"local_folder"`), `music_folder: str = ""`,
  `jamendo_client_id: str = ""`. All validated in `__post_init__` the same way
  `output_resolution` already is. Task 4 (`clipstory_assembly`), Task 5
  (`clipstory_runner`/music resolution), and Task 6 (`bridge.py`) all read these fields.

- [ ] **Step 1: Add failing tests to the existing test file**

Append to `tests/unit/test_clipstory_config.py`:

```python
class TestClipStoryConfigPhase2Fields:
    def test_defaults_match_phase1_behavior(self) -> None:
        clips = [ClipSpec(path="/a.mp4", trim_in=0.0, trim_out=10.0, script_text="Hi.")]
        config = ClipStoryConfig(topic="Test", clips=clips)
        assert config.transition == "cut"
        assert config.captions is False
        assert config.music_enabled is False
        assert config.music_provider == "jamendo"
        assert config.music_folder == ""
        assert config.jamendo_client_id == ""

    def test_crossfade_transition_accepted(self) -> None:
        clips = [ClipSpec(path="/a.mp4", trim_in=0.0, trim_out=10.0, script_text="Hi.")]
        config = ClipStoryConfig(topic="Test", clips=clips, transition="crossfade")
        assert config.transition == "crossfade"

    def test_invalid_transition_raises(self) -> None:
        clips = [ClipSpec(path="/a.mp4", trim_in=0.0, trim_out=10.0, script_text="Hi.")]
        with pytest.raises(ValueError, match="transition"):
            ClipStoryConfig(topic="Test", clips=clips, transition="wipe")

    def test_local_folder_music_provider_accepted(self) -> None:
        clips = [ClipSpec(path="/a.mp4", trim_in=0.0, trim_out=10.0, script_text="Hi.")]
        config = ClipStoryConfig(topic="Test", clips=clips, music_provider="local_folder")
        assert config.music_provider == "local_folder"

    def test_invalid_music_provider_raises(self) -> None:
        clips = [ClipSpec(path="/a.mp4", trim_in=0.0, trim_out=10.0, script_text="Hi.")]
        with pytest.raises(ValueError, match="music_provider"):
            ClipStoryConfig(topic="Test", clips=clips, music_provider="spotify")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_clipstory_config.py -v -k Phase2`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'transition'`.

- [ ] **Step 3: Implement**

In `docu_studio/clipstory/clipstory_config.py`, add a module-level constant and extend
`ClipStoryConfig`:

```python
_VALID_TRANSITIONS = ("cut", "crossfade")
_VALID_MUSIC_PROVIDERS = ("jamendo", "local_folder")
```

Extend the `ClipStoryConfig` dataclass fields (after `tts_voice: str = ""`):

```python
    transition: str = "cut"
    captions: bool = False
    music_enabled: bool = False
    music_provider: str = "jamendo"
    music_folder: str = ""
    jamendo_client_id: str = ""
```

Extend `__post_init__` (after the existing `output_resolution` check):

```python
        if self.transition not in _VALID_TRANSITIONS:
            raise ValueError(
                f"transition must be one of {_VALID_TRANSITIONS}, got {self.transition!r}"
            )
        if self.music_provider not in _VALID_MUSIC_PROVIDERS:
            raise ValueError(
                f"music_provider must be one of {_VALID_MUSIC_PROVIDERS}, "
                f"got {self.music_provider!r}"
            )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_clipstory_config.py -v`
Expected: PASS (all, including the 5 new Phase 2 cases).

- [ ] **Step 5: Full-suite regression check**

Run: `.venv/bin/python -m pytest tests/ -q --ignore=tests/integration/test_edge_tts_adapter.py 2>&1 | tail -10`
Expected: `645 passed, 24 failed` (5 new tests, zero regressions).

- [ ] **Step 6: Commit**

```bash
git add docu_studio/clipstory/clipstory_config.py tests/unit/test_clipstory_config.py
git commit -m "feat(clipstory): add Phase 2 config fields (transition, captions, music)"
```

---

### Task 2: `clipstory_music.py` — local-folder provider + fallback resolver

**Files:**
- Create: `docu_studio/clipstory/clipstory_music.py`
- Create: `tests/unit/test_clipstory_music.py`

**Interfaces:**
- Consumes: `JamendoMusicProvider`, `TrackCandidate`, `DEFAULT_MUSIC_MOOD` from
  `docu_studio.common.music_jamendo` (unchanged, 100% reuse).
- Produces: `class LocalFolderMusicProvider(folder_path: str, seed: int = 0)` with
  `search(query, max_duration) -> list[TrackCandidate]` / `fetch(candidate) -> str`;
  `resolve_music_track(provider_name: str, mood: str, max_duration: float,
  jamendo_client_id: str = "", local_folder: str = "", seed: int = 0) -> tuple[str, str] |
  None`. Task 5 (`clipstory_runner.py`) calls `resolve_music_track` directly — this is a
  verbatim copy of `docu_studio/slideshow/slideshow_music.py`'s shape (deliberately not
  shared, per the shared-core design's already-made decision).

- [ ] **Step 1: Write the failing tests**

```python
"""Unit tests for clipstory_music: local-folder provider + fallback resolver.
Mirrors tests/unit/test_slideshow_music.py's structure — same technique, own module."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from docu_studio.clipstory.clipstory_music import (
    LocalFolderMusicProvider,
    resolve_music_track,
)
from docu_studio.common.music_jamendo import TrackCandidate


class TestLocalFolderMusicProvider:
    def test_missing_folder_returns_empty(self) -> None:
        provider = LocalFolderMusicProvider("/nonexistent/folder")
        assert provider.search("cinematic", 30.0) == []

    def test_empty_folder_returns_empty(self, tmp_path: Path) -> None:
        provider = LocalFolderMusicProvider(str(tmp_path))
        assert provider.search("cinematic", 30.0) == []

    def test_folder_with_no_audio_files_returns_empty(self, tmp_path: Path) -> None:
        (tmp_path / "notes.txt").write_text("hi")
        provider = LocalFolderMusicProvider(str(tmp_path))
        assert provider.search("cinematic", 30.0) == []

    def test_picks_a_deterministic_track_with_fixed_seed(self, tmp_path: Path) -> None:
        (tmp_path / "a.mp3").write_bytes(b"x")
        (tmp_path / "b.mp3").write_bytes(b"x")
        provider = LocalFolderMusicProvider(str(tmp_path), seed=42)
        result1 = provider.search("cinematic", 30.0)
        result2 = LocalFolderMusicProvider(str(tmp_path), seed=42).search("cinematic", 30.0)
        assert len(result1) == 1
        assert result1[0].title == result2[0].title

    def test_fetch_returns_local_path(self, tmp_path: Path) -> None:
        (tmp_path / "a.mp3").write_bytes(b"x")
        provider = LocalFolderMusicProvider(str(tmp_path))
        candidate = provider.search("cinematic", 30.0)[0]
        assert provider.fetch(candidate) == candidate.local_path

    def test_empty_folder_path_is_treated_as_no_folder(self) -> None:
        provider = LocalFolderMusicProvider("")
        assert provider.search("cinematic", 30.0) == []


class TestResolveMusicTrack:
    def test_jamendo_success_returns_track(self, tmp_path: Path) -> None:
        candidate = TrackCandidate(
            title="Song", duration=60.0, download_url="http://x", source="jamendo",
        )
        with patch("docu_studio.clipstory.clipstory_music.JamendoMusicProvider") as MockJamendo:
            instance = MockJamendo.return_value
            instance.search.return_value = [candidate]
            instance.fetch.return_value = "/cache/song.mp3"
            result = resolve_music_track(
                "jamendo", "cinematic", 30.0, jamendo_client_id="abc",
            )
        assert result == ("/cache/song.mp3", "Song")

    def test_jamendo_empty_falls_back_to_local_folder(self, tmp_path: Path) -> None:
        (tmp_path / "a.mp3").write_bytes(b"x")
        with patch("docu_studio.clipstory.clipstory_music.JamendoMusicProvider") as MockJamendo:
            instance = MockJamendo.return_value
            instance.search.return_value = []
            result = resolve_music_track(
                "jamendo", "cinematic", 30.0,
                jamendo_client_id="abc", local_folder=str(tmp_path),
            )
        assert result is not None
        assert result[0].endswith("a.mp3")

    def test_local_folder_provider_selected_directly(self, tmp_path: Path) -> None:
        (tmp_path / "a.mp3").write_bytes(b"x")
        result = resolve_music_track(
            "local_folder", "cinematic", 30.0, local_folder=str(tmp_path),
        )
        assert result is not None

    def test_no_usable_track_from_any_provider_returns_none(self) -> None:
        with patch("docu_studio.clipstory.clipstory_music.JamendoMusicProvider") as MockJamendo:
            instance = MockJamendo.return_value
            instance.search.return_value = []
            result = resolve_music_track("jamendo", "cinematic", 30.0, local_folder="")
        assert result is None

    def test_jamendo_fetch_failure_falls_back_to_local_folder(self, tmp_path: Path) -> None:
        (tmp_path / "a.mp3").write_bytes(b"x")
        candidate = TrackCandidate(
            title="Song", duration=60.0, download_url="http://x", source="jamendo",
        )
        with patch("docu_studio.clipstory.clipstory_music.JamendoMusicProvider") as MockJamendo:
            instance = MockJamendo.return_value
            instance.search.return_value = [candidate]
            instance.fetch.side_effect = Exception("network error")
            result = resolve_music_track(
                "jamendo", "cinematic", 30.0,
                jamendo_client_id="abc", local_folder=str(tmp_path),
            )
        assert result is not None
        assert result[0].endswith("a.mp3")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_clipstory_music.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'docu_studio.clipstory.clipstory_music'`.

- [ ] **Step 3: Write the implementation**

```python
"""Music provider abstraction for Clip Story — a verbatim copy of
docu_studio.slideshow.slideshow_music's shape (LocalFolderMusicProvider,
resolve_music_track), deliberately not shared with Slideshow: the shared-core
extraction already decided each feature's "local" music concept differs
(Shorts' bundled manifest vs. a user-browsed folder) and isn't worth unifying.
Jamendo search+cache+fetch (JamendoMusicProvider, TrackCandidate) comes from
the shared docu_studio.common.music_jamendo module — that part IS shared.

resolve_music_track() is the single entry point callers use. It walks the
configured provider, falls back to the local folder, then gives up (None) —
never raising. The music bed is always optional.
"""
from __future__ import annotations

import logging
import random
from pathlib import Path

from docu_studio.common.music_jamendo import (
    DEFAULT_MUSIC_MOOD,
    JamendoMusicProvider,
    TrackCandidate,
)

_log = logging.getLogger(__name__)

_AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".ogg"}


class LocalFolderMusicProvider:
    """Picks a random audio file from a user-browsed folder. search() never
    raises — a missing/empty folder or a folder with no recognized audio
    files just returns an empty candidate list."""

    def __init__(self, folder_path: str, seed: int = 0) -> None:
        self._folder_path = folder_path
        self._seed = seed

    def search(self, query: str, max_duration: float) -> list[TrackCandidate]:
        folder = Path(self._folder_path) if self._folder_path else None
        if folder is None:
            return []
        try:
            if not folder.is_dir():
                return []
            files = sorted(
                p for p in folder.iterdir()
                if p.is_file() and p.suffix.lower() in _AUDIO_EXTENSIONS
            )
        except OSError as exc:
            _log.warning("LocalFolderMusicProvider: search failed (%s) — returning empty list", exc)
            return []
        if not files:
            return []
        chosen = random.Random(self._seed).choice(files)
        return [TrackCandidate(
            title=chosen.name,
            duration=max_duration,
            download_url="",
            source="local_folder",
            local_path=str(chosen),
        )]

    def fetch(self, candidate: TrackCandidate) -> str:
        if not candidate.local_path:
            raise ValueError("LocalFolderMusicProvider candidate is missing local_path")
        return candidate.local_path


def resolve_music_track(
    provider_name: str,
    mood: str,
    max_duration: float,
    jamendo_client_id: str = "",
    local_folder: str = "",
    seed: int = 0,
) -> tuple[str, str] | None:
    """Resolve a local, playable music file, honoring the provider -> local
    folder -> none fallback chain. Returns (local_path, label), or None if no
    provider produced a usable track — callers must skip the music bed
    gracefully in that case."""
    if provider_name == "jamendo":
        jamendo = JamendoMusicProvider(jamendo_client_id)
        candidates = jamendo.search(mood, max_duration)
        if candidates:
            try:
                path = jamendo.fetch(candidates[0])
                _log.info("Clip Story music: using Jamendo track %r", candidates[0].title)
                return path, candidates[0].title
            except Exception as exc:
                _log.warning("Jamendo: download failed (%s) — falling back to local folder", exc)
        else:
            _log.info("Jamendo: no usable candidates — falling back to local folder")

    local = LocalFolderMusicProvider(local_folder, seed=seed)
    candidates = local.search(mood, max_duration)
    if candidates:
        path = local.fetch(candidates[0])
        _log.info("Clip Story music: using local-folder track %r", candidates[0].title)
        return path, candidates[0].title

    _log.info("Clip Story music: no usable track from any provider — skipping music bed")
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_clipstory_music.py -v`
Expected: PASS (12 tests).

- [ ] **Step 5: Full-suite regression check**

Run: `.venv/bin/python -m pytest tests/ -q --ignore=tests/integration/test_edge_tts_adapter.py 2>&1 | tail -10`
Expected: `657 passed, 24 failed`.

- [ ] **Step 6: Commit**

```bash
git add docu_studio/clipstory/clipstory_music.py tests/unit/test_clipstory_music.py
git commit -m "feat(clipstory): add local-folder music provider + resolve_music_track"
```

---

### Task 3: `clipstory_ffmpeg.py` — captions, ducking, crossfade methods + cleanup

**Files:**
- Modify: `docu_studio/clipstory/clipstory_ffmpeg.py`
- Modify: `tests/unit/test_clipstory_ffmpeg.py`

**Interfaces:**
- Consumes: `finalize_filter` (already imported); deferred-import
  `build_ducking_filtergraph` from `docu_studio.common.audio_ducking` inside
  `mix_music_bed` only (mirrors Slideshow's deferred-import discipline).
- Produces new methods on `ClipStoryFFmpeg`: `burn_captions(input_path: str, ass_path:
  str, output_path: str) -> None`; `mix_music_bed(voice_path: str, music_path: str,
  video_duration: float, output_path: str) -> None`; `concat_segments_with_xfade(
  input_paths: list[str], durations: list[float], transition_duration: float,
  output_path: str) -> None` (raises `ValueError` if `len(input_paths) < 2`). Also fixes
  two Minor cleanup items in this same file (see below). Task 4 (`clipstory_assembly.py`)
  calls all three new methods plus the fixed `concat_segments`/`apply_reconciliation`.

- [ ] **Step 1: Write the failing tests — append to the existing test file**

```python
class TestBurnCaptions(object):
    def test_filter_string_uses_subtitles_and_finalizes(self, wrapper: ClipStoryFFmpeg, tmp_path) -> None:
        ass_path = tmp_path / "captions.ass"
        ass_path.write_text("dummy")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.burn_captions("/in.mp4", str(ass_path), "/out.mp4")
        args = mock_run.call_args[0][0]
        vf = args[args.index("-vf") + 1]
        assert vf.startswith("subtitles=captions.ass")
        assert "setsar=1,format=yuv420p" in vf

    def test_runs_with_cwd_set_to_ass_directory(self, wrapper: ClipStoryFFmpeg, tmp_path) -> None:
        ass_path = tmp_path / "captions.ass"
        ass_path.write_text("dummy")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.burn_captions("/in.mp4", str(ass_path), "/out.mp4")
        assert mock_run.call_args.kwargs["cwd"] == str(tmp_path)

    def test_ffmpeg_failure_raises_ffmpeg_error(self, wrapper: ClipStoryFFmpeg, tmp_path) -> None:
        ass_path = tmp_path / "captions.ass"
        ass_path.write_text("dummy")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="boom")
            with pytest.raises(FFmpegError):
                wrapper.burn_captions("/in.mp4", str(ass_path), "/out.mp4")


class TestMixMusicBed:
    def test_uses_ducking_filtergraph_and_loops_music_input(self, wrapper: ClipStoryFFmpeg) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.mix_music_bed("/voice.mp4", "/music.mp3", 30.0, "/out.m4a")
        args = mock_run.call_args[0][0]
        assert "-stream_loop" in args
        assert args[args.index("-stream_loop") + 1] == "-1"
        assert "-map" in args and args[args.index("-map") + 1] == "[aout]"
        fc = args[args.index("-filter_complex") + 1]
        assert "sidechaincompress" in fc and "amix" in fc

    def test_ffmpeg_failure_raises_ffmpeg_error(self, wrapper: ClipStoryFFmpeg) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="boom")
            with pytest.raises(FFmpegError):
                wrapper.mix_music_bed("/voice.mp4", "/music.mp3", 30.0, "/out.m4a")


class TestConcatSegmentsWithXfade:
    def test_two_segments_chains_xfade_and_acrossfade(self, wrapper: ClipStoryFFmpeg) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.concat_segments_with_xfade(
                ["/a.mp4", "/b.mp4"], [10.0, 8.0], 0.5, "/out.mp4",
            )
        args = mock_run.call_args[0][0]
        fc = args[args.index("-filter_complex") + 1]
        assert "xfade=transition=fade:duration=0.50:offset=9.500" in fc
        assert "acrossfade=d=0.50" in fc
        assert "setsar=1,format=yuv420p" in fc
        assert args[args.index("-map") + 1] == "[vout]"
        assert args[args.index("-map", args.index("-map") + 1) + 1] == "[aout]"

    def test_three_segments_chains_cumulative_offsets(self, wrapper: ClipStoryFFmpeg) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.concat_segments_with_xfade(
                ["/a.mp4", "/b.mp4", "/c.mp4"], [10.0, 8.0, 6.0], 0.5, "/out.mp4",
            )
        args = mock_run.call_args[0][0]
        fc = args[args.index("-filter_complex") + 1]
        # offset 1: 10.0 - 0.5 = 9.5; offset 2: (9.5+8.0) - 0.5 = 17.0
        assert "offset=9.500" in fc
        assert "offset=17.000" in fc
        assert fc.count("xfade=") == 2
        assert fc.count("acrossfade=") == 2

    def test_fewer_than_two_segments_raises(self, wrapper: ClipStoryFFmpeg) -> None:
        with pytest.raises(ValueError, match="at least 2"):
            wrapper.concat_segments_with_xfade(["/a.mp4"], [10.0], 0.5, "/out.mp4")

    def test_ffmpeg_failure_raises_ffmpeg_error(self, wrapper: ClipStoryFFmpeg) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="boom")
            with pytest.raises(FFmpegError):
                wrapper.concat_segments_with_xfade(
                    ["/a.mp4", "/b.mp4"], [10.0, 8.0], 0.5, "/out.mp4",
                )


class TestApplyReconciliationNoneBranchErrorHandling:
    def test_copy_failure_raises_ffmpeg_error_not_os_error(self, wrapper: ClipStoryFFmpeg) -> None:
        from docu_studio.clipstory.clipstory_pacing import ReconciliationPlan
        plan = ReconciliationPlan(action="none", adjustment_seconds=0.0)
        with patch("shutil.copy", side_effect=OSError("disk full")):
            with pytest.raises(FFmpegError, match="disk full"):
                wrapper.apply_reconciliation("/in.mp3", plan, 10.0, "/out.mp3")


class TestConcatSegmentsNoRedundantScale:
    def test_filter_complex_has_no_scale_only_fps(self, wrapper: ClipStoryFFmpeg) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.concat_segments(["/a.mp4", "/b.mp4"], "16:9", "/out.mp4")
        args = mock_run.call_args[0][0]
        fc = args[args.index("-filter_complex") + 1]
        assert "scale=" not in fc
        assert "fps=30" in fc
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_clipstory_ffmpeg.py -v -k "BurnCaptions or MixMusicBed or Xfade or NoneBranch or NoRedundantScale"`
Expected: FAIL — `AttributeError: 'ClipStoryFFmpeg' object has no attribute 'burn_captions'`
(and similar for the other new methods); the two cleanup tests fail against current
behavior (`test_copy_failure_raises_ffmpeg_error_not_os_error` raises a raw `OSError`
instead, `test_filter_complex_has_no_scale_only_fps` finds `scale=` present).

- [ ] **Step 3: Implement — add methods and apply the two cleanup fixes**

Add `os` to the existing imports (`import os` alongside `shutil`/`subprocess`).

Add these three new methods to `ClipStoryFFmpeg` (place after `extract_poster_frame`,
before `concat_segments`):

```python
    def burn_captions(self, input_path: str, ass_path: str, output_path: str) -> None:
        """Burn *ass_path* (ASS pop-caption subtitles) into *input_path* via
        ffmpeg's subtitles filter. *input_path* is video-only — captions burn
        in per-clip, before narration is muxed, so there's no audio stream to
        preserve at this stage. Same cwd-relative-filename technique as
        SlideshowFFmpeg.burn_captions: ffmpeg's -vf value is parsed by the
        avfilter graph description parser, which splits on unescaped ':' —
        this breaks on any colon in the path. Sidestepping it: run ffmpeg with
        cwd set to the subtitle file's own directory and reference only its
        bare filename in the filter string."""
        ass_dir = os.path.dirname(ass_path) or "."
        ass_name = os.path.basename(ass_path)
        vf = finalize_filter(f"subtitles={ass_name}")
        cmd = [
            self._ffmpeg, "-y",
            "-i", os.path.abspath(input_path),
            "-vf", vf,
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "20",
            os.path.abspath(output_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=ass_dir)
        self._check(result, f"burn_captions → {output_path!r}")

    def mix_music_bed(
        self, voice_path: str, music_path: str, video_duration: float, output_path: str,
    ) -> None:
        """Loop/trim *music_path* to *video_duration*, duck it under
        *voice_path* via sidechaincompress, and write the mixed result to
        *output_path* as a standalone audio file. *voice_path* may be a video
        file with an embedded narration track (e.g. the fully-assembled
        Clip Story output) — ffmpeg's [0:a] reference resolves to that file's
        audio stream automatically, no separate extraction pass needed."""
        from docu_studio.common.audio_ducking import build_ducking_filtergraph

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

    @staticmethod
    def _xfade_offsets(durations: list[float], transition_duration: float) -> list[float]:
        """Return the N-1 ffmpeg `offset=` values for chaining `xfade` across
        N segments of the given *durations*. Each offset is the point in the
        running merged timeline where the next segment's crossfade begins:
        cumulative_duration_so_far - transition_duration. Same cumulative
        technique as SlideshowFFmpeg._xfade_offsets, reimplemented locally
        (Clip Story's crossfade was never a shared-core candidate)."""
        offsets: list[float] = []
        cumulative = durations[0]
        for d in durations[1:]:
            offset = cumulative - transition_duration
            offsets.append(offset)
            cumulative = offset + d
        return offsets

    def concat_segments_with_xfade(
        self, input_paths: list[str], durations: list[float],
        transition_duration: float, output_path: str,
    ) -> None:
        """Concatenate already-narration-muxed Clip Story segments with a
        crossfade, chaining ffmpeg's xfade (video) and acrossfade (audio)
        filters together in one filter_complex so video and audio shrink by
        the same overlap at every cut and stay in sync by construction — see
        docs/superpowers/specs/2026-07-13-clipstory-phase2-design.md,
        "the real design fork", for why this differs from Slideshow's
        video-only crossfade (Slideshow never has audio muxed into its
        segments before concat; Clip Story already does). *durations* are
        each segment's actual measured duration (unmodified — unlike
        Slideshow, Clip Story's target duration is the physical trim length,
        not a single narration length to preserve, so a crossfade legitimately
        shortens total output by (n-1) * transition_duration; nothing is
        inflated to compensate). The final xfade stage is finalized through
        setsar=1,format=yuv420p so this path can't reintroduce the SAR
        concat-crash bug."""
        n = len(input_paths)
        if n < 2:
            raise ValueError("concat_segments_with_xfade requires at least 2 segments")
        offsets = self._xfade_offsets(durations, transition_duration)

        stages = []
        prev_v, prev_a = "[0:v]", "[0:a]"
        for i in range(1, n):
            next_v, next_a = f"[{i}:v]", f"[{i}:a]"
            is_last = i == n - 1
            out_v = "[vout]" if is_last else f"[x{i}v]"
            out_a = "[aout]" if is_last else f"[x{i}a]"
            v_stage = (
                f"{prev_v}{next_v}xfade=transition=fade:"
                f"duration={transition_duration:.2f}:offset={offsets[i - 1]:.3f}"
            )
            if is_last:
                v_stage = finalize_filter(v_stage)
            v_stage += out_v
            a_stage = f"{prev_a}{next_a}acrossfade=d={transition_duration:.2f}" + out_a
            stages.append(v_stage)
            stages.append(a_stage)
            prev_v, prev_a = f"[x{i}v]", f"[x{i}a]"
        filter_complex = ";".join(stages)

        cmd = [self._ffmpeg, "-y"]
        for p in input_paths:
            cmd += ["-i", p]
        cmd += [
            "-filter_complex", filter_complex,
            "-map", "[vout]",
            "-map", "[aout]",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "22",
            "-c:a", "aac",
            output_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        self._check(result, f"concat_segments_with_xfade → {output_path!r}")
```

Fix `apply_reconciliation`'s `"none"` branch (replace the bare `else: shutil.copy(...)`):

```python
        else:
            try:
                shutil.copy(input_path, output_path)
            except OSError as exc:
                raise FFmpegError(
                    f"apply_reconciliation(none) → {output_path!r}: {exc}"
                ) from exc
```

Add `FFmpegError` to the existing `docu_studio.media.ffmpeg_wrapper` import line:
```python
from docu_studio.media.ffmpeg_wrapper import FFmpegError, FFmpegWrapper
```

Fix `concat_segments`'s redundant per-segment `scale=` (segments are already exactly
`output_resolution` from `normalize_clip` — re-scaling was always a no-op re-encode).
Change:
```python
        scale_parts = ";".join(f"[{i}:v]fps=30,scale={w}:{h}[v{i}]" for i in range(n))
```
to:
```python
        scale_parts = ";".join(f"[{i}:v]fps=30[v{i}]" for i in range(n))
```
(The `w, h` computed just above are now unused for this purpose but stay — they're still
needed by `_OUTPUT_RESOLUTIONS` validation. If a linter flags `w`/`h` as unused after this
change, keep the validation lookup as `_OUTPUT_RESOLUTIONS[output_resolution]` without
unpacking, e.g. `if output_resolution not in _OUTPUT_RESOLUTIONS: raise ...` only — no
functional difference either way, prefer whichever reads cleaner.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_clipstory_ffmpeg.py -v`
Expected: PASS (all existing tests plus the new ones — no regressions in
`normalize_clip`/`apply_atempo`/`extract_poster_frame`/pad-and-trim_fade branches of
`apply_reconciliation`, which are untouched).

- [ ] **Step 5: Full-suite regression check**

Run: `.venv/bin/python -m pytest tests/ -q --ignore=tests/integration/test_edge_tts_adapter.py 2>&1 | tail -10`
Expected: no new failures beyond the 24 baseline; passed count up by the number of new
tests added in this task.

- [ ] **Step 6: Commit**

```bash
git add docu_studio/clipstory/clipstory_ffmpeg.py tests/unit/test_clipstory_ffmpeg.py
git commit -m "feat(clipstory): add caption burn, music ducking, xfade+acrossfade concat"
```

---

### Task 4: `clipstory_assembly.py` — wire captions/crossfade/music into the pipeline

**Files:**
- Modify: `docu_studio/clipstory/clipstory_assembly.py`
- Modify: `tests/unit/test_clipstory_assembly.py` (or create if Phase 1 didn't leave one at
  this exact name — check first: `ls tests/unit/ | grep clipstory_assembly`)

**Interfaces:**
- Consumes: `estimate_word_timestamps`, `write_ass_file` from `docu_studio.common.captions`
  (deferred import, only when `config.captions`); the three new `ClipStoryFFmpeg` methods
  from Task 3; `_OUTPUT_RESOLUTIONS`-equivalent width/height lookup (reuse
  `ClipStoryFFmpeg._OUTPUT_RESOLUTIONS` or add a small local helper — check what's already
  exposed before adding a duplicate mapping).
- Produces: `assemble_clip_story(config, tts, work_dir, output_path, cancel_event=None,
  music_path: str | None = None) -> None` — new `music_path` parameter, defaulting to
  `None` (Phase 1 callers/tests that don't pass it get identical behavior). Raises a new
  `ClipStoryTransitionError` (naming: mirror `ClipStoryFitError`'s style) when crossfade is
  requested but a clip's duration doesn't support the fixed transition length. Task 5
  (`clipstory_runner.py`) passes `music_path` through; both new/changed exceptions surface
  through the existing `ClipStoryRunner.run()` try/except (already catches bare
  `Exception`, so no runner change needed for the new exception type itself — only for
  passing `music_path` through, see Task 5).

- [ ] **Step 1: Check for and read the existing orchestration test file**

Run: `find tests/unit -iname "*clipstory_assembly*" -o -iname "*clipstory_runner*"`
Read whatever exists to match its exact mocking conventions (how `ClipStoryFFmpeg` and
`TTSProvider` are mocked/patched) before writing new tests — reuse that pattern exactly.

- [ ] **Step 2: Write the failing tests** (adapt mocking style to match what Step 1 found;
the shapes below describe required behavior, not literal fixture code, since the exact
mock setup depends on Phase 1's existing test file)

Required new test cases, added to whatever the existing orchestration test file is
(or a new `tests/unit/test_clipstory_assembly.py` if Phase 1 only tested this via
`clipstory_runner`):

- `test_captions_disabled_by_default_skips_burn_captions` — all-off config (Phase 1
  defaults): asserts `burn_captions` is never called, `concat_segments` (not the xfade
  variant) is called, no `mix_music_bed` call — i.e. **byte-for-byte the same call
  sequence as Phase 1's existing passing test(s)**. This is the regression guard.
- `test_captions_enabled_burns_per_clip_with_clip_local_duration` — `config.captions =
  True`: asserts `estimate_word_timestamps`/`write_ass_file`/`burn_captions` are each
  called once per clip, with each call's `script_text`/`duration` argument being that
  specific clip's own final values (not a whole-project aggregate) — mock 2 clips with
  different `measured_target_duration`/`script_text` and assert both calls' arguments
  differ accordingly.
- `test_crossfade_enabled_with_valid_durations_calls_xfade_concat` — `config.transition =
  "crossfade"`, 2+ mocked clips each with `measured_target_duration` comfortably above
  0.5s: asserts `concat_segments_with_xfade` is called (not `concat_segments`), with the
  durations list matching each clip's measured duration in order.
- `test_crossfade_with_clip_too_short_halts_before_any_concat_call` — one clip's
  `measured_target_duration` mocked to something `<= 0.5`: asserts a
  `ClipStoryTransitionError` (or equivalent) is raised, and neither `concat_segments` nor
  `concat_segments_with_xfade` is ever called.
- `test_crossfade_with_exactly_one_clip_falls_back_to_hard_cut` — 1 clip, `transition =
  "crossfade"`: asserts `concat_segments` (hard cut) is called, not the xfade variant, no
  error raised.
- `test_music_enabled_with_resolved_track_mixes_and_remuxes` — `music_path` passed as a
  non-`None` string: asserts, after the concat call, `mix_music_bed` is called with the
  assembled path as `voice_path` and the given `music_path`, followed by a final
  `mux_audio_video` call using the `mix_music_bed` output as the new audio source.
- `test_music_enabled_with_no_resolved_track_skips_mix` — `music_path=None` (the
  "resolver found nothing" case, already handled at the runner level per Task 5): asserts
  `mix_music_bed` is never called and the final output is the concat step's output
  directly (same as Phase 1).

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest <the test file from Step 1> -v -k "captions or crossfade or music"`
Expected: FAIL — either `TypeError` (unexpected `music_path` kwarg not yet accepted) or
`AssertionError` (new methods never called because the wiring doesn't exist yet).

- [ ] **Step 4: Implement**

In `docu_studio/clipstory/clipstory_assembly.py`:

Add a new exception class near `ClipStoryFitError`... actually this lives in
`clipstory_assembly.py` itself per Phase 1's structure — confirm by reading the current
file's top before adding; if `ClipStoryFitError` is defined here, add alongside it:

```python
class ClipStoryTransitionError(Exception):
    """Raised when a crossfade transition is requested but at least one clip's
    measured duration is too short to support the fixed transition length —
    the xfade offset= math would go negative/invalid for that pair. Halt
    rather than silently clamp or produce broken ffmpeg output, same
    halt-and-report philosophy as ClipStoryFitError."""


_TRANSITION_DURATION = 0.5
```

Change `assemble_clip_story`'s signature to accept `music_path`:

```python
def assemble_clip_story(
    config: ClipStoryConfig,
    tts: TTSProvider,
    work_dir: Path,
    output_path: Path,
    cancel_event: Event | None = None,
    music_path: str | None = None,
) -> None:
```

Inside the per-clip loop, after `ffmpeg.normalize_clip(trimmed_path, config.output_resolution, normalized_path)`
and before the TTS/fit/reconciliation block, insert the caption-burn step. Track a
`video_for_mux_path` variable that starts as `normalized_path` and is reassigned if
captions burn:

```python
        video_for_mux_path = normalized_path
```

Then, after `plan_reconciliation`/`apply_reconciliation` have produced
`final_narration_path` (i.e. right before the existing `mux_audio_video` call), insert:

```python
        if config.captions:
            from docu_studio.common.captions import estimate_word_timestamps, write_ass_file

            timings = estimate_word_timestamps(clip.script_text, measured_target_duration)
            ass_path = str(work_dir / f"clip_{i}_captions.ass")
            out_w, out_h = _OUTPUT_RESOLUTIONS[config.output_resolution]
            write_ass_file(timings, ass_path, out_w, out_h, measured_target_duration)
            captioned_path = str(work_dir / f"clip_{i}_captioned.mp4")
            ffmpeg.burn_captions(normalized_path, ass_path, captioned_path)
            video_for_mux_path = captioned_path
```

(`_OUTPUT_RESOLUTIONS` is `ClipStoryFFmpeg`'s private module-level dict in
`clipstory_ffmpeg.py` — import it: `from docu_studio.clipstory.clipstory_ffmpeg import
_OUTPUT_RESOLUTIONS, ClipStoryFFmpeg` at the top, alongside the existing
`ClipStoryFFmpeg` import. If the existing Phase 1 import already only imports
`ClipStoryFFmpeg`, extend that line.)

Change the existing mux call to use `video_for_mux_path` instead of `normalized_path`:
```python
        segment_path = str(work_dir / f"clip_{i}_segment.mp4")
        ffmpeg.mux_audio_video(video_for_mux_path, final_narration_path, segment_path)
        segment_paths.append(segment_path)
```

Also track each clip's `measured_target_duration` in a list alongside `segment_paths`
(needed for the crossfade branch below):

```python
    segment_durations: list[float] = []
```
(declared alongside `segment_paths` at the top of the function), and appended right after
`measured_target_duration` is computed:
```python
        segment_durations.append(measured_target_duration)
```

Replace the final concat block:

```python
    if cancel_event is not None and cancel_event.is_set():
        return

    assembled_path = str(work_dir / "clipstory_assembled.mp4")
    if config.transition == "crossfade" and len(segment_paths) > 1:
        too_short = [
            (i, d) for i, d in enumerate(segment_durations) if d <= _TRANSITION_DURATION
        ]
        if too_short:
            details = ", ".join(f"clip {i} ({d:.2f}s)" for i, d in too_short)
            raise ClipStoryTransitionError(
                f"Clip Story crossfade requires every clip to be longer than "
                f"{_TRANSITION_DURATION}s; too short: {details}"
            )
        ffmpeg.concat_segments_with_xfade(
            segment_paths, segment_durations, _TRANSITION_DURATION, assembled_path,
        )
    else:
        ffmpeg.concat_segments(segment_paths, config.output_resolution, assembled_path)

    if music_path:
        total_duration = ffmpeg.get_duration(assembled_path)
        mixed_audio_path = str(work_dir / "clipstory_music_mixed.m4a")
        ffmpeg.mix_music_bed(assembled_path, music_path, total_duration, mixed_audio_path)
        ffmpeg.mux_audio_video(assembled_path, mixed_audio_path, str(output_path))
    else:
        shutil.copy(assembled_path, str(output_path))
```

(Add `import shutil` at the top if not already present — check first, since
`clipstory_ffmpeg.py` already imports it but `clipstory_assembly.py` may not.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest <the test file from Step 1> -v`
Expected: PASS, including the regression-guard "all-off" case matching Phase 1's exact
prior call sequence.

- [ ] **Step 6: Full-suite regression check**

Run: `.venv/bin/python -m pytest tests/ -q --ignore=tests/integration/test_edge_tts_adapter.py 2>&1 | tail -10`
Expected: no new failures beyond the 24 baseline.

- [ ] **Step 7: Commit**

```bash
git add docu_studio/clipstory/clipstory_assembly.py <the test file from Step 1>
git commit -m "feat(clipstory): wire captions, crossfade, and music mix into assembly"
```

---

### Task 5: `clipstory_runner.py` — resolve music before assembly

**Files:**
- Modify: `docu_studio/clipstory/clipstory_runner.py`
- Modify: whatever test file covers `ClipStoryRunner` (check `tests/unit/` for
  `test_clipstory_runner.py`; if none exists, this is covered adequately by Task 4's
  assembly-level tests plus the E2E verification in Task 7 — do not invent a new test
  file just for this if Phase 1 didn't have one, per the "no speculative test scaffolding"
  guidance; only add tests here if a `test_clipstory_runner.py` already exists to extend).

**Interfaces:**
- Consumes: `resolve_music_track`, `DEFAULT_MUSIC_MOOD` from
  `docu_studio.clipstory.clipstory_music` (Task 2).
- Produces: `ClipStoryRunner._execute` resolves a music track once (mirroring
  `SlideshowRunner._execute`'s exact ordering) before calling `assemble_clip_story`,
  passing the resolved path through as the new `music_path` parameter from Task 4.

- [ ] **Step 1: Check for an existing runner test file**

Run: `find tests/unit -iname "*clipstory_runner*"`. If found, read it first to match its
mocking conventions before making any change.

- [ ] **Step 2: Implement**

In `docu_studio/clipstory/clipstory_runner.py`, add the import:
```python
from docu_studio.clipstory.clipstory_music import DEFAULT_MUSIC_MOOD, resolve_music_track
```

In `_execute`, after the `ProgressEvent(stage="ClipStory Assembly", ...)` line and before
the `with tempfile.TemporaryDirectory(...)` block, insert:

```python
        music_path = None
        if self.config.music_enabled:
            total_estimate = sum(c.duration_estimate for c in self.config.clips)
            resolved = resolve_music_track(
                provider_name=self.config.music_provider,
                mood=DEFAULT_MUSIC_MOOD,
                max_duration=total_estimate,
                jamendo_client_id=self.config.jamendo_client_id,
                local_folder=self.config.music_folder,
            )
            if resolved:
                music_path, music_label = resolved
                self.event_queue.put(ProgressEvent(
                    stage="ClipStory Assembly", message=f"Music: using {music_label!r}",
                ))
            else:
                self.event_queue.put(ProgressEvent(
                    stage="ClipStory Assembly",
                    message="Music: no usable track found — continuing without music bed",
                ))
        if self._cancelled():
            return
```

Update the `assemble_clip_story(...)` call to pass `music_path=music_path`:
```python
            assemble_clip_story(
                self.config, self.tts, Path(tmp), output_path,
                cancel_event=self.cancel_event, music_path=music_path,
            )
```

Update `run()`'s exception handling to also catch the new
`ClipStoryTransitionError` alongside the existing `ClipStoryFitError` — check the current
`except ClipStoryFitError as exc:` clause and add the new exception type to it (either as
a second `except` clause with the same body, or by importing and using a tuple):

```python
        except (ClipStoryFitError, ClipStoryTransitionError) as exc:
            self.event_queue.put(ErrorEvent(message=str(exc), fatal=True))
```

(Update the import line accordingly: `from docu_studio.clipstory.clipstory_assembly
import ClipStoryFitError, ClipStoryTransitionError, assemble_clip_story`.)

- [ ] **Step 3: If a runner test file exists, extend it; otherwise skip to Step 4**

Add a case asserting `resolve_music_track` is called with `music_enabled=True` and
skipped entirely when `music_enabled=False` (mock `clipstory_music.resolve_music_track`
at the runner module's import site).

- [ ] **Step 4: Full-suite regression check**

Run: `.venv/bin/python -m pytest tests/ -q --ignore=tests/integration/test_edge_tts_adapter.py 2>&1 | tail -10`
Expected: no new failures beyond the 24 baseline.

- [ ] **Step 5: Commit**

```bash
git add docu_studio/clipstory/clipstory_runner.py
git commit -m "feat(clipstory): resolve music track before assembly, mirroring Slideshow"
```

---

### Task 6: GUI wiring — index.html, app.js, bridge.py, cache-bust

**Files:**
- Modify: `docu_studio/gui/web/index.html`
- Modify: `docu_studio/gui/web/app.js`
- Modify: `docu_studio/gui/bridge.py`
- Modify: `docu_studio/gui/webview_app.py`

**Interfaces:** No new Python-level interfaces — this task is pure GUI wiring on top of
Task 1-5's already-complete backend.

- [ ] **Step 1: `index.html` — add three new rows**

In `docu_studio/gui/web/index.html`, insert directly after the existing
`clipstory-review-row` block (after its closing `</div>` at line 484) and before the
"Start button" comment (line 486):

```html
        <!-- Transition (clipstory) -->
        <div id="clipstory-transition-row" class="mt-6" style="display:none">
          <label class="text-sm font-medium text-dim block">Transition</label>
          <select id="clipstory-transition-select"
            class="mt-2 w-full bg-input border border-border rounded-lg px-4 py-3 text-white text-sm focus:border-accent focus:outline-none">
            <option value="cut">Hard cut</option>
            <option value="crossfade">Crossfade</option>
          </select>
        </div>

        <!-- Captions toggle (clipstory) -->
        <div id="clipstory-captions-row" class="mt-4 flex items-center justify-between" style="display:none">
          <div>
            <label class="text-sm font-medium text-dim block">Burned-in captions</label>
            <p class="text-xs text-faint mt-0.5">Word-level pop captions, per clip.</p>
          </div>
          <input id="clipstory-captions-toggle" type="checkbox" class="w-5 h-5 accent-accent cursor-pointer">
        </div>

        <!-- Music toggle (clipstory) -->
        <div id="clipstory-music-row" class="mt-4" style="display:none">
          <div class="flex items-center justify-between">
            <div>
              <label class="text-sm font-medium text-dim block">Background music</label>
              <p class="text-xs text-faint mt-0.5">Ducked under narration, only if a track is available.</p>
            </div>
            <input id="clipstory-music-toggle" type="checkbox"
              onchange="onClipStoryMusicToggleChange()" class="w-5 h-5 accent-accent cursor-pointer">
          </div>
          <div id="clipstory-music-provider-row" class="mt-3" style="display:none">
            <select id="clipstory-music-provider-select" onchange="onClipStoryMusicProviderChange(this.value)"
              class="w-full bg-input border border-border rounded-lg px-4 py-2.5 text-white text-sm focus:border-accent focus:outline-none">
              <option value="jamendo">Jamendo</option>
              <option value="local_folder">Local folder</option>
            </select>
            <div id="clipstory-music-folder-row" class="mt-2 flex items-center gap-2" style="display:none">
              <input id="clipstory-music-folder" type="text" readonly placeholder="No folder selected"
                class="flex-1 bg-input border border-border rounded-lg px-4 py-2.5 text-white text-sm">
              <button onclick="browseClipStoryMusicFolder()" type="button"
                class="px-4 py-2.5 bg-hover border border-border rounded-lg text-dim text-sm hover:text-white transition-colors">Browse…</button>
            </div>
          </div>
        </div>
```

- [ ] **Step 2: `app.js` — new toggle handlers**

Add, near the existing `onSlideshowMusicToggleChange`/`onSlideshowMusicProviderChange`/
`browseSlideshowMusicFolder` (around line 119-132):

```javascript
function onClipStoryMusicToggleChange() {
  const on = _q('clipstory-music-toggle').checked;
  _q('clipstory-music-provider-row').style.display = on ? '' : 'none';
  if (on) onClipStoryMusicProviderChange(_q('clipstory-music-provider-select').value);
}

function onClipStoryMusicProviderChange(provider) {
  _q('clipstory-music-folder-row').style.display = provider === 'local_folder' ? '' : 'none';
}

async function browseClipStoryMusicFolder() {
  const path = await window.pywebview.api.browse_folder();
  if (path) _q('clipstory-music-folder').value = path;
}
```

- [ ] **Step 3: `app.js` — `startConfig(mode)` show/hide for the new rows**

In `startConfig`, add alongside the existing `clipstory-review-row` line (line 248):

```javascript
  _q('clipstory-transition-row').style.display = mode === 'clipstory' ? '' : 'none';
  _q('clipstory-captions-row').style.display = mode === 'clipstory' ? '' : 'none';
  _q('clipstory-music-row').style.display = mode === 'clipstory' ? '' : 'none';
```

And change line 249's unconditional call to also cover Clip Story's toggle:
```javascript
  onSlideshowMusicToggleChange();
  onClipStoryMusicToggleChange();
```

- [ ] **Step 4: `app.js` — `startRun()`'s clipstory branch gains the new fields**

In the `_runMode === 'clipstory'` branch's `start_clipstory_run(...)` call object, add:

```javascript
      transition: _q('clipstory-transition-select').value,
      captions: _q('clipstory-captions-toggle').checked,
      music_enabled: _q('clipstory-music-toggle').checked,
      music_provider: _q('clipstory-music-provider-select').value,
      music_folder: _q('clipstory-music-folder').value,
```

(alongside the existing `topic`, `output_resolution`, `clips` keys — order doesn't
matter, just add all five.)

- [ ] **Step 5: `bridge.py` — `start_clipstory_run` reads the new fields**

In `docu_studio/gui/bridge.py`'s `start_clipstory_run`, change the `ClipStoryConfig(...)`
construction to add the five new fields, plus resolve the Jamendo client id the same way
`start_slideshow_run` does (add `jamendo_client_id = key_cache.get("docu_studio_jamendo")
or ""` before the config construction):

```python
            jamendo_client_id = key_cache.get("docu_studio_jamendo") or ""
            clipstory_config = ClipStoryConfig(
                topic=config.get("topic", ""),
                clips=clip_specs,
                output_resolution=config.get("output_resolution", "16:9"),
                tts_provider=tts_prov,
                tts_voice=tts_voice,
                transition=config.get("transition", "cut"),
                captions=bool(config.get("captions", False)),
                music_enabled=bool(config.get("music_enabled", False)),
                music_provider=config.get("music_provider", "jamendo"),
                music_folder=config.get("music_folder", ""),
                jamendo_client_id=jamendo_client_id,
            )
```

- [ ] **Step 6: Opportunistic cleanup — narration textarea `innerHTML`**

While in `app.js` for this task, also fix the Minor item from the Phase 1 report:
`_renderClipStoryReview`'s `row.innerHTML = \`...${entry.text}...\`` (around line 424-427)
interpolates narration text (LLM-generated or user-written) directly into HTML via
`innerHTML`, which is unsafe if that text ever contains characters like `</textarea>` or
`<script>`. Replace with DOM construction, matching the style already used in
`_renderClipStoryClips`:

```javascript
function _renderClipStoryReview() {
  const list = _q('clipstory-review-list');
  list.innerHTML = '';
  Object.keys(_clipStoryReview).sort((a, b) => a - b).forEach(idx => {
    const entry = _clipStoryReview[idx];
    const clip = _clipStoryClips[idx];
    const targetDuration = (clip.trimOut - clip.trimIn).toFixed(1);
    const row = document.createElement('div');
    row.className = 'bg-input border border-border rounded-lg px-3 py-3 text-sm text-white';

    const label = document.createElement('div');
    label.className = 'text-xs text-faint';
    label.textContent = `Clip ${Number(idx) + 1} — target ${targetDuration}s, estimated pace ${entry.pace_estimate_seconds.toFixed(1)}s`;
    row.appendChild(label);

    const textarea = document.createElement('textarea');
    textarea.rows = 3;
    textarea.dataset.idx = idx;
    textarea.className = 'mt-1 w-full bg-panel border border-border rounded px-2 py-1 text-white text-xs';
    textarea.value = entry.text;
    textarea.onchange = (e) => {
      _clipStoryReview[idx].text = e.target.value;
      _clipStoryClips[idx].scriptText = e.target.value;
    };
    row.appendChild(textarea);

    list.appendChild(row);
  });
  const startBtn = _q('start-run-btn');
  if (_runMode === 'clipstory') startBtn.disabled = Object.keys(_clipStoryReview).length !== _clipStoryClips.length;
}
```

(This is a same-neighborhood opportunistic fix per the task's §2d — note it in the final
report as taken, distinct from the two `clipstory_ffmpeg.py` cleanups already done in
Task 3.)

- [ ] **Step 7: Cache-bust bump**

In `docu_studio/gui/webview_app.py:33`, change `?v=13` to `?v=14`.

- [ ] **Step 8: Restart and manually smoke-check the GUI loads without console errors**

```bash
pkill -f docu_studio 2>/dev/null
DISPLAY=:1 .venv/bin/python -m docu_studio
```
Click into Clip Story mode; confirm the new Transition/Captions/Music rows render below
the narration review section, toggle correctly (music row reveals provider select,
local_folder reveals folder+Browse), and that Documentary/Shorts/Slideshow mode cards are
visually unchanged (byte-for-byte behavior check per the design spec's GUI requirement).

- [ ] **Step 9: Full-suite regression check**

Run: `.venv/bin/python -m pytest tests/ -q --ignore=tests/integration/test_edge_tts_adapter.py 2>&1 | tail -10`
Expected: no new failures beyond the 24 baseline (this task adds no new Python tests,
GUI-only).

- [ ] **Step 10: Commit**

```bash
git add docu_studio/gui/web/index.html docu_studio/gui/web/app.js docu_studio/gui/bridge.py \
        docu_studio/gui/webview_app.py
git commit -m "feat(clipstory): add captions/music/transition GUI controls, fix review textarea XSS-adjacent innerHTML"
```

---

### Task 7: Real end-to-end verification

**Files:** none (verification only — do not write new source files for this task).

- [ ] **Step 1: Prepare 3+ real uploaded video clips of varying duration**

Use whatever short sample video files are available in the environment (check
`tests/fixtures/` or similar for existing sample media first before sourcing new ones);
each clip should be long enough to comfortably exceed 0.5s (the fixed crossfade
transition duration) — a few seconds each is enough.

- [ ] **Step 2: Restart the app**

```bash
pkill -f docu_studio 2>/dev/null
DISPLAY=:1 .venv/bin/python -m docu_studio
```

- [ ] **Step 3: All-on run**

In the GUI: Clip Story mode, upload the 3+ clips, set trims, write/flag narration for
each, "Generate Narration", review, enable Captions, enable Music (Jamendo if a key is
cached, else point Local folder at a folder with at least one `.mp3`/`.wav`/`.m4a`/`.ogg`
file), set Transition to Crossfade, then Render.

- [ ] **Step 4: Extract and personally inspect frames from the all-on output**

```bash
.venv/bin/python -c "
import subprocess
# adjust path to the actual project output folder from the run just completed
"
```
Use `ffmpeg -i <output> -vf fps=1 frame_%03d.png` (or targeted `-ss <timestamp>` single-frame
extracts at each clip boundary) to pull frames at: the midpoint of each clip (confirm
caption text present and matches that clip's own narration, not bleeding from an adjacent
clip), each crossfade cut point (confirm a smooth blend, no visible tearing/SAR
artifacts/color banding), and listen to (or waveform-inspect via
`ffmpeg -i <output> -af showwavespic=s=1200x300 wave.png`) the audio through a
transition point to confirm no audible pop/glitch/desync.

- [ ] **Step 5: All-off run**

Same clips, same trims/narration, but Captions off, Music off, Transition = Hard cut.
Confirm the render completes and structurally matches what Phase 1 alone would have
produced (duration, segment boundaries, no captions burned in, no music track).

- [ ] **Step 6: Report findings**

Document, in the final handoff report (not a new file — just the chat response), exactly
what was verified-by-eyes (frame/waveform inspection) vs. verified-by-logs-only (e.g. "the
log confirms `mix_music_bed` ran and which track was chosen, but I did not personally
listen for ducking quality" if that's genuinely the case — be honest about the boundary).

---

### Task 8: Final report

**Files:** none.

- [ ] **Step 1: Run the full test suite one final time**

Run: `.venv/bin/python -m pytest tests/ -q --ignore=tests/integration/test_edge_tts_adapter.py 2>&1 | tail -10`
Record the final pass/fail count against the Task 0 baseline (640/24).

- [ ] **Step 2: Compile the handoff report**, covering (same format as Phase 1's):
- Summary of what was built (captions, music+ducking, crossfade) and how each maps to
  the design spec's decisions.
- Test count before/after, confirming zero regressions in the 24 pre-existing failures.
- Real E2E findings from Task 7 (verified-by-eyes vs. verified-by-logs-only).
- Opportunistic cleanup status: which of the four Phase 1 Minor items were fixed (the two
  in `clipstory_ffmpeg.py` from Task 3, the `innerHTML` one from Task 6) and which
  remain explicitly deferred (the Back-navigation Start-button state leak — not in this
  phase's touched files).
- Any open questions or follow-ups for a hypothetical Phase 3.

- [ ] **Step 3: Do not push** — hand off for review per the standing instruction; only
push if the user explicitly says to.
