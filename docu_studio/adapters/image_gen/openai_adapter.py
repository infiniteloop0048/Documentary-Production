"""OpenAI GPT-Image-1 adapter — text-to-image, distinct from
docu_studio/adapters/llm/openai_adapter.py (chat completions)."""
from __future__ import annotations

import base64

from openai import OpenAI

from docu_studio.adapters.image_gen.base import ImageGenProvider
from docu_studio.retry import retry

# GPT-Image-1 only supports these three fixed sizes — request whichever is
# closest to the caller's aspect ratio; the existing Ken Burns scale+crop step
# handles the final exact fit regardless of provider-returned pixel size.
_SIZE_SQUARE = "1024x1024"
_SIZE_PORTRAIT = "1024x1536"
_SIZE_LANDSCAPE = "1536x1024"


def _closest_size(width: int, height: int) -> str:
    if width == height:
        return _SIZE_SQUARE
    return _SIZE_PORTRAIT if height > width else _SIZE_LANDSCAPE


class OpenAIImageGenAdapter(ImageGenProvider):
    def __init__(self, api_key: str, model: str = "gpt-image-1") -> None:
        self._client = OpenAI(api_key=api_key)
        self._model = model

    @retry(max_attempts=3, backoff_factor=2.0, base_delay=1.0)
    def generate(self, prompt: str, width: int, height: int) -> bytes:
        response = self._client.images.generate(
            model=self._model,
            prompt=prompt,
            size=_closest_size(width, height),
            n=1,
        )
        b64 = response.data[0].b64_json
        if not b64:
            raise RuntimeError("OpenAI image generation returned no image data")
        return base64.b64decode(b64)
