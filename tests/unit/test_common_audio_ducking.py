"""Unit tests for the shared music-bed ducking filtergraph string construction.

Union of the former test_shorts_audio_mix.py and test_slideshow_audio_mix.py
cases (deduped where both files asserted the same behavior with only a
different duration value).
"""
from __future__ import annotations

from docu_studio.common.audio_ducking import build_ducking_filtergraph


class TestBuildDuckingFiltergraph:
    def test_references_both_input_streams(self) -> None:
        graph = build_ducking_filtergraph(30.0)
        assert "[0:a]" in graph
        assert "[1:a]" in graph

    def test_includes_sidechaincompress_keyed_by_voice(self) -> None:
        graph = build_ducking_filtergraph(30.0)
        assert "sidechaincompress" in graph
        assert "[music_faded][0:a]sidechaincompress" in graph

    def test_includes_fade_in_and_out(self) -> None:
        graph = build_ducking_filtergraph(30.0)
        assert "afade=t=in" in graph
        assert "afade=t=out" in graph

    def test_fade_out_starts_one_second_before_end(self) -> None:
        graph = build_ducking_filtergraph(30.0)
        assert "afade=t=out:st=29.000:d=1.00" in graph

    def test_short_clip_fade_out_start_clamped_to_zero(self) -> None:
        graph = build_ducking_filtergraph(0.5)
        assert "afade=t=out:st=0.000:d=1.00" in graph

    def test_final_output_label_is_aout(self) -> None:
        graph = build_ducking_filtergraph(30.0)
        assert graph.endswith("[aout]")

    def test_amix_does_not_auto_normalize(self) -> None:
        graph = build_ducking_filtergraph(30.0)
        assert "normalize=0" in graph

    def test_trims_music_to_exact_video_duration(self) -> None:
        graph = build_ducking_filtergraph(47.25)
        assert "atrim=0:47.250" in graph

    def test_baseline_volume_reduction_is_within_spec_range(self) -> None:
        graph = build_ducking_filtergraph(30.0)
        assert "volume=-20dB" in graph  # within the -18 to -22 dB spec range

    def test_amix_normalize_disabled_so_voice_stays_dominant(self) -> None:
        graph = build_ducking_filtergraph(10.0)
        assert "amix=inputs=2:duration=first:normalize=0[aout]" in graph

    def test_custom_music_baseline_db_overrides_default(self) -> None:
        graph = build_ducking_filtergraph(30.0, music_baseline_db=-10)
        assert "volume=-10dB" in graph
        assert "volume=-20dB" not in graph
