"""Factory for footage adapters."""
from __future__ import annotations

import logging

from docu_studio.adapters.footage.base import FootageProvider

_log = logging.getLogger(__name__)


def build_footage_providers(
    primary: str,
    fallback: str,
    pexels_key: str,
    pixabay_key: str,
    coverr_key: str = "",
    fallback2: str = "none",
) -> list[FootageProvider]:
    def _build(name: str) -> FootageProvider | None:
        if name == "pexels":
            from docu_studio.adapters.footage.pexels_adapter import PexelsAdapter
            return PexelsAdapter(api_key=pexels_key)
        if name == "pixabay":
            if not pixabay_key:
                return None
            from docu_studio.adapters.footage.pixabay_adapter import PixabayAdapter
            return PixabayAdapter(api_key=pixabay_key)
        if name == "coverr":
            if not coverr_key:
                return None
            from docu_studio.adapters.footage.coverr_adapter import CoverrAdapter
            return CoverrAdapter(api_key=coverr_key)
        return None

    primary_p = _build(primary)
    if primary_p is None:
        primary_p = _build(fallback) or _build("pexels")
        providers = [primary_p] if primary_p else []
        active = [type(p).__name__.removesuffix("Adapter") for p in providers]
        _log.info("Footage providers: %s", active)
        return providers

    providers: list[FootageProvider] = [primary_p]

    if fallback and fallback != primary and fallback != "none":
        fallback_p = _build(fallback)
        if fallback_p:
            providers.append(fallback_p)

    # Append Coverr as extra provider if key is set and not already in a slot
    if coverr_key and primary != "coverr" and fallback != "coverr":
        from docu_studio.adapters.footage.coverr_adapter import CoverrAdapter
        providers.append(CoverrAdapter(api_key=coverr_key))

    if fallback2 and fallback2 != "none" and fallback2 != primary and fallback2 != fallback:
        fb2 = _build(fallback2)
        if fb2 and not any(type(fb2) is type(p) for p in providers):
            providers.append(fb2)

    active = [type(p).__name__.removesuffix("Adapter") for p in providers]
    _log.info("Footage providers: %s", active)
    return providers
