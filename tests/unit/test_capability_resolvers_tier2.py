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
