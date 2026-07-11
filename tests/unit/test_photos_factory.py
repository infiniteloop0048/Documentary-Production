"""Unit tests for the photo-provider factory: Pexels always included, Pixabay
only when a key is configured."""
from __future__ import annotations

from docu_studio.adapters.photos.factory import build_photo_providers
from docu_studio.adapters.photos.pexels_photos_adapter import PexelsPhotosAdapter
from docu_studio.adapters.photos.pixabay_photos_adapter import PixabayPhotosAdapter


class TestBuildPhotoProviders:
    def test_pexels_always_included(self) -> None:
        providers = build_photo_providers(pexels_key="", pixabay_key="")
        assert len(providers) == 1
        assert isinstance(providers[0], PexelsPhotosAdapter)

    def test_pixabay_included_when_key_present(self) -> None:
        providers = build_photo_providers(pexels_key="pk", pixabay_key="pixk")
        assert len(providers) == 2
        assert isinstance(providers[0], PexelsPhotosAdapter)
        assert isinstance(providers[1], PixabayPhotosAdapter)

    def test_pixabay_excluded_when_key_missing(self) -> None:
        providers = build_photo_providers(pexels_key="pk", pixabay_key="")
        assert len(providers) == 1
