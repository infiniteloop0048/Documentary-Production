"""FCPXML 1.9 generator — pure function; sync gate enforced before any file write.

validate_sync() MUST be called before generate_fcpxml() (Constitution Principle V).
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

_SYNC_TOLERANCE_S = 0.050
_FCPXML_VERSION = "1.9"
_FRAME_RATE_NUM = 30000
_FRAME_RATE_DEN = 1001  # 29.97 fps


@dataclass
class FinalScene:
    index: int
    title: str
    narration: str
    audio_path: str
    audio_duration: float
    video_path: str
    video_duration: float


class ExportSyncError(Exception):
    """Raised when the sync invariant (|video - audio| ≤ 50 ms) is violated."""


def validate_sync(scenes: list[FinalScene], tolerance_s: float = _SYNC_TOLERANCE_S) -> None:
    """Raise ExportSyncError if any scene's audio/video durations diverge beyond tolerance."""
    for scene in scenes:
        delta = abs(scene.video_duration - scene.audio_duration)
        if delta > tolerance_s:
            raise ExportSyncError(
                f"Scene {scene.index} sync invariant violated: "
                f"audio={scene.audio_duration:.3f}s, video={scene.video_duration:.3f}s, "
                f"delta={delta:.3f}s > {tolerance_s:.3f}s tolerance"
            )


def generate_fcpxml(scenes: list[FinalScene], project_folder: Path, topic: str) -> str:
    """Generate an FCPXML 1.9 string for *scenes*; runs validate_sync() first.

    Returns the XML string. Callers are responsible for writing it to disk.
    """
    validate_sync(scenes)

    fcpxml = ET.Element("fcpxml", version=_FCPXML_VERSION)
    resources = ET.SubElement(fcpxml, "resources")

    # Format resource
    fmt_id = "r1"
    ET.SubElement(
        resources, "format",
        id=fmt_id,
        name="FFVideoFormat1080p2997",
        frameDuration=f"{_FRAME_RATE_DEN}/{_FRAME_RATE_NUM}s",
        width="1920",
        height="1080",
    )

    library = ET.SubElement(fcpxml, "library")
    event = ET.SubElement(library, "event", name=topic)
    project = ET.SubElement(event, "project", name=topic)
    sequence = ET.SubElement(
        project, "sequence",
        duration=_seconds_to_fcp(sum(s.audio_duration for s in scenes)),
        format=fmt_id,
        tcStart="0s",
        tcFormat="NDF",
        audioLayout="stereo",
        audioRate="48k",
    )
    spine = ET.SubElement(sequence, "spine")

    offset_s = 0.0
    for scene in scenes:
        clip = ET.SubElement(
            spine, "clip",
            name=scene.title,
            offset=_seconds_to_fcp(offset_s),
            duration=_seconds_to_fcp(scene.audio_duration),
            start="0s",
        )
        ET.SubElement(
            clip, "marker",
            start="0s",
            duration="1/30s",
            value=scene.title,
        )
        offset_s += scene.audio_duration

    return ET.tostring(fcpxml, encoding="unicode", xml_declaration=True)


def _seconds_to_fcp(seconds: float) -> str:
    """Convert seconds to a FCPXML rational time string (e.g. '30030/30000s')."""
    numerator = round(seconds * _FRAME_RATE_NUM)
    return f"{numerator}/{_FRAME_RATE_NUM}s"
