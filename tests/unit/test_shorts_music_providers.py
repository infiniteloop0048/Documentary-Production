"""Unit tests for the Shorts music-provider abstraction: Jamendo search/fetch
parsing, cache-path naming, and the jamendo → local → none fallback chain.
No real network access — requests.get is always mocked."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from docu_studio.shorts.music_library import MusicTrack
from docu_studio.shorts.music_providers import (
    JamendoMusicProvider,
    LocalMusicProvider,
    TrackCandidate,
    resolve_music_track,
    safe_cache_filename,
)

_JAMENDO_PAYLOAD = {
    "results": [
        {
            "name": "Epic Battle Theme",
            "duration": 180,
            "audiodownload": "https://prod-1.jamendo.com/track/epic-battle.mp3",
        },
        {
            "name": "Calm Waters",
            "duration": 210,
            "audiodownload": "https://prod-1.jamendo.com/track/calm-waters.mp3",
        },
    ]
}


class TestSafeCacheFilename:
    def test_strips_unsafe_characters(self) -> None:
        name = safe_cache_filename("Epic Battle! Theme (Remix)")
        assert name.endswith(".mp3")
        stem = name[: -len(".mp3")]
        assert all(c.isalnum() or c == "_" for c in stem)

    def test_empty_title_still_produces_a_name(self) -> None:
        assert safe_cache_filename("") == "track.mp3"


class TestJamendoSearch:
    def test_missing_client_id_returns_empty_without_http_call(self) -> None:
        provider = JamendoMusicProvider(client_id="")
        with patch("docu_studio.shorts.music_providers.requests.get") as mock_get:
            result = provider.search("epic", max_duration=20.0)
        mock_get.assert_not_called()
        assert result == []

    def test_parses_mocked_payload_into_track_candidates(self) -> None:
        provider = JamendoMusicProvider(client_id="fake-client-id")
        with patch("docu_studio.shorts.music_providers.requests.get") as mock_get:
            mock_get.return_value = MagicMock(
                status_code=200, json=lambda: _JAMENDO_PAYLOAD,
            )
            candidates = provider.search("epic", max_duration=20.0)

        assert len(candidates) == 2
        assert candidates[0] == TrackCandidate(
            title="Epic Battle Theme",
            duration=180.0,
            download_url="https://prod-1.jamendo.com/track/epic-battle.mp3",
            bpm=None,
            source="jamendo",
        )

        params = mock_get.call_args.kwargs["params"]
        assert params["client_id"] == "fake-client-id"
        assert params["tags"] == "epic"

    def test_network_error_returns_empty_list(self) -> None:
        provider = JamendoMusicProvider(client_id="fake-client-id")
        with patch(
            "docu_studio.shorts.music_providers.requests.get",
            side_effect=ConnectionError("boom"),
        ):
            result = provider.search("epic", max_duration=20.0)
        assert result == []

    def test_zero_results_returns_empty_list(self) -> None:
        provider = JamendoMusicProvider(client_id="fake-client-id")
        with patch("docu_studio.shorts.music_providers.requests.get") as mock_get:
            mock_get.return_value = MagicMock(status_code=200, json=lambda: {"results": []})
            result = provider.search("epic", max_duration=20.0)
        assert result == []

    def test_filters_out_tracks_with_empty_audiodownload(self) -> None:
        """Real Jamendo API responses mix downloadable tracks (audiodownload
        populated, audiodownload_allowed=True) with tracks the artist has
        disabled downloads for (audiodownload="", audiodownload_allowed=False,
        streaming-only via `audio`) — both shapes come back with the
        `audiodownload` key present, so a bare `item["audiodownload"]` read
        used to let the empty string through and crash fetch() with
        "Invalid URL '': No scheme supplied"."""
        payload = {
            "results": [
                {
                    "name": "Musical Appendix No.2",
                    "duration": 180,
                    "audiodownload": "https://prod-1.storage.jamendo.com/download/track/2065241/mp31/",
                    "audiodownload_allowed": True,
                    "audio": "https://prod-1.storage.jamendo.com/?trackid=2065241&format=mp31",
                },
                {
                    "name": "Mountain King",
                    "duration": 210,
                    "audiodownload": "",
                    "audiodownload_allowed": False,
                    "audio": "https://prod-1.storage.jamendo.com/?trackid=2148681&format=mp31",
                },
                {
                    "name": "CINE INSTRU",
                    "duration": 150,
                    "audiodownload": "https://prod-1.storage.jamendo.com/download/track/2255487/mp31/",
                    "audiodownload_allowed": True,
                    "audio": "https://prod-1.storage.jamendo.com/?trackid=2255487&format=mp31",
                },
            ]
        }
        provider = JamendoMusicProvider(client_id="fake-client-id")
        with patch("docu_studio.shorts.music_providers.requests.get") as mock_get:
            mock_get.return_value = MagicMock(status_code=200, json=lambda: payload)
            candidates = provider.search("cinematic", max_duration=20.0)

        assert len(candidates) == 2
        assert {c.title for c in candidates} == {"Musical Appendix No.2", "CINE INSTRU"}
        assert all(c.download_url for c in candidates)

    def test_missing_audiodownload_key_is_also_filtered(self) -> None:
        payload = {"results": [{"name": "No Download Field", "duration": 120}]}
        provider = JamendoMusicProvider(client_id="fake-client-id")
        with patch("docu_studio.shorts.music_providers.requests.get") as mock_get:
            mock_get.return_value = MagicMock(status_code=200, json=lambda: payload)
            result = provider.search("epic", max_duration=20.0)
        assert result == []


class TestJamendoFetch:
    def test_downloads_and_caches_by_safe_filename(self, tmp_path: Path) -> None:
        provider = JamendoMusicProvider(client_id="fake-client-id")
        candidate = TrackCandidate(
            title="Epic Battle Theme", duration=180.0,
            download_url="https://prod-1.jamendo.com/track/epic-battle.mp3",
            source="jamendo",
        )
        with patch("docu_studio.shorts.music_providers.music_cache_dir", return_value=tmp_path):
            with patch("docu_studio.shorts.music_providers.requests.get") as mock_get:
                mock_get.return_value = MagicMock(status_code=200, content=b"fake-mp3-bytes")
                path = provider.fetch(candidate)

        assert Path(path).exists()
        assert Path(path).read_bytes() == b"fake-mp3-bytes"
        assert Path(path).parent == tmp_path

    def test_skips_redownload_when_cache_file_already_exists(self, tmp_path: Path) -> None:
        provider = JamendoMusicProvider(client_id="fake-client-id")
        candidate = TrackCandidate(
            title="Epic Battle Theme", duration=180.0,
            download_url="https://prod-1.jamendo.com/track/epic-battle.mp3",
            source="jamendo",
        )
        cached = tmp_path / safe_cache_filename(candidate.title)
        cached.write_bytes(b"already-here")

        with patch("docu_studio.shorts.music_providers.music_cache_dir", return_value=tmp_path):
            with patch("docu_studio.shorts.music_providers.requests.get") as mock_get:
                path = provider.fetch(candidate)

        mock_get.assert_not_called()
        assert Path(path).read_bytes() == b"already-here"


class TestResolveMusicTrackFallbackChain:
    def test_uses_jamendo_when_it_returns_a_usable_candidate(self, tmp_path: Path) -> None:
        with patch.object(
            JamendoMusicProvider, "search",
            return_value=[TrackCandidate(
                title="Epic Battle Theme", duration=180.0,
                download_url="https://x/epic.mp3", source="jamendo",
            )],
        ):
            with patch.object(JamendoMusicProvider, "fetch", return_value="/cache/epic.mp3"):
                with patch.object(LocalMusicProvider, "search") as local_search:
                    result = resolve_music_track(
                        "jamendo", mood="epic", max_duration=20.0,
                        jamendo_client_id="fake-id",
                    )
        local_search.assert_not_called()
        assert result == ("/cache/epic.mp3", "Epic Battle Theme", None)

    def test_falls_back_to_local_when_jamendo_search_fails(self) -> None:
        local_track = MusicTrack(filename="calm.mp3", mood="calm", bpm=90)
        with patch.object(JamendoMusicProvider, "search", return_value=[]):
            with patch(
                "docu_studio.shorts.music_providers.select_music_track",
                return_value=local_track,
            ):
                result = resolve_music_track(
                    "jamendo", mood="epic", max_duration=20.0,
                    jamendo_client_id="fake-id",
                )
        assert result is not None
        path, label, bpm = result
        assert path.endswith("calm.mp3")
        assert bpm == 90

    def test_falls_back_to_local_when_jamendo_fetch_raises(self) -> None:
        local_track = MusicTrack(filename="calm.mp3", mood="calm", bpm=90)
        with patch.object(
            JamendoMusicProvider, "search",
            return_value=[TrackCandidate(
                title="Epic Battle Theme", duration=180.0,
                download_url="https://x/epic.mp3", source="jamendo",
            )],
        ):
            with patch.object(JamendoMusicProvider, "fetch", side_effect=ConnectionError("boom")):
                with patch(
                    "docu_studio.shorts.music_providers.select_music_track",
                    return_value=local_track,
                ):
                    result = resolve_music_track(
                        "jamendo", mood="epic", max_duration=20.0,
                        jamendo_client_id="fake-id",
                    )
        assert result is not None
        assert result[0].endswith("calm.mp3")
        assert result[2] == 90

    def test_returns_none_when_nothing_available_anywhere(self) -> None:
        with patch.object(JamendoMusicProvider, "search", return_value=[]):
            with patch(
                "docu_studio.shorts.music_providers.select_music_track", return_value=None,
            ):
                result = resolve_music_track(
                    "jamendo", mood="epic", max_duration=20.0,
                    jamendo_client_id="fake-id",
                )
        assert result is None

    def test_local_provider_selected_directly_never_touches_jamendo(self) -> None:
        local_track = MusicTrack(filename="calm.mp3", mood="calm", bpm=90)
        with patch.object(JamendoMusicProvider, "search") as jamendo_search:
            with patch(
                "docu_studio.shorts.music_providers.select_music_track",
                return_value=local_track,
            ):
                result = resolve_music_track("local", mood="epic", max_duration=20.0)
        jamendo_search.assert_not_called()
        assert result is not None
        assert result[0].endswith("calm.mp3")
        assert result[2] == 90
