"""Estimator: planned (padded) duration and an adaptive overrun-aware padding (R4)."""
from __future__ import annotations

import math
from collections import defaultdict

from .config import Settings


def n_steps(minutes: float, step_min: int) -> int:
    return max(1, math.ceil(minutes / step_min - 1e-9))


class Estimator:
    """n_plan = ceil(p90 / dt) when a p90 is given, else ceil(estimate * PAD / dt).

    PAD is per workload type (training overruns most). History of actual/estimated ratios can
    raise the pad (`observe`) but never lowers it below the configured value.
    """

    def __init__(self, settings: Settings, adaptive: bool = True):
        self.s = settings
        self.adaptive = adaptive
        self.history: dict[str, list[float]] = defaultdict(list)

    def pad(self, wtype: str) -> float:
        base = self.s.pad_for(wtype)
        h = self.history[wtype]
        if self.adaptive and len(h) >= 5:
            p90 = sorted(h)[min(len(h) - 1, int(0.9 * len(h)))]
            return min(2.5, max(base, p90 * 1.05))
        return base

    def planned_steps(self, wtype: str, est_min: float, p90_min: float | None = None) -> int:
        if p90_min is not None:
            return n_steps(p90_min, self.s.step_min)
        return n_steps(est_min * self.pad(wtype), self.s.step_min)

    def estimate_steps(self, est_min: float) -> int:
        return n_steps(est_min, self.s.step_min)

    def duration_range(self, wtype: str, est_min: float, p90_min: float | None = None) -> tuple[float, float]:
        """(estimate, padded planning duration) in minutes."""
        return est_min, self.planned_steps(wtype, est_min, p90_min) * self.s.step_min

    def observe(self, wtype: str, estimated_min: float, actual_min: float) -> None:
        if estimated_min > 0:
            self.history[wtype].append(actual_min / estimated_min)
