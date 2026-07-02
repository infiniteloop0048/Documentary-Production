"""T043: HTTP-mocked integration tests for PixabayAdapter."""
from __future__ import annotations

from unittest.mock import patch

import pytest
import responses as resp_lib

from docu_studio.adapters.footage.base import FootageClip
from docu_studio.adapters.footage.pixabay_adapter import PixabayAdapter
from docu_studio.config.settings import Settings

_PIXABAY_URL = "https://pixabay.com/api/videos/"

_SAMPLE_RESPONSE = {
    "hits": [
        {
            "videos": {
                "large": {"url": "https://cdn.pixabay.com/clip1.mp4", "width": 1920, "height": 1080}
            },
            "duration": 12,
        },
        {
            "videos": {
                "large": {"url": "https://cdn.pixabay.com/clip2.mp4", "width": 1280, "height": 720}
            },
            "duration": 18,
        },
    ]
}


def _make_adapter() -> PixabayAdapter:
    settings = Settings()
    with patch.object(Settings, "get_key", return_value="pixabay-fake-key"):
        return PixabayAdapter(settings)


class TestPixabayAdapterSearch:
    @resp_lib.activate
    def test_returns_list_of_footage_clips(self) -> None:
        resp_lib.add(resp_lib.GET, _PIXABAY_URL, json=_SAMPLE_RESPONSE, status=200)
        adapter = _make_adapter()
        clips = adapter.search(["nature", "space"], min_duration=10.0)
        assert isinstance(clips, list)
        assert all(isinstance(c, FootageClip) for c in clips)
        assert len(clips) == 2

    @resp_lib.activate
    def test_clips_have_expected_fields(self) -> None:
        resp_lib.add(resp_lib.GET, _PIXABAY_URL, json=_SAMPLE_RESPONSE, status=200)
        adapter = _make_adapter()
        clips = adapter.search(["keyword"], min_duration=5.0)
        c = clips[0]
        assert isinstance(c.url, str)
        assert isinstance(c.duration, float)

    @resp_lib.activate
    def test_returns_empty_list_on_api_error(self) -> None:
        resp_lib.add(resp_lib.GET, _PIXABAY_URL, json={}, status=500)
        adapter = _make_adapter()
        clips = adapter.search(["topic"], min_duration=5.0)
        assert clips == []
