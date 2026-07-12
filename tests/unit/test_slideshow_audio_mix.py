"""Unit tests for slideshow_audio_mix — pure string building, no I/O."""
from __future__ import annotations

from docu_studio.slideshow.slideshow_audio_mix import build_ducking_filtergraph


class TestBuildDuckingFiltergraph:
    def test_references_voice_as_sidechain_key(self) -> None:
        graph = build_ducking_filtergraph(10.0)
        assert "[music_faded][0:a]sidechaincompress" in graph

    def test_trims_music_to_video_duration(self) -> None:
        graph = build_ducking_filtergraph(12.5)
        assert "atrim=0:12.500" in graph

    def test_fade_out_start_is_duration_minus_one_second(self) -> None:
        graph = build_ducking_filtergraph(12.5)
        assert "afade=t=out:st=11.500:d=1.00" in graph

    def test_short_video_clamps_fade_out_start_to_zero(self) -> None:
        graph = build_ducking_filtergraph(0.5)
        assert "afade=t=out:st=0.000:d=1.00" in graph

    def test_amix_normalize_disabled_so_voice_stays_dominant(self) -> None:
        graph = build_ducking_filtergraph(10.0)
        assert "amix=inputs=2:duration=first:normalize=0[aout]" in graph
