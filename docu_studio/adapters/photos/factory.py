"""Factory for photo adapters."""
from __future__ import annotations

import logging

from docu_studio.adapters.photos.base import PhotoProvider

_log = logging.getLogger(__name__)


def build_photo_providers(pexels_key: str, pixabay_key: str) -> list[PhotoProvider]:
    from docu_studio.adapters.photos.pexels_photos_adapter import PexelsPhotosAdapter

    providers: list[PhotoProvider] = [PexelsPhotosAdapter(api_key=pexels_key)]

    if pixabay_key:
        from docu_studio.adapters.photos.pixabay_photos_adapter import PixabayPhotosAdapter
        providers.append(PixabayPhotosAdapter(api_key=pixabay_key))

    active = [type(p).__name__.removesuffix("Adapter") for p in providers]
    _log.info("Photo providers: %s", active)
    return providers
