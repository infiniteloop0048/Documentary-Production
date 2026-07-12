"""Unit tests for the shared Jamendo music-provider client + cache
primitives: search/fetch parsing, cache-path naming, cache-hit/cache-miss
behavior, empty-client-id short-circuit, and malformed-response handling.
No real network access — requests.get is always mocked.

Union of the Jamendo-related test classes formerly duplicated across
test_shorts_music_providers.py and test_slideshow_music.py (deduped where
both asserted the same behavior). Each per-feature test file keeps its own
local-provider tests and resolve_music_track() fallback-chain tests, now
importing JamendoMusicProvider/TrackCandidate/music_cache_dir/
safe_cache_filename from here.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from docu_studio.common.music_jamendo import (
    JamendoMusicProvider,
    TrackCandidate,
    music_cache_dir,
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


class TestMusicCacheDir:
    def test_uses_unified_music_cache_dirname(self) -> None:
        assert music_cache_dir().name == "music_cache"


class TestSafeCacheFilename:
    def test_strips_unsafe_characters(self) -> None:
        name = safe_cache_filename("Epic Battle! Theme (Remix)")
        assert name.endswith(".mp3")
        stem = name[: -len(".mp3")]
        assert all(c.isalnum() or c == "_" for c in stem)

    def test_slugifies_title(self) -> None:
        assert safe_cache_filename("Cinematic Piano #1!") == "cinematic_piano_1.mp3"

    def test_empty_title_still_produces_a_name(self) -> None:
        assert safe_cache_filename("") == "track.mp3"


class TestJamendoSearch:
    def test_missing_client_id_returns_empty_without_http_call(self) -> None:
        provider = JamendoMusicProvider(client_id="")
        with patch("docu_studio.common.music_jamendo.requests.get") as mock_get:
            result = provider.search("epic", max_duration=20.0)
        mock_get.assert_not_called()
        assert result == []

    def test_parses_mocked_payload_into_track_candidates(self) -> None:
        provider = JamendoMusicProvider(client_id="fake-client-id")
        with patch("docu_studio.common.music_jamendo.requests.get") as mock_get:
            mock_get.return_value = MagicMock(
                status_code=200, json=lambda: _JAMENDO_PAYLOAD,
            )
            candidates = provider.search("epic", max_duration=20.0)

        assert len(candidates) == 2
        assert candidates[0] == TrackCandidate(
            title="Epic Battle Theme",
            duration=180.0,
            download_url="https://prod-1.jamendo.com/track/epic-battle.mp3",
            source="jamendo",
        )

        params = mock_get.call_args.kwargs["params"]
        assert params["client_id"] == "fake-client-id"
        assert params["tags"] == "epic"

    def test_network_error_returns_empty_list(self) -> None:
        provider = JamendoMusicProvider(client_id="fake-client-id")
        with patch(
            "docu_studio.common.music_jamendo.requests.get",
            side_effect=ConnectionError("boom"),
        ):
            result = provider.search("epic", max_duration=20.0)
        assert result == []

    def test_zero_results_returns_empty_list(self) -> None:
        provider = JamendoMusicProvider(client_id="fake-client-id")
        with patch("docu_studio.common.music_jamendo.requests.get") as mock_get:
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
        with patch("docu_studio.common.music_jamendo.requests.get") as mock_get:
            mock_get.return_value = MagicMock(status_code=200, json=lambda: payload)
            candidates = provider.search("cinematic", max_duration=20.0)

        assert len(candidates) == 2
        assert {c.title for c in candidates} == {"Musical Appendix No.2", "CINE INSTRU"}
        assert all(c.download_url for c in candidates)

    def test_missing_audiodownload_key_is_also_filtered(self) -> None:
        payload = {"results": [{"name": "No Download Field", "duration": 120}]}
        provider = JamendoMusicProvider(client_id="fake-client-id")
        with patch("docu_studio.common.music_jamendo.requests.get") as mock_get:
            mock_get.return_value = MagicMock(status_code=200, json=lambda: payload)
            result = provider.search("epic", max_duration=20.0)
        assert result == []

    def test_search_request_failure_returns_empty(self) -> None:
        provider = JamendoMusicProvider(client_id="fake-id")
        with patch("docu_studio.common.music_jamendo.requests.get", side_effect=Exception("boom")):
            assert provider.search("cinematic", 10.0) == []

    def test_malformed_result_item_is_skipped(self) -> None:
        """A result item missing required keys (name/duration) after passing
        the audiodownload check must be skipped, not crash the whole search."""
        payload = {
            "results": [
                {"audiodownload": "https://example.com/t.mp3"},  # missing name/duration
                {
                    "name": "Has Download",
                    "duration": 90,
                    "audiodownload": "https://example.com/t2.mp3",
                },
            ]
        }
        provider = JamendoMusicProvider(client_id="fake-id")
        with patch("docu_studio.common.music_jamendo.requests.get") as mock_get:
            mock_get.return_value = MagicMock(status_code=200, json=lambda: payload)
            candidates = provider.search("cinematic", 10.0)
        assert len(candidates) == 1
        assert candidates[0].title == "Has Download"


class TestJamendoFetch:
    def test_downloads_and_caches_by_safe_filename(self, tmp_path: Path) -> None:
        provider = JamendoMusicProvider(client_id="fake-client-id")
        candidate = TrackCandidate(
            title="Epic Battle Theme", duration=180.0,
            download_url="https://prod-1.jamendo.com/track/epic-battle.mp3",
            source="jamendo",
        )
        with patch("docu_studio.common.music_jamendo.music_cache_dir", return_value=tmp_path):
            with patch("docu_studio.common.music_jamendo.requests.get") as mock_get:
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

        with patch("docu_studio.common.music_jamendo.music_cache_dir", return_value=tmp_path):
            with patch("docu_studio.common.music_jamendo.requests.get") as mock_get:
                path = provider.fetch(candidate)

        mock_get.assert_not_called()
        assert Path(path).read_bytes() == b"already-here"
