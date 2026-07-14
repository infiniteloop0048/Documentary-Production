"""Unit tests for GTTSAdapter's silence-trim + concat pipeline.

Uses real ffmpeg on tiny synthetic (lavfi-generated) audio fixtures instead
of mocking subprocess.run — the bug this adapter fixes is a silence-trimming
correctness bug, not a command-construction bug, so mocking ffmpeg away would
test the wrong thing. Only the network-calling gTTS object is stubbed; no
real network calls happen in this suite.
"""
from __future__ import annotations

import subprocess
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from docu_studio.adapters.tts.gtts_adapter import (
    _SILENCE_PAD_SECONDS,
    GTTSAdapter,
)

_FFMPEG_TIMEOUT = 15


def _run(cmd: list[str]) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=_FFMPEG_TIMEOUT)
    assert result.returncode == 0, result.stderr


def _make_chunk(
    path: Path,
    lead_silence: float,
    tone_duration: float,
    trail_silence: float,
    fade_out: float = 0.0,
    freq: int = 440,
) -> None:
    """Build a synthetic mono 24kHz MP3: lead_silence + tone (optionally
    fading out over its final `fade_out` seconds) + trail_silence. Mirrors
    the shape of a real gTTS per-request chunk (leading/trailing silence
    around real content)."""
    tone_path = path.with_suffix(".tone.mp3")
    tone_cmd = [
        "ffmpeg", "-y", "-f", "lavfi", "-t", str(tone_duration),
        "-i", f"sine=frequency={freq}:sample_rate=24000",
    ]
    if fade_out > 0:
        fade_start = max(0.0, tone_duration - fade_out)
        tone_cmd += ["-af", f"afade=t=out:st={fade_start}:d={fade_out}"]
    tone_cmd += [str(tone_path)]
    _run(tone_cmd)

    _run([
        "ffmpeg", "-y",
        "-f", "lavfi", "-t", str(lead_silence), "-i", "anullsrc=r=24000:cl=mono",
        "-i", str(tone_path),
        "-f", "lavfi", "-t", str(trail_silence), "-i", "anullsrc=r=24000:cl=mono",
        "-filter_complex", "[0:a][1:a][2:a]concat=n=3:v=0:a=1[out]",
        "-map", "[out]", str(path),
    ])


def _duration(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(path),
        ],
        capture_output=True, text=True, timeout=_FFMPEG_TIMEOUT,
    )
    assert result.returncode == 0, result.stderr
    return float(result.stdout.strip())


def _silence_gaps(path: Path, noise_db: str = "-45dB", min_dur: float = 0.03) -> list[float]:
    """Return the duration (seconds) of every silence run ffmpeg detects."""
    result = subprocess.run(
        [
            "ffmpeg", "-i", str(path),
            "-af", f"silencedetect=noise={noise_db}:d={min_dur}",
            "-f", "null", "-",
        ],
        capture_output=True, text=True, timeout=_FFMPEG_TIMEOUT,
    )
    gaps = []
    for line in result.stderr.splitlines():
        if "silence_duration" in line:
            gaps.append(float(line.strip().split(": ")[-1]))
    return gaps


@pytest.fixture
def adapter() -> GTTSAdapter:
    return GTTSAdapter()


