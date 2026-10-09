#!/usr/bin/env python3
"""Carbon-aware AI workload scheduler (stdlib only).

Modules: Observer (forecast + historical-average fallback), Estimator (padded durations),
Scheduler (multi-job, capacity- and deadline-aware), Executor (re-plans every 6h, locks started jobs),
Advisor (reason strings + alerts). Run: python carbon_scheduler.py -> results.json

NOTE: grid intensity here is a SYNTHETIC India-like diurnal profile (solar dip midday, evening peak).
Swap `make_actual`/`forecast` for the Carbon Aware SDK / WattTime / Electricity Maps to use real data.
"""
import json, math, random

STEP, SPD = 30, 48          # minutes per step, steps per day
H = SPD * 6                 # horizon (steps)
CAP, PAD, TICK = 8.0, 1.25, 12   # cluster kW, duration padding, re-plan every 12 steps (6h)


def base_ci(h, solar=1.0):
    g = lambda x, m, s: math.exp(-((x - m) ** 2) / (2 * s * s))
    return 700 - 170 * solar * g(h, 13, 3.2) + 90 * g(h, 20, 1.8) + 40 * g(h, 7, 1.5) - 40 * g(h, 3, 3)


HIST = [base_ci((t % SPD) / 2) for t in range(H)]   # fallback: static historical average


def make_actual(rng, solar):
    return [base_ci((t % SPD) / 2, solar) * (1 + rng.gauss(0, 0.03)) for t in range(H)]


def forecast(actual, tick, rng, outage):
    """Observer: noisy forecast whose error grows with horizon; falls back to HIST on outage."""
    if outage:
        return HIST[:], True
    fc = [actual[t] if t < tick else actual[t] * (1 + rng.gauss(0, min(0.15, 0.03 + 0.002 * (t - tick))))
          for t in range(H)]
    return fc, False


KINDS = {  # kind: (dur_min_lo, dur_min_hi, kw, slack_steps_lo, slack_steps_hi, weight)
    "urgent_inference": (30, 60, 2.0, 1, 3, 2),
    "batch_inference": (60, 120, 1.5, 6, 14, 3),
    "training": (120, 360, 3.0, 12, 30, 3),
    "etl": (60, 120, 1.0, 24, 40, 2),
}


