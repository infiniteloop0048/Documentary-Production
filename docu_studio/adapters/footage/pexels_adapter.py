"""Pexels video search adapter."""
from __future__ import annotations

import logging

import requests

from docu_studio.adapters.footage.base import FootageClip, FootageProvider
from docu_studio.pipeline.events import sanitize_log_message
from docu_studio.retry import retry

_API_URL = "https://api.pexels.com/videos/search"
_log = logging.getLogger(__name__)


class PexelsAdapter(FootageProvider):
    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    @retry(max_attempts=3, backoff_factor=2.0, base_delay=1.0)
    def search(self, keywords: list[str], min_duration: float, page: int = 1) -> list[FootageClip]:
        query = " ".join(keywords)
        try:
            response = requests.get(
                _API_URL,
                headers={"Authorization": self._api_key},
                params={"query": query, "per_page": 20, "orientation": "landscape", "page": page},
                timeout=15,
            )
        except requests.Timeout:
            _log.warning("Pexels: request timed out")
            return []
        except (ConnectionResetError, ConnectionError) as exc:
            _log.warning("Pexels: connection failed: %s", exc)
            return []

        status = response.status_code
        if status == 429:
            _log.warning("Pexels: rate limit hit (429), skipping")
            return []
        if status in (401, 403):
            _log.warning("Pexels: invalid API key (%d)", status)
            return []
        if status == 400:
            _log.warning("Pexels: bad request (400): %s", response.text[:200])
            return []
        if status == 404:
            return []
        if status != 200:
            _log.warning("Pexels: HTTP %d", status)
            return []

        data = response.json()
        clips: list[FootageClip] = []
        for video in data.get("videos", []):
            duration = float(video.get("duration", 0))
            if duration < min_duration:
                continue
            files = video.get("video_files", [])
            hd_files = [f for f in files if f.get("quality") in ("hd", "uhd")]
            if not hd_files:
                continue
            f = hd_files[0]
            clips.append(FootageClip(
                url=f["link"],
                duration=duration,
                width=f.get("width", 1920),
                height=f.get("height", 1080),
                clip_id=str(video.get("id", "")),
            ))
        return clips
