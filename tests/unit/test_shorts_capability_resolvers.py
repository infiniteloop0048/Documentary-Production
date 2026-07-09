"""Unit tests for the Tier-3 estimated word-timing algorithm."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from docu_studio.shorts.capability_resolvers import (
    WordTiming,
    estimate_word_timestamps,
    get_word_timestamps,
    resolve_beat_grid,
)


class TestEstimateWordTimestamps:
    def test_empty_script_returns_empty(self) -> None:
        assert estimate_word_timestamps("", 10.0) == []

    def test_zero_duration_returns_empty(self) -> None:
        assert estimate_word_timestamps("hello world", 0.0) == []

    def test_timestamps_span_the_full_duration(self) -> None:
        timestamps = estimate_word_timestamps("one two three four five", 10.0)
        assert timestamps[0].start == pytest.approx(0.0)
        assert timestamps[-1].end == pytest.approx(10.0, abs=1e-6)

    def test_timestamps_are_monotonically_increasing(self) -> None:
        timestamps = estimate_word_timestamps(
            "a short burst of narration with several words in it", 8.0
        )
        for a, b in zip(timestamps, timestamps[1:]):
            assert a.end == pytest.approx(b.start, abs=1e-9)
            assert b.start >= a.start

    def test_longer_words_get_more_time(self) -> None:
        timestamps = estimate_word_timestamps("a extraordinarily", 3.0)
        short_span = timestamps[0].end - timestamps[0].start
        long_span = timestamps[1].end - timestamps[1].start
        assert long_span > short_span

    def test_word_field_matches_input_order(self) -> None:
        timestamps = estimate_word_timestamps("red green blue", 3.0)
        assert [t.word for t in timestamps] == ["red", "green", "blue"]

    def test_returns_word_timing_instances(self) -> None:
        timestamps = estimate_word_timestamps("hi", 1.0)
        assert isinstance(timestamps[0], WordTiming)


class TestGetWordTimestamps:
    def test_falls_back_to_tier3_when_adapter_has_no_native_timestamps(self) -> None:
        tts = MagicMock(spec=["synthesize"])  # no get_word_timestamps attribute
        with patch(
            "docu_studio.shorts.capability_resolvers.FFmpegWrapper"
        ) as ffmpeg_cls:
            ffmpeg_cls.return_value.get_duration.return_value = 5.0
            timestamps, tier = get_word_timestamps("audio.mp3", "hello world", tts)
        assert tier == "tier3_estimated"
        assert timestamps[-1].end == 5.0

    def test_uses_tier1_when_adapter_exposes_native_timestamps(self) -> None:
        tts = MagicMock()
        tts.get_word_timestamps.return_value = [("hi", 0.0, 0.5), ("there", 0.5, 1.0)]
        timestamps, tier = get_word_timestamps("audio.mp3", "hi there", tts)
        assert tier == "tier1_native"
        assert [t.word for t in timestamps] == ["hi", "there"]

    def test_tier1_exception_falls_back_to_tier3(self) -> None:
        tts = MagicMock()
        tts.get_word_timestamps.side_effect = RuntimeError("boom")
        with patch(
            "docu_studio.shorts.capability_resolvers.FFmpegWrapper"
        ) as ffmpeg_cls:
            ffmpeg_cls.return_value.get_duration.return_value = 2.0
            timestamps, tier = get_word_timestamps("audio.mp3", "hi there", tts)
        assert tier == "tier3_estimated"

    def test_tier1_empty_result_falls_back_to_tier3(self) -> None:
        tts = MagicMock()
        tts.get_word_timestamps.return_value = []
        with patch(
            "docu_studio.shorts.capability_resolvers.FFmpegWrapper"
        ) as ffmpeg_cls:
            ffmpeg_cls.return_value.get_duration.return_value = 3.0
            timestamps, tier = get_word_timestamps("audio.mp3", "hi there", tts)
        assert tier == "tier3_estimated"


class TestResolveBeatGrid:
    def test_uses_librosa_tier_when_it_succeeds(self) -> None:
        with patch(
            "docu_studio.shorts.shorts_beat_detection.detect_beats_librosa",
            return_value=[0.5, 1.0, 1.5, 2.0],
        ):
            grid, tier = resolve_beat_grid("/track.mp3", bpm=None, duration=10.0)
        assert tier == "librosa"
        assert grid == [0.5, 1.0, 1.5, 2.0]

    def test_falls_back_to_bpm_metadata_when_librosa_returns_none(self) -> None:
        with patch(
            "docu_studio.shorts.shorts_beat_detection.detect_beats_librosa",
            return_value=None,
        ):
            grid, tier = resolve_beat_grid("/track.mp3", bpm=120, duration=2.0)
        assert tier == "bpm_metadata"
        # 120 BPM -> 0.5s interval; 2.0s duration -> beats at 0.0, 0.5, 1.0, 1.5, 2.0
        assert grid == [0.0, 0.5, 1.0, 1.5, 2.0]

    def test_falls_back_to_none_tier_when_no_bpm_and_librosa_fails(self) -> None:
        with patch(
            "docu_studio.shorts.shorts_beat_detection.detect_beats_librosa",
            return_value=None,
        ):
            grid, tier = resolve_beat_grid("/track.mp3", bpm=None, duration=10.0)
        assert tier == "none"
        assert grid is None

    def test_bpm_of_zero_or_negative_is_treated_as_absent(self) -> None:
        with patch(
            "docu_studio.shorts.shorts_beat_detection.detect_beats_librosa",
            return_value=None,
        ):
            grid, tier = resolve_beat_grid("/track.mp3", bpm=0, duration=10.0)
        assert tier == "none"
        assert grid is None

    def test_librosa_exception_falls_through_to_bpm_tier(self) -> None:
        with patch(
            "docu_studio.shorts.shorts_beat_detection.detect_beats_librosa",
            side_effect=RuntimeError("boom"),
        ):
            grid, tier = resolve_beat_grid("/track.mp3", bpm=100, duration=1.2)
        assert tier == "bpm_metadata"
        assert grid is not None
