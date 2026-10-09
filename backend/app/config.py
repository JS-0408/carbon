"""Settings loader: config.yaml plus environment overrides (Section 18 of the spec)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


@dataclass
class RegionCfg:
    key: str
    label: str
    synthetic: bool
    profile: dict
    codes: dict = field(default_factory=dict)


@dataclass
class Settings:
    step_min: int = 30
    cap_kw: float = 8.0
    pad: float = 1.25
    pad_by_type: dict = field(default_factory=dict)
    tick_steps: int = 12
    timeline_steps: int = 288
    replan_alert_steps: int = 4
    provider: str = "mock"
    provider_timeout_s: float = 5.0
    cache_ttl_min: float = 15.0
    stale_after_min: float = 180.0
    bench_seeds: int = 20
    transfer_g_per_gb: float = 5.0
    overrun_by_type: dict = field(default_factory=dict)
    regions: dict = field(default_factory=dict)
    casdk_url: str | None = None
    watttime_user: str | None = None
    watttime_pass: str | None = None
    emaps_token: str | None = None
    emaps_base: str = "https://api.electricitymap.org/v4"  # docs now show v4; spec said v3 (see DECISIONS.md)
    api_key: str | None = None

    @property
    def spd(self) -> int:
        return 24 * 60 // self.step_min

    def pad_for(self, wtype: str) -> float:
        return float(self.pad_by_type.get(wtype, self.pad))

    def copy(self, **kw) -> "Settings":
        import dataclasses
        return dataclasses.replace(self, **kw)


_ENV = {
    "STEP_MIN": ("step_min", int), "CAP_KW": ("cap_kw", float), "PAD": ("pad", float),
    "TICK_STEPS": ("tick_steps", int), "PROVIDER": ("provider", str),
    "PROVIDER_TIMEOUT_S": ("provider_timeout_s", float), "CACHE_TTL_MIN": ("cache_ttl_min", float),
    "STALE_AFTER_MIN": ("stale_after_min", float), "BENCH_SEEDS": ("bench_seeds", int),
    "CASDK_URL": ("casdk_url", str), "WATTTIME_USER": ("watttime_user", str),
    "WATTTIME_PASS": ("watttime_pass", str), "EMAPS_TOKEN": ("emaps_token", str),
    "EMAPS_BASE": ("emaps_base", str), "API_KEY": ("api_key", str),
}


def load_settings(path: Path | None = None) -> Settings:
    path = path or Path(os.environ.get("CONFIG_FILE", ROOT / "config.yaml"))
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
    regions = {k: RegionCfg(k, v.get("label", k), bool(v.get("synthetic", True)), v["profile"], v.get("codes") or {})
               for k, v in (raw.pop("regions", None) or {}).items()}
    known = Settings.__dataclass_fields__
    s = Settings(**{k: v for k, v in raw.items() if k in known}, regions=regions)
    for env, (attr, cast) in _ENV.items():
        if os.environ.get(env):
            setattr(s, attr, cast(os.environ[env]))
    if 60 % s.step_min:
        raise ValueError("STEP_MIN must divide 60")
    if not s.regions:
        s.regions = {"default": RegionCfg("default", "Default (synthetic)", True,
                                          {"base": 700, "dip": 170, "dip_c": 13, "dip_w": 3.2, "peak": 90,
                                           "peak_c": 20, "peak_w": 1.8})}
    return s
