"""Pixabay photo search adapter — the photo endpoint, distinct from
docu_studio/adapters/footage/pixabay_adapter.py's video endpoint."""
from __future__ import annotations

import logging

import requests

from docu_studio.adapters.photos.base import PhotoProvider, PhotoResult
from docu_studio.retry import retry

_API_URL = "https://pixabay.com/api/"
_log = logging.getLogger(__name__)


class PixabayPhotosAdapter(PhotoProvider):
    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    @retry(max_attempts=3, backoff_factor=2.0, base_delay=1.0)
    def search(self, query: str, page: int = 1) -> list[PhotoResult]:
        if not self._api_key:
            _log.warning("Pixabay photos: no API key configured")
            return []

        try:
            response = requests.get(
                _API_URL,
                params={
                    "key": self._api_key,
                    "q": query,
                    "per_page": 20,
                    "page": page,
                    "image_type": "photo",
                },
                timeout=15,
            )
        except requests.Timeout:
            _log.warning("Pixabay photos: request timed out")
            return []
        except (ConnectionResetError, ConnectionError) as exc:
            _log.warning("Pixabay photos: connection failed, skipping: %s", exc)
            return []
        except Exception as exc:
            _log.warning("Pixabay photos request failed: %s", exc)
            return []

        status = response.status_code
        if status == 429:
            _log.warning("Pixabay photos: rate limit hit (429), skipping")
            return []
        if status in (401, 403):
            _log.warning("Pixabay photos: invalid API key (%d)", status)
            return []
        if status == 400:
            _log.warning("Pixabay photos: bad request (400): %s", response.text[:200])
            return []
        if status != 200:
            _log.warning("Pixabay photos: HTTP %d", status)
            return []

        data = response.json()
        photos: list[PhotoResult] = []
        for hit in data.get("hits", []):
            url = hit.get("largeImageURL", "")
            if not url:
                continue
            photos.append(PhotoResult(
                url=url,
                width=hit.get("imageWidth", 0),
                height=hit.get("imageHeight", 0),
                photo_id=str(hit.get("id", "")),
            ))
        return photos
