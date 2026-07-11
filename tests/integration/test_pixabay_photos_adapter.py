"""HTTP-mocked integration tests for PixabayPhotosAdapter (the photo search
endpoint, distinct from the existing video-search PixabayAdapter)."""
from __future__ import annotations

import responses as resp_lib

from docu_studio.adapters.photos.base import PhotoResult
from docu_studio.adapters.photos.pixabay_photos_adapter import PixabayPhotosAdapter

_PIXABAY_PHOTO_URL = "https://pixabay.com/api/"

_SAMPLE_RESPONSE = {
    "hits": [
        {"id": 10, "imageWidth": 1920, "imageHeight": 1080, "largeImageURL": "https://cdn.pixabay.com/10.jpg"},
        {"id": 11, "imageWidth": 1280, "imageHeight": 720, "largeImageURL": "https://cdn.pixabay.com/11.jpg"},
    ]
}


def _make_adapter() -> PixabayPhotosAdapter:
    return PixabayPhotosAdapter(api_key="pixabay-fake-key")


class TestPixabayPhotosAdapterSearch:
    @resp_lib.activate
    def test_returns_list_of_photo_results(self) -> None:
        resp_lib.add(resp_lib.GET, _PIXABAY_PHOTO_URL, json=_SAMPLE_RESPONSE, status=200)
        adapter = _make_adapter()
        photos = adapter.search("mountains")
        assert isinstance(photos, list)
        assert all(isinstance(p, PhotoResult) for p in photos)
        assert len(photos) == 2

    @resp_lib.activate
    def test_photos_have_expected_fields(self) -> None:
        resp_lib.add(resp_lib.GET, _PIXABAY_PHOTO_URL, json=_SAMPLE_RESPONSE, status=200)
        adapter = _make_adapter()
        photo = adapter.search("mountains")[0]
        assert photo.url == "https://cdn.pixabay.com/10.jpg"
        assert photo.width == 1920
        assert photo.height == 1080
        assert photo.photo_id == "10"

    @resp_lib.activate
    def test_returns_empty_list_on_500(self) -> None:
        resp_lib.add(resp_lib.GET, _PIXABAY_PHOTO_URL, json={}, status=500)
        adapter = _make_adapter()
        assert adapter.search("mountains") == []

    def test_returns_empty_list_with_no_api_key(self) -> None:
        adapter = PixabayPhotosAdapter(api_key="")
        assert adapter.search("mountains") == []

    @resp_lib.activate
    def test_skips_hit_missing_large_image_url(self) -> None:
        resp_lib.add(resp_lib.GET, _PIXABAY_PHOTO_URL, json={
            "hits": [{"id": 12, "imageWidth": 800, "imageHeight": 600}]
        }, status=200)
        adapter = _make_adapter()
        assert adapter.search("mountains") == []
