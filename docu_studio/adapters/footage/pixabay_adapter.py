"""Pixabay video search adapter."""
from __future__ import annotations

import logging

import requests

from docu_studio.adapters.footage.base import FootageClip, FootageProvider
from docu_studio.retry import retry

_API_URL = "https://pixabay.com/api/videos/"
_log = logging.getLogger(__name__)


class PixabayAdapter(FootageProvider):
    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    @retry(max_attempts=3, backoff_factor=2.0, base_delay=1.0)
    def search(self, keywords: list[str], min_duration: float, page: int = 1) -> list[FootageClip]:
        if not self._api_key:
            _log.warning("Pixabay: no API key configured")
            return []

        query = " ".join(keywords)
        try:
            response = requests.get(
                _API_URL,
                params={
                    "key": self._api_key,
                    "q": query,
                    "per_page": 20,
                    "page": page,
                    "video_type": "film",
                },
                timeout=15,
            )
        except requests.Timeout:
            _log.warning("Pixabay: request timed out")
            return []
        except (ConnectionResetError, ConnectionError) as exc:
            _log.warning("Pixabay: connection failed, skipping: %s", exc)
            return []
        except Exception as exc:
            _log.warning("Pixabay request failed: %s", exc)
            return []

        status = response.status_code
        if status == 429:
            _log.warning("Pixabay: rate limit hit (429), skipping")
            return []
        if status in (401, 403):
            _log.warning("Pixabay: invalid API key (%d)", status)
            return []
        if status == 400:
            _log.warning("Pixabay: bad request (400): %s", response.text[:200])
            return []
        if status != 200:
            _log.warning("Pixabay: HTTP %d", status)
            return []

        data = response.json()
        total_hits = data.get("totalHits", len(data.get("hits", [])))
        _log.info("Pixabay: found %d results for query '%s'", total_hits, query)

        clips: list[FootageClip] = []
        for hit in data.get("hits", []):
            videos = hit.get("videos", {})
            for size in ("large", "medium", "small"):
                v = videos.get(size, {})
                duration = float(hit.get("duration", 0))
                if duration < min_duration:
                    break
                url = v.get("url", "")
                if url:
                    clips.append(FootageClip(
                        url=url,
                        duration=duration,
                        width=v.get("width", 1920),
                        height=v.get("height", 1080),
                    ))
                    _log.debug("Pixabay: queued clip %s (%.1fs)", url, duration)
                    break
        return clips
