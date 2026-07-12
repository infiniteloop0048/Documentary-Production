"""Unit tests for the Shorts music-provider abstraction: LocalMusicProvider
and the jamendo → local → none fallback chain in resolve_music_track(). No
real network access — requests.get is always mocked.

Jamendo search/fetch/cache-naming coverage lives in
test_common_music_jamendo.py (JamendoMusicProvider is now shared, imported
from docu_studio.common.music_jamendo)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from docu_studio.common.music_jamendo import JamendoMusicProvider, TrackCandidate
from docu_studio.shorts.music_library import MusicTrack
from docu_studio.shorts.music_providers import LocalMusicProvider, resolve_music_track


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