class TestTrimChunk:
    def test_trims_leading_and_trailing_silence_to_small_pad(
        self, adapter: GTTSAdapter, tmp_path: Path
    ) -> None:
        raw = tmp_path / "raw.mp3"
        trimmed = tmp_path / "trimmed.mp3"
        _make_chunk(raw, lead_silence=0.4, tone_duration=1.0, trail_silence=0.4)

        original_duration = _duration(raw)
        adapter._trim_chunk(str(raw), str(trimmed))
        trimmed_duration = _duration(trimmed)

        assert original_duration > 1.7  # sanity: fixture built as expected
        # Trimmed should retain ~tone_duration + 2*pad, well short of the original.
        assert 1.1 <= trimmed_duration <= 1.4
        assert trimmed_duration < original_duration - 0.4

    def test_preserves_fading_tail_ending_in_soft_content(
        self, adapter: GTTSAdapter, tmp_path: Path
    ) -> None:
        """Regression guard: a chunk whose last 250ms fades out (standing in
        for a real soft/nasal consonant's natural decay, e.g. the "...
        coastline" case measured against real gTTS output) must not have
        that decay clipped — only the true silence after it should go."""
        raw = tmp_path / "raw.mp3"
        trimmed = tmp_path / "trimmed.mp3"
        _make_chunk(raw, lead_silence=0.4, tone_duration=1.0, trail_silence=0.4, fade_out=0.25)

        adapter._trim_chunk(str(raw), str(trimmed))
        trimmed_duration = _duration(trimmed)

        # If the fade's decay were clipped as "silence", this would drop well
        # below ~1.0s (tone_duration). Real measurement: ~1.22s.
        assert trimmed_duration >= 1.1
        assert trimmed_duration <= 1.4

    def test_does_not_touch_internal_word_boundary_pauses(
        self, adapter: GTTSAdapter, tmp_path: Path
    ) -> None:
        """A ~40ms internal gap (typical inter-word pause, per real gTTS
        measurements) mid-chunk must survive — only the leading/trailing
        silence runs are targets."""
        raw = tmp_path / "raw.mp3"
        trimmed = tmp_path / "trimmed.mp3"
        tone_a = tmp_path / "tone_a.mp3"
        tone_b = tmp_path / "tone_b.mp3"
        _run(["ffmpeg", "-y", "-f", "lavfi", "-t", "0.5", "-i", "sine=frequency=440:sample_rate=24000", str(tone_a)])
        _run(["ffmpeg", "-y", "-f", "lavfi", "-t", "0.5", "-i", "sine=frequency=660:sample_rate=24000", str(tone_b)])
        # lead(0.3) + tone_a(0.5) + internal_gap(0.04) + tone_b(0.5) + trail(0.3)
        _run([
            "ffmpeg", "-y",
            "-f", "lavfi", "-t", "0.3", "-i", "anullsrc=r=24000:cl=mono",
            "-i", str(tone_a),
            "-f", "lavfi", "-t", "0.04", "-i", "anullsrc=r=24000:cl=mono",
            "-i", str(tone_b),
            "-f", "lavfi", "-t", "0.3", "-i", "anullsrc=r=24000:cl=mono",
            "-filter_complex", "[0:a][1:a][2:a][3:a][4:a]concat=n=5:v=0:a=1[out]",
            "-map", "[out]", str(raw),
        ])

        adapter._trim_chunk(str(raw), str(trimmed))
        gaps = _silence_gaps(trimmed, min_dur=0.02)
        # Expect exactly the leading pad, the untouched internal ~40ms gap,
        # and the trailing pad — the internal gap must not have been merged
        # away or extended.
        internal_gaps = [g for g in gaps if 0.02 <= g <= 0.06]
        assert internal_gaps, f"internal word-boundary gap missing from {gaps}"


class TestConcatChunks:
    def test_concatenates_trimmed_chunks_into_continuous_file(
        self, adapter: GTTSAdapter, tmp_path: Path
    ) -> None:
        chunk_a = tmp_path / "a.mp3"
        chunk_b = tmp_path / "b.mp3"
        _make_chunk(chunk_a, lead_silence=0.08, tone_duration=0.5, trail_silence=0.08)
        _make_chunk(chunk_b, lead_silence=0.08, tone_duration=0.5, trail_silence=0.08, freq=660)

        out = tmp_path / "concat_out.mp3"
        adapter._concat_chunks([chunk_a, chunk_b], str(out))

        expected = _duration(chunk_a) + _duration(chunk_b)
        assert abs(_duration(out) - expected) < 0.1


