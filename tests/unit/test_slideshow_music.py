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
