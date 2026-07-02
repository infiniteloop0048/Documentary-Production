"""T042: HTTP-mocked integration tests for PexelsAdapter."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import responses as resp_lib

from docu_studio.adapters.footage.base import FootageClip
from docu_studio.adapters.footage.pexels_adapter import PexelsAdapter
from docu_studio.config.settings import Settings

_PEXELS_VIDEO_URL = "https://api.pexels.com/videos/search"

_SAMPLE_RESPONSE = {
    "videos": [
        {
            "video_files": [
                {"link": "https://cdn.pexels.com/clip1.mp4", "width": 1920, "height": 1080, "quality": "hd"}
            ],
            "duration": 15,
        },
        {
            "video_files": [
                {"link": "https://cdn.pexels.com/clip2.mp4", "width": 1280, "height": 720, "quality": "hd"}
            ],
            "duration": 20,
        },
    ]
}


def _make_adapter() -> PexelsAdapter:
    settings = Settings()
    with patch.object(Settings, "get_key", return_value="pexels-fake-key"):
        return PexelsAdapter(settings)


class TestPexelsAdapterSearch:
    @resp_lib.activate
    def test_returns_list_of_footage_clips(self) -> None:
        resp_lib.add(resp_lib.GET, _PEXELS_VIDEO_URL, json=_SAMPLE_RESPONSE, status=200)
        adapter = _make_adapter()
        clips = adapter.search(["rocket", "space"], min_duration=10.0)
        assert isinstance(clips, list)
        assert all(isinstance(c, FootageClip) for c in clips)
        assert len(clips) == 2

    @resp_lib.activate
    def test_clips_have_expected_fields(self) -> None:
        resp_lib.add(resp_lib.GET, _PEXELS_VIDEO_URL, json=_SAMPLE_RESPONSE, status=200)
        adapter = _make_adapter()
        clips = adapter.search(["keyword"], min_duration=5.0)
        c = clips[0]
        assert isinstance(c.url, str)
        assert isinstance(c.duration, float)
        assert isinstance(c.width, int)
        assert isinstance(c.height, int)

    @resp_lib.activate
    def test_returns_empty_list_on_404(self) -> None:
        resp_lib.add(resp_lib.GET, _PEXELS_VIDEO_URL, json={}, status=404)
        adapter = _make_adapter()
        clips = adapter.search(["topic"], min_duration=5.0)
        assert clips == []
