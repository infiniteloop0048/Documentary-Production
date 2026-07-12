"""Unit tests for the shared SAR/pixel-format filter-chain finalizer.

Union of the former TestFinalizeFilter classes in test_shorts_ffmpeg.py and
test_slideshow_ffmpeg.py (deduped where both asserted the same behavior),
now that finalize_filter is a module-level function in
docu_studio/common/ffmpeg_finalize.py rather than a per-class staticmethod.
"""
from __future__ import annotations

from docu_studio.common.ffmpeg_finalize import _SAR_PIXFMT_SUFFIX, finalize_filter


class TestFinalizeFilter:
    def test_appends_setsar_and_format_suffix(self) -> None:
        result = finalize_filter("scale=100:100")
        assert result == "scale=100:100,setsar=1,format=yuv420p"

    def test_ends_with_setsar_1_regardless_of_upstream_filters(self) -> None:
        # Real-run regression: chained scale/crop/zoompan filters occasionally
        # round the encoded SAR to a near-1:1-but-not-exact value (e.g.
        # 17485:17484), which ffmpeg's concat filter rejects outright when
        # joining against segments that ARE exactly 1:1. Every per-segment
        # filter chain must end with setsar=1 no matter what preceded it.
        chains = [
            "setpts=PTS/1.35",
            "scale=4320:-2:flags=lanczos,zoompan=z='1.0':x='0':y='0':d=90:s=1080x1920:fps=30",
            "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920",
            "subtitles=captions.ass",
        ]
        for chain in chains:
            result = finalize_filter(chain)
            assert result.endswith(",setsar=1,format=yuv420p")

    def test_suffix_constant_matches_documented_value(self) -> None:
        assert _SAR_PIXFMT_SUFFIX == "setsar=1,format=yuv420p"