class TestSynthesizeTrimmedIntegration:
    def test_multi_chunk_narration_collapses_dead_air_gaps(
        self, adapter: GTTSAdapter, tmp_path: Path
    ) -> None:
        """End-to-end: stub gTTS.stream() to yield 3 chunks shaped like real
        measured gTTS output (leading ~0.3s, trailing ~0.25s per chunk) and
        confirm the final file has no gap anywhere near the ~500-700ms dead
        air the naive tts.save() concatenation would have produced."""
        raw_chunks = []
        for i, freq in enumerate([440, 550, 660]):
            p = tmp_path / f"stub_chunk_{i}.mp3"
            _make_chunk(p, lead_silence=0.3, tone_duration=0.8, trail_silence=0.25, freq=freq)
            raw_chunks.append(p.read_bytes())

        fake_tts = MagicMock()
        fake_tts.stream.return_value = iter(raw_chunks)

        output_path = tmp_path / "final.mp3"
        adapter._synthesize_trimmed(fake_tts, str(output_path))

        assert output_path.exists()
        gaps = _silence_gaps(output_path, min_dur=0.05)
        # Naive concatenation of these chunks would produce ~550ms gaps
        # (0.25 trail + 0.3 lead) at each of the 2 internal seams, plus the
        # ~0.3s leading silence at the very start. After trimming, every gap
        # must collapse to roughly 2*pad (~0.16s) or the initial single pad.
        internal_gaps = gaps[1:-1] if len(gaps) > 2 else []
        for g in internal_gaps:
            assert g < 2 * _SILENCE_PAD_SECONDS + 0.15, (
                f"gap {g}s still resembles the pre-fix dead-air seam; gaps={gaps}"
            )

    def test_single_chunk_short_text_still_produces_valid_output(
        self, adapter: GTTSAdapter, tmp_path: Path
    ) -> None:
        p = tmp_path / "only_chunk.mp3"
        _make_chunk(p, lead_silence=0.3, tone_duration=0.6, trail_silence=0.3)

        fake_tts = MagicMock()
        fake_tts.stream.return_value = iter([p.read_bytes()])

        output_path = tmp_path / "final.mp3"
        adapter._synthesize_trimmed(fake_tts, str(output_path))

        assert output_path.exists()
        assert 0.7 <= _duration(output_path) <= 1.0

    def test_no_chunks_raises(self, adapter: GTTSAdapter, tmp_path: Path) -> None:
        fake_tts = MagicMock()
        fake_tts.stream.return_value = iter([])
        with pytest.raises(RuntimeError, match="no audio chunks"):
            adapter._synthesize_trimmed(fake_tts, str(tmp_path / "final.mp3"))


class TestSynthesizeRetryBehavior:
    """Retry/backoff loop around _synthesize_trimmed — pre-existing behavior,
    previously untested (no test file existed for this adapter)."""

    def test_succeeds_after_transient_connection_reset(self, adapter: GTTSAdapter) -> None:
        calls = {"n": 0}

        def flaky_synthesize(tts, output_path) -> None:
            calls["n"] += 1
            if calls["n"] < 2:
                raise ConnectionResetError("reset")
            Path(output_path).write_bytes(b"fake-mp3-bytes")

        with patch("docu_studio.adapters.tts.gtts_adapter.gTTS") as mock_gtts, \
             patch.object(adapter, "_synthesize_trimmed", side_effect=flaky_synthesize), \
             patch.object(adapter._ffmpeg, "get_duration", return_value=3.5), \
             patch("time.sleep") as mock_sleep:
            mock_gtts.return_value = MagicMock()
            duration = adapter.synthesize("some narration text", "/tmp/out.mp3")

        assert duration == 3.5
        assert calls["n"] == 2
        mock_sleep.assert_called_once()

    def test_raises_after_exhausting_all_retries(self, adapter: GTTSAdapter) -> None:
        with patch("docu_studio.adapters.tts.gtts_adapter.gTTS") as mock_gtts, \
             patch.object(
                 adapter, "_synthesize_trimmed",
                 side_effect=ConnectionResetError("still down"),
             ), \
             patch("time.sleep"):
            mock_gtts.return_value = MagicMock()
            with pytest.raises(RuntimeError, match="could not connect after 5 attempts"):
                adapter.synthesize("some narration text", "/tmp/out.mp3")
