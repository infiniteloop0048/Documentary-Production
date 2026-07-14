"""Unit tests for the adapter-agnostic silence-trim + join utility used to
stitch per-sentence TTS audio (any adapter) into one continuous narration
file without stacking each sentence's own leading/trailing silence into an
audible gap at sentence boundaries.

Uses real ffmpeg on tiny synthetic (lavfi-generated) audio fixtures instead
of mocking subprocess.run — this is a silence-trimming correctness module,
not a command-construction one, so mocking ffmpeg away would test the wrong
thing.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from docu_studio.shorts.shorts_tts_join import (
    SilenceTrimParams,
    concat_audio,
    trim_and_join,
    trim_silence,
)

_FFMPEG_TIMEOUT = 15
_DEFAULT_PARAMS = SilenceTrimParams()


def _run(cmd: list[str]) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=_FFMPEG_TIMEOUT)
    assert result.returncode == 0, result.stderr


def _make_clip(
    path: Path,
    lead_silence: float,
    tone_duration: float,
    trail_silence: float,
    fade_out: float = 0.0,
    freq: int = 440,
) -> None:
    """Build a synthetic mono 24kHz MP3: lead_silence + tone (optionally
    fading out over its final `fade_out` seconds) + trail_silence. Mirrors
    the shape of a real per-sentence TTS clip (leading/trailing silence
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


class TestTrimSilence:
    def test_trims_leading_and_trailing_silence_to_small_pad(self, tmp_path: Path) -> None:
        raw = tmp_path / "raw.mp3"
        trimmed = tmp_path / "trimmed.mp3"
        _make_clip(raw, lead_silence=0.4, tone_duration=1.0, trail_silence=0.4)

        original_duration = _duration(raw)
        trim_silence(str(raw), str(trimmed), _DEFAULT_PARAMS)
        trimmed_duration = _duration(trimmed)

        assert original_duration > 1.7
        assert 1.1 <= trimmed_duration <= 1.4
        assert trimmed_duration < original_duration - 0.4

    def test_preserves_fading_tail_ending_in_soft_content(self, tmp_path: Path) -> None:
        raw = tmp_path / "raw.mp3"
        trimmed = tmp_path / "trimmed.mp3"
        _make_clip(raw, lead_silence=0.4, tone_duration=1.0, trail_silence=0.4, fade_out=0.25)

        trim_silence(str(raw), str(trimmed), _DEFAULT_PARAMS)
        trimmed_duration = _duration(trimmed)

        assert trimmed_duration >= 1.1
        assert trimmed_duration <= 1.4

    def test_does_not_touch_internal_word_boundary_pauses(self, tmp_path: Path) -> None:
        raw = tmp_path / "raw.mp3"
        trimmed = tmp_path / "trimmed.mp3"
        tone_a = tmp_path / "tone_a.mp3"
        tone_b = tmp_path / "tone_b.mp3"
        _run(["ffmpeg", "-y", "-f", "lavfi", "-t", "0.5", "-i", "sine=frequency=440:sample_rate=24000", str(tone_a)])
        _run(["ffmpeg", "-y", "-f", "lavfi", "-t", "0.5", "-i", "sine=frequency=660:sample_rate=24000", str(tone_b)])
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

        trim_silence(str(raw), str(trimmed), _DEFAULT_PARAMS)
        gaps = _silence_gaps(trimmed, min_dur=0.02)
        internal_gaps = [g for g in gaps if 0.02 <= g <= 0.06]
        assert internal_gaps, f"internal word-boundary gap missing from {gaps}"


class TestConcatAudio:
    def test_concatenates_clips_into_continuous_file(self, tmp_path: Path) -> None:
        clip_a = tmp_path / "a.mp3"
        clip_b = tmp_path / "b.mp3"
        _make_clip(clip_a, lead_silence=0.08, tone_duration=0.5, trail_silence=0.08)
        _make_clip(clip_b, lead_silence=0.08, tone_duration=0.5, trail_silence=0.08, freq=660)

        out = tmp_path / "concat_out.mp3"
        concat_audio([clip_a, clip_b], str(out))

        expected = _duration(clip_a) + _duration(clip_b)
        assert abs(_duration(out) - expected) < 0.1


class TestTrimAndJoin:
    def test_multiple_clips_collapse_dead_air_at_every_boundary(self, tmp_path: Path) -> None:
        """3 clips shaped like real per-sentence TTS output (leading ~0.3s,
        trailing ~0.25s each) must join with no gap anywhere near the raw
        ~500-700ms dead air a naive concat would produce."""
        clips = []
        for i, freq in enumerate([440, 550, 660]):
            p = tmp_path / f"clip_{i}.mp3"
            _make_clip(p, lead_silence=0.3, tone_duration=0.8, trail_silence=0.25, freq=freq)
            clips.append(p)

        output_path = tmp_path / "final.mp3"
        trim_and_join(clips, str(output_path), _DEFAULT_PARAMS)

        assert output_path.exists()
        gaps = _silence_gaps(output_path, min_dur=0.05)
        internal_gaps = gaps[1:-1] if len(gaps) > 2 else []
        for g in internal_gaps:
            assert g < 2 * _DEFAULT_PARAMS.pad_seconds + 0.15, (
                f"gap {g}s still resembles the pre-fix dead-air seam; gaps={gaps}"
            )

    def test_single_clip_trims_directly_without_concat_demuxer(self, tmp_path: Path) -> None:
        p = tmp_path / "only_clip.mp3"
        _make_clip(p, lead_silence=0.3, tone_duration=0.6, trail_silence=0.3)

        output_path = tmp_path / "final.mp3"
        trim_and_join([p], str(output_path), _DEFAULT_PARAMS)

        assert output_path.exists()
        assert 0.7 <= _duration(output_path) <= 1.0

    def test_empty_list_raises(self, tmp_path: Path) -> None:
        with pytest.raises(RuntimeError, match="no audio clips"):
            trim_and_join([], str(tmp_path / "final.mp3"), _DEFAULT_PARAMS)

    def test_clips_join_in_given_order_not_sorted_order(self, tmp_path: Path) -> None:
        """Regression guard for the ordering guarantee: trim_and_join must
        preserve the caller's list order exactly — callers (e.g. the
        per-sentence join step) are responsible for passing clips already
        sorted by sentence index, not completion order; this module must not
        silently re-sort or otherwise disturb that order."""
        import numpy as np
        import librosa

        clip_low_freq = tmp_path / "z_clip.mp3"  # filename sorts after b_clip
        clip_high_freq = tmp_path / "b_clip.mp3"
        _make_clip(clip_low_freq, lead_silence=0.05, tone_duration=0.4, trail_silence=0.05, freq=220)
        _make_clip(clip_high_freq, lead_silence=0.05, tone_duration=0.4, trail_silence=0.05, freq=880)

        # Pass in [low_freq (z_clip), high_freq (b_clip)] — the reverse of
        # what alphabetical filename sorting would produce.
        output_path = tmp_path / "final.mp3"
        trim_and_join([clip_low_freq, clip_high_freq], str(output_path), _DEFAULT_PARAMS)

        # If concat_audio (or ffmpeg's concat demuxer) silently reordered by
        # filename, the low-frequency tone would play second, not first.
        # Detect actual playback order via FFT dominant-frequency check on
        # each half of the joined output.
        y, sr = librosa.load(str(output_path), sr=None, mono=True)
        midpoint = len(y) // 2

        def dominant_freq(segment: np.ndarray) -> float:
            spectrum = np.abs(np.fft.rfft(segment))
            freqs = np.fft.rfftfreq(len(segment), d=1.0 / sr)
            return float(freqs[np.argmax(spectrum)])

        first_half_freq = dominant_freq(y[:midpoint])
        second_half_freq = dominant_freq(y[midpoint:])

        assert abs(first_half_freq - 220) < abs(first_half_freq - 880), (
            f"first half's dominant frequency ({first_half_freq}Hz) is closer to 880Hz "
            f"than 220Hz — clips were reordered, not preserved in caller order"
        )
        assert abs(second_half_freq - 880) < abs(second_half_freq - 220)
