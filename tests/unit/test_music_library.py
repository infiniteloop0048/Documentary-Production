"""Unit tests for the shorts music-bed manifest loader."""
from __future__ import annotations

import json

from docu_studio.shorts.music_library import MusicTrack, load_manifest, select_music_track


class TestLoadManifest:
    def test_missing_directory_returns_empty(self, tmp_path) -> None:
        assert load_manifest(tmp_path / "does_not_exist" / "manifest.json") == []

    def test_malformed_json_returns_empty(self, tmp_path) -> None:
        manifest = tmp_path / "manifest.json"
        manifest.write_text("{not valid json", encoding="utf-8")
        assert load_manifest(manifest) == []

    def test_entry_pointing_at_missing_file_is_skipped(self, tmp_path) -> None:
        manifest = tmp_path / "manifest.json"
        manifest.write_text(
            json.dumps({"tracks": [{"filename": "ghost.mp3", "mood": "calm", "bpm": 90}]}),
            encoding="utf-8",
        )
        assert load_manifest(manifest) == []

    def test_valid_entry_with_file_present_is_returned(self, tmp_path) -> None:
        (tmp_path / "track.mp3").write_bytes(b"fake-audio")
        manifest = tmp_path / "manifest.json"
        manifest.write_text(
            json.dumps({"tracks": [{"filename": "track.mp3", "mood": "uplifting", "bpm": 120}]}),
            encoding="utf-8",
        )
        tracks = load_manifest(manifest)
        assert tracks == [MusicTrack(filename="track.mp3", mood="uplifting", bpm=120)]

    def test_malformed_entry_is_skipped_but_others_load(self, tmp_path) -> None:
        (tmp_path / "good.mp3").write_bytes(b"fake-audio")
        manifest = tmp_path / "manifest.json"
        manifest.write_text(
            json.dumps({"tracks": [
                {"filename": "good.mp3", "mood": "calm", "bpm": 100},
                {"mood": "missing-filename-key", "bpm": 80},
            ]}),
            encoding="utf-8",
        )
        tracks = load_manifest(manifest)
        assert len(tracks) == 1
        assert tracks[0].filename == "good.mp3"

    def test_real_shipped_manifest_has_no_usable_tracks_out_of_the_box(self) -> None:
        """The placeholder entry in the real manifest.json points at a file
        that isn't shipped — confirms the graceful empty-music-dir behavior
        on a fresh checkout without needing a test-only manifest."""
        assert load_manifest() == []


class TestSelectMusicTrack:
    def test_no_tracks_returns_none(self, tmp_path) -> None:
        assert select_music_track(seed=1, manifest_path=tmp_path / "missing.json") is None

    def test_reproducible_for_same_seed(self, tmp_path) -> None:
        for name in ("a.mp3", "b.mp3", "c.mp3"):
            (tmp_path / name).write_bytes(b"x")
        manifest = tmp_path / "manifest.json"
        manifest.write_text(
            json.dumps({"tracks": [
                {"filename": "a.mp3", "mood": "calm", "bpm": 90},
                {"filename": "b.mp3", "mood": "energetic", "bpm": 128},
                {"filename": "c.mp3", "mood": "uplifting", "bpm": 110},
            ]}),
            encoding="utf-8",
        )
        first = select_music_track(seed=42, manifest_path=manifest)
        second = select_music_track(seed=42, manifest_path=manifest)
        assert first == second
