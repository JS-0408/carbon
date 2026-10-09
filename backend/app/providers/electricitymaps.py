"""Electricity Maps adapter (optional). Grid AVERAGE signal, already gCO2eq/kWh.

GET {base}/carbon-intensity/forecast?zone=<zone>&horizonHours=72  header: auth-token
The free tier has no forecast endpoint (latest + 24 h history only) and is limited to one zone, so a
403 is reported as an access error. Current docs show v4; the base URL is configurable (EMAPS_BASE).
"""
from __future__ import annotations

from datetime import datetime

import httpx

from .base import PointProvider, ProviderAccessError, ProviderError, parse_ts


class ElectricityMapsProvider(PointProvider):
    name = "electricitymaps"

    def __init__(self, token: str | None, base: str, timeout: float = 5.0, transport=None):
        self.token, self.base, self.timeout, self.transport = token, base.rstrip("/"), timeout, transport

    def fetch_points(self, region_cfg, start: datetime, end: datetime):
        if not self.token:
            raise ProviderError("EMAPS_TOKEN is not configured")
        zone = (region_cfg.codes.get("electricitymaps") or {}).get("zone")
        if not zone:
            raise ProviderError(f"region {region_cfg.key} has no electricitymaps zone in config.yaml")
        try:
            with httpx.Client(timeout=self.timeout, transport=self.transport) as c:
                r = c.get(f"{self.base}/carbon-intensity/forecast", params={"zone": zone, "horizonHours": 72},
                          headers={"auth-token": self.token})
            if r.status_code in (401, 403):
                raise ProviderAccessError("Electricity Maps denied access. Forecasts need a paid or trial key "
                                          "(free tier: latest/history only, one zone).")
            r.raise_for_status()
            j = r.json()
        except ProviderError:
            raise
        except (httpx.HTTPError, ValueError) as e:
            raise ProviderError(f"Electricity Maps request failed: {e}")
        data = j.get("forecast") or []
        if not data:
            raise ProviderError("Electricity Maps returned no forecast points")
        pts = [(parse_ts(d["datetime"]), float(d["carbonIntensity"])) for d in data if d.get("carbonIntensity") is not None]
        return pts, (parse_ts(j["updatedAt"]) if j.get("updatedAt") else None)
