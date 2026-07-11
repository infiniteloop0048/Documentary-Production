"""Pexels photo search adapter — the photo endpoint, distinct from
docu_studio/adapters/footage/pexels_adapter.py's video endpoint."""
from __future__ import annotations

import logging

import requests

from docu_studio.adapters.photos.base import PhotoProvider, PhotoResult
from docu_studio.retry import retry

_API_URL = "https://api.pexels.com/v1/search"
_log = logging.getLogger(__name__)


class PexelsPhotosAdapter(PhotoProvider):
    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    @retry(max_attempts=3, backoff_factor=2.0, base_delay=1.0)
    def search(self, query: str, page: int = 1) -> list[PhotoResult]:
        try:
            response = requests.get(
                _API_URL,
                headers={"Authorization": self._api_key},
                params={"query": query, "per_page": 20, "page": page},
                timeout=15,
            )
        except requests.Timeout:
            _log.warning("Pexels photos: request timed out")
            return []
        except (ConnectionResetError, ConnectionError) as exc:
            _log.warning("Pexels photos: connection failed: %s", exc)
            return []

        status = response.status_code
        if status == 429:
            _log.warning("Pexels photos: rate limit hit (429), skipping")
            return []
        if status in (401, 403):
            _log.warning("Pexels photos: invalid API key (%d)", status)
            return []
        if status == 400:
            _log.warning("Pexels photos: bad request (400): %s", response.text[:200])
            return []
        if status == 404:
            return []
        if status != 200:
            _log.warning("Pexels photos: HTTP %d", status)
            return []

        data = response.json()
        photos: list[PhotoResult] = []
        for photo in data.get("photos", []):
            src = photo.get("src", {})
            url = src.get("large", "")
            if not url:
                continue
            photos.append(PhotoResult(
                url=url,
                width=photo.get("width", 0),
                height=photo.get("height", 0),
                photo_id=str(photo.get("id", "")),
            ))
        return photos
