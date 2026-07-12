"""Unit tests for slideshow_music: LocalFolderMusicProvider and the jamendo
-> local folder -> none fallback chain in resolve_music_track(). Requests/
filesystem mocked, no network.

Jamendo search/fetch/cache-naming coverage lives in
test_common_music_jamendo.py (JamendoMusicProvider is now shared, imported
from docu_studio.common.music_jamendo)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from docu_studio.common.music_jamendo import TrackCandidate
from docu_studio.slideshow.slideshow_music import (
    LocalFolderMusicProvider,
    resolve_music_track,
)


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
            title="song.mp3", duration=10.0, download_url="", source="local_folder",
            local_path=str(tmp_path / "song.mp3"),
        )
        provider = LocalFolderMusicProvider(str(tmp_path))
        assert provider.fetch(candidate) == str(tmp_path / "song.mp3")

    def test_fetch_without_local_path_raises(self) -> None:
        candidate = TrackCandidate(title="x", duration=10.0, download_url="", source="local_folder")
        provider = LocalFolderMusicProvider("/anywhere")
        with pytest.raises(ValueError, match="local_path"):
            provider.fetch(candidate)

    def test_search_handles_oserror_during_iteration(self, tmp_path: Path) -> None:
        provider = LocalFolderMusicProvider(str(tmp_path))
        with patch.object(Path, "iterdir", side_effect=OSError("permission denied")):
            assert provider.search("cinematic", 10.0) == []


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
