"""Provider registry/factory."""
from __future__ import annotations

from ..config import Settings
from .base import (Forecast, PointProvider, ProviderAccessError, ProviderError, SeriesProvider,  # noqa: F401
                   lbs_mwh_to_g_kwh)
from .carbon_aware_sdk import CarbonAwareSDKProvider
from .electricitymaps import ElectricityMapsProvider
from .mock import MockProvider
from .uk import UKReplayProvider
from .watttime import WattTimeProvider

PROVIDERS = ("mock", "uk_replay", "carbon_aware_sdk", "watttime", "electricitymaps")


def make_provider(name: str, settings: Settings, seed: int = 0, **kw):
    if name == "mock":
        return MockProvider(settings, seed=seed, **kw)
    if name == "uk_replay":
        return UKReplayProvider(timeout=max(settings.provider_timeout_s, 15))
    if name == "carbon_aware_sdk":
        return CarbonAwareSDKProvider(settings.casdk_url, settings.provider_timeout_s)
    if name == "watttime":
        return WattTimeProvider(settings.watttime_user, settings.watttime_pass, settings.provider_timeout_s)
    if name == "electricitymaps":
        return ElectricityMapsProvider(settings.emaps_token, settings.emaps_base, settings.provider_timeout_s)
    raise ValueError(f"unknown provider '{name}'. Choose one of {', '.join(PROVIDERS)}")
