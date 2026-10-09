"""Pure scheduling math (Section 6 of the spec). No I/O, no clocks.

Units: intensity I in gCO2/kWh, power P in kW, step dt in minutes.
Emissions if a job starts at step s with n steps: C(s) = sum_k P * (dt/60) * I[s+k]  (grams CO2).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional


# --------------------------------------------------------------------------- profiles
def base_ci(h: float, solar: float = 1.0, base: float = 700, dip: float = 170, dip_c: float = 13,
            dip_w: float = 3.2, peak: float = 90, peak_c: float = 20, peak_w: float = 1.8) -> float:
    """Synthetic diurnal grid intensity: solar dip at midday, evening peak (ported from the reference)."""
    g = lambda x, m, s: math.exp(-((x - m) ** 2) / (2 * s * s))
    return base - dip * solar * g(h, dip_c, dip_w) + peak * g(h, peak_c, peak_w) + 40 * g(h, 7, 1.5) - 40 * g(h, 3, 3)


def profile_series(profile: dict, steps: int, step_min: int, solar: float = 1.0) -> list[float]:
    spd = 24 * 60 // step_min
    return [base_ci(((t % spd) * step_min) / 60.0, solar, **profile) for t in range(steps)]


# --------------------------------------------------------------------------- job model
@dataclass
class Job:
    id: str
    wtype: str
    kw: float
    sub: int                 # submit step
    dl: int                  # deadline step (job must finish at or before)
    n_est: int               # estimated steps (unpadded)
    pn: int                  # planning (padded) steps
    an: int                  # actual steps (known only to the executor / simulator)
    home: str = "default"
    allowed: list = field(default_factory=lambda: ["default"])
    data_gb: float = 0.0
    priority: str = "normal"
    preemptible: bool = False
    # runtime fields
    state: str = "PENDING"   # PENDING|PLANNED|RUNNING|DONE|FAILED|INFEASIBLE
    start: Optional[int] = None          # planned start step
    region: Optional[str] = None         # planned region
    forced: bool = False
    infeasible: bool = False
    plan: Optional["PlanResult"] = None
    actual_start: Optional[int] = None
    actual_end: Optional[int] = None
    reason: str = ""
    overrun_flagged: bool = False
    fc_at_plan: Optional[list] = None
    meta: dict = field(default_factory=dict)


@dataclass
class PlanResult:
    start: int
    region: str
    forced: bool
    expected_g: float
    baseline_g: float
    alternatives: list
    wait_cap_steps: int = 0
    penalty_g: float = 0.0


# --------------------------------------------------------------------------- helpers
def fc_at(fc: list, i: int) -> float:
    """Forecast lookup that repeats the last day beyond its end (keeps forced starts costed)."""
    if i < len(fc):
        return fc[i]
    spd = 48 if len(fc) >= 48 else max(1, len(fc))
    return fc[len(fc) - spd + ((i - len(fc)) % spd)]


def ext(load: list, upto: int) -> None:
    if len(load) < upto:
        load.extend([0.0] * (upto - len(load)))


def fits(load: list, kw: float, s: int, n: int, cap: float) -> bool:
    ext(load, s + n)
    return all(load[s + k] + kw <= cap + 1e-9 for k in range(n))


def cost(fc: list, s: int, n: int, kw: float, step: int) -> float:
    return sum(fc_at(fc, s + k) for k in range(n)) * kw * step / 60.0


def add_load(load: list, kw: float, s: int, n: int) -> None:
    ext(load, s + n)
    for k in range(n):
        load[s + k] += kw


def slack(j: Job, now: int) -> int:
    return j.dl - j.pn - max(now, j.sub)


def penalty(j: Job, region: str, transfer_g_per_gb: float) -> float:
    return 0.0 if region == j.home else j.data_gb * transfer_g_per_gb


# --------------------------------------------------------------------------- planner
def plan(pending: list[Job], fcs: dict, loads: dict, now: int, cap: float, step: int,
         transfer_g_per_gb: float = 0.0) -> dict:
    """Least-slack-first greedy planner. `loads` is mutated (pass copies).

    Chooses the (region, start) minimising emissions (+ transfer penalty) subject to
      s >= max(now, submit),  s + n_plan <= deadline,  load[s+k] + P <= CAP for all k.
    Ties go to the earliest start, then the home region. If no feasible window exists the job is
    forced to the earliest capacity-feasible step and `forced=True` (never hidden).
    realtime_inference is never delayed (INV6).
    """
    out: dict = {}

    def order(j: Job):
        return (-10**9 if j.wtype == "realtime_inference" else slack(j, now), j.sub, j.id)

    for j in sorted(pending, key=order):
        n, lo = j.pn, max(now, j.sub)
        regs = [r for r in ([j.home] + [x for x in j.allowed if x != j.home]) if r in fcs]
        if not regs:
            regs = [next(iter(fcs))]
        for r in regs:
            loads.setdefault(r, [])
        home = j.home if j.home in loads else regs[0]

        # earliest capacity-feasible start in home region (run-now alternative / baseline for this job)
        s_now = lo
        while not fits(loads[home], j.kw, s_now, n, cap):
            s_now += 1
        cap_wait = s_now - lo

        best = None   # (cost, start, region)
        if j.wtype != "realtime_inference":
            for r in regs:
                pen = penalty(j, r, transfer_g_per_gb)
                for s in range(lo, j.dl - n + 1):
                    if fits(loads[r], j.kw, s, n, cap):
                        c = cost(fcs[r], s, n, j.kw, step) + pen
                        if best is None or c < best[0] - 1e-9:
                            best = (c, s, r)
        else:
            if s_now + n <= j.dl:
                best = (cost(fcs[home], s_now, n, j.kw, step), s_now, home)

        forced = best is None
        if forced:
            s, r = s_now, home
        else:
            _, s, r = best
        pen = penalty(j, r, transfer_g_per_gb)
        exp_g = cost(fcs[r], s, n, j.kw, step) + pen
        run_now_g = cost(fcs[home], s_now, n, j.kw, step)

        # latest feasible alternative in the home region
        s_late = None
        for s2 in range(j.dl - n, lo - 1, -1):
            if fits(loads[home], j.kw, s2, n, cap):
                s_late = s2
                break
        alts = [dict(label="run_now", start=s_now, region=home, gco2=round(run_now_g, 1), finish=s_now + n),
                dict(label="optimal" if not forced else "forced_start", start=s, region=r,
                     gco2=round(exp_g, 1), finish=s + n)]
        if s_late is not None:
            alts.append(dict(label="latest_feasible", start=s_late, region=home,
                             gco2=round(cost(fcs[home], s_late, n, j.kw, step), 1), finish=s_late + n))
        add_load(loads[r], j.kw, s, n)
        out[j.id] = PlanResult(start=s, region=r, forced=forced, expected_g=exp_g, baseline_g=run_now_g,
                               alternatives=alts, wait_cap_steps=cap_wait, penalty_g=pen)
    return out


def baseline(jobs: list[Job], cap: float, attr: str = "an") -> dict:
    """E_base schedule: submission order, earliest step with free capacity, home region.
    `attr` selects the duration used: 'an' (actual, default) or 'n_est' (estimated, forecasted basis)."""
    loads: dict = {}
    out = {}
    for j in sorted(jobs, key=lambda j: (j.sub, j.id)):
        n = getattr(j, attr)
        load = loads.setdefault(j.home, [])
        s = j.sub
        while not fits(load, j.kw, s, n, cap):
            s += 1
        add_load(load, j.kw, s, n)
        out[j.id] = s
    return out
