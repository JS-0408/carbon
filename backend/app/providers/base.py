"""Provider interface and shared helpers (Section 7). All adapters normalise to gCO2/kWh."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

LBS_PER_MWH_TO_G_PER_KWH = 0.45359237   # WattTime MOER is lbs CO2/MWh


def lbs_mwh_to_g_kwh(x: float) -> float:
    return x * LBS_PER_MWH_TO_G_PER_KWH


def parse_ts(s: str) -> datetime:
    d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def iso(d: datetime) -> str:
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class ProviderError(Exception):
    """Any provider failure (timeout, HTTP error, empty or invalid data)."""


class ProviderAccessError(ProviderError):
    """Credentials valid but plan lacks access (e.g. WattTime free tier outside CAISO_NORTH)."""


@dataclass
class Forecast:
    region: str
    generated_at: str
    source: str                  # carbon_aware_sdk|watttime|electricitymaps|uk_replay|fallback|mock
    step_minutes: int
    values: list                 # absolute-indexed gCO2/kWh, one per step from timeline step 0
    is_fallback: bool = False
    partial: bool = False        # provider covered only part of the horizon; rest filled by fallback profile
    synthetic: bool = False
    note: str = ""


class SeriesProvider:
    """Simulation-style provider: returns a full absolute-indexed series for a clock position."""
    kind = "series"
    name = "series"
    synthetic = False

    def series_forecast(self, region: str, now: int, total: int, step_min: int) -> list:
        raise NotImplementedError

    def actual(self, region: str, total: int, step_min: int) -> list | None:
        return None


class PointProvider:
    """Live provider: returns timestamped points (UTC) that the observer resamples onto steps."""
    kind = "points"
    name = "points"
    synthetic = False

    def fetch_points(self, region_cfg, start: datetime, end: datetime) -> tuple[list, datetime | None]:
        """-> ([(datetime, g_per_kwh), ...] sorted, generated_at or None)"""
        raise NotImplementedError


def resample(points: list, origin: datetime, step_min: int, now: int, total: int) -> list:
    """Map (datetime, value) points onto steps [now, now+k). Stops at first uncovered step."""
    if not points:
        return []
    pts = sorted(points, key=lambda p: p[0])
    out, i = [], 0
    last_end = pts[-1][0] + timedelta(minutes=step_min)
    for t in range(now, total):
        when = origin + timedelta(minutes=t * step_min)
        if when >= last_end or when < pts[0][0]:
            if out:
                break
            continue
        while i + 1 < len(pts) and pts[i + 1][0] <= when:
            i += 1
        out.append(pts[i][1])
    return out


def valid_series(vals) -> bool:
    return bool(vals) and all(isinstance(v, (int, float)) and math.isfinite(v) and v > 0 for v in vals)
