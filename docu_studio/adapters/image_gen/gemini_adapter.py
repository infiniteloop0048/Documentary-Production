"""Google Gemini image generation adapter — covers both "Nano Banana"
(gemini-2.5-flash-image) and "Nano Banana Pro" (gemini-3-pro-image-preview);
model id is passed in by the caller, this class doesn't hardcode a tier."""
from __future__ import annotations

import base64

import requests

from docu_studio.adapters.image_gen.base import ImageGenProvider
from docu_studio.retry import retry

_API_URL_TEMPLATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def _aspect_ratio(width: int, height: int) -> str:
    if width == height:
        return "1:1"
    return "9:16" if height > width else "16:9"


class GeminiImageGenAdapter(ImageGenProvider):
    def __init__(self, api_key: str, model: str) -> None:
        self._api_key = api_key
        self._model = model

    @retry(max_attempts=3, backoff_factor=2.0, base_delay=1.0)
    def generate(self, prompt: str, width: int, height: int) -> bytes:
        response = requests.post(
            _API_URL_TEMPLATE.format(model=self._model),
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": self._api_key,
            },
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "responseModalities": ["IMAGE"],
                    "imageConfig": {"aspectRatio": _aspect_ratio(width, height)},
                },
            },
            timeout=60,
        )
        if response.status_code != 200:
            raise RuntimeError(
                f"Gemini image generation failed: HTTP {response.status_code}: {response.text[:300]}"
            )
        data = response.json()
        for candidate in data.get("candidates", []):
            for part in candidate.get("content", {}).get("parts", []):
                inline = part.get("inlineData")
                if inline and inline.get("data"):
                    return base64.b64decode(inline["data"])
        raise RuntimeError("Gemini image generation returned no image data")
