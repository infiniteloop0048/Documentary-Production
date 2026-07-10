"""Coverr video search adapter."""
from __future__ import annotations

import logging

import requests

from docu_studio.adapters.footage.base import FootageClip, FootageProvider
from docu_studio.retry import retry

_API_URL = "https://api.coverr.co/videos"
_log = logging.getLogger(__name__)


class CoverrAdapter(FootageProvider):
    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    @retry(max_attempts=3, backoff_factor=2.0, base_delay=1.0)
    def search(self, keywords: list[str], min_duration: float, page: int = 1) -> list[FootageClip]:
        if not self._api_key:
            _log.warning("Coverr: no API key configured")
            return []

        query = " ".join(keywords)
        try:
            response = requests.get(
                _API_URL,
                params={
                    "api_key": self._api_key,
                    "query": query,
                    "page_size": 20,
                    "page": max(0, page - 1),  # Coverr is 0-based
                },
                timeout=15,
            )
        except requests.Timeout:
            _log.warning("Coverr: request timed out")
            return []
        except (ConnectionResetError, ConnectionError) as exc:
            _log.warning("Coverr: connection failed: %s", exc)
            return []

        status = response.status_code
        if status == 429:
            _log.warning("Coverr: rate limit hit (429), skipping")
            return []
        if status in (401, 403):
            _log.warning("Coverr: invalid API key (%d)", status)
            return []
        if status == 400:
            _log.warning("Coverr: bad request (400): %s", response.text[:200])
            return []
        if status != 200:
            _log.warning("Coverr: HTTP %d", status)
            return []

        data = response.json()
        hits = data.get("hits", [])
        if not hits:
            _log.info("Coverr: no results for '%s'", query)
            return []

        _log.info("Coverr: found %d results for '%s'", len(hits), query)
        clips: list[FootageClip] = []
        for hit in hits:
            url = hit.get("mp4_download") or hit.get("mp4_preview", "")
            if not url:
                continue
            duration = float(hit.get("duration", 0))
            if duration < min_duration:
                continue
            clips.append(FootageClip(
                url=url, duration=duration, width=1920, height=1080,
                clip_id=str(hit.get("id", "")),
            ))
        return clips
