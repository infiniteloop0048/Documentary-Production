"""HTTP-mocked integration tests for PexelsPhotosAdapter (the photo search
endpoint, distinct from the existing video-search PexelsAdapter)."""
from __future__ import annotations

import responses as resp_lib

from docu_studio.adapters.photos.base import PhotoResult
from docu_studio.adapters.photos.pexels_photos_adapter import PexelsPhotosAdapter

_PEXELS_PHOTO_URL = "https://api.pexels.com/v1/search"

_SAMPLE_RESPONSE = {
    "photos": [
        {"id": 1, "width": 1920, "height": 1080, "src": {"large": "https://images.pexels.com/1.jpg"}},
        {"id": 2, "width": 1280, "height": 720, "src": {"large": "https://images.pexels.com/2.jpg"}},
    ]
}


def _make_adapter() -> PexelsPhotosAdapter:
    return PexelsPhotosAdapter(api_key="pexels-fake-key")


class TestPexelsPhotosAdapterSearch:
    @resp_lib.activate
    def test_returns_list_of_photo_results(self) -> None:
        resp_lib.add(resp_lib.GET, _PEXELS_PHOTO_URL, json=_SAMPLE_RESPONSE, status=200)
        adapter = _make_adapter()
        photos = adapter.search("mountains")
        assert isinstance(photos, list)
        assert all(isinstance(p, PhotoResult) for p in photos)
        assert len(photos) == 2

    @resp_lib.activate
    def test_photos_have_expected_fields(self) -> None:
        resp_lib.add(resp_lib.GET, _PEXELS_PHOTO_URL, json=_SAMPLE_RESPONSE, status=200)
        adapter = _make_adapter()
        photo = adapter.search("mountains")[0]
        assert photo.url == "https://images.pexels.com/1.jpg"
        assert photo.width == 1920
        assert photo.height == 1080
        assert photo.photo_id == "1"

    @resp_lib.activate
    def test_returns_empty_list_on_404(self) -> None:
        resp_lib.add(resp_lib.GET, _PEXELS_PHOTO_URL, json={}, status=404)
        adapter = _make_adapter()
        assert adapter.search("mountains") == []

    @resp_lib.activate
    def test_returns_empty_list_on_401(self) -> None:
        resp_lib.add(resp_lib.GET, _PEXELS_PHOTO_URL, json={}, status=401)
        adapter = _make_adapter()
        assert adapter.search("mountains") == []

    @resp_lib.activate
    def test_returns_empty_list_on_429(self) -> None:
        resp_lib.add(resp_lib.GET, _PEXELS_PHOTO_URL, json={}, status=429)
        adapter = _make_adapter()
        assert adapter.search("mountains") == []

    @resp_lib.activate
    def test_skips_photo_missing_large_src(self) -> None:
        resp_lib.add(resp_lib.GET, _PEXELS_PHOTO_URL, json={
            "photos": [{"id": 3, "width": 800, "height": 600, "src": {}}]
        }, status=200)
        adapter = _make_adapter()
        assert adapter.search("mountains") == []
