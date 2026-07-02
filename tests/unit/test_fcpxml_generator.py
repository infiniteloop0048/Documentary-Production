"""Unit tests for fcpxml_generator — pure function, no I/O."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

import pytest

from docu_studio.media.fcpxml_generator import (
    ExportSyncError,
    FinalScene,
    generate_fcpxml,
    validate_sync,
)


def _make_scene(index: int, audio_dur: float, video_dur: float) -> FinalScene:
    return FinalScene(
        index=index,
        title=f"Scene {index}",
        narration="Test narration.",
        audio_path=f"/audio/{index}.mp3",
        audio_duration=audio_dur,
        video_path=f"/video/{index}.mp4",
        video_duration=video_dur,
    )


class TestValidateSync:
    def test_passes_when_within_tolerance(self) -> None:
        scenes = [_make_scene(1, 10.0, 10.03), _make_scene(2, 15.0, 14.98)]
        validate_sync(scenes)  # must not raise

    def test_raises_when_delta_exceeds_50ms(self) -> None:
        scenes = [_make_scene(1, 10.0, 10.06)]
        with pytest.raises(ExportSyncError):
            validate_sync(scenes)

    def test_raises_with_scene_info_in_message(self) -> None:
        scenes = [_make_scene(2, 5.0, 5.1)]
        with pytest.raises(ExportSyncError, match="Scene 2"):
            validate_sync(scenes)


class TestGenerateFcpxml:
    def test_returns_valid_xml_string(self, tmp_path: Path) -> None:
        scenes = [_make_scene(1, 10.0, 10.0), _make_scene(2, 8.0, 8.0)]
        xml_str = generate_fcpxml(scenes, tmp_path, "Test Topic")
        root = ET.fromstring(xml_str)
        assert root.tag == "fcpxml"

    def test_contains_correct_marker_count(self, tmp_path: Path) -> None:
        scenes = [_make_scene(i, 10.0, 10.0) for i in range(1, 4)]
        xml_str = generate_fcpxml(scenes, tmp_path, "Topic")
        root = ET.fromstring(xml_str)
        markers = root.findall(".//{*}marker") or root.findall(".//marker")
        assert len(markers) == 3

    def test_raises_export_sync_error_on_violated_invariant(self, tmp_path: Path) -> None:
        scenes = [_make_scene(1, 10.0, 10.2)]
        with pytest.raises(ExportSyncError):
            generate_fcpxml(scenes, tmp_path, "Topic")
