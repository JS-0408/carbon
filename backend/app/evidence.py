"""Evidence: baseline vs optimized emissions, labelled forecasted or realized (R9, Section 12).

Baseline and optimized are always computed with the same signal (same intensity series, same units).
 - forecasted: latest forecast, estimated (unpadded) durations, planned starts.
 - realized:   actual intensity, actual durations, executed starts (DONE jobs only).
"""
from __future__ import annotations

from .core import Job, baseline, cost, penalty


def _pct(eb: float, eo: float) -> float:
    return round((eb - eo) / eb * 100.0, 2) if eb > 0 else 0.0


def evaluate(jobs: list[Job], cap: float, step: int, forecasts: dict, actual: dict, transfer_g_per_gb: float) -> dict:
    jobs = list(jobs)
    out = {"forecasted": None, "realized": None, "jobs": [], "deadlines": None, "wait": None}

    # ---- forecasted basis (all jobs that have a plan)
    planned = [j for j in jobs if j.plan is not None]
    if planned:
        base_f = baseline(planned, cap, attr="n_est")
        eb = eo = 0.0
        for j in planned:
            snap = j.meta.get("fcs") or forecasts       # forecast as it stood when the job was last planned
            eb += cost(snap[j.home], base_f[j.id], j.n_est, j.kw, step)
            region = j.plan.region
            eo += cost(snap[region], j.plan.start, j.n_est, j.kw, step) + penalty(j, region, transfer_g_per_gb)
        out["forecasted"] = {"basis": "forecasted", "e_base_g": round(eb), "e_opt_g": round(eo),
                             "savings_pct": _pct(eb, eo), "jobs": len(planned)}

    # ---- realized basis (DONE jobs, actual intensity)
    done = [j for j in jobs if j.state == "DONE"]
    if done and all(actual.get(r) is not None for r in {j.home for j in done} | {j.region for j in done}):
        base_r = baseline(jobs, cap, attr="an")
        eb = eo = 0.0
        hit_b = hit_o = 0
        wb = wo = 0
        for j in done:
            s0, s1 = base_r[j.id], j.actual_start
            e0 = cost(actual[j.home], s0, j.an, j.kw, step)
            e1 = cost(actual[j.region], s1, j.an, j.kw, step) + penalty(j, j.region, transfer_g_per_gb)
            eb, eo = eb + e0, eo + e1
            hit_b += s0 + j.an <= j.dl
            hit_o += j.actual_end <= j.dl
            wb += (s0 - j.sub) * step
            wo += (s1 - j.sub) * step
            out["jobs"].append({"id": j.id, "e_base_g": round(e0), "e_opt_g": round(e1),
                                "savings_pct": _pct(e0, e1), "basis": "realized",
                                "base_start": s0, "start": s1})
        n = len(done)
        out["realized"] = {"basis": "realized", "e_base_g": round(eb), "e_opt_g": round(eo),
                           "savings_pct": _pct(eb, eo), "jobs": n}
        out["deadlines"] = {"base_pct": round(hit_b / n * 100, 1), "opt_pct": round(hit_o / n * 100, 1), "jobs": n}
        out["wait"] = {"base_min": round(wb / n), "opt_min": round(wo / n)}
    return out
