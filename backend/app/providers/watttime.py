"""WattTime v3 adapter (optional, feature-flagged by credentials).

Free (Basic) plan only covers region CAISO_NORTH. India is a national region (IND), not per state, and
requires a paid plan. Always resolve the region with /v3/region-from-loc. Signal: co2_moer (MARGINAL),
unit lbs CO2/MWh -> converted to g/kWh. Do not mix with average signals in one comparison.
"""
from __future__ import annotations

from datetime import datetime

import httpx

from .base import PointProvider, ProviderAccessError, ProviderError, lbs_mwh_to_g_kwh, parse_ts

BASE = "https://api.watttime.org"


class WattTimeProvider(PointProvider):
    name = "watttime"

    def __init__(self, user: str | None, password: str | None, timeout: float = 5.0, transport=None,
                 base: str = BASE, signal: str = "co2_moer"):
        self.user, self.password, self.timeout, self.transport, self.base, self.signal = user, password, timeout, transport, base, signal
        self._token: str | None = None
        self._regions: dict = {}

    def _client(self):
        return httpx.Client(timeout=self.timeout, transport=self.transport)

    def _login(self, c: httpx.Client) -> str:
        if not (self.user and self.password):
            raise ProviderError("WATTTIME_USER / WATTTIME_PASS are not configured")
        r = c.get(f"{self.base}/login", auth=(self.user, self.password))
        r.raise_for_status()
        self._token = r.json()["token"]
        return self._token

    def _get(self, c, path, params):
        token = self._token or self._login(c)
        r = c.get(f"{self.base}{path}", params=params, headers={"Authorization": f"Bearer {token}"})
        if r.status_code == 401:                       # token expired (30 min): re-login once
            token = self._login(c)
            r = c.get(f"{self.base}{path}", params=params, headers={"Authorization": f"Bearer {token}"})
        if r.status_code == 403:
            raise ProviderAccessError("WattTime denied access to this region/signal. The free plan only "
                                      "includes region CAISO_NORTH; upgrade the plan or use another provider.")
        r.raise_for_status()
        return r.json()

    def resolve_region(self, c, region_cfg) -> str:
        if region_cfg.key in self._regions:
            return self._regions[region_cfg.key]
        loc = (region_cfg.codes.get("watttime") or {})
        if "region" in loc:
            code = loc["region"]
        elif "lat" in loc and "lon" in loc:
            j = self._get(c, "/v3/region-from-loc", {"latitude": loc["lat"], "longitude": loc["lon"],
                                                      "signal_type": self.signal})
            code = j["region"]
        else:
            raise ProviderError(f"region {region_cfg.key} has no watttime lat/lon in config.yaml")
        self._regions[region_cfg.key] = code
        return code

    def fetch_points(self, region_cfg, start: datetime, end: datetime):
        try:
            with self._client() as c:
                region = self.resolve_region(c, region_cfg)
                j = self._get(c, "/v3/forecast", {"region": region, "signal_type": self.signal, "horizon_hours": 72})
        except ProviderError:
            raise
        except (httpx.HTTPError, KeyError, ValueError) as e:
            raise ProviderError(f"WattTime request failed: {e}")
        data = j.get("data") or []
        if not data:
            raise ProviderError("WattTime returned no forecast points")
        pts = [(parse_ts(d["point_time"]), lbs_mwh_to_g_kwh(float(d["value"]))) for d in data]
        gen = (j.get("meta") or {}).get("generated_at")
        return pts, (parse_ts(gen) if gen else None)
