"""Curated model presets + factory for image-generation adapters. Prices are
static, published-price estimates captured at spec time — used only for the
GUI's pre-run cost estimate, not for billing. Update manually if a vendor
changes pricing."""
from __future__ import annotations

import logging

from docu_studio.adapters.image_gen.base import ImageGenProvider

_log = logging.getLogger(__name__)

IMAGE_GEN_PRESETS: dict[str, dict] = {
    "openai_gpt_image_1": {
        "provider": "openai", "model": "gpt-image-1",
        "price_per_image_usd": 0.07,
        "label": "OpenAI — GPT-Image-1 (premium, ~$0.07/image)",
    },
    "gemini_nano_banana": {
        "provider": "gemini", "model": "gemini-2.5-flash-image",
        "price_per_image_usd": 0.04,
        "label": "Google — Nano Banana (mid, ~$0.04/image)",
    },
    "gemini_nano_banana_pro": {
        "provider": "gemini", "model": "gemini-3-pro-image-preview",
        "price_per_image_usd": 0.15,
        "label": "Google — Nano Banana Pro (premium, ~$0.15/image)",
    },
    "replicate_flux_schnell": {
        "provider": "replicate", "model": "black-forest-labs/flux-schnell",
        "price_per_image_usd": 0.003,
        "label": "Replicate — FLUX.1 Schnell (cheap, ~$0.003/image)",
    },
    "replicate_flux_dev": {
        "provider": "replicate", "model": "black-forest-labs/flux-dev",
        "price_per_image_usd": 0.025,
        "label": "Replicate — FLUX.1 Dev (mid, ~$0.025/image)",
    },
    "replicate_sdxl": {
        "provider": "replicate", "model": "stability-ai/sdxl",
        "price_per_image_usd": 0.0055,
        "label": "Replicate — SDXL (cheap, ~$0.0055/image)",
    },
    "fal_flux_schnell": {
        "provider": "fal", "model": "fal-ai/flux/schnell",
        "price_per_image_usd": 0.003,
        "label": "fal.ai — FLUX.1 Schnell (cheap, ~$0.003/image)",
    },
    "fal_flux_dev": {
        "provider": "fal", "model": "fal-ai/flux/dev",
        "price_per_image_usd": 0.025,
        "label": "fal.ai — FLUX.1 Dev (mid, ~$0.025/image)",
    },
}


def build_image_gen_provider(
    preset_id: str, openai_key: str, gemini_key: str, replicate_key: str, fal_key: str,
) -> ImageGenProvider:
    preset = IMAGE_GEN_PRESETS.get(preset_id)
    if preset is None:
        raise ValueError(f"Unknown image-gen preset {preset_id!r}")
    provider, model = preset["provider"], preset["model"]

    if provider == "openai":
        from docu_studio.adapters.image_gen.openai_adapter import OpenAIImageGenAdapter
        return OpenAIImageGenAdapter(api_key=openai_key, model=model)
    if provider == "gemini":
        from docu_studio.adapters.image_gen.gemini_adapter import GeminiImageGenAdapter
        return GeminiImageGenAdapter(api_key=gemini_key, model=model)
    if provider == "replicate":
        from docu_studio.adapters.image_gen.replicate_adapter import ReplicateImageGenAdapter
        return ReplicateImageGenAdapter(api_key=replicate_key, model=model)
    from docu_studio.adapters.image_gen.fal_adapter import FalImageGenAdapter
    return FalImageGenAdapter(api_key=fal_key, model=model)
