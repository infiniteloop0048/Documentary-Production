"""fal.ai image generation adapter — hosts FLUX and other models behind
queue.fal.run. Fast (schnell-tier) models return their result directly in the
initial response rather than requiring polling, which this adapter relies on."""
from __future__ import annotations

import requests

from docu_studio.adapters.image_gen.base import ImageGenProvider
from docu_studio.retry import retry

_QUEUE_URL_TEMPLATE = "https://queue.fal.run/{model}"


class FalImageGenAdapter(ImageGenProvider):
    def __init__(self, api_key: str, model: str) -> None:
        self._api_key = api_key
        self._model = model

    @retry(max_attempts=3, backoff_factor=2.0, base_delay=1.0)
    def generate(self, prompt: str, width: int, height: int) -> bytes:
        response = requests.post(
            _QUEUE_URL_TEMPLATE.format(model=self._model),
            headers={
                "Authorization": f"Key {self._api_key}",
                "Content-Type": "application/json",
            },
            json={"prompt": prompt, "image_size": {"width": width, "height": height}},
            timeout=60,
        )
        if response.status_code != 200:
            raise RuntimeError(
                f"fal.ai image generation failed: HTTP {response.status_code}: {response.text[:300]}"
            )
        images = response.json().get("images", [])
        if not images:
            raise RuntimeError("fal.ai image generation returned no image")
        image_response = requests.get(images[0]["url"], timeout=30)
        image_response.raise_for_status()
        return image_response.content
