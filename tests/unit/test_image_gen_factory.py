"""Unit tests for docu_studio.adapters.image_gen.factory."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from docu_studio.adapters.image_gen.factory import (
    IMAGE_GEN_PRESETS,
    build_image_gen_provider,
)


class TestImageGenPresets:
    def test_covers_all_four_providers(self) -> None:
        providers = {preset["provider"] for preset in IMAGE_GEN_PRESETS.values()}
        assert providers == {"openai", "gemini", "replicate", "fal"}

    def test_every_preset_has_a_positive_price(self) -> None:
        for preset_id, preset in IMAGE_GEN_PRESETS.items():
            assert preset["price_per_image_usd"] > 0, preset_id

    def test_every_preset_has_a_label(self) -> None:
        for preset_id, preset in IMAGE_GEN_PRESETS.items():
            assert preset["label"], preset_id


class TestBuildImageGenProvider:
    def test_openai_preset_builds_openai_adapter_with_model_and_key(self) -> None:
        with patch("docu_studio.adapters.image_gen.openai_adapter.OpenAIImageGenAdapter") as mock_cls:
            build_image_gen_provider("openai_gpt_image_1", "openai-key", "", "", "")
        mock_cls.assert_called_once_with(api_key="openai-key", model="gpt-image-1")

    def test_gemini_preset_builds_gemini_adapter_with_model_and_key(self) -> None:
        with patch("docu_studio.adapters.image_gen.gemini_adapter.GeminiImageGenAdapter") as mock_cls:
            build_image_gen_provider("gemini_nano_banana_pro", "", "gemini-key", "", "")
        mock_cls.assert_called_once_with(api_key="gemini-key", model="gemini-3-pro-image-preview")

    def test_replicate_preset_builds_replicate_adapter_with_model_and_key(self) -> None:
        with patch("docu_studio.adapters.image_gen.replicate_adapter.ReplicateImageGenAdapter") as mock_cls:
            build_image_gen_provider("replicate_flux_schnell", "", "", "replicate-key", "")
        mock_cls.assert_called_once_with(api_key="replicate-key", model="black-forest-labs/flux-schnell")

    def test_fal_preset_builds_fal_adapter_with_model_and_key(self) -> None:
        with patch("docu_studio.adapters.image_gen.fal_adapter.FalImageGenAdapter") as mock_cls:
            build_image_gen_provider("fal_flux_dev", "", "", "", "fal-key")
        mock_cls.assert_called_once_with(api_key="fal-key", model="fal-ai/flux/dev")

    def test_unknown_preset_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown image-gen preset"):
            build_image_gen_provider("not_a_real_preset", "", "", "", "")
