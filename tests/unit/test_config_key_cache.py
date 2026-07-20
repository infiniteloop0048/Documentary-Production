"""Unit tests for the new AI-image-generation credential slots in key_cache."""
from __future__ import annotations

from docu_studio.config.key_cache import _USERNAMES


class TestImageGenCredentialSlots:
    def test_gemini_replicate_fal_usernames_present(self) -> None:
        assert "docu_studio_gemini" in _USERNAMES
        assert "docu_studio_replicate" in _USERNAMES
        assert "docu_studio_fal" in _USERNAMES
