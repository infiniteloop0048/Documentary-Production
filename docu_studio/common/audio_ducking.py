"""Pure ffmpeg filtergraph construction for music-bed ducking.

Kept as pure string building (no subprocess) so the ducking graph is directly
unit-testable — ShortsFFmpeg.mix_music_bed and SlideshowFFmpeg.mix_music_bed
are the only callers that actually invoke ffmpeg with this string.
"""
from __future__ import annotations

_FADE_SECONDS = 1.0
# Combined with sidechaincompress ducking below, lands music around -18 to
# -22 dB under narration — voice always dominant.
_MUSIC_BASELINE_DB = -20


def build_ducking_filtergraph(video_duration: float) -> str:
    """Return a -filter_complex string that loops/trims a music input ([1:a])
    to *video_duration* seconds, fades it in/out, ducks it under a voice
    input ([0:a]) via sidechaincompress, and mixes the two with amix
    (normalize=0 so ffmpeg's default equal-weighting doesn't undermine "voice
    always dominant").

    Input stream order is fixed: [0:a] = voice (also the sidechain key),
    [1:a] = music (looped via -stream_loop -1 on the input args by the caller).
    """
    fade_out_start = max(0.0, video_duration - _FADE_SECONDS)
    return (
        f"[1:a]atrim=0:{video_duration:.3f},"
        f"afade=t=in:st=0:d={_FADE_SECONDS:.2f},"
        f"afade=t=out:st={fade_out_start:.3f}:d={_FADE_SECONDS:.2f},"
        f"volume={_MUSIC_BASELINE_DB}dB[music_faded];"
        f"[music_faded][0:a]sidechaincompress=threshold=0.05:ratio=8:attack=5:release=300[music_ducked];"
        f"[0:a][music_ducked]amix=inputs=2:duration=first:normalize=0[aout]"
    )
