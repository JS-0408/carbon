"""Demo scenarios: build a ready-to-run Engine (simulated clock) for the dashboard and benchmarks."""
from __future__ import annotations

import random
from datetime import datetime, timezone

from .bench import SCENARIO_MAP, bench_settings, gen_jobs, make_job
from .config import Settings
from .engine import Engine
from .providers import MockProvider, make_provider

EXTRA = {
    "spatial_demo": "12 mixed jobs that may run in 'default' or the cleaner 'hydro' region (data-transfer penalty applies)",
    "uk_real_data": "12 mixed jobs replayed on REAL Great Britain grid data (UK Carbon Intensity API)",
}


def scenario_list() -> list[dict]:
    return [{"name": n, "desc": d} for n, (d, _) in SCENARIO_MAP.items()] + \
           [{"name": n, "desc": d} for n, d in EXTRA.items()]


def build_demo_engine(settings: Settings, scenario: str, seed: int = 0, store=None, backend=None) -> Engine:
    origin = datetime(2026, 10, 9, tzinfo=timezone.utc)
    s = settings
    if scenario in SCENARIO_MAP:
        desc, sc = SCENARIO_MAP[scenario]
        s = bench_settings(settings)
        tick = s.tick_steps
        outage = set(sc.get("outage", []))
        prov = MockProvider(s, seed=seed, solar=sc.get("solar", 1.0), fail_fn=lambda now: (now // tick) in outage)
        eng = Engine(s, provider=prov, seed=seed, origin=origin, store=store, backend=backend)
        rng = random.Random(seed)
        for sp in gen_jobs(rng, sc["n"], sc.get("tight", False), s.step_min, s.spd):
            eng.add_job(make_job(eng, sp, sc.get("overrun", 1.0)))
        return eng
    if scenario == "spatial_demo":
        s = settings.copy(regions={k: v for k, v in settings.regions.items() if k in ("default", "hydro")})
        eng = Engine(s, provider=MockProvider(s, seed=seed), seed=seed, origin=origin, store=store, backend=backend)
        rng = random.Random(seed)
        for sp in gen_jobs(rng, 12, False, s.step_min, s.spd):
            eng.add_job(make_job(eng, sp, 1.0, allowed=["default", "hydro"], data_gb=round(rng.uniform(0, 30), 1)))
        return eng
    if scenario == "uk_real_data":
        s = settings.copy(regions={k: v for k, v in settings.regions.items() if k == "uk"})
        eng = Engine(s, provider=make_provider("uk_replay", s), seed=seed, store=store, backend=backend)
        rng = random.Random(seed)
        for sp in gen_jobs(rng, 12, False, s.step_min, s.spd):
            eng.add_job(make_job(eng, sp, 1.0, home="uk", allowed=["uk"]))
        return eng
    raise KeyError(scenario)
