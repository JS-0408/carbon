"""Carbon Aware SDK (GSF) WebApi adapter. Primary live provider (self-hosted).

GET {CASDK_URL}/emissions/forecasts/current?location=<loc>&dataStartAt=<iso>&dataEndAt=<iso>&windowSize=<min>
-> list (one per location) with forecastData[{timestamp,duration,value}] and optimalDataPoints.
We only use forecastData and compute emissions ourselves (the SDK returns window averages).
"""
from __future__ import annotations

from datetime import datetime

import httpx

from .base import PointProvider, ProviderError, iso, parse_ts


class CarbonAwareSDKProvider(PointProvider):
    name = "carbon_aware_sdk"

    def __init__(self, base_url: str | None, timeout: float = 5.0, transport=None, window_min: int = 30):
        self.base_url, self.timeout, self.transport, self.window = (base_url or "").rstrip("/"), timeout, transport, window_min

    def fetch_points(self, region_cfg, start: datetime, end: datetime):
        if not self.base_url:
            raise ProviderError("CASDK_URL is not configured")
        loc = (region_cfg.codes.get("carbon_aware_sdk") or {}).get("location")
        if not loc:
            raise ProviderError(f"region {region_cfg.key} has no carbon_aware_sdk location in config.yaml")
        try:
            with httpx.Client(timeout=self.timeout, transport=self.transport) as c:
                r = c.get(f"{self.base_url}/emissions/forecasts/current",
                          params={"location": loc, "dataStartAt": iso(start), "dataEndAt": iso(end),
                                  "windowSize": self.window})
                r.raise_for_status()
                body = r.json()
        except httpx.HTTPError as e:
            raise ProviderError(f"Carbon Aware SDK request failed: {e}")
        forecasts = body if isinstance(body, list) else [body]
        if not forecasts or not forecasts[0].get("forecastData"):
            raise ProviderError("Carbon Aware SDK returned no forecastData")
        f = forecasts[0]
        pts = [(parse_ts(d["timestamp"]), float(d["value"])) for d in f["forecastData"]]   # already gCO2/kWh
        gen = f.get("generatedAt") or f.get("requestedAt")
        return pts, (parse_ts(gen) if gen else None)
