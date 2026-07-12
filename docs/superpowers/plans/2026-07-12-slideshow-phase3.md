# Slideshow Phase 3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add optional crossfade transitions, vignette/grain overlays, burned-in captions, and background music (with ducking) to the Slideshow pipeline, all default-off and purely additive to Phase 1/2 behavior.

**Architecture:** Four new self-contained modules under `docu_studio/slideshow/` (`slideshow_captions.py`, `slideshow_music.py`, `slideshow_audio_mix.py`, plus new methods on `slideshow_ffmpeg.py`), each mirroring a Shorts module's *technique* without importing `docu_studio/shorts/`. `slideshow_config.py` and `slideshow_assembly.py` gain new optional fields/params, all defaulting to today's Phase 1/2 behavior. `slideshow_runner.py` and `gui/bridge.py` thread the new options through; `index.html`/`app.js` add the GUI controls.

**Tech Stack:** Python 3.11+, ffmpeg (`xfade`, `vignette`, `noise`, `subtitles`, `sidechaincompress` filters), `requests` (Jamendo), pytest + `unittest.mock`.

## Global Constraints

- Do not import anything from `docu_studio/shorts/` — every new module is self-contained, reimplementing the needed technique with its own constants (Phase 1 design decision, reconfirmed for Phase 3).
- Every ffmpeg output that re-encodes video must end in the same SAR/pixfmt finalize discipline `apply_ken_burns_image` already uses (`setsar=1,format=yuv420p`), so the SAR concat-crash bug class cannot reappear through a new code path.
- All new `SlideshowConfig`/`assemble_slideshow`/`SlideshowRunner` parameters default to today's Phase 1/2 behavior (hard cut, no overlays, no captions, no music) — a caller that passes none of the new arguments must get byte-for-byet-equivalent existing tests passing unchanged.
- Do not touch `pipeline/`, `runner/`, `adapters/` (except adding new ones), `history/`, `licensing.py`, or existing test files unless fixing an actual bug in them.
- Correct venv is `.venv/` — use `.venv/bin/python` for everything.
- Always restart before manually testing any GUI change (Python doesn't hot-reload): `pkill -f docu_studio 2>/dev/null; DISPLAY=:1 .venv/bin/python -m docu_studio`.
- Baseline: 512 passed / 24 failed / 1 error (pre-existing, unrelated dead-code/missing-module failures) — reconfirmed 2026-07-12. Every task must not change this delta except by adding new passing tests.

---

### Task 1: `slideshow_audio_mix.py` — ducking filtergraph

**Files:**
- Create: `docu_studio/slideshow/slideshow_audio_mix.py`
- Test: `tests/unit/test_slideshow_audio_mix.py`

**Interfaces:**
- Produces: `build_ducking_filtergraph(video_duration: float) -> str`

- [ ] **Step 1: Write the failing tests**

```python
"""Unit tests for slideshow_audio_mix — pure string building, no I/O."""
from __future__ import annotations

from docu_studio.slideshow.slideshow_audio_mix import build_ducking_filtergraph


class TestBuildDuckingFiltergraph:
    def test_references_voice_as_sidechain_key(self) -> None:
        graph = build_ducking_filtergraph(10.0)
        assert "[music_faded][0:a]sidechaincompress" in graph

    def test_trims_music_to_video_duration(self) -> None:
        graph = build_ducking_filtergraph(12.5)
        assert "atrim=0:12.500" in graph

    def test_fade_out_start_is_duration_minus_one_second(self) -> None:
        graph = build_ducking_filtergraph(12.5)
        assert "afade=t=out:st=11.500:d=1.00" in graph

    def test_short_video_clamps_fade_out_start_to_zero(self) -> None:
        graph = build_ducking_filtergraph(0.5)
        assert "afade=t=out:st=0.000:d=1.00" in graph

    def test_amix_normalize_disabled_so_voice_stays_dominant(self) -> None:
        graph = build_ducking_filtergraph(10.0)
        assert "amix=inputs=2:duration=first:normalize=0[aout]" in graph
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_slideshow_audio_mix.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'docu_studio.slideshow.slideshow_audio_mix'`

- [ ] **Step 3: Write the implementation**

```python
"""Pure ffmpeg filtergraph construction for Slideshow music-bed mixing.

Kept as pure string building (no subprocess) so the ducking graph is directly
unit-testable — SlideshowFFmpeg.mix_music_bed is the only caller that actually
invokes ffmpeg with this string. Same sidechaincompress ducking technique as
docu_studio.shorts.shorts_audio_mix, reimplemented with its own constants per
the Phase 1 design decision to keep slideshow/ self-contained (zero imports
from shorts/).
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

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_slideshow_audio_mix.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add docu_studio/slideshow/slideshow_audio_mix.py tests/unit/test_slideshow_audio_mix.py
git commit -m "feat(slideshow): add self-contained ducking filtergraph builder"
```

---

### Task 2: `slideshow_captions.py` — word timing + ASS generation

**Files:**
- Create: `docu_studio/slideshow/slideshow_captions.py`
- Test: `tests/unit/test_slideshow_captions.py`

**Interfaces:**
- Produces: `WordTiming(word: str, start: float, end: float)` (frozen dataclass), `estimate_word_timestamps(script_text: str, duration: float) -> list[WordTiming]`, `group_words(timings: list[WordTiming]) -> list[list[WordTiming]]`, `generate_ass(timings: list[WordTiming], out_width: int, out_height: int, audio_duration: float | None = None) -> str`, `write_ass_file(timings: list[WordTiming], output_path: str, out_width: int, out_height: int, audio_duration: float | None = None) -> None`

- [ ] **Step 1: Write the failing tests**

```python
"""Unit tests for slideshow_captions — pure text generation, no ffmpeg/I/O
beyond tmp_path for write_ass_file."""
from __future__ import annotations

from pathlib import Path

from docu_studio.slideshow.slideshow_captions import (
    WordTiming,
    estimate_word_timestamps,
    generate_ass,
    group_words,
    write_ass_file,
)


class TestEstimateWordTimestamps:
    def test_distributes_words_across_duration(self) -> None:
        timings = estimate_word_timestamps("one two three", 9.0)
        assert len(timings) == 3
        assert timings[0].start == 0.0
        assert timings[-1].end == 9.0

    def test_weights_by_character_length(self) -> None:
        timings = estimate_word_timestamps("a bb", 3.0)
        span_a = timings[0].end - timings[0].start
        span_bb = timings[1].end - timings[1].start
        assert span_bb == 2 * span_a

    def test_empty_script_returns_empty_list(self) -> None:
        assert estimate_word_timestamps("", 5.0) == []

    def test_zero_duration_returns_empty_list(self) -> None:
        assert estimate_word_timestamps("hello", 0.0) == []


class TestGroupWords:
    def test_groups_of_four_by_default(self) -> None:
        timings = [WordTiming(word=str(i), start=float(i), end=float(i + 1)) for i in range(8)]
        groups = group_words(timings)
        assert [len(g) for g in groups] == [4, 4]

    def test_single_leftover_borrows_from_previous_group(self) -> None:
        timings = [WordTiming(word=str(i), start=float(i), end=float(i + 1)) for i in range(13)]
        groups = group_words(timings)
        assert [len(g) for g in groups] == [4, 4, 3, 2]

    def test_single_word_returns_one_group_below_floor(self) -> None:
        timings = [WordTiming(word="hi", start=0.0, end=1.0)]
        assert group_words(timings) == [[timings[0]]]

    def test_empty_input_returns_empty_list(self) -> None:
        assert group_words([]) == []


class TestGenerateAss:
    def test_header_uses_caller_dimensions(self) -> None:
        timings = estimate_word_timestamps("hello there", 2.0)
        doc = generate_ass(timings, out_width=1920, out_height=1080)
        assert "PlayResX: 1920" in doc
        assert "PlayResY: 1080" in doc

    def test_margin_v_is_22_percent_of_height(self) -> None:
        timings = estimate_word_timestamps("hello there", 2.0)
        doc = generate_ass(timings, out_width=1080, out_height=1920)
        # Style line's MarginV is the second-to-last field before Encoding.
        style_line = next(l for l in doc.splitlines() if l.startswith("Style:"))
        margin_v = style_line.split(",")[-2]
        assert margin_v == str(round(1920 * 0.22))

    def test_events_are_gapless(self) -> None:
        timings = estimate_word_timestamps("one two three four five", 5.0)
        doc = generate_ass(timings, out_width=1080, out_height=1920, audio_duration=5.0)
        dialogue_lines = [l for l in doc.splitlines() if l.startswith("Dialogue:")]
        assert len(dialogue_lines) == 5

    def test_empty_timings_produces_header_only(self) -> None:
        doc = generate_ass([], out_width=1080, out_height=1920)
        assert "Dialogue:" not in doc


class TestWriteAssFile:
    def test_writes_utf8_file(self, tmp_path: Path) -> None:
        timings = estimate_word_timestamps("hi there", 2.0)
        out = tmp_path / "captions.ass"
        write_ass_file(timings, str(out), 1080, 1920)
        assert out.exists()
        assert "Dialogue:" in out.read_text(encoding="utf-8")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_slideshow_captions.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'docu_studio.slideshow.slideshow_captions'`

- [ ] **Step 3: Write the implementation**

```python
"""Burned-in "pop" caption generation for Slideshow: groups word-level
timings into 2-4 word chunks and emits an ASS (Advanced SubStation Alpha)
subtitle document with the currently-spoken word bolded and briefly scaled
up. SlideshowFFmpeg.burn_captions consumes the .ass file this module writes.

Same technique as docu_studio.shorts.shorts_captions, reimplemented
self-contained (own WordTiming, own timing estimate, dimensions parameterized
on the caller's actual out_width/out_height instead of Shorts' hardcoded
1080x1920) per the Phase 1 design decision to keep slideshow/ free of imports
from shorts/.

Word-level timing comes from estimate_word_timestamps() — a character-length-
weighted distribution across the narration's measured duration (Shorts' own
Tier 3 fallback technique), not audio-aligned. Slideshow's TTS adapters expose
no native timestamps and, per the Phase 3 design decision, this phase does not
pull in a Whisper alignment dependency for a first pass at captions — so this
estimate is the only tier here, not one of several.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

_MIN_GROUP = 2
_MAX_GROUP = 4
_MIN_WORD_DURATION = 0.05  # guards against zero-duration Dialogue lines

# libass resolves this via fontconfig substitution if unavailable on the host,
# giving effectively a system-safe fallback without a literal comma-list.
_FONT_NAME = "DejaVu Sans"

_SAFE_AREA_BOTTOM_FRACTION = 0.22

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


@dataclass(frozen=True)
class WordTiming:
    word: str
    start: float
    end: float


def estimate_word_timestamps(script_text: str, duration: float) -> list[WordTiming]:
    """Distribute the words of *script_text* across *duration* seconds,
    weighting each word's time span by its character length."""
    words = script_text.split()
    if not words or duration <= 0:
        return []
    weights = [len(w) for w in words]
    total_weight = sum(weights)
    timestamps: list[WordTiming] = []
    cursor = 0.0
    for word, weight in zip(words, weights):
        span = duration * (weight / total_weight)
        timestamps.append(WordTiming(word=word, start=cursor, end=cursor + span))
        cursor += span
    return timestamps


def group_words(timings: list[WordTiming]) -> list[list[WordTiming]]:
    """Split *timings* into 2-4 word "pop caption" chunks.

    Greedy 4-word chunking, with a borrow-fixup: if the final chunk would be
    a single leftover word, one word is moved over from the second-to-last
    chunk so both end chunks land at >=2. A single-word script is the only
    case returned below the 2-word floor, since there's nothing to borrow.
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
                r"{\t(0,60,\fscx118\fscy118)\t(60,120,\fscx100\fscy100)\b1}"
                + word_text + r"{\r}"
            )
        else:
            parts.append(word_text)
    return " ".join(parts)


def generate_ass(
    timings: list[WordTiming],
    out_width: int,
    out_height: int,
    audio_duration: float | None = None,
) -> str:
    """Build a full ASS subtitle document from word-level *timings*, sized to
    *out_width*x*out_height* (Slideshow's actual output dimensions, unlike
    Shorts' hardcoded 1080x1920). Events are gapless: each word's Start stays
    at its own estimated timestamp, but its End is pinned to the *next*
    word's Start, so exactly one Dialogue event is ever active. The last
    word's End uses *audio_duration* when given, else its own estimated end.
    """
    margin_v = round(out_height * _SAFE_AREA_BOTTOM_FRACTION)
    header = _ASS_HEADER_TEMPLATE.format(
        width=out_width, height=out_height, font=_FONT_NAME, margin_v=margin_v,
    )
    lines = [header]
    groups = group_words(timings)
    flat: list[tuple[list[WordTiming], int, WordTiming]] = [
        (group, active_index, word)
        for group in groups
        for active_index, word in enumerate(group)
    ]
    for i, (group, active_index, word) in enumerate(flat):
        start = word.start
        if i + 1 < len(flat):
            next_start = flat[i + 1][2].start
        elif audio_duration is not None:
            next_start = audio_duration
        else:
            next_start = word.end
        end_seconds = max(next_start, start + _MIN_WORD_DURATION)
        text = _render_group_text(group, active_index)
        lines.append(
            f"Dialogue: 0,{_format_ass_time(start)},{_format_ass_time(end_seconds)},"
            f"Pop,,0,0,0,,{text}"
        )
    return "\n".join(lines) + "\n"


def write_ass_file(
    timings: list[WordTiming],
    output_path: str,
    out_width: int,
    out_height: int,
    audio_duration: float | None = None,
) -> None:
    Path(output_path).write_text(
        generate_ass(timings, out_width, out_height, audio_duration), encoding="utf-8"
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_slideshow_captions.py -v`
Expected: 13 passed

- [ ] **Step 5: Commit**

```bash
git add docu_studio/slideshow/slideshow_captions.py tests/unit/test_slideshow_captions.py
git commit -m "feat(slideshow): add self-contained word-timing estimate and ASS caption generation"
```

---

### Task 3: `slideshow_music.py` — providers + fallback resolver

**Files:**
- Create: `docu_studio/slideshow/slideshow_music.py`
- Test: `tests/unit/test_slideshow_music.py`

**Interfaces:**
- Produces: `TrackCandidate(title, duration, download_url, source="local_folder", local_path=None)`, `LocalFolderMusicProvider(folder_path, seed=0)` with `.search()`/`.fetch()`, `JamendoMusicProvider(client_id, timeout=10.0)` with `.search()`/`.fetch()`, `resolve_music_track(provider_name, mood, max_duration, jamendo_client_id="", local_folder="", seed=0) -> tuple[str, str] | None`, `DEFAULT_MUSIC_MOOD: str`, `music_cache_dir() -> Path`, `safe_cache_filename(title, ext="mp3") -> str`

- [ ] **Step 1: Write the failing tests**

```python
"""Unit tests for slideshow_music — requests/filesystem mocked, no network."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from docu_studio.slideshow.slideshow_music import (
    JamendoMusicProvider,
    LocalFolderMusicProvider,
    TrackCandidate,
    resolve_music_track,
    safe_cache_filename,
)


class TestSafeCacheFilename:
    def test_slugifies_title(self) -> None:
        assert safe_cache_filename("Cinematic Piano #1!") == "cinematic_piano_1.mp3"

    def test_empty_title_falls_back_to_track(self) -> None:
        assert safe_cache_filename("") == "track.mp3"


class TestLocalFolderMusicProvider:
    def test_returns_empty_for_nonexistent_folder(self) -> None:
        provider = LocalFolderMusicProvider("/does/not/exist")
        assert provider.search("cinematic", 10.0) == []

    def test_returns_empty_for_empty_folder(self, tmp_path: Path) -> None:
        provider = LocalFolderMusicProvider(str(tmp_path))
        assert provider.search("cinematic", 10.0) == []

    def test_ignores_non_audio_files(self, tmp_path: Path) -> None:
        (tmp_path / "notes.txt").write_text("not audio")
        provider = LocalFolderMusicProvider(str(tmp_path))
        assert provider.search("cinematic", 10.0) == []

    def test_picks_an_audio_file(self, tmp_path: Path) -> None:
        (tmp_path / "song.mp3").write_bytes(b"fake")
        provider = LocalFolderMusicProvider(str(tmp_path))
        candidates = provider.search("cinematic", 10.0)
        assert len(candidates) == 1
        assert candidates[0].local_path == str(tmp_path / "song.mp3")
        assert candidates[0].source == "local_folder"

    def test_fetch_returns_local_path(self, tmp_path: Path) -> None:
        candidate = TrackCandidate(
            title="song.mp3", duration=10.0, download_url="", local_path=str(tmp_path / "song.mp3"),
        )
        provider = LocalFolderMusicProvider(str(tmp_path))
        assert provider.fetch(candidate) == str(tmp_path / "song.mp3")

    def test_fetch_without_local_path_raises(self) -> None:
        candidate = TrackCandidate(title="x", duration=10.0, download_url="")
        provider = LocalFolderMusicProvider("/anywhere")
        with pytest.raises(ValueError, match="local_path"):
            provider.fetch(candidate)


class TestJamendoMusicProvider:
    def test_search_without_client_id_returns_empty(self) -> None:
        provider = JamendoMusicProvider(client_id="")
        assert provider.search("cinematic", 10.0) == []

    def test_search_skips_results_without_download_url(self) -> None:
        provider = JamendoMusicProvider(client_id="fake-id")
        with patch("docu_studio.slideshow.slideshow_music.requests.get") as mock_get:
            mock_get.return_value = MagicMock(
                status_code=200,
                json=lambda: {"results": [
                    {"name": "No Download", "duration": 120, "audiodownload": ""},
                    {"name": "Has Download", "duration": 90, "audiodownload": "https://example.com/t.mp3"},
                ]},
            )
            candidates = provider.search("cinematic", 10.0)
        assert len(candidates) == 1
        assert candidates[0].title == "Has Download"

    def test_search_request_failure_returns_empty(self) -> None:
        provider = JamendoMusicProvider(client_id="fake-id")
        with patch("docu_studio.slideshow.slideshow_music.requests.get", side_effect=Exception("boom")):
            assert provider.search("cinematic", 10.0) == []

    def test_fetch_caches_by_slug(self, tmp_path: Path) -> None:
        provider = JamendoMusicProvider(client_id="fake-id")
        candidate = TrackCandidate(
            title="Cinematic Piano", duration=90, download_url="https://example.com/t.mp3", source="jamendo",
        )
        with patch("docu_studio.slideshow.slideshow_music.music_cache_dir", return_value=tmp_path):
            with patch("docu_studio.slideshow.slideshow_music.requests.get") as mock_get:
                mock_get.return_value = MagicMock(status_code=200, content=b"audio-bytes")
                path = provider.fetch(candidate)
        assert path == str(tmp_path / "cinematic_piano.mp3")
        assert Path(path).read_bytes() == b"audio-bytes"

    def test_fetch_cache_hit_skips_download(self, tmp_path: Path) -> None:
        provider = JamendoMusicProvider(client_id="fake-id")
        cached = tmp_path / "cinematic_piano.mp3"
        cached.write_bytes(b"already-here")
        candidate = TrackCandidate(
            title="Cinematic Piano", duration=90, download_url="https://example.com/t.mp3", source="jamendo",
        )
        with patch("docu_studio.slideshow.slideshow_music.music_cache_dir", return_value=tmp_path):
            with patch("docu_studio.slideshow.slideshow_music.requests.get") as mock_get:
                path = provider.fetch(candidate)
        mock_get.assert_not_called()
        assert path == str(cached)


class TestResolveMusicTrack:
    def test_jamendo_success_returns_path_and_label(self, tmp_path: Path) -> None:
        with patch("docu_studio.slideshow.slideshow_music.JamendoMusicProvider") as mock_cls:
            mock_provider = MagicMock()
            mock_provider.search.return_value = [
                TrackCandidate(title="Track A", duration=90, download_url="https://x/y.mp3", source="jamendo"),
            ]
            mock_provider.fetch.return_value = str(tmp_path / "track_a.mp3")
            mock_cls.return_value = mock_provider
            result = resolve_music_track("jamendo", "cinematic", 10.0, jamendo_client_id="fake-id")
        assert result == (str(tmp_path / "track_a.mp3"), "Track A")

    def test_jamendo_empty_falls_back_to_local_folder(self, tmp_path: Path) -> None:
        (tmp_path / "song.mp3").write_bytes(b"fake")
        with patch("docu_studio.slideshow.slideshow_music.JamendoMusicProvider") as mock_cls:
            mock_provider = MagicMock()
            mock_provider.search.return_value = []
            mock_cls.return_value = mock_provider
            result = resolve_music_track(
                "jamendo", "cinematic", 10.0, jamendo_client_id="fake-id", local_folder=str(tmp_path),
            )
        assert result is not None
        assert result[0] == str(tmp_path / "song.mp3")

    def test_local_folder_provider_used_directly(self, tmp_path: Path) -> None:
        (tmp_path / "song.mp3").write_bytes(b"fake")
        result = resolve_music_track("local_folder", "cinematic", 10.0, local_folder=str(tmp_path))
        assert result is not None
        assert result[0] == str(tmp_path / "song.mp3")

    def test_empty_local_folder_returns_none_without_raising(self, tmp_path: Path) -> None:
        result = resolve_music_track("local_folder", "cinematic", 10.0, local_folder=str(tmp_path))
        assert result is None

    def test_nonexistent_local_folder_returns_none_without_raising(self) -> None:
        result = resolve_music_track("local_folder", "cinematic", 10.0, local_folder="/does/not/exist")
        assert result is None

    def test_no_provider_configured_returns_none(self) -> None:
        result = resolve_music_track("local_folder", "cinematic", 10.0, local_folder="")
        assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_slideshow_music.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'docu_studio.slideshow.slideshow_music'`

- [ ] **Step 3: Write the implementation**

```python
"""Music provider abstraction for Slideshow.

Providers implement search()/fetch(): search(query, max_duration) returns
candidate tracks, fetch(candidate) resolves one to a local, playable file
path. Same Jamendo search+cache+fetch technique as
docu_studio.shorts.music_providers, reimplemented self-contained (own
TrackCandidate, own cache dir) per the Phase 1 design decision to keep
slideshow/ free of imports from shorts/. LocalFolderMusicProvider wraps a
user-browsed folder rather than Shorts' bundled assets/music/ manifest, since
Slideshow ships no bundled tracks (Phase 3 design decision).

resolve_music_track() is the single entry point callers use. It walks the
configured provider, falls back to the local folder, then gives up (None) —
never raising. The music bed is always optional.
"""
from __future__ import annotations

import logging
import random
import re
from dataclasses import dataclass
from pathlib import Path

import requests

from docu_studio.platform_layer import config_dir

_log = logging.getLogger(__name__)

JAMENDO_API_URL = "https://api.jamendo.com/v3.0/tracks"
DEFAULT_MUSIC_MOOD = "cinematic"

_MUSIC_CACHE_DIRNAME = "slideshow_music_cache"
_REQUEST_TIMEOUT = 10.0
# Upper bound on the durationbetween range sent to Jamendo — generous enough
# that "at least the slideshow's duration" never excludes a normal track.
_MAX_TRACK_DURATION = 1200
_AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".ogg"}


def music_cache_dir() -> Path:
    return config_dir() / _MUSIC_CACHE_DIRNAME


def safe_cache_filename(title: str, ext: str = "mp3") -> str:
    """Return a filesystem-safe, lowercase cache filename derived from *title*."""
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", title).strip("_").lower()
    return f"{slug or 'track'}.{ext}"


@dataclass(frozen=True)
class TrackCandidate:
    title: str
    duration: float
    download_url: str
    source: str = "local_folder"
    local_path: str | None = None


class LocalFolderMusicProvider:
    """Picks a random audio file from a user-browsed folder. search() never
    raises — a missing/empty folder or a folder with no recognized audio
    files just returns an empty candidate list."""

    def __init__(self, folder_path: str, seed: int = 0) -> None:
        self._folder_path = folder_path
        self._seed = seed

    def search(self, query: str, max_duration: float) -> list[TrackCandidate]:
        folder = Path(self._folder_path) if self._folder_path else None
        if folder is None or not folder.is_dir():
            return []
        files = sorted(
            p for p in folder.iterdir()
            if p.is_file() and p.suffix.lower() in _AUDIO_EXTENSIONS
        )
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


class JamendoMusicProvider:
    """Searches/downloads instrumental tracks from Jamendo's public API.
    Requires a free client_id (https://developer.jamendo.com)."""

    def __init__(self, client_id: str, timeout: float = _REQUEST_TIMEOUT) -> None:
        self._client_id = client_id
        self._timeout = timeout

    def search(self, query: str, max_duration: float) -> list[TrackCandidate]:
        if not self._client_id:
            _log.warning("Jamendo: no client_id configured — skipping search")
            return []
        params = {
            "client_id": self._client_id,
            "format": "json",
            "limit": 10,
            "tags": query,
            "durationbetween": f"{max(1, int(max_duration))}_{_MAX_TRACK_DURATION}",
            "vocalinstrumental": "instrumental",
            "audioformat": "mp31",
        }
        try:
            response = requests.get(JAMENDO_API_URL, params=params, timeout=self._timeout)
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            _log.warning("Jamendo: search request failed (%s)", exc)
            return []

        raw_results = data.get("results", [])
        candidates: list[TrackCandidate] = []
        for item in raw_results:
            # Jamendo tracks can have downloads disabled by the artist — the
            # item still comes back with an `audiodownload` key, but it's an
            # empty string rather than the key being absent.
            download_url = item.get("audiodownload") or ""
            if not download_url:
                continue
            try:
                candidates.append(TrackCandidate(
                    title=str(item["name"]),
                    duration=float(item["duration"]),
                    download_url=str(download_url),
                    source="jamendo",
                ))
            except (KeyError, TypeError, ValueError):
                continue
        if not candidates:
            _log.info("Jamendo: zero usable results for query %r", query)
        return candidates

    def fetch(self, candidate: TrackCandidate) -> str:
        cache_dir = music_cache_dir()
        cache_dir.mkdir(parents=True, exist_ok=True)
        dest = cache_dir / safe_cache_filename(candidate.title)
        if dest.exists():
            _log.info("Jamendo: cache hit for %r", candidate.title)
            return str(dest)
        response = requests.get(candidate.download_url, timeout=self._timeout)
        response.raise_for_status()
        dest.write_bytes(response.content)
        _log.info("Jamendo: downloaded %r -> %s", candidate.title, dest)
        return str(dest)


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
                _log.info("Music: using Jamendo track %r", candidates[0].title)
                return path, candidates[0].title
            except Exception as exc:
                _log.warning("Jamendo: download failed (%s) — falling back to local folder", exc)
        else:
            _log.info("Jamendo: no usable candidates — falling back to local folder")

    local = LocalFolderMusicProvider(local_folder, seed=seed)
    candidates = local.search(mood, max_duration)
    if candidates:
        path = local.fetch(candidates[0])
        _log.info("Music: using local-folder track %r", candidates[0].title)
        return path, candidates[0].title

    _log.info("Music: no usable track from any provider — skipping music bed")
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_slideshow_music.py -v`
Expected: 19 passed

- [ ] **Step 5: Commit**

```bash
git add docu_studio/slideshow/slideshow_music.py tests/unit/test_slideshow_music.py
git commit -m "feat(slideshow): add self-contained Jamendo + local-folder music providers"
```

---

### Task 4: `SlideshowConfig` — new optional fields

**Files:**
- Modify: `docu_studio/slideshow/slideshow_config.py`
- Test: `tests/unit/test_slideshow_config.py` (extend existing file, do not remove existing tests)

**Interfaces:**
- Consumes: nothing new
- Produces: `SlideshowConfig` gains `transition: str = "cut"`, `vignette: bool = False`, `grain: bool = False`, `captions: bool = False`, `music_enabled: bool = False`, `music_provider: str = "jamendo"`, `music_folder: str = ""`, `jamendo_client_id: str = ""`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_slideshow_config.py`:

```python
class TestPhase3Fields:
    def test_defaults_match_phase1_phase2_behavior(self) -> None:
        cfg = SlideshowConfig(script_text="Hi.", image_paths=["/a.jpg"])
        assert cfg.transition == "cut"
        assert cfg.vignette is False
        assert cfg.grain is False
        assert cfg.captions is False
        assert cfg.music_enabled is False
        assert cfg.music_provider == "jamendo"
        assert cfg.music_folder == ""
        assert cfg.jamendo_client_id == ""

    def test_crossfade_transition_accepted(self) -> None:
        cfg = SlideshowConfig(script_text="Hi.", image_paths=["/a.jpg"], transition="crossfade")
        assert cfg.transition == "crossfade"

    def test_unknown_transition_raises(self) -> None:
        with pytest.raises(ValueError, match="transition"):
            SlideshowConfig(script_text="Hi.", image_paths=["/a.jpg"], transition="wipe")

    def test_local_folder_music_provider_accepted(self) -> None:
        cfg = SlideshowConfig(
            script_text="Hi.", image_paths=["/a.jpg"], music_provider="local_folder",
        )
        assert cfg.music_provider == "local_folder"

    def test_unknown_music_provider_raises(self) -> None:
        with pytest.raises(ValueError, match="music_provider"):
            SlideshowConfig(script_text="Hi.", image_paths=["/a.jpg"], music_provider="spotify")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_slideshow_config.py -v`
Expected: FAIL — `TestPhase3Fields` tests error with `TypeError: SlideshowConfig.__init__() got an unexpected keyword argument 'transition'`

- [ ] **Step 3: Modify the implementation**

In `docu_studio/slideshow/slideshow_config.py`, replace the `SlideshowConfig` class body:

```python
@dataclass
class SlideshowConfig:
    script_text: str
    image_paths: list[str]
    aspect_ratio: str = SLIDESHOW_DEFAULT_ASPECT
    transition: str = "cut"
    vignette: bool = False
    grain: bool = False
    captions: bool = False
    music_enabled: bool = False
    music_provider: str = "jamendo"
    music_folder: str = ""
    jamendo_client_id: str = ""

    def __post_init__(self) -> None:
        if not self.script_text.strip():
            raise ValueError("script_text must not be empty")
        if not self.image_paths:
            raise ValueError("image_paths must not be empty")
        if self.aspect_ratio not in SLIDESHOW_ASPECT_DIMENSIONS:
            raise ValueError(
                f"aspect_ratio must be one of {sorted(SLIDESHOW_ASPECT_DIMENSIONS)}, "
                f"got {self.aspect_ratio!r}"
            )
        if self.transition not in ("cut", "crossfade"):
            raise ValueError(
                f"transition must be one of ('cut', 'crossfade'), got {self.transition!r}"
            )
        if self.music_provider not in ("jamendo", "local_folder"):
            raise ValueError(
                f"music_provider must be one of ('jamendo', 'local_folder'), "
                f"got {self.music_provider!r}"
            )

    @property
    def output_dimensions(self) -> tuple[int, int]:
        return SLIDESHOW_ASPECT_DIMENSIONS[self.aspect_ratio]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_slideshow_config.py -v`
Expected: 12 passed (7 existing + 5 new)

- [ ] **Step 5: Commit**

```bash
git add docu_studio/slideshow/slideshow_config.py tests/unit/test_slideshow_config.py
git commit -m "feat(slideshow): add Phase 3 config fields (transition, overlays, captions, music)"
```

---

### Task 5: `SlideshowFFmpeg.concat_segments_with_xfade` — crossfade transitions

**Files:**
- Modify: `docu_studio/slideshow/slideshow_ffmpeg.py`
- Test: `tests/unit/test_slideshow_ffmpeg.py` (extend existing file)

**Interfaces:**
- Consumes: `_SAR_PIXFMT_SUFFIX` (existing module constant), `self._check` (existing base method)
- Produces: `SlideshowFFmpeg._xfade_offsets(durations: list[float], transition_duration: float) -> list[float]` (static method), `SlideshowFFmpeg.concat_segments_with_xfade(input_paths: list[str], durations: list[float], transition_duration: float, output_path: str) -> None`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_slideshow_ffmpeg.py`:

```python
class TestXfadeOffsets:
    def test_two_segments(self) -> None:
        # seg0=3.5s, seg1=3.0s, transition=0.5s -> offset = 3.5 - 0.5 = 3.0
        offsets = SlideshowFFmpeg._xfade_offsets([3.5, 3.0], 0.5)
        assert offsets == pytest.approx([3.0])

    def test_three_segments_offsets_are_cumulative(self) -> None:
        # base [3,3,3] inflated to [3.5, 3.5, 3] by concat_segments_with_xfade's
        # caller (slideshow_assembly.crossfade_segment_durations) before this
        # method ever sees them.
        offsets = SlideshowFFmpeg._xfade_offsets([3.5, 3.5, 3.0], 0.5)
        assert offsets == pytest.approx([3.0, 6.0])


class TestConcatSegmentsWithXfade:
    def test_requires_at_least_two_segments(self, wrapper: SlideshowFFmpeg) -> None:
        with pytest.raises(ValueError, match="at least 2"):
            wrapper.concat_segments_with_xfade(["/a.mp4"], [3.0], 0.5, "/out.mp4")

    def test_builds_chained_xfade_filter_complex(self, wrapper: SlideshowFFmpeg) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.concat_segments_with_xfade(
                ["/a.mp4", "/b.mp4", "/c.mp4"], [3.5, 3.5, 3.0], 0.5, "/out.mp4",
            )
        cmd = mock_run.call_args[0][0]
        filter_complex = cmd[cmd.index("-filter_complex") + 1]
        assert filter_complex == (
            "[0:v][1:v]xfade=transition=fade:duration=0.50:offset=3.000[x1];"
            "[x1][2:v]xfade=transition=fade:duration=0.50:offset=6.000,"
            "setsar=1,format=yuv420p[vout]"
        )
        assert cmd[cmd.index("-map") + 1] == "[vout]"
        assert cmd.count("-i") == 3

    def test_raises_ffmpeg_error_on_nonzero_exit(self, wrapper: SlideshowFFmpeg) -> None:
        from docu_studio.media.ffmpeg_wrapper import FFmpegError
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="xfade boom")
            with pytest.raises(FFmpegError, match="xfade boom"):
                wrapper.concat_segments_with_xfade(
                    ["/a.mp4", "/b.mp4"], [3.5, 3.0], 0.5, "/out.mp4",
                )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_slideshow_ffmpeg.py -v -k Xfade`
Expected: FAIL with `AttributeError: type object 'SlideshowFFmpeg' has no attribute '_xfade_offsets'`

- [ ] **Step 3: Modify the implementation**

In `docu_studio/slideshow/slideshow_ffmpeg.py`, add inside the `SlideshowFFmpeg` class (after `_finalize_filter`):

```python
    @staticmethod
    def _xfade_offsets(durations: list[float], transition_duration: float) -> list[float]:
        """Return the N-1 ffmpeg `offset=` values for chaining `xfade` across
        N segments of the given *durations* (already inflated by the caller
        so the post-crossfade total equals the pre-inflation sum — see
        slideshow_assembly.crossfade_segment_durations). Each offset is the
        point in the running merged timeline where the next segment's
        crossfade begins: cumulative_duration_so_far - transition_duration."""
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
        """Concatenate already-Ken-Burns'd segment videos with a crossfade
        (ffmpeg's xfade filter) between each pair, instead of a hard cut.
        *durations* are the segments' actual rendered lengths (inflated by
        transition_duration on all but the last, per
        slideshow_assembly.crossfade_segment_durations), used here to compute
        each xfade's `offset=`. The final xfade stage is finalized through
        the same setsar=1,format=yuv420p suffix apply_ken_burns_image uses,
        so this new concat path can't reintroduce the SAR concat-crash bug."""
        n = len(input_paths)
        if n < 2:
            raise ValueError("concat_segments_with_xfade requires at least 2 segments")
        offsets = self._xfade_offsets(durations, transition_duration)

        stages = []
        prev_label = "[0:v]"
        for i in range(1, n):
            next_label = f"[{i}:v]"
            is_last = i == n - 1
            out_label = "[vout]" if is_last else f"[x{i}]"
            stage = (
                f"{prev_label}{next_label}xfade=transition=fade:"
                f"duration={transition_duration:.2f}:offset={offsets[i - 1]:.3f}"
            )
            if is_last:
                stage += f",{_SAR_PIXFMT_SUFFIX}"
            stage += out_label
            stages.append(stage)
            prev_label = f"[x{i}]"
        filter_complex = ";".join(stages)

        cmd = [self._ffmpeg, "-y"]
        for p in input_paths:
            cmd += ["-i", p]
        cmd += [
            "-filter_complex", filter_complex,
            "-map", "[vout]",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "22",
            output_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        self._check(result, f"concat_segments_with_xfade → {output_path!r}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_slideshow_ffmpeg.py -v`
Expected: all previous tests + 5 new pass

- [ ] **Step 5: Commit**

```bash
git add docu_studio/slideshow/slideshow_ffmpeg.py tests/unit/test_slideshow_ffmpeg.py
git commit -m "feat(slideshow): add xfade crossfade concat, finalized through the SAR suffix"
```

---

### Task 6: `SlideshowFFmpeg.apply_overlays` — vignette + grain

**Files:**
- Modify: `docu_studio/slideshow/slideshow_ffmpeg.py`
- Test: `tests/unit/test_slideshow_ffmpeg.py` (extend existing file)

**Interfaces:**
- Consumes: `self._finalize_filter` (existing)
- Produces: `SlideshowFFmpeg.apply_overlays(input_path: str, output_path: str, vignette: bool, grain: bool) -> None`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_slideshow_ffmpeg.py`:

```python
class TestApplyOverlays:
    def test_raises_when_neither_flag_set(self, wrapper: SlideshowFFmpeg) -> None:
        with pytest.raises(ValueError, match="at least one"):
            wrapper.apply_overlays("/in.mp4", "/out.mp4", vignette=False, grain=False)

    def test_vignette_only(self, wrapper: SlideshowFFmpeg) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.apply_overlays("/in.mp4", "/out.mp4", vignette=True, grain=False)
        vf = mock_run.call_args[0][0][mock_run.call_args[0][0].index("-vf") + 1]
        assert vf == "vignette,setsar=1,format=yuv420p"

    def test_grain_only(self, wrapper: SlideshowFFmpeg) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.apply_overlays("/in.mp4", "/out.mp4", vignette=False, grain=True)
        vf = mock_run.call_args[0][0][mock_run.call_args[0][0].index("-vf") + 1]
        assert vf == "noise=alls=8:allf=t,setsar=1,format=yuv420p"

    def test_both_combined_in_order(self, wrapper: SlideshowFFmpeg) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.apply_overlays("/in.mp4", "/out.mp4", vignette=True, grain=True)
        vf = mock_run.call_args[0][0][mock_run.call_args[0][0].index("-vf") + 1]
        assert vf == "vignette,noise=alls=8:allf=t,setsar=1,format=yuv420p"

    def test_raises_ffmpeg_error_on_nonzero_exit(self, wrapper: SlideshowFFmpeg) -> None:
        from docu_studio.media.ffmpeg_wrapper import FFmpegError
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="overlay boom")
            with pytest.raises(FFmpegError, match="overlay boom"):
                wrapper.apply_overlays("/in.mp4", "/out.mp4", vignette=True, grain=False)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_slideshow_ffmpeg.py -v -k Overlays`
Expected: FAIL with `AttributeError: 'SlideshowFFmpeg' object has no attribute 'apply_overlays'`

- [ ] **Step 3: Modify the implementation**

In `docu_studio/slideshow/slideshow_ffmpeg.py`, add inside the `SlideshowFFmpeg` class (after `concat_segments_with_xfade`):

```python
    def apply_overlays(
        self, input_path: str, output_path: str, vignette: bool, grain: bool,
    ) -> None:
        """Apply optional vignette and/or subtle film grain as a single
        ffmpeg pass. Caller (slideshow_assembly) only invokes this when at
        least one flag is set — both False is a caller contract violation,
        not a silent no-op, so it's guarded here rather than left to produce
        a wasted identity encode."""
        if not vignette and not grain:
            raise ValueError("apply_overlays requires at least one of vignette/grain to be True")
        filters = []
        if vignette:
            filters.append("vignette")
        if grain:
            # alls=8 is a subtle grain amount, not ffmpeg's heavier default.
            filters.append("noise=alls=8:allf=t")
        vf = self._finalize_filter(",".join(filters))
        cmd = [
            self._ffmpeg, "-y",
            "-i", input_path,
            "-vf", vf,
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "22",
            output_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        self._check(result, f"apply_overlays → {output_path!r}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_slideshow_ffmpeg.py -v`
Expected: all previous tests + 5 new pass

- [ ] **Step 5: Commit**

```bash
git add docu_studio/slideshow/slideshow_ffmpeg.py tests/unit/test_slideshow_ffmpeg.py
git commit -m "feat(slideshow): add optional vignette/grain overlay pass"
```

---

### Task 7: `SlideshowFFmpeg.burn_captions` — ASS burn-in

**Files:**
- Modify: `docu_studio/slideshow/slideshow_ffmpeg.py` (add `import os` to the top-level imports)
- Test: `tests/unit/test_slideshow_ffmpeg.py` (extend existing file)

**Interfaces:**
- Consumes: nothing new from this codebase (writes/reads plain files)
- Produces: `SlideshowFFmpeg.burn_captions(input_path: str, ass_path: str, output_path: str) -> None`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_slideshow_ffmpeg.py`:

```python
class TestBurnCaptions:
    def test_uses_subtitles_filter_with_bare_filename(self, wrapper: SlideshowFFmpeg, tmp_path) -> None:
        ass_path = tmp_path / "captions.ass"
        ass_path.write_text("[Script Info]\n", encoding="utf-8")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.burn_captions(str(tmp_path / "in.mp4"), str(ass_path), str(tmp_path / "out.mp4"))
        cmd = mock_run.call_args[0][0]
        vf = cmd[cmd.index("-vf") + 1]
        assert vf == "subtitles=captions.ass,setsar=1,format=yuv420p"

    def test_runs_with_cwd_set_to_ass_directory(self, wrapper: SlideshowFFmpeg, tmp_path) -> None:
        ass_path = tmp_path / "captions.ass"
        ass_path.write_text("[Script Info]\n", encoding="utf-8")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.burn_captions(str(tmp_path / "in.mp4"), str(ass_path), str(tmp_path / "out.mp4"))
        assert mock_run.call_args.kwargs["cwd"] == str(tmp_path)

    def test_raises_ffmpeg_error_on_nonzero_exit(self, wrapper: SlideshowFFmpeg, tmp_path) -> None:
        from docu_studio.media.ffmpeg_wrapper import FFmpegError
        ass_path = tmp_path / "captions.ass"
        ass_path.write_text("[Script Info]\n", encoding="utf-8")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="subtitles boom")
            with pytest.raises(FFmpegError, match="subtitles boom"):
                wrapper.burn_captions(str(tmp_path / "in.mp4"), str(ass_path), str(tmp_path / "out.mp4"))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_slideshow_ffmpeg.py -v -k BurnCaptions`
Expected: FAIL with `AttributeError: 'SlideshowFFmpeg' object has no attribute 'burn_captions'`

- [ ] **Step 3: Modify the implementation**

In `docu_studio/slideshow/slideshow_ffmpeg.py`, add `import os` near the top (with `import subprocess`), then add inside the `SlideshowFFmpeg` class (after `apply_overlays`):

```python
    def burn_captions(self, input_path: str, ass_path: str, output_path: str) -> None:
        """Burn *ass_path* (ASS pop-caption subtitles) into *input_path* via
        ffmpeg's subtitles filter. *input_path* here is video-only — no
        audio stream to preserve at this stage (captions burn in before mux).

        Same cwd-relative-filename technique as ShortsFFmpeg.burn_captions:
        ffmpeg's -vf value is parsed by the avfilter graph description parser,
        which splits on unescaped ':' — this breaks on any colon in the path.
        Sidestepping it: run ffmpeg with cwd set to the subtitle file's own
        directory and reference only its bare filename in the filter string.
        input_path/output_path are unaffected — they're plain argv values.

        Also runs through _finalize_filter like every other new re-encoding
        path in this phase: the subtitles filter itself can't introduce SAR
        drift (it draws an overlay, it doesn't scale), so this is stricter
        than strictly required, but it keeps the SAR/pixfmt discipline
        uniform across every method instead of leaving one silent exception
        a future reader would have to know Shorts' history to trust.
        """
        ass_dir = os.path.dirname(ass_path) or "."
        ass_name = os.path.basename(ass_path)
        vf = self._finalize_filter(f"subtitles={ass_name}")
        cmd = [
            self._ffmpeg, "-y",
            "-i", os.path.abspath(input_path),
            "-vf", vf,
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "22",
            os.path.abspath(output_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=ass_dir)
        self._check(result, f"burn_captions → {output_path!r}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_slideshow_ffmpeg.py -v`
Expected: all previous tests + 3 new pass

- [ ] **Step 5: Commit**

```bash
git add docu_studio/slideshow/slideshow_ffmpeg.py tests/unit/test_slideshow_ffmpeg.py
git commit -m "feat(slideshow): add ASS caption burn-in with colon-safe cwd handling"
```

---

### Task 8: `SlideshowFFmpeg.mix_music_bed` — ducked music mixing

**Files:**
- Modify: `docu_studio/slideshow/slideshow_ffmpeg.py`
- Test: `tests/unit/test_slideshow_ffmpeg.py` (extend existing file)

**Interfaces:**
- Consumes: `slideshow_audio_mix.build_ducking_filtergraph` (Task 1)
- Produces: `SlideshowFFmpeg.mix_music_bed(voice_path: str, music_path: str, video_duration: float, output_path: str) -> None`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_slideshow_ffmpeg.py`:

```python
class TestMixMusicBed:
    def test_maps_aout_and_loops_music_input(self, wrapper: SlideshowFFmpeg) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.mix_music_bed("/voice.mp3", "/music.mp3", 12.0, "/out.mp3")
        cmd = mock_run.call_args[0][0]
        assert cmd[cmd.index("-map") + 1] == "[aout]"
        assert "-stream_loop" in cmd
        assert cmd[cmd.index("-stream_loop") + 1] == "-1"
        # -stream_loop -1 must immediately precede the music input, not the voice input.
        music_i_index = cmd.index("-i", cmd.index("-stream_loop"))
        assert cmd[music_i_index + 1] == "/music.mp3"

    def test_filter_complex_uses_build_ducking_filtergraph(self, wrapper: SlideshowFFmpeg) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wrapper.mix_music_bed("/voice.mp3", "/music.mp3", 12.0, "/out.mp3")
        cmd = mock_run.call_args[0][0]
        filter_complex = cmd[cmd.index("-filter_complex") + 1]
        assert "atrim=0:12.000" in filter_complex
        assert "sidechaincompress" in filter_complex

    def test_raises_ffmpeg_error_on_nonzero_exit(self, wrapper: SlideshowFFmpeg) -> None:
        from docu_studio.media.ffmpeg_wrapper import FFmpegError
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="mix boom")
            with pytest.raises(FFmpegError, match="mix boom"):
                wrapper.mix_music_bed("/voice.mp3", "/music.mp3", 12.0, "/out.mp3")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_slideshow_ffmpeg.py -v -k MixMusicBed`
Expected: FAIL with `AttributeError: 'SlideshowFFmpeg' object has no attribute 'mix_music_bed'`

- [ ] **Step 3: Modify the implementation**

In `docu_studio/slideshow/slideshow_ffmpeg.py`, add inside the `SlideshowFFmpeg` class (after `burn_captions`):

```python
    def mix_music_bed(
        self, voice_path: str, music_path: str, video_duration: float, output_path: str,
    ) -> None:
        """Loop/trim *music_path* to *video_duration*, duck it under
        *voice_path* via sidechaincompress, and write the mixed result to
        *output_path* as a standalone audio file — the caller
        (slideshow_assembly) passes this into mux_audio_video exactly as it
        would the raw narration track, so that method's -map discipline
        never needs to change."""
        from docu_studio.slideshow.slideshow_audio_mix import build_ducking_filtergraph

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

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_slideshow_ffmpeg.py -v`
Expected: all previous tests + 3 new pass

- [ ] **Step 5: Commit**

```bash
git add docu_studio/slideshow/slideshow_ffmpeg.py tests/unit/test_slideshow_ffmpeg.py
git commit -m "feat(slideshow): add sidechaincompress music-bed ducking"
```

---

### Task 9: `slideshow_assembly.py` — wire all four features into the pipeline

**Files:**
- Modify: `docu_studio/slideshow/slideshow_assembly.py`
- Test: `tests/unit/test_slideshow_assembly.py` (extend existing file, do not remove existing tests)

**Interfaces:**
- Consumes: `SlideshowFFmpeg.concat_segments_with_xfade` (Task 5), `SlideshowFFmpeg.apply_overlays` (Task 6), `SlideshowFFmpeg.burn_captions` (Task 7), `SlideshowFFmpeg.mix_music_bed` (Task 8), `slideshow_captions.estimate_word_timestamps`/`write_ass_file` (Task 2)
- Produces: `crossfade_segment_durations(base_durations: list[float], transition_duration: float) -> list[float]`, `assemble_slideshow(..., transition: str = "cut", vignette: bool = False, grain: bool = False, captions: bool = False, script_text: str = "", music_path: str | None = None)`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_slideshow_assembly.py`:

```python
class TestCrossfadeSegmentDurations:
    def test_inflates_all_but_last_segment(self) -> None:
        from docu_studio.slideshow.slideshow_assembly import crossfade_segment_durations
        result = crossfade_segment_durations([3.0, 3.0, 3.0], 0.5)
        assert result == pytest.approx([3.5, 3.5, 3.0])

    def test_single_segment_unchanged(self) -> None:
        from docu_studio.slideshow.slideshow_assembly import crossfade_segment_durations
        assert crossfade_segment_durations([9.0], 0.5) == [9.0]


class TestAssembleSlideshowCrossfade:
    def test_crossfade_uses_xfade_concat_with_inflated_durations(self, tmp_path: Path) -> None:
        ffmpeg = MagicMock()
        event_queue: "queue.Queue[object]" = queue.Queue()
        assemble_slideshow(
            image_paths=["/img0.jpg", "/img1.jpg", "/img2.jpg"],
            audio_path="/narration.mp3",
            audio_duration=9.0,
            ffmpeg=ffmpeg,
            scene_dir=tmp_path,
            output_path=tmp_path / "final.mp4",
            out_width=1080,
            out_height=1920,
            event_queue=event_queue,
            transition="crossfade",
        )
        ffmpeg.concat_segments_video_only.assert_not_called()
        ffmpeg.concat_segments_with_xfade.assert_called_once()
        call_args = ffmpeg.concat_segments_with_xfade.call_args.args
        assert call_args[1] == pytest.approx([3.5, 3.5, 3.0])  # durations, inflated
        assert call_args[2] == 0.5  # transition_duration

    def test_crossfade_segments_rendered_with_inflated_durations(self, tmp_path: Path) -> None:
        ffmpeg = MagicMock()
        event_queue: "queue.Queue[object]" = queue.Queue()
        assemble_slideshow(
            image_paths=["/img0.jpg", "/img1.jpg", "/img2.jpg"],
            audio_path="/narration.mp3",
            audio_duration=9.0,
            ffmpeg=ffmpeg,
            scene_dir=tmp_path,
            output_path=tmp_path / "final.mp4",
            out_width=1080,
            out_height=1920,
            event_queue=event_queue,
            transition="crossfade",
        )
        first_seg_duration = ffmpeg.apply_ken_burns_image.call_args_list[0].args[2]
        last_seg_duration = ffmpeg.apply_ken_burns_image.call_args_list[2].args[2]
        assert first_seg_duration == pytest.approx(3.5)
        assert last_seg_duration == pytest.approx(3.0)

    def test_single_image_crossfade_falls_back_to_hard_cut(self, tmp_path: Path) -> None:
        ffmpeg = MagicMock()
        event_queue: "queue.Queue[object]" = queue.Queue()
        assemble_slideshow(
            image_paths=["/img0.jpg"],
            audio_path="/narration.mp3",
            audio_duration=3.0,
            ffmpeg=ffmpeg,
            scene_dir=tmp_path,
            output_path=tmp_path / "final.mp4",
            out_width=1080,
            out_height=1920,
            event_queue=event_queue,
            transition="crossfade",
        )
        ffmpeg.concat_segments_with_xfade.assert_not_called()
        ffmpeg.concat_segments_video_only.assert_called_once()

    def test_hard_cut_default_still_uses_concat_segments_video_only(self, tmp_path: Path) -> None:
        ffmpeg = MagicMock()
        event_queue: "queue.Queue[object]" = queue.Queue()
        assemble_slideshow(
            image_paths=["/img0.jpg", "/img1.jpg"],
            audio_path="/narration.mp3",
            audio_duration=6.0,
            ffmpeg=ffmpeg,
            scene_dir=tmp_path,
            output_path=tmp_path / "final.mp4",
            out_width=1080,
            out_height=1920,
            event_queue=event_queue,
        )
        ffmpeg.concat_segments_with_xfade.assert_not_called()
        ffmpeg.concat_segments_video_only.assert_called_once()


class TestAssembleSlideshowOverlays:
    def test_overlays_applied_when_vignette_enabled(self, tmp_path: Path) -> None:
        ffmpeg = MagicMock()
        event_queue: "queue.Queue[object]" = queue.Queue()
        assemble_slideshow(
            image_paths=["/img0.jpg"], audio_path="/narration.mp3", audio_duration=3.0,
            ffmpeg=ffmpeg, scene_dir=tmp_path, output_path=tmp_path / "final.mp4",
            out_width=1080, out_height=1920, event_queue=event_queue, vignette=True,
        )
        ffmpeg.apply_overlays.assert_called_once_with(
            str(tmp_path / "slideshow_concat.mp4"), str(tmp_path / "slideshow_overlay.mp4"), True, False,
        )
        ffmpeg.mux_audio_video.assert_called_once_with(
            str(tmp_path / "slideshow_overlay.mp4"), "/narration.mp3", str(tmp_path / "final.mp4"),
        )

    def test_overlays_skipped_when_both_flags_false(self, tmp_path: Path) -> None:
        ffmpeg = MagicMock()
        event_queue: "queue.Queue[object]" = queue.Queue()
        assemble_slideshow(
            image_paths=["/img0.jpg"], audio_path="/narration.mp3", audio_duration=3.0,
            ffmpeg=ffmpeg, scene_dir=tmp_path, output_path=tmp_path / "final.mp4",
            out_width=1080, out_height=1920, event_queue=event_queue,
        )
        ffmpeg.apply_overlays.assert_not_called()


class TestAssembleSlideshowCaptions:
    def test_captions_burned_when_enabled(self, tmp_path: Path) -> None:
        ffmpeg = MagicMock()
        event_queue: "queue.Queue[object]" = queue.Queue()
        assemble_slideshow(
            image_paths=["/img0.jpg"], audio_path="/narration.mp3", audio_duration=3.0,
            ffmpeg=ffmpeg, scene_dir=tmp_path, output_path=tmp_path / "final.mp4",
            out_width=1080, out_height=1920, event_queue=event_queue,
            captions=True, script_text="hello there world",
        )
        ffmpeg.burn_captions.assert_called_once()
        call_args = ffmpeg.burn_captions.call_args.args
        assert call_args[0] == str(tmp_path / "slideshow_concat.mp4")
        assert call_args[1] == str(tmp_path / "captions.ass")
        assert (tmp_path / "captions.ass").exists()
        ffmpeg.mux_audio_video.assert_called_once_with(
            str(tmp_path / "slideshow_captioned.mp4"), "/narration.mp3", str(tmp_path / "final.mp4"),
        )

    def test_captions_skipped_when_disabled(self, tmp_path: Path) -> None:
        ffmpeg = MagicMock()
        event_queue: "queue.Queue[object]" = queue.Queue()
        assemble_slideshow(
            image_paths=["/img0.jpg"], audio_path="/narration.mp3", audio_duration=3.0,
            ffmpeg=ffmpeg, scene_dir=tmp_path, output_path=tmp_path / "final.mp4",
            out_width=1080, out_height=1920, event_queue=event_queue,
        )
        ffmpeg.burn_captions.assert_not_called()

    def test_captions_run_after_overlays_on_overlay_output(self, tmp_path: Path) -> None:
        ffmpeg = MagicMock()
        event_queue: "queue.Queue[object]" = queue.Queue()
        assemble_slideshow(
            image_paths=["/img0.jpg"], audio_path="/narration.mp3", audio_duration=3.0,
            ffmpeg=ffmpeg, scene_dir=tmp_path, output_path=tmp_path / "final.mp4",
            out_width=1080, out_height=1920, event_queue=event_queue,
            vignette=True, captions=True, script_text="hi",
        )
        assert ffmpeg.burn_captions.call_args.args[0] == str(tmp_path / "slideshow_overlay.mp4")


class TestAssembleSlideshowMusic:
    def test_music_mixed_into_narration_before_mux(self, tmp_path: Path) -> None:
        ffmpeg = MagicMock()
        event_queue: "queue.Queue[object]" = queue.Queue()
        assemble_slideshow(
            image_paths=["/img0.jpg"], audio_path="/narration.mp3", audio_duration=3.0,
            ffmpeg=ffmpeg, scene_dir=tmp_path, output_path=tmp_path / "final.mp4",
            out_width=1080, out_height=1920, event_queue=event_queue,
            music_path="/music/track.mp3",
        )
        ffmpeg.mix_music_bed.assert_called_once_with(
            "/narration.mp3", "/music/track.mp3", 3.0, str(tmp_path / "narration_with_music.mp3"),
        )
        ffmpeg.mux_audio_video.assert_called_once_with(
            str(tmp_path / "slideshow_concat.mp4"),
            str(tmp_path / "narration_with_music.mp3"),
            str(tmp_path / "final.mp4"),
        )

    def test_no_music_path_skips_mixing(self, tmp_path: Path) -> None:
        ffmpeg = MagicMock()
        event_queue: "queue.Queue[object]" = queue.Queue()
        assemble_slideshow(
            image_paths=["/img0.jpg"], audio_path="/narration.mp3", audio_duration=3.0,
            ffmpeg=ffmpeg, scene_dir=tmp_path, output_path=tmp_path / "final.mp4",
            out_width=1080, out_height=1920, event_queue=event_queue,
        )
        ffmpeg.mix_music_bed.assert_not_called()
        ffmpeg.mux_audio_video.assert_called_once_with(
            str(tmp_path / "slideshow_concat.mp4"), "/narration.mp3", str(tmp_path / "final.mp4"),
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_slideshow_assembly.py -v`
Expected: FAIL — new tests error (`ImportError` for `crossfade_segment_durations`, or `TypeError: assemble_slideshow() got an unexpected keyword argument 'transition'`); the 4 pre-existing tests still pass.

- [ ] **Step 3: Modify the implementation**

Replace the full contents of `docu_studio/slideshow/slideshow_assembly.py`:

```python
"""Audio-first assembly for Slideshow: TTS duration -> even image split ->
Ken Burns -> concat (hard cut or crossfade) -> overlays -> captions -> mux
narration (+ music) over the result.

Deliberately does not use sentence_spans()/audio-aligned word-timing/
sentence-scoped pool assignment — those solve a problem (aligning per-sentence
narration to per-sentence *searched* image results) that doesn't exist yet
with a flat, manually-ordered image list and no topic search. See the Phase 1
design spec for why this is out of scope here. Phase 3's captions use a
duration-estimate word timing instead (slideshow_captions.py), which is a
different thing from that deferred sentence-scoped alignment.
"""
from __future__ import annotations

import logging
from pathlib import Path

from docu_studio.pipeline.events import LogEvent, LogLevel, ProgressEvent
from docu_studio.slideshow.slideshow_ffmpeg import SlideshowFFmpeg
from docu_studio.slideshow.slideshow_motion import direction_for_index

_log = logging.getLogger(__name__)

_TRANSITION_DURATION = 0.5


def split_duration_evenly(total_duration: float, count: int) -> list[float]:
    """Split *total_duration* into *count* segment durations that sum
    exactly to *total_duration*. All segments get the same duration except
    the last, which absorbs the rounding remainder."""
    if count <= 0:
        raise ValueError("count must be positive")
    base = round(total_duration / count, 3)
    durations = [base] * (count - 1)
    last = round(total_duration - sum(durations), 3)
    durations.append(last)
    return durations


def crossfade_segment_durations(base_durations: list[float], transition_duration: float) -> list[float]:
    """Inflate every segment except the last by *transition_duration*
    seconds. Chaining N-1 xfade merges each shortens the timeline by
    *transition_duration*, so inflating N-1 of the N segments by that amount
    means the post-crossfade total still equals sum(base_durations) exactly
    — no shrinkage relative to the narration's measured length."""
    if len(base_durations) < 2:
        return list(base_durations)
    return [d + transition_duration for d in base_durations[:-1]] + [base_durations[-1]]


def assemble_slideshow(
    image_paths: list[str],
    audio_path: str,
    audio_duration: float,
    ffmpeg: SlideshowFFmpeg,
    scene_dir: Path,
    output_path: Path,
    out_width: int,
    out_height: int,
    event_queue,
    transition: str = "cut",
    vignette: bool = False,
    grain: bool = False,
    captions: bool = False,
    script_text: str = "",
    music_path: str | None = None,
) -> None:
    """Build the final slideshow video. All Phase 3 parameters default to
    Phase 1/2 behavior: hard cut, no overlays, no captions, no music — a
    caller that passes none of them gets the exact prior pipeline."""
    base_durations = split_duration_evenly(audio_duration, len(image_paths))
    use_crossfade = transition == "crossfade" and len(image_paths) > 1
    durations = crossfade_segment_durations(base_durations, _TRANSITION_DURATION) if use_crossfade else base_durations

    event_queue.put(ProgressEvent(
        stage="Slideshow Assembly", message=f"Building {len(image_paths)} segments…",
    ))
    segment_paths: list[str] = []
    for i, (image_path, duration) in enumerate(zip(image_paths, durations)):
        direction = direction_for_index(i)
        seg_path = str(scene_dir / f"seg_{i:03d}.mp4")
        try:
            ffmpeg.apply_ken_burns_image(
                image_path, seg_path, duration, direction, out_width, out_height,
            )
        except Exception as exc:
            raise RuntimeError(
                f"Segment {i} (image {image_path!r}) failed to render: {exc}"
            ) from exc
        segment_paths.append(seg_path)
        _log.info(
            "Segment %d: image=%s duration=%.2f direction=%s",
            i, image_path, duration, direction,
        )

    concat_path = str(scene_dir / "slideshow_concat.mp4")
    if use_crossfade:
        ffmpeg.concat_segments_with_xfade(segment_paths, durations, _TRANSITION_DURATION, concat_path)
    else:
        ffmpeg.concat_segments_video_only(segment_paths, concat_path)
    video_path = concat_path

    if vignette or grain:
        overlay_path = str(scene_dir / "slideshow_overlay.mp4")
        ffmpeg.apply_overlays(video_path, overlay_path, vignette, grain)
        video_path = overlay_path

    if captions:
        from docu_studio.slideshow.slideshow_captions import estimate_word_timestamps, write_ass_file

        timings = estimate_word_timestamps(script_text, audio_duration)
        ass_path = str(scene_dir / "captions.ass")
        write_ass_file(timings, ass_path, out_width, out_height, audio_duration)
        captioned_path = str(scene_dir / "slideshow_captioned.mp4")
        ffmpeg.burn_captions(video_path, ass_path, captioned_path)
        video_path = captioned_path

    event_queue.put(ProgressEvent(stage="Slideshow Mux", message="Muxing final slideshow…"))
    narration_path = audio_path
    if music_path:
        mixed_audio_path = str(scene_dir / "narration_with_music.mp3")
        ffmpeg.mix_music_bed(audio_path, music_path, audio_duration, mixed_audio_path)
        narration_path = mixed_audio_path
    ffmpeg.mux_audio_video(video_path, narration_path, str(output_path))

    event_queue.put(LogEvent(
        message=f"Slideshow assembled: {len(image_paths)} segments → {output_path}",
        level=LogLevel.INFO,
    ))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_slideshow_assembly.py -v`
Expected: all 4 pre-existing tests + 13 new pass (17 total)

- [ ] **Step 5: Commit**

```bash
git add docu_studio/slideshow/slideshow_assembly.py tests/unit/test_slideshow_assembly.py
git commit -m "feat(slideshow): wire transitions, overlays, captions, and music into assembly pipeline"
```

---

### Task 10: `SlideshowRunner` — thread Phase 3 options through

**Files:**
- Modify: `docu_studio/slideshow/slideshow_runner.py`
- Test: `tests/unit/test_slideshow_runner.py` (extend existing file, do not remove existing tests)

**Interfaces:**
- Consumes: `SlideshowConfig` (Task 4, new fields), `slideshow_music.resolve_music_track`/`DEFAULT_MUSIC_MOOD` (Task 3), `assemble_slideshow` (Task 9, new params)
- Produces: `SlideshowRunner.__init__` gains `transition`, `vignette`, `grain`, `captions`, `music_enabled`, `music_provider`, `music_folder`, `jamendo_client_id` keyword arguments (all defaulting to Phase 1/2 behavior)

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_slideshow_runner.py`:

```python
class TestPhase3Wiring:
    def test_defaults_produce_config_matching_phase1_phase2(self, tmp_path: Path) -> None:
        image = tmp_path / "photo.jpg"
        image.write_bytes(b"\xff\xd8\xff")
        runner = SlideshowRunner(
            script_text="Hello.", image_paths=[str(image)], tts=MagicMock(), output_base=tmp_path,
        )
        assert runner.config.transition == "cut"
        assert runner.config.vignette is False
        assert runner.config.music_enabled is False

    def test_phase3_kwargs_reach_config(self, tmp_path: Path) -> None:
        image = tmp_path / "photo.jpg"
        image.write_bytes(b"\xff\xd8\xff")
        runner = SlideshowRunner(
            script_text="Hello.", image_paths=[str(image)], tts=MagicMock(), output_base=tmp_path,
            transition="crossfade", vignette=True, grain=True, captions=True,
            music_enabled=True, music_provider="local_folder", music_folder="/tunes",
            jamendo_client_id="fake-id",
        )
        assert runner.config.transition == "crossfade"
        assert runner.config.vignette is True
        assert runner.config.grain is True
        assert runner.config.captions is True
        assert runner.config.music_enabled is True
        assert runner.config.music_provider == "local_folder"
        assert runner.config.music_folder == "/tunes"
        assert runner.config.jamendo_client_id == "fake-id"

    def test_music_enabled_resolves_track_before_assembly(self, tmp_path: Path) -> None:
        image = tmp_path / "photo.jpg"
        image.write_bytes(b"\xff\xd8\xff")
        tts = MagicMock()
        tts.synthesize.return_value = 6.0
        runner = SlideshowRunner(
            script_text="Hello world.", image_paths=[str(image)], tts=tts, output_base=tmp_path,
            music_enabled=True, music_provider="local_folder", music_folder="/tunes",
        )
        with patch("docu_studio.slideshow.slideshow_runner.SlideshowFFmpeg") as mock_ffmpeg_cls, \
             patch("docu_studio.slideshow.slideshow_runner.assemble_slideshow") as mock_assemble, \
             patch("docu_studio.slideshow.slideshow_runner.resolve_music_track") as mock_resolve, \
             patch("docu_studio.slideshow.slideshow_runner.save_run"):
            mock_ffmpeg_cls.return_value = MagicMock()
            mock_resolve.return_value = ("/tunes/song.mp3", "song.mp3")
            runner.run()
        mock_resolve.assert_called_once()
        assert mock_resolve.call_args.kwargs["provider_name"] == "local_folder"
        assert mock_resolve.call_args.kwargs["local_folder"] == "/tunes"
        assert mock_assemble.call_args.kwargs["music_path"] == "/tunes/song.mp3"

    def test_music_enabled_but_unresolved_still_completes(self, tmp_path: Path) -> None:
        image = tmp_path / "photo.jpg"
        image.write_bytes(b"\xff\xd8\xff")
        tts = MagicMock()
        tts.synthesize.return_value = 6.0
        runner = SlideshowRunner(
            script_text="Hello world.", image_paths=[str(image)], tts=tts, output_base=tmp_path,
            music_enabled=True, music_provider="local_folder", music_folder="/empty",
        )
        with patch("docu_studio.slideshow.slideshow_runner.SlideshowFFmpeg") as mock_ffmpeg_cls, \
             patch("docu_studio.slideshow.slideshow_runner.assemble_slideshow") as mock_assemble, \
             patch("docu_studio.slideshow.slideshow_runner.resolve_music_track", return_value=None), \
             patch("docu_studio.slideshow.slideshow_runner.save_run"):
            mock_ffmpeg_cls.return_value = MagicMock()
            runner.run()
        assert runner._status == SlideshowRunStatus.COMPLETED
        assert mock_assemble.call_args.kwargs["music_path"] is None

    def test_captions_pass_script_text_into_assembly(self, tmp_path: Path) -> None:
        image = tmp_path / "photo.jpg"
        image.write_bytes(b"\xff\xd8\xff")
        tts = MagicMock()
        tts.synthesize.return_value = 6.0
        runner = SlideshowRunner(
            script_text="Hello world.", image_paths=[str(image)], tts=tts, output_base=tmp_path,
            captions=True,
        )
        with patch("docu_studio.slideshow.slideshow_runner.SlideshowFFmpeg") as mock_ffmpeg_cls, \
             patch("docu_studio.slideshow.slideshow_runner.assemble_slideshow") as mock_assemble, \
             patch("docu_studio.slideshow.slideshow_runner.save_run"):
            mock_ffmpeg_cls.return_value = MagicMock()
            runner.run()
        assert mock_assemble.call_args.kwargs["captions"] is True
        assert mock_assemble.call_args.kwargs["script_text"] == "Hello world."
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_slideshow_runner.py -v`
Expected: FAIL — new tests error (`TypeError: SlideshowRunner.__init__() got an unexpected keyword argument 'transition'`); the 4 pre-existing tests still pass.

- [ ] **Step 3: Modify the implementation**

Replace the full contents of `docu_studio/slideshow/slideshow_runner.py`:

```python
"""SlideshowRunner — background thread that orchestrates the Slideshow
pipeline.

Mirrors ShortsRunner's public shape (event_queue, cancel_event,
_final_video_path, _project_folder, run()) so Bridge._translate_events()
works unmodified for slideshow runs — a new branch is added alongside
start_shorts_run, not into it. Does not import anything from
docu_studio.shorts, per the Phase 1 design decision to defer all shared
infrastructure extraction until a later phase actually needs it.
"""
from __future__ import annotations

import queue
import threading
from datetime import datetime
from enum import Enum
from pathlib import Path

from docu_studio.adapters.tts.base import TTSProvider
from docu_studio.history.run_history import RunRecord, save_run
from docu_studio.output.project_folder import create_project_folder
from docu_studio.pipeline.events import ErrorEvent, LogEvent, LogLevel, ProgressEvent
from docu_studio.slideshow.slideshow_assembly import assemble_slideshow
from docu_studio.slideshow.slideshow_config import SlideshowConfig
from docu_studio.slideshow.slideshow_ffmpeg import SlideshowFFmpeg
from docu_studio.slideshow.slideshow_images import validate_manual_images
from docu_studio.slideshow.slideshow_music import DEFAULT_MUSIC_MOOD, resolve_music_track


class SlideshowRunStatus(str, Enum):
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class SlideshowRunner(threading.Thread):
    def __init__(
        self,
        script_text: str,
        image_paths: list[str],
        tts: TTSProvider,
        output_base: Path,
        aspect_ratio: str = "9:16",
        transition: str = "cut",
        vignette: bool = False,
        grain: bool = False,
        captions: bool = False,
        music_enabled: bool = False,
        music_provider: str = "jamendo",
        music_folder: str = "",
        jamendo_client_id: str = "",
    ) -> None:
        super().__init__(daemon=True, name="SlideshowRunner")
        self.config = SlideshowConfig(
            script_text=script_text, image_paths=image_paths, aspect_ratio=aspect_ratio,
            transition=transition, vignette=vignette, grain=grain, captions=captions,
            music_enabled=music_enabled, music_provider=music_provider,
            music_folder=music_folder, jamendo_client_id=jamendo_client_id,
        )
        self.tts = tts
        self.output_base = output_base

        self.event_queue: "queue.Queue[object]" = queue.Queue()
        self.cancel_event = threading.Event()

        self._status = SlideshowRunStatus.FAILED
        self._project_folder: Path | None = None
        self._final_video_path: Path | None = None
        self._started_at = datetime.now()

    def run(self) -> None:
        try:
            self._execute()
        except Exception as exc:
            self.event_queue.put(ErrorEvent(message=str(exc), fatal=True))
            self._status = SlideshowRunStatus.FAILED
        finally:
            self._save_history()
            self.event_queue.put(None)

    def _execute(self) -> None:
        if self._cancelled():
            return
        images = validate_manual_images(self.config.image_paths)
        self._project_folder = create_project_folder(
            "slideshow", self._started_at, self.output_base
        )
        ffmpeg = SlideshowFFmpeg()

        self.event_queue.put(ProgressEvent(
            stage="Slideshow TTS", message="Synthesizing narration…",
        ))
        audio_path = str(self._project_folder / "audio" / "narration.mp3")
        audio_duration = self.tts.synthesize(self.config.script_text, audio_path)
        self.event_queue.put(LogEvent(
            message=f"Narration: {audio_duration:.2f}s", level=LogLevel.INFO,
        ))
        if self._cancelled():
            return

        music_path = None
        if self.config.music_enabled:
            resolved = resolve_music_track(
                provider_name=self.config.music_provider,
                mood=DEFAULT_MUSIC_MOOD,
                max_duration=audio_duration,
                jamendo_client_id=self.config.jamendo_client_id,
                local_folder=self.config.music_folder,
            )
            if resolved:
                music_path, music_label = resolved
                self.event_queue.put(LogEvent(
                    message=f"Music: using {music_label!r}", level=LogLevel.INFO,
                ))
            else:
                self.event_queue.put(LogEvent(
                    message="Music: no usable track found — continuing without music bed",
                    level=LogLevel.INFO,
                ))
        if self._cancelled():
            return

        out_width, out_height = self.config.output_dimensions
        output_path = self._project_folder / "slideshow_final.mp4"
        assemble_slideshow(
            image_paths=images,
            audio_path=audio_path,
            audio_duration=audio_duration,
            ffmpeg=ffmpeg,
            scene_dir=self._project_folder / "video",
            output_path=output_path,
            out_width=out_width,
            out_height=out_height,
            event_queue=self.event_queue,
            transition=self.config.transition,
            vignette=self.config.vignette,
            grain=self.config.grain,
            captions=self.config.captions,
            script_text=self.config.script_text,
            music_path=music_path,
        )
        if self._cancelled():
            return

        self._final_video_path = output_path
        self._status = SlideshowRunStatus.COMPLETED
        self.event_queue.put(ProgressEvent(
            stage="Done", message=f"Slideshow completed: {output_path}",
        ))

    def _cancelled(self) -> bool:
        if self.cancel_event.is_set():
            self._status = SlideshowRunStatus.CANCELLED
            self.event_queue.put(ProgressEvent(stage="Cancelled", message="Run cancelled by user."))
            return True
        return False

    def _save_history(self) -> None:
        try:
            record = RunRecord(
                topic="Slideshow",
                mode="slideshow",
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

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_slideshow_runner.py -v`
Expected: all 4 pre-existing tests + 5 new pass (9 total)

- [ ] **Step 5: Commit**

```bash
git add docu_studio/slideshow/slideshow_runner.py tests/unit/test_slideshow_runner.py
git commit -m "feat(slideshow): thread transitions, overlays, captions, and music through the runner"
```

---

### Task 11: `bridge.py` — wire Phase 3 config from the GUI

**Files:**
- Modify: `docu_studio/gui/bridge.py:332-368` (the `start_slideshow_run` method)

**Interfaces:**
- Consumes: `key_cache.get` (existing), `SlideshowRunner` (Task 10, new kwargs)
- Produces: no new public interface — `start_slideshow_run(config: dict)` now reads `transition`, `vignette`, `grain`, `captions`, `music_enabled`, `music_provider`, `music_folder` from *config* and the Jamendo key from `key_cache`

There is no isolated unit test file for `bridge.py` (it's exercised through the GUI, verified manually in Task 14) — this task is a direct, minimal-diff edit.

- [ ] **Step 1: Edit the method**

In `docu_studio/gui/bridge.py`, inside `start_slideshow_run`, locate:

```python
            output_base = (
                Path(s.output_folder)
                if getattr(s, "output_folder", None)
                else Path.home() / "DocuStudio"
            )

            self._runner = SlideshowRunner(
                script_text=config.get("script_text", ""),
                image_paths=list(config.get("image_paths", [])),
                tts=tts,
                output_base=output_base,
                aspect_ratio=config.get("aspect_ratio", "9:16"),
            )
```

Replace with:

```python
            output_base = (
                Path(s.output_folder)
                if getattr(s, "output_folder", None)
                else Path.home() / "DocuStudio"
            )
            jamendo_client_id = key_cache.get("docu_studio_jamendo") or ""

            self._runner = SlideshowRunner(
                script_text=config.get("script_text", ""),
                image_paths=list(config.get("image_paths", [])),
                tts=tts,
                output_base=output_base,
                aspect_ratio=config.get("aspect_ratio", "9:16"),
                transition=config.get("transition", "cut"),
                vignette=bool(config.get("vignette", False)),
                grain=bool(config.get("grain", False)),
                captions=bool(config.get("captions", False)),
                music_enabled=bool(config.get("music_enabled", False)),
                music_provider=config.get("music_provider", "jamendo"),
                music_folder=config.get("music_folder", ""),
                jamendo_client_id=jamendo_client_id,
            )
```

- [ ] **Step 2: Verify the app still imports cleanly**

Run: `.venv/bin/python -c "from docu_studio.gui.bridge import Bridge; Bridge()"`
Expected: no output, exit code 0 (no import/syntax errors)

- [ ] **Step 3: Run the full unit suite to confirm nothing else broke**

Run: `.venv/bin/python -m pytest -q --continue-on-collection-errors`
Expected: previous total + all Phase 3 tests so far pass; still 24 failed / 1 error (unchanged pre-existing baseline)

- [ ] **Step 4: Commit**

```bash
git add docu_studio/gui/bridge.py
git commit -m "feat(slideshow): wire Phase 3 config fields and Jamendo key into start_slideshow_run"
```

---

### Task 12: `index.html` — Phase 3 GUI controls

**Files:**
- Modify: `docu_studio/gui/web/index.html:366-375` (insert new rows after the existing `slideshow-aspect-row` block)

No automated test — GUI markup is verified in Task 14's manual click-through (or, if the environment still blocks it, deferred to the user's manual check per the standing note).

- [ ] **Step 1: Insert the new controls**

Locate this existing block:

```html
        <!-- Aspect ratio (slideshow) -->
        <div id="slideshow-aspect-row" class="mt-6" style="display:none">
          <label class="text-sm font-medium text-dim block">Aspect ratio</label>
          <select id="slideshow-aspect-select"
            class="mt-2 w-full bg-input border border-border rounded-lg px-4 py-3 text-white text-sm focus:border-accent focus:outline-none">
            <option value="9:16">9:16 vertical (1080 × 1920)</option>
            <option value="16:9">16:9 widescreen (1920 × 1080)</option>
            <option value="1:1">1:1 square (1080 × 1080)</option>
          </select>
        </div>

        <!-- Start button -->
```

Replace with (inserting five new rows between the aspect row and the Start button):

```html
        <!-- Aspect ratio (slideshow) -->
        <div id="slideshow-aspect-row" class="mt-6" style="display:none">
          <label class="text-sm font-medium text-dim block">Aspect ratio</label>
          <select id="slideshow-aspect-select"
            class="mt-2 w-full bg-input border border-border rounded-lg px-4 py-3 text-white text-sm focus:border-accent focus:outline-none">
            <option value="9:16">9:16 vertical (1080 × 1920)</option>
            <option value="16:9">16:9 widescreen (1920 × 1080)</option>
            <option value="1:1">1:1 square (1080 × 1080)</option>
          </select>
        </div>

        <!-- Transition (slideshow) -->
        <div id="slideshow-transition-row" class="mt-6" style="display:none">
          <label class="text-sm font-medium text-dim block">Transition</label>
          <select id="slideshow-transition-select"
            class="mt-2 w-full bg-input border border-border rounded-lg px-4 py-3 text-white text-sm focus:border-accent focus:outline-none">
            <option value="cut">Hard cut</option>
            <option value="crossfade">Crossfade</option>
          </select>
        </div>

        <!-- Vignette toggle (slideshow) -->
        <div id="slideshow-vignette-row" class="mt-4 flex items-center justify-between" style="display:none">
          <div>
            <label class="text-sm font-medium text-dim block">Vignette</label>
            <p class="text-xs text-faint mt-0.5">Subtle darkened edges.</p>
          </div>
          <input id="slideshow-vignette-toggle" type="checkbox" class="w-5 h-5 accent-accent cursor-pointer">
        </div>

        <!-- Grain toggle (slideshow) -->
        <div id="slideshow-grain-row" class="mt-4 flex items-center justify-between" style="display:none">
          <div>
            <label class="text-sm font-medium text-dim block">Film grain</label>
            <p class="text-xs text-faint mt-0.5">Subtle texture overlay.</p>
          </div>
          <input id="slideshow-grain-toggle" type="checkbox" class="w-5 h-5 accent-accent cursor-pointer">
        </div>

        <!-- Captions toggle (slideshow) -->
        <div id="slideshow-captions-row" class="mt-4 flex items-center justify-between" style="display:none">
          <div>
            <label class="text-sm font-medium text-dim block">Burned-in captions</label>
            <p class="text-xs text-faint mt-0.5">Word-level pop captions in the safe area.</p>
          </div>
          <input id="slideshow-captions-toggle" type="checkbox" class="w-5 h-5 accent-accent cursor-pointer">
        </div>

        <!-- Music toggle (slideshow) -->
        <div id="slideshow-music-row" class="mt-4" style="display:none">
          <div class="flex items-center justify-between">
            <div>
              <label class="text-sm font-medium text-dim block">Background music</label>
              <p class="text-xs text-faint mt-0.5">Ducked under narration, only if a track is available.</p>
            </div>
            <input id="slideshow-music-toggle" type="checkbox"
              onchange="onSlideshowMusicToggleChange()" class="w-5 h-5 accent-accent cursor-pointer">
          </div>
          <div id="slideshow-music-provider-row" class="mt-3" style="display:none">
            <select id="slideshow-music-provider-select" onchange="onSlideshowMusicProviderChange(this.value)"
              class="w-full bg-input border border-border rounded-lg px-4 py-2.5 text-white text-sm focus:border-accent focus:outline-none">
              <option value="jamendo">Jamendo</option>
              <option value="local_folder">Local folder</option>
            </select>
            <div id="slideshow-music-folder-row" class="mt-2 flex items-center gap-2" style="display:none">
              <input id="slideshow-music-folder" type="text" readonly placeholder="No folder selected"
                class="flex-1 bg-input border border-border rounded-lg px-4 py-2.5 text-white text-sm">
              <button onclick="browseSlideshowMusicFolder()" type="button"
                class="px-4 py-2.5 bg-hover border border-border rounded-lg text-dim text-sm hover:text-white transition-colors">Browse…</button>
            </div>
          </div>
        </div>

        <!-- Start button -->
```

- [ ] **Step 2: Verify the file is well-formed HTML**

Run: `.venv/bin/python -c "
import re
html = open('docu_studio/gui/web/index.html').read()
for row_id in ['slideshow-transition-row', 'slideshow-vignette-row', 'slideshow-grain-row', 'slideshow-captions-row', 'slideshow-music-row', 'slideshow-music-provider-row', 'slideshow-music-folder-row']:
    assert f'id=\"{row_id}\"' in html, f'{row_id} missing'
print('all rows present')
"`
Expected: `all rows present`

- [ ] **Step 3: Commit**

```bash
git add docu_studio/gui/web/index.html
git commit -m "feat(slideshow): add transition, overlay, caption, and music GUI controls"
```

---

### Task 13: `app.js` — wire the new controls up

**Files:**
- Modify: `docu_studio/gui/web/app.js` (three locations: `startConfig`, a new section near `onMusicProviderChange`/`browseFolder`, and `startRun`)

No automated test — GUI wiring is verified in Task 14's manual click-through (or deferred to the user's manual check per the standing note).

- [ ] **Step 1: Show/hide the new rows in `startConfig`**

Locate this block in `docu_studio/gui/web/app.js`:

```javascript
  _q('slideshow-topic-row').style.display = mode === 'slideshow' ? '' : 'none';
  _q('slideshow-images-row').style.display = mode === 'slideshow' ? '' : 'none';
  _q('slideshow-script-row').style.display = mode === 'slideshow' ? '' : 'none';
  _q('slideshow-aspect-row').style.display = mode === 'slideshow' ? '' : 'none';
  showScreen('config');
}
```

Replace with:

```javascript
  _q('slideshow-topic-row').style.display = mode === 'slideshow' ? '' : 'none';
  _q('slideshow-images-row').style.display = mode === 'slideshow' ? '' : 'none';
  _q('slideshow-script-row').style.display = mode === 'slideshow' ? '' : 'none';
  _q('slideshow-aspect-row').style.display = mode === 'slideshow' ? '' : 'none';
  _q('slideshow-transition-row').style.display = mode === 'slideshow' ? '' : 'none';
  _q('slideshow-vignette-row').style.display = mode === 'slideshow' ? '' : 'none';
  _q('slideshow-grain-row').style.display = mode === 'slideshow' ? '' : 'none';
  _q('slideshow-captions-row').style.display = mode === 'slideshow' ? '' : 'none';
  _q('slideshow-music-row').style.display = mode === 'slideshow' ? '' : 'none';
  onSlideshowMusicToggleChange();
  showScreen('config');
}
```

- [ ] **Step 2: Add the new wiring functions**

Locate this block in `docu_studio/gui/web/app.js`:

```javascript
function onMusicProviderChange(provider) {
  _q('jamendo-key-row').style.display = provider === 'jamendo' ? '' : 'none';
}
```

Add immediately after it:

```javascript

function onSlideshowMusicToggleChange() {
  const on = _q('slideshow-music-toggle').checked;
  _q('slideshow-music-provider-row').style.display = on ? '' : 'none';
  if (on) onSlideshowMusicProviderChange(_q('slideshow-music-provider-select').value);
}

function onSlideshowMusicProviderChange(provider) {
  _q('slideshow-music-folder-row').style.display = provider === 'local_folder' ? '' : 'none';
}

async function browseSlideshowMusicFolder() {
  const path = await window.pywebview.api.browse_folder();
  if (path) _q('slideshow-music-folder').value = path;
}
```

- [ ] **Step 3: Add the new fields to the `start_slideshow_run` payload**

Locate this block in `docu_studio/gui/web/app.js`:

```javascript
    const res = await window.pywebview.api.start_slideshow_run({
      script_text: scriptText,
      image_paths: _slideshowImages,
      aspect_ratio: _q('slideshow-aspect-select').value,
    });
```

Replace with:

```javascript
    const res = await window.pywebview.api.start_slideshow_run({
      script_text: scriptText,
      image_paths: _slideshowImages,
      aspect_ratio: _q('slideshow-aspect-select').value,
      transition: _q('slideshow-transition-select').value,
      vignette: _q('slideshow-vignette-toggle').checked,
      grain: _q('slideshow-grain-toggle').checked,
      captions: _q('slideshow-captions-toggle').checked,
      music_enabled: _q('slideshow-music-toggle').checked,
      music_provider: _q('slideshow-music-provider-select').value,
      music_folder: _q('slideshow-music-folder').value,
    });
```

- [ ] **Step 4: Verify the file has no syntax errors**

Run: `.venv/bin/python -c "
import subprocess
result = subprocess.run(['node', '--check', 'docu_studio/gui/web/app.js'], capture_output=True, text=True)
print(result.returncode, result.stderr)
" 2>&1 || echo "node not available — falling back to a manual read-through, see Step 5"`
Expected: `0 ` (exit code 0, no stderr) if `node` is installed; otherwise proceed to Step 5

- [ ] **Step 5: If `node` isn't available, manually re-read the three edited regions**

Confirm: `startConfig`'s new lines are inside the function body (before its closing `}`), the two new functions and `browseSlideshowMusicFolder` are top-level (not nested inside another function), and the `start_slideshow_run` payload object's new keys are separated by commas with no trailing comma issues.

- [ ] **Step 6: Commit**

```bash
git add docu_studio/gui/web/app.js
git commit -m "feat(slideshow): wire Phase 3 GUI controls to start_slideshow_run"
```

---

### Task 14: Real end-to-end verification + final report

**Files:** none (verification only)

This task has no code changes. It runs the full unit suite, then exercises the real pipeline end to end twice (all Phase 3 features on, then all off), and personally inspects the output.

- [ ] **Step 1: Run the full unit suite**

Run: `.venv/bin/python -m pytest -q --continue-on-collection-errors`
Expected: baseline 24 failed / 1 error unchanged, passed count = 512 + (all Phase 3 tests added across Tasks 1-10)

- [ ] **Step 2: All-on real run**

Using the real GUI if the environment allows a manual click-through now (topic input is not used by Slideshow; instead: pick 3+ local images via "Add images", enter or generate a script, aspect ratio 9:16, transition = Crossfade, Vignette on, Grain on, Captions on, Music on with a local folder pointed at a directory containing at least one `.mp3`), click Start. If the environment still blocks synthetic input into QtWebEngine (as in Phases 1-2 and as re-confirmed at the start of this phase), drive the same path directly through Python instead — construct a `SlideshowRunner` with `transition="crossfade", vignette=True, grain=True, captions=True, music_enabled=True, music_provider="local_folder", music_folder=<a real folder with an mp3>` and a real TTS provider (gTTS needs no API key), call `.run()` synchronously, and let it finish.

- [ ] **Step 3: Personally inspect the all-on output**

Run: `.venv/bin/python -c "
from docu_studio.slideshow.slideshow_ffmpeg import SlideshowFFmpeg
f = SlideshowFFmpeg()
print('duration:', f.get_duration('<path to slideshow_final.mp4 from step 2>'))
"`

Then extract and view frames at the crossfade boundary and confirm by eye:
- No visible SAR distortion or stretched/squashed frames at the transition boundary (extract with `ffmpeg -ss <boundary_time> -i slideshow_final.mp4 -frames:v 1 boundary.png` and open `boundary.png`).
- Captions are visible, legible, and roughly time-aligned with the narration audio (spot-check by playing the video or extracting a frame partway through a sentence and confirming the caption text matches what should be spoken around that timestamp).
- Music is audible under the narration and clearly ducked (quieter) rather than overpowering — spot-check by ear.
- Vignette/grain are visible but subtle, not distracting.

- [ ] **Step 4: All-off real run**

Repeat Step 2 with all Phase 3 options at their defaults (`transition="cut"`, `vignette=False`, `grain=False`, `captions=False`, `music_enabled=False`) — equivalent to a plain Phase 1/2 call.

- [ ] **Step 5: Confirm the all-off output matches Phase 1/2 behavior**

Run: `.venv/bin/python -c "
from docu_studio.slideshow.slideshow_ffmpeg import SlideshowFFmpeg
f = SlideshowFFmpeg()
print('has_audio:', f.has_audio_stream('<path to the all-off slideshow_final.mp4>'))
"`
Expected: `has_audio: True` (narration only, no music-mix artifacts), and visually the video has hard cuts with no vignette/grain/caption overlay — confirm by extracting one frame and viewing it.

- [ ] **Step 6: Write the final phase report**

No file to create — report directly to the user in this session, covering (per the standing handoff format from Phases 1-2): commits list (`git log --oneline` since the branch point), what was verified by eyes vs. logs only, before/after test counts, any bugs found/fixed during the real runs, GUI click-through status (verified live, or still deferred to the user with the specific blocker reconfirmed), and what's left open for a future session — explicitly including the shared-code extraction with `shorts/` that has now been deliberately deferred across all three phases, since this is the closing report for the Slideshow feature as a whole.
