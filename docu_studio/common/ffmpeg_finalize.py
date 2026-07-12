"""Shared SAR/pixel-format normalization for per-segment ffmpeg filter chains.

Chained scale operations (vertical_convert's force_original_aspect_ratio
crop, Ken Burns' 4x lanczos upscale + zoompan) occasionally round the
encoded SAR to a near-1:1-but-not-exact value (e.g. 17485:17484); ffmpeg's
concat filter rejects segments whose SAR doesn't match exactly. Every
per-segment filter chain — in both ShortsFFmpeg and SlideshowFFmpeg — must
end with this suffix, regardless of which combination of filters preceded
it.
"""
from __future__ import annotations

_SAR_PIXFMT_SUFFIX = "setsar=1,format=yuv420p"


def finalize_filter(filter_chain: str) -> str:
    """Append the shared SAR/pixel-format normalization suffix as the last
    step of a per-segment filter chain (no output-pad label). Every
    function that finalizes a segment's filter chain before its
    per-segment encode must route through this single helper — see the
    module docstring for why."""
    return f"{filter_chain},{_SAR_PIXFMT_SUFFIX}"
