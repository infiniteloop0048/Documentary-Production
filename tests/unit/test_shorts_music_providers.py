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
                        "jamendo", moods=["epic"], max_duration=20.0,
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
                    "jamendo", moods=["epic"], max_duration=20.0,
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
                        "jamendo", moods=["epic"], max_duration=20.0,
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
                    "jamendo", moods=["epic"], max_duration=20.0,
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
                result = resolve_music_track("local", moods=["epic"], max_duration=20.0)
        jamendo_search.assert_not_called()
        assert result is not None
        assert result[0].endswith("calm.mp3")
        assert result[2] == 90


class TestResolveMusicTrackTagFallbackChain:
    def test_tries_second_tag_when_first_tag_has_no_candidates(self) -> None:
        candidate = TrackCandidate(
            title="Calm Waters", duration=180.0,
            download_url="https://x/calm.mp3", source="jamendo",
        )

        def fake_search(query: str, max_duration: float) -> list[TrackCandidate]:
            return [] if query == "epic" else [candidate]

        with patch.object(JamendoMusicProvider, "search", side_effect=fake_search):
            with patch.object(JamendoMusicProvider, "fetch", return_value="/cache/calm.mp3"):
                result = resolve_music_track(
                    "jamendo", moods=["epic", "calm", "dramatic"], max_duration=20.0,
                    jamendo_client_id="fake-id",
                )
        assert result == ("/cache/calm.mp3", "Calm Waters", None)

    def test_tries_third_tag_when_first_two_fail(self) -> None:
        candidate = TrackCandidate(
            title="Dramatic Score", duration=180.0,
            download_url="https://x/dramatic.mp3", source="jamendo",
        )
        tried: list[str] = []

        def fake_search(query: str, max_duration: float) -> list[TrackCandidate]:
            tried.append(query)
            return [candidate] if query == "dramatic" else []

        with patch.object(JamendoMusicProvider, "search", side_effect=fake_search):
            with patch.object(JamendoMusicProvider, "fetch", return_value="/cache/dramatic.mp3"):
                result = resolve_music_track(
                    "jamendo", moods=["epic", "calm", "dramatic"], max_duration=20.0,
                    jamendo_client_id="fake-id",
                )
        assert tried == ["epic", "calm", "dramatic"]
        assert result == ("/cache/dramatic.mp3", "Dramatic Score", None)

    def test_falls_through_to_broad_no_tag_query_when_all_3_tags_fail(self) -> None:
        candidate = TrackCandidate(
            title="Whatever Track", duration=180.0,
            download_url="https://x/whatever.mp3", source="jamendo",
        )
        tried: list[str] = []

        def fake_search(query: str, max_duration: float) -> list[TrackCandidate]:
            tried.append(query)
            return [candidate] if query == "" else []

        with patch.object(JamendoMusicProvider, "search", side_effect=fake_search):
            with patch.object(JamendoMusicProvider, "fetch", return_value="/cache/whatever.mp3"):
                with patch.object(LocalMusicProvider, "search") as local_search:
                    result = resolve_music_track(
                        "jamendo", moods=["epic", "calm", "dramatic"], max_duration=20.0,
                        jamendo_client_id="fake-id",
                    )
        assert tried == ["epic", "calm", "dramatic", ""]
        local_search.assert_not_called()
        assert result == ("/cache/whatever.mp3", "Whatever Track", None)

    def test_still_falls_back_to_local_when_broad_query_also_fails(self) -> None:
        local_track = MusicTrack(filename="calm.mp3", mood="calm", bpm=90)
        with patch.object(JamendoMusicProvider, "search", return_value=[]):
            with patch(
                "docu_studio.shorts.music_providers.select_music_track",
                return_value=local_track,
            ):
                result = resolve_music_track(
                    "jamendo", moods=["epic", "calm", "dramatic"], max_duration=20.0,
                    jamendo_client_id="fake-id",
                )
        assert result is not None
        assert result[0].endswith("calm.mp3")

    def test_more_than_3_moods_are_capped_at_3_tag_attempts(self) -> None:
        tried: list[str] = []

        def fake_search(query: str, max_duration: float) -> list[TrackCandidate]:
            tried.append(query)
            return []

        with patch.object(JamendoMusicProvider, "search", side_effect=fake_search):
            with patch(
                "docu_studio.shorts.music_providers.select_music_track", return_value=None,
            ):
                resolve_music_track(
                    "jamendo", moods=["epic", "calm", "dramatic", "upbeat", "sad"],
                    max_duration=20.0, jamendo_client_id="fake-id",
                )
        assert tried == ["epic", "calm", "dramatic", ""]

    def test_empty_moods_list_falls_back_to_default_mood_tag(self) -> None:
        tried: list[str] = []

        def fake_search(query: str, max_duration: float) -> list[TrackCandidate]:
            tried.append(query)
            return []

        with patch.object(JamendoMusicProvider, "search", side_effect=fake_search):
            with patch(
                "docu_studio.shorts.music_providers.select_music_track", return_value=None,
            ):
                resolve_music_track(
                    "jamendo", moods=[], max_duration=20.0, jamendo_client_id="fake-id",
                )
        assert tried == ["cinematic", ""]
