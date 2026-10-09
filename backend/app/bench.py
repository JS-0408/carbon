"""Benchmark (R13, Section 14): five scenarios x N seeds, driven through the real Engine.

Run:  python -m backend.app.bench [--seeds 20] [--out bench/results.json]
Job generator and scenario parameters are ported from reference/carbon_scheduler.py. Mapping note:
reference `urgent_inference` is treated as `realtime_inference` (never delayed, INV6), so savings can differ
slightly from the reference table. Intensity data is SYNTHETIC.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

from .config import ROOT, Settings, load_settings
from .core import Job
from .engine import Engine
from .estimator import n_steps
from .providers import MockProvider, UKReplayProvider

KINDS = {  # kind: (workload_type, dur_lo, dur_hi, kw, slack_lo, slack_hi, weight)
    "urgent_inference": ("realtime_inference", 30, 60, 2.0, 1, 3, 2),
    "batch_inference": ("batch_inference", 60, 120, 1.5, 6, 14, 3),
    "training": ("model_training", 120, 360, 3.0, 12, 30, 3),
    "etl": ("etl", 60, 120, 1.0, 24, 40, 2),
}

SCENARIOS = [
    ("weekday_mix", "12 mixed jobs, normal forecast, 8 kW cluster", dict(n=12)),
    ("tight_deadlines", "Same mix but deadlines cut to a quarter of normal slack", dict(n=12, tight=True)),
    ("api_outage", "Carbon API down for 12 hours; fallback profile in use", dict(n=12, outage=[1, 2])),
    ("overrun_cloudy", "Cloudy day (weak solar dip) and training jobs run 45% longer than estimated",
     dict(n=12, solar=0.35, overrun=1.45)),
    ("heavy_load", "24 jobs competing for the same 8 kW", dict(n=24)),
    ("uk_real_data", "12 mixed jobs replayed on REAL Great Britain grid data (UK Carbon Intensity API)",
     dict(n=12, real_data="uk")),
]
SCENARIO_MAP = {n: (d, sc) for n, d, sc in SCENARIOS}


def bench_settings(base: Settings | None = None, **over) -> Settings:
    s = base or load_settings()
    regions = {"default": s.regions["default"]}
    if "uk" in s.regions:
        regions["uk"] = s.regions["uk"]
    return s.copy(regions=regions, **over)


def gen_jobs(rng: random.Random, n: int, tight: bool, step: int, spd: int) -> list[dict]:
    jobs, kinds = [], list(KINDS)
    for i in range(n):
        k = rng.choices(kinds, [KINDS[x][6] for x in kinds])[0]
        wt, lo, hi, kw, sl, sh, _ = KINDS[k]
        dur = rng.randrange(lo, hi + 1, 30)
        sub, slack = rng.randrange(0, spd), rng.randint(sl, sh)
        if tight:
            slack = max(1, slack // 4)
        jobs.append(dict(id=f"{k[:3]}-{i + 1:02d}", kind=k, wtype=wt, dur=dur, kw=kw, sub=sub,
                         dl=sub + math.ceil(dur / step) + slack))
    return jobs


def make_job(eng: Engine, spec: dict, overrun: float, home: str = "default", allowed: list | None = None,
             data_gb: float = 0.0) -> Job:
    f = overrun if spec["wtype"] == "model_training" else 1.0
    pn = eng.estimator.planned_steps(spec["wtype"], spec["dur"])
    j = Job(id=spec["id"], wtype=spec["wtype"], kw=spec["kw"], sub=spec["sub"], dl=spec["dl"],
            n_est=eng.estimator.estimate_steps(spec["dur"]), pn=pn,
            an=n_steps(spec["dur"] * f, eng.s.step_min), home=home, allowed=allowed or [home], data_gb=data_gb)
    j.meta.update(est_min=spec["dur"], act_min=spec["dur"] * f, kind=spec["kind"])
    return j


def run_once(settings: Settings, sc: dict, seed: int, keep_detail: bool = False) -> dict:
    s = settings
    tick = s.tick_steps
    outage = set(sc.get("outage", []))
    is_uk = sc.get("real_data") == "uk"
    if is_uk:
        prov = UKReplayProvider(use_snapshot=True, force_snapshot=True)
        prov.load()
        origin = datetime.fromisoformat(prov.meta["from"].replace("Z", "+00:00"))
        eng = Engine(s, provider=prov, seed=seed, auto_replan=False, origin=origin, adaptive_pad=False)
        home_region = "uk"
    else:
        prov = MockProvider(s, seed=seed, solar=sc.get("solar", 1.0), fail_fn=lambda now: (now // tick) in outage)
        eng = Engine(s, provider=prov, seed=seed, auto_replan=False, origin=datetime(2026, 10, 9, tzinfo=timezone.utc),
                     adaptive_pad=False)
        home_region = "default"
    rng = random.Random(seed)
    specs = gen_jobs(rng, sc["n"], sc.get("tight", False), s.step_min, s.spd)
    revealed: set = set()
    for tick_start in range(0, s.spd * 3, tick):
        for sp in specs:
            if sp["id"] not in revealed and sp["sub"] < tick_start + tick:
                revealed.add(sp["id"])
                eng.add_job(make_job(eng, sp, sc.get("overrun", 1.0), home=home_region, allowed=[home_region]), plan_now=False)
        eng.replan("tick")
        eng.advance(tick)
    while any(j.state != "DONE" for j in eng.jobs.values()) and eng.now < s.timeline_steps - 80:
        eng.advance(1)
    m = eng.metrics()
    r = m["realized"]
    out = {"seed": seed, "jobs": len(specs), "done": r["jobs"] if r else 0,
           "savings_pct": r["savings_pct"] if r else 0.0, "e_base_g": r["e_base_g"] if r else 0,
           "e_opt_g": r["e_opt_g"] if r else 0,
           "forecasted_savings_pct": m["forecasted"]["savings_pct"] if m["forecasted"] else 0.0,
           "hit_base": m["deadlines"]["base_pct"] if m["deadlines"] else 0.0,
           "hit_opt": m["deadlines"]["opt_pct"] if m["deadlines"] else 0.0,
           "wait_base_min": m["wait"]["base_min"] if m["wait"] else 0,
           "wait_opt_min": m["wait"]["opt_min"] if m["wait"] else 0,
           "alert_types": sorted(eng.alerts.types())}
    if keep_detail:
        out["detail"] = {"jobs": eng.jobs_view(), "alerts": eng.alerts.as_list(),
                         "series": [round(v) for v in eng.actual[home_region][:s.spd * 3]]}
    return out


def summarize(runs: list[dict]) -> dict:
    def mean(k):
        return round(statistics.mean(x[k] for x in runs), 2)
    sv = [x["savings_pct"] for x in runs]
    return {"seeds": len(runs), "savings_mean": mean("savings_pct"), "savings_min": min(sv), "savings_max": max(sv),
            "savings_stdev": round(statistics.pstdev(sv), 2), "negative_runs": sum(v < 0 for v in sv),
            "forecasted_savings_mean": mean("forecasted_savings_pct"),
            "hit_base": mean("hit_base"), "hit_opt": mean("hit_opt"),
            "wait_base_min": mean("wait_base_min"), "wait_opt_min": mean("wait_opt_min"),
            "e_base_g_mean": round(statistics.mean(x["e_base_g"] for x in runs)),
            "e_opt_g_mean": round(statistics.mean(x["e_opt_g"] for x in runs))}


def run_scenario(name: str, seeds: int = 20, settings: Settings | None = None, index: int | None = None) -> dict:
    s = settings or bench_settings()
    desc, sc = SCENARIO_MAP[name]
    i = index if index is not None else [n for n, _, _ in SCENARIOS].index(name)
    runs = [run_once(s, sc, 100 * i + k, keep_detail=(k == 0)) for k in range(seeds)]
    res = {"name": name, "desc": desc, "kpi": summarize(runs), "seed0": runs[0].get("detail"),
           "per_seed_savings": [r["savings_pct"] for r in runs]}
    return res


def run_all(seeds: int = 20, settings: Settings | None = None) -> dict:
    s = settings or bench_settings()
    results = [run_scenario(n, seeds, s, i) for i, (n, _, _) in enumerate(SCENARIOS)]
    return {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "seeds": seeds,
            "data": "synthetic (mock provider) + real data (UK Carbon Intensity API)",
            "pad": s.pad, "pad_by_type": s.pad_by_type, "scenarios": results}


def compare_padding(seeds: int = 20) -> dict:
    """T18 before/after: reference padding (1.25 for all) vs per-type padding (training 1.6)."""
    before = run_all(seeds, bench_settings(pad_by_type={}))
    after = run_all(seeds, bench_settings())
    return {"before": before, "after": after}


def markdown_table(res: dict) -> str:
    lines = ["| Scenario | Savings mean (min..max) | Neg. runs | Deadlines met, immediate -> scheduled | Avg wait (min), immediate -> scheduled |",
             "|---|---|---|---|---|"]
    for r in res["scenarios"]:
        k = r["kpi"]
        lines.append(f"| {r['name']} | {k['savings_mean']:.1f}% ({k['savings_min']:.1f}..{k['savings_max']:.1f}) | "
                     f"{k['negative_runs']}/{k['seeds']} | {k['hit_base']:.0f}% -> {k['hit_opt']:.0f}% | "
                     f"{k['wait_base_min']:.0f} -> {k['wait_opt_min']:.0f} |")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=None)
    ap.add_argument("--out", default=str(ROOT / "bench" / "results.json"))
    ap.add_argument("--compare", action="store_true", help="also run T18 before/after padding comparison")
    a = ap.parse_args(argv)
    s = load_settings()
    seeds = a.seeds or s.bench_seeds
    res = run_all(seeds, bench_settings(s))
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res), encoding="utf-8")
    md = markdown_table(res)
    (out.parent / "results.md").write_text(md + "\n", encoding="utf-8")
    print(md)
    if a.compare:
        cmp = compare_padding(seeds)
        (out.parent / "padding_comparison.json").write_text(json.dumps(
            {k: {"pad_by_type": v["pad_by_type"], "scenarios": {r["name"]: r["kpi"] for r in v["scenarios"]}}
             for k, v in cmp.items()}, indent=1), encoding="utf-8")
        print("\nBEFORE (pad 1.25 everywhere):\n" + markdown_table(cmp["before"]))
        print("\nAFTER (training pad 1.6):\n" + markdown_table(cmp["after"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
