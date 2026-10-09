"""UK Carbon Intensity API (keyless, real data). Used as a REAL-DATA REPLAY: the last ~6 days of
half-hourly published `forecast` and `actual` values drive the simulated clock, so planning uses
real forecasts and realized savings use real actuals. This is Great Britain, not India."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from ..config import ROOT
from .base import ProviderError, SeriesProvider, iso, parse_ts

BASE = "https://api.carbonintensity.org.uk"
SNAPSHOT = ROOT / "backend" / "data" / "uk_snapshot.json"


class UKReplayProvider(SeriesProvider):
    name = "uk_replay"
    synthetic = False

    def __init__(self, timeout: float = 15.0, transport=None, use_snapshot: bool = True, days: int = 6,
                 force_snapshot: bool = False):
        self.timeout, self.transport, self.use_snapshot, self.days = timeout, transport, use_snapshot, days
        self.force_snapshot = force_snapshot
        self.fc: list | None = None
        self.act: list | None = None
        self.meta: dict = {}

    def _fetch_live(self) -> dict:
        end = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) - timedelta(hours=2)
        start = end - timedelta(days=self.days)
        url = f"{BASE}/intensity/{start.strftime('%Y-%m-%dT%H:%MZ')}/{end.strftime('%Y-%m-%dT%H:%MZ')}"
        with httpx.Client(timeout=self.timeout, transport=self.transport) as c:
            r = c.get(url, headers={"Accept": "application/json"})
            r.raise_for_status()
            data = r.json()["data"]
        if not data:
            raise ProviderError("UK API returned no data")
        return {"fetched_at": iso(datetime.now(timezone.utc)), "from": data[0]["from"], "to": data[-1]["to"],
                "points": [{"from": d["from"], "forecast": d["intensity"]["forecast"],
                            "actual": d["intensity"]["actual"]} for d in data]}

    def load(self) -> None:
        if self.fc is not None:
            return
        snap, live = None, True
        if self.force_snapshot and self.use_snapshot and SNAPSHOT.exists():
            snap, live = json.loads(SNAPSHOT.read_text(encoding="utf-8")), False
        else:
            try:
                snap = self._fetch_live()
                if self.use_snapshot:
                    SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
                    SNAPSHOT.write_text(json.dumps(snap), encoding="utf-8")
            except Exception as e:                       # network down: use last real snapshot if present
                if self.use_snapshot and SNAPSHOT.exists():
                    snap, live = json.loads(SNAPSHOT.read_text(encoding="utf-8")), False
                else:
                    raise ProviderError(f"UK Carbon Intensity API unavailable: {e}")
        pts = [p for p in snap["points"] if p["forecast"] is not None or p["actual"] is not None]
        self.fc = [float(p["forecast"] if p["forecast"] is not None else p["actual"]) for p in pts]
        self.act = [float(p["actual"] if p["actual"] is not None else self.fc[i]) for i, p in enumerate(pts)]
        self.meta = {"live": live, "fetched_at": snap["fetched_at"], "from": snap["from"], "to": snap["to"],
                     "points": len(pts)}

    def actual(self, region: str, total: int, step_min: int) -> list:
        if region != "uk":
            raise ProviderError("UK replay only serves region 'uk'")
        if step_min != 30:
            raise ProviderError("UK API is half-hourly; STEP_MIN must be 30")
        self.load()
        return (self.act + self.act[-48:] * total)[:total]

    def series_forecast(self, region: str, now: int, total: int, step_min: int) -> list:
        act = self.actual(region, total, step_min)
        fc = (self.fc + self.fc[-48:] * total)[:total]
        return [act[t] if t < now else fc[t] for t in range(total)]
