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
