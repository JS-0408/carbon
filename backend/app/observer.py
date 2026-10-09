"""Observer: forecast retrieval with retries, TTL cache, validation and a guaranteed fallback.

The observer NEVER raises to callers (INV4): on timeout, HTTP error, empty/invalid data or stale data
it returns the historical-average diurnal profile for the region with is_fallback=True.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from .config import Settings
from .core import profile_series
from .providers.base import Forecast, PointProvider, ProviderError, SeriesProvider, iso, resample, valid_series


class Observer:
    def __init__(self, settings: Settings, provider, origin: datetime, clock=time.monotonic,
                 now_dt=lambda: datetime.now(timezone.utc), backoff_s: float = 0.2, retries: int = 2):
        self.s, self.provider, self.origin = settings, provider, origin
        self.clock, self.now_dt, self.backoff_s, self.retries = clock, now_dt, backoff_s, retries
        self._cache: dict = {}
        self.last_error: str | None = None

    def invalidate(self) -> None:
        self._cache.clear()

    # ---------------------------------------------------------------- fallback
    def fallback(self, region: str, total: int, why: str) -> Forecast:
        cfg = self.s.regions[region]
        return Forecast(region=region, generated_at=iso(self.now_dt()), source="fallback",
                        step_minutes=self.s.step_min,
                        values=profile_series(cfg.profile, total, self.s.step_min),
                        is_fallback=True, synthetic=True,
                        note=f"Static historical-average profile in use ({why}).")

    # ---------------------------------------------------------------- public
    def get_forecast(self, region: str, now: int, total: int) -> Forecast:
        key = (region, now, total)
        hit = self._cache.get(key)
        if hit and self.clock() - hit[0] < self.s.cache_ttl_min * 60:
            return hit[1]
        err = "unknown error"
        for attempt in range(self.retries + 1):
            try:
                fc = self._fetch(region, now, total)
                self._cache[key] = (self.clock(), fc)
                self.last_error = None
                return fc
            except ProviderError as e:
                err = str(e)
            except Exception as e:                      # adapters must not break the planner
                err = f"{type(e).__name__}: {e}"
            if attempt < self.retries and self.backoff_s:
                time.sleep(self.backoff_s * (2 ** attempt))
        self.last_error = err
        return self.fallback(region, total, err)

    # ---------------------------------------------------------------- internals
    def _fetch(self, region: str, now: int, total: int) -> Forecast:
        p = self.provider
        step = self.s.step_min
        cfg = self.s.regions[region]
        if p.kind == "series":
            vals = p.series_forecast(region, now, total, step)
            if len(vals) < total or not valid_series(vals):
                raise ProviderError("provider returned empty or invalid series")
            return Forecast(region, iso(self.now_dt()), p.name, step, [float(v) for v in vals],
                            synthetic=p.synthetic, note="Synthetic data" if p.synthetic else "Real data replay")
        start = self.origin + timedelta(minutes=now * step)
        end = self.origin + timedelta(minutes=total * step)
        pts, gen = p.fetch_points(cfg, start, end)
        if gen is not None and self.now_dt() - gen > timedelta(minutes=self.s.stale_after_min):
            raise ProviderError(f"forecast is stale (generated {iso(gen)})")
        part = resample(pts, self.origin, step, now, total)
        if not part or not valid_series(part):
            raise ProviderError("provider returned no usable points for the planning window")
        base = profile_series(cfg.profile, total, step)          # fill gaps (past steps, uncovered tail)
        vals = base[:now] + part + base[now + len(part):total]
        partial = now + len(part) < total
        return Forecast(region, iso(gen or self.now_dt()), p.name, step, vals, partial=partial,
                        synthetic=False,
                        note="Provider covers only part of the horizon; remainder uses the static profile." if partial else "")
