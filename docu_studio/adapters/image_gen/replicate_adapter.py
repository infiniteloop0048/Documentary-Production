"""Replicate image generation adapter — hosts FLUX (Black Forest Labs), SDXL
(Stability AI), and other models behind one HTTP API. Prediction creation is
asynchronous: POST to create, then poll the returned status URL until the
prediction reaches a terminal state, then download the output URL."""
from __future__ import annotations

import time

import requests

from docu_studio.adapters.image_gen.base import ImageGenProvider
from docu_studio.retry import retry

_PREDICTIONS_URL_TEMPLATE = "https://api.replicate.com/v1/models/{model}/predictions"
_POLL_INTERVAL_SECONDS = 2.0
_POLL_TIMEOUT_SECONDS = 120.0
_TERMINAL_STATUSES = ("succeeded", "failed", "canceled")


def _aspect_ratio(width: int, height: int) -> str:
    if width == height:
        return "1:1"
    return "9:16" if height > width else "16:9"


class ReplicateImageGenAdapter(ImageGenProvider):
    def __init__(self, api_key: str, model: str) -> None:
        self._api_key = api_key
        self._model = model

    @retry(max_attempts=3, backoff_factor=2.0, base_delay=1.0)
    def generate(self, prompt: str, width: int, height: int) -> bytes:
        response = requests.post(
            _PREDICTIONS_URL_TEMPLATE.format(model=self._model),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "Prefer": "wait=30",
            },
            json={"input": {"prompt": prompt, "aspect_ratio": _aspect_ratio(width, height)}},
            timeout=45,
        )
        if response.status_code not in (200, 201):
            raise RuntimeError(
                f"Replicate prediction create failed: HTTP {response.status_code}: {response.text[:300]}"
            )
        prediction = self._await_completion(response.json())
        return self._download_output(prediction)

    def _await_completion(self, prediction: dict) -> dict:
        elapsed = 0.0
        while prediction.get("status") not in _TERMINAL_STATUSES:
            if elapsed >= _POLL_TIMEOUT_SECONDS:
                raise RuntimeError("Replicate prediction timed out")
            time.sleep(_POLL_INTERVAL_SECONDS)
            elapsed += _POLL_INTERVAL_SECONDS
            poll_response = requests.get(
                prediction["urls"]["get"],
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout=30,
            )
            poll_response.raise_for_status()
            prediction = poll_response.json()
        if prediction.get("status") != "succeeded":
            raise RuntimeError(f"Replicate prediction failed: {prediction.get('error')}")
        return prediction

    def _download_output(self, prediction: dict) -> bytes:
        output = prediction.get("output")
        url = output[0] if isinstance(output, list) else output
        if not url:
            raise RuntimeError("Replicate prediction succeeded but returned no output")
        image_response = requests.get(url, timeout=30)
        image_response.raise_for_status()
        return image_response.content