def gen_jobs(rng, n, tight):
    jobs, kinds = [], list(KINDS)
    for i in range(n):
        k = rng.choices(kinds, [KINDS[x][5] for x in kinds])[0]
        lo, hi, kw, sl, sh, _ = KINDS[k]
        dur = rng.randrange(lo, hi + 1, 30)
        sub, slack = rng.randrange(0, SPD), rng.randint(sl, sh)
        if tight:
            slack = max(1, slack // 4)
        jobs.append(dict(id=f"{k[:3]}-{i+1:02d}", kind=k, dur=dur, kw=kw, sub=sub,
                         dl=sub + math.ceil(dur / STEP) + slack))
    return jobs


def fits(load, j, s, n):
    return all(load[s + k] + j["kw"] <= CAP for k in range(n))


def plan(pend, fc, load, now):
    """Scheduler: least-slack-first; pick min-carbon feasible start with C = sum P*dt*I."""
    out = {}
    for j in sorted(pend, key=lambda j: j["dl"] - j["pn"] - max(now, j["sub"])):
        n, best = j["pn"], None
        for s in range(max(now, j["sub"]), j["dl"] - n + 1):
            if fits(load, j, s, n):
                c = sum(fc[s + k] for k in range(n)) * j["kw"] * STEP / 60
                if best is None or c < best[0] - 1e-9:
                    best = (c, s)
        forced = best is None            # no feasible green window: run at earliest slot, flag SLA risk
        if forced:
            s = max(now, j["sub"])
            while not fits(load, j, s, n):
                s += 1
        else:
            s = best[1]
        for k in range(n):
            load[s + k] += j["kw"]
        out[j["id"]] = (s, forced)
    return out


def label(t):
    return f"D{t // SPD + 1} {t % SPD // 2:02d}:{30 * (t % 2):02d}"


def simulate(name, desc, sc, seed):
    rng = random.Random(seed)
    actual = make_actual(rng, sc.get("solar", 1.0))
    jobs = gen_jobs(rng, sc["n"], sc.get("tight", False))
    for j in jobs:
        f = sc.get("overrun", 1.0) if j["kind"] == "training" else 1.0
        j["an"], j["pn"] = math.ceil(j["dur"] * f / STEP), math.ceil(j["dur"] * PAD / STEP)
    # baseline: run as soon as capacity allows (standard scheduler behaviour)
    bl, base = [0.0] * H, {}
    for j in sorted(jobs, key=lambda j: j["sub"]):
        s = j["sub"]
        while not fits(bl, j, s, j["an"]):
            s += 1
        for k in range(j["an"]):
            bl[s + k] += j["kw"]
        base[j["id"]] = s
    # optimized: re-plan every TICK steps against a fresh forecast
    lock, start, last, alerts = [0.0] * H, {}, {}, []
    outage = set(sc.get("outage", []))
    A = lambda t, lvl, typ, msg: alerts.append(dict(time=label(t), level=lvl, type=typ, msg=msg))
    for ti, tick in enumerate(range(0, SPD * 3, TICK)):
        fc, fb = forecast(actual, tick, rng, ti in outage)
        if fb:
            A(tick, "warning", "fallback", "Carbon data unavailable. Using historical-average profile.")
        pend = [j for j in jobs if j["id"] not in start and j["sub"] < tick + TICK]
        if not pend:
            continue
        plans = plan(pend, fc, lock[:], tick)
        for j in pend:
            s, forced = plans[j["id"]]
            if forced:
                A(tick, "critical", "sla_risk", f"{j['id']}: no feasible window before deadline. Starting at earliest slot.")
            if j["id"] in last and abs(last[j["id"]] - s) >= 4:
                A(tick, "info", "replan", f"{j['id']}: start moved {label(last[j['id']])} -> {label(s)} after forecast update.")
            last[j["id"]] = s
            if s < tick + TICK:
                start[j["id"]] = s
                for k in range(j["an"]):
                    lock[s + k] += j["kw"]
    for j in jobs:
        start.setdefault(j["id"], last[j["id"]])
    em = lambda j, s: sum(actual[s + k] for k in range(j["an"])) * j["kw"] * STEP / 60
    rows, eb, eo, hb, ho, wb, wo = [], 0, 0, 0, 0, 0, 0
    for j in jobs:
        s0, s1 = base[j["id"]], start[j["id"]]
        g0, g1 = em(j, s0), em(j, s1)
        ok0, ok1 = s0 + j["an"] <= j["dl"], s1 + j["an"] <= j["dl"]
        i0, i1 = g0 / (j["kw"] * j["an"] * STEP / 60), g1 / (j["kw"] * j["an"] * STEP / 60)
        left = (j["dl"] - s1 - j["an"]) * STEP
        if s1 <= s0:
            why = "Ran at baseline time: little slack or cluster capacity left no greener window."
        else:
            why = (f"Delayed {(s1 - s0) * STEP} min: realized intensity {i1:.0f} vs {i0:.0f} gCO2/kWh "
                   f"({(i1 - i0) / i0 * 100:+.0f}%); {max(left, 0)} min of slack remained.")
        if not ok1:
            A(s1 + j["an"], "critical", "sla_miss", f"{j['id']} missed deadline by {-left} min (duration overran estimate).")
            why += " DEADLINE MISSED."
        rows.append(dict(id=j["id"], kind=j["kind"], kw=j["kw"], sub=j["sub"], base=s0, opt=s1, n=j["an"], dl=j["dl"],
                         g_base=round(g0), g_opt=round(g1), hit_base=ok0, hit_opt=ok1, why=why))
        eb, eo, hb, ho = eb + g0, eo + g1, hb + ok0, ho + ok1
        wb, wo = wb + (s0 - j["sub"]) * STEP, wo + (s1 - j["sub"]) * STEP
    n = len(jobs)
    alerts.sort(key=lambda a: a["time"])
    return dict(name=name, desc=desc, kpi=dict(
        e_base_g=round(eb), e_opt_g=round(eo), savings_pct=round((eb - eo) / eb * 100, 1),
        hit_base=round(hb / n * 100), hit_opt=round(ho / n * 100),
        wait_base_min=round(wb / n), wait_opt_min=round(wo / n), jobs=n),
        jobs=rows, alerts=alerts, series=[round(x) for x in actual[:SPD * 3]])


SCENARIOS = [
    ("weekday_mix", "12 mixed jobs, normal forecast, 8 kW cluster", dict(n=12)),
    ("tight_deadlines", "Same mix but deadlines cut to a quarter of normal slack", dict(n=12, tight=True)),
    ("api_outage", "Carbon API down for 12 hours; fallback profile in use", dict(n=12, outage=[1, 2])),
    ("overrun_cloudy", "Cloudy day (weak solar dip) and training jobs run 45% longer than estimated", dict(n=12, solar=0.35, overrun=1.45)),
    ("heavy_load", "24 jobs competing for the same 8 kW", dict(n=24)),
]

if __name__ == "__main__":
    res = []
    for i, (nm, d, sc) in enumerate(SCENARIOS):
        # average over 20 seeds for the headline numbers; keep seed 0 as the detailed run
        runs = [simulate(nm, d, sc, 100 * i + s) for s in range(20)]
        r = runs[0]
        mean = lambda k: round(sum(x["kpi"][k] for x in runs) / len(runs), 1)
        r["kpi20"] = {k: mean(k) for k in ("savings_pct", "hit_base", "hit_opt", "wait_base_min", "wait_opt_min")}
        r["kpi20"]["min_savings"] = min(x["kpi"]["savings_pct"] for x in runs)
        r["kpi20"]["max_savings"] = max(x["kpi"]["savings_pct"] for x in runs)
        res.append(r)
        k = r["kpi20"]
        print(f"{nm:16s} savings {k['savings_pct']:5.1f}% (range {k['min_savings']:.1f}..{k['max_savings']:.1f}) "
              f"deadline-hit base {k['hit_base']:.0f}% -> opt {k['hit_opt']:.0f}%  wait {k['wait_base_min']:.0f} -> {k['wait_opt_min']:.0f} min")
    json.dump(res, open("results.json", "w"))
