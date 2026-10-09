"""Deterministic synthetic provider (default for tests and demo). Always labelled synthetic."""
from __future__ import annotations

import random
from typing import Callable, Optional

from ..config import Settings
from ..core import profile_series
from .base import ProviderError, SeriesProvider


class MockProvider(SeriesProvider):
    name = "mock"
    synthetic = True

    def __init__(self, settings: Settings, seed: int = 0, solar: float = 1.0, fc_noise: float = 1.0,
                 act_noise: float = 0.03, fail_fn: Optional[Callable[[int], bool]] = None):
        self.s, self.seed, self.solar = settings, seed, solar
        self.fc_noise, self.act_noise = fc_noise, act_noise
        self.fail_fn = fail_fn
        self.down = False            # manual outage switch (demo API-outage moment)
        self._actual: dict = {}

    def actual(self, region: str, total: int, step_min: int) -> list:
        key = (region, total)
        if key not in self._actual:
            rng = random.Random(f"{self.seed}:{region}:actual")
            base = profile_series(self.s.regions[region].profile, total, step_min, self.solar)
            self._actual[key] = [b * (1 + rng.gauss(0, self.act_noise)) for b in base]
        return self._actual[key]

    def series_forecast(self, region: str, now: int, total: int, step_min: int) -> list:
        if self.down or (self.fail_fn and self.fail_fn(now)):
            raise ProviderError("simulated provider outage")
        act = self.actual(region, total, step_min)
        rng = random.Random(f"{self.seed}:{region}:{now}")
        return [act[t] if t < now else
                act[t] * (1 + self.fc_noise * rng.gauss(0, min(0.15, 0.03 + 0.002 * (t - now))))
                for t in range(total)]
