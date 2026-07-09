"""Unit tests for librosa-based beat detection — librosa itself is mocked so
these tests never touch real audio or the real librosa import."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from docu_studio.shorts.shorts_beat_detection import detect_beats_librosa


class TestDetectBeatsLibrosa:
    def test_returns_beat_times_from_mocked_librosa(self) -> None:
        mock_librosa = MagicMock()
        mock_librosa.load.return_value = ("fake_y", 22050)
        mock_librosa.beat.beat_track.return_value = (120.0, [10, 20, 30, 40])
        mock_librosa.frames_to_time.return_value = [0.5, 1.0, 1.5, 2.0]

        with patch.dict("sys.modules", {"librosa": mock_librosa}):
            result = detect_beats_librosa("/fake/track.mp3")

        assert result == [0.5, 1.0, 1.5, 2.0]
        mock_librosa.load.assert_called_once_with("/fake/track.mp3", sr=None, mono=True)

    def test_returns_none_when_librosa_import_fails(self) -> None:
        with patch.dict("sys.modules", {"librosa": None}):
            result = detect_beats_librosa("/fake/track.mp3")
        assert result is None

    def test_returns_none_when_fewer_than_two_beats_detected(self) -> None:
        mock_librosa = MagicMock()
        mock_librosa.load.return_value = ("fake_y", 22050)
        mock_librosa.beat.beat_track.return_value = (120.0, [10])
        mock_librosa.frames_to_time.return_value = [0.5]

        with patch.dict("sys.modules", {"librosa": mock_librosa}):
            result = detect_beats_librosa("/fake/track.mp3")
        assert result is None

    def test_returns_none_when_load_raises(self) -> None:
        mock_librosa = MagicMock()
        mock_librosa.load.side_effect = RuntimeError("bad file")

        with patch.dict("sys.modules", {"librosa": mock_librosa}):
            result = detect_beats_librosa("/fake/track.mp3")
        assert result is None

    def test_beat_times_are_rounded_to_two_decimals(self) -> None:
        mock_librosa = MagicMock()
        mock_librosa.load.return_value = ("fake_y", 22050)
        mock_librosa.beat.beat_track.return_value = (120.0, [1, 2])
        mock_librosa.frames_to_time.return_value = [0.123456, 0.654321]

        with patch.dict("sys.modules", {"librosa": mock_librosa}):
            result = detect_beats_librosa("/fake/track.mp3")
        assert result == [0.12, 0.65]
