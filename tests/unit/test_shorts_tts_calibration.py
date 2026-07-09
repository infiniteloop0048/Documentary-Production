"""Unit tests for shorts_tts_calibration: persisted per-(provider, voice) WPM."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from docu_studio.shorts.shorts_tts_calibration import (
    CALIBRATION_MAX_WPM,
    CALIBRATION_MIN_WPM,
    calibration_key,
    get_wpm,
    load_calibration,
    record_measurement,
)


def _patched(tmp_path: Path):
    return patch("docu_studio.shorts.shorts_tts_calibration.config_dir", return_value=tmp_path)


class TestCalibrationKey:
    def test_key_combines_provider_and_voice(self) -> None:
        assert calibration_key("elevenlabs", "Rachel") == "elevenlabs:Rachel"


class TestGetWpm:
    def test_default_path_when_no_calibration_exists(self, tmp_path: Path) -> None:
        with _patched(tmp_path):
            assert get_wpm("elevenlabs", "Rachel", default=170.0) == 170.0

    def test_returns_stored_value_after_measurement(self, tmp_path: Path) -> None:
        with _patched(tmp_path):
            record_measurement("elevenlabs", "Rachel", word_count=100, measured_duration_seconds=50.0)
            assert get_wpm("elevenlabs", "Rachel", default=170.0) == 120.0

    def test_different_voice_keys_are_independent(self, tmp_path: Path) -> None:
        with _patched(tmp_path):
            record_measurement("elevenlabs", "Rachel", word_count=100, measured_duration_seconds=50.0)
            assert get_wpm("elevenlabs", "Bella", default=170.0) == 170.0


class TestRecordMeasurement:
    def test_round_trip_persists_across_loads(self, tmp_path: Path) -> None:
        with _patched(tmp_path):
            record_measurement("deepgram", "aura-asteria-en", word_count=130, measured_duration_seconds=60.0)
            data = load_calibration()
        assert data[calibration_key("deepgram", "aura-asteria-en")] == 130.0

    def test_returns_unsmoothed_measured_wpm(self, tmp_path: Path) -> None:
        with _patched(tmp_path):
            measured = record_measurement(
                "deepgram", "aura-asteria-en", word_count=130, measured_duration_seconds=60.0
            )
        assert measured == 130.0

    def test_rolling_average_blends_with_previous_measurement(self, tmp_path: Path) -> None:
        with _patched(tmp_path):
            record_measurement("gtts", "default", word_count=100, measured_duration_seconds=60.0)  # 100 wpm
            record_measurement("gtts", "default", word_count=200, measured_duration_seconds=60.0)  # 200 wpm
            stored = get_wpm("gtts", "default", default=170.0)
        # EMA(alpha=0.3): 0.3*200 + 0.7*100 = 130, strictly between the two raw measurements
        assert 100.0 < stored < 200.0

    def test_clamps_to_max_wpm(self, tmp_path: Path) -> None:
        with _patched(tmp_path):
            record_measurement("fast_voice", "x", word_count=500, measured_duration_seconds=60.0)  # 500 wpm
            stored = get_wpm("fast_voice", "x", default=170.0)
        assert stored == CALIBRATION_MAX_WPM

    def test_clamps_to_min_wpm(self, tmp_path: Path) -> None:
        with _patched(tmp_path):
            record_measurement("slow_voice", "x", word_count=10, measured_duration_seconds=60.0)  # 10 wpm
            stored = get_wpm("slow_voice", "x", default=170.0)
        assert stored == CALIBRATION_MIN_WPM

    def test_zero_duration_is_a_no_op(self, tmp_path: Path) -> None:
        with _patched(tmp_path):
            measured = record_measurement("p", "v", word_count=50, measured_duration_seconds=0.0)
            data = load_calibration()
        assert measured == 0.0
        assert data == {}

    def test_zero_word_count_is_a_no_op(self, tmp_path: Path) -> None:
        with _patched(tmp_path):
            measured = record_measurement("p", "v", word_count=0, measured_duration_seconds=30.0)
            data = load_calibration()
        assert measured == 0.0
        assert data == {}


class TestLoadCalibration:
    def test_returns_empty_dict_when_no_file(self, tmp_path: Path) -> None:
        with _patched(tmp_path):
            assert load_calibration() == {}

    def test_returns_empty_dict_on_corrupt_file(self, tmp_path: Path) -> None:
        (tmp_path / "shorts_tts_calibration.json").write_text("not json", encoding="utf-8")
        with _patched(tmp_path):
            assert load_calibration() == {}
