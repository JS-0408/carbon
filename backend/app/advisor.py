"""Advisor: plain-language reason strings and alternatives (R8, R12)."""
from __future__ import annotations

from .core import Job, PlanResult, fc_at


def _hhmm(minutes: int) -> str:
    h, m = divmod(int(minutes), 60)
    return f"{h} h {m:02d} min" if h else f"{m} min"


def avg_intensity(res_cost: float, kw: float, n: int, step: int) -> float:
    e_kwh = kw * n * step / 60.0
    return res_cost / e_kwh if e_kwh else 0.0


def explain(j: Job, res: PlanResult, now: int, step: int, label) -> str:
    """label(step)->human time string. Returns the reason shown in the queue and decision panel."""
    run_now = next(a for a in res.alternatives if a["label"] == "run_now")
    wait_min = (res.start - max(now, j.sub)) * step
    slack_min = max(0, (j.dl - res.start - j.pn) * step)
    if j.infeasible:
        return (f"Cannot finish by the deadline even if started immediately. Starting at the earliest free slot "
                f"({label(res.start)}) so the work still gets done. Extend the deadline or shorten the job to fix this.")
    if res.forced:
        return (f"No low-carbon window fits before the deadline with the capacity available. Starting at the "
                f"earliest free slot ({label(res.start)}) to protect the deadline.")
    if j.wtype == "realtime_inference":
        return f"Real-time inference is never delayed. Starting at the earliest free slot ({label(res.start)})."
    if res.start == run_now["start"] and res.region == run_now["region"]:
        return (f"Starting at {label(res.start)}: little slack or cluster capacity left no greener window "
                f"before the deadline ({_hhmm(slack_min)} of slack).")
    a_opt = avg_intensity(res.expected_g - res.penalty_g, j.kw, j.pn, step)
    a_now = avg_intensity(run_now["gco2"], j.kw, j.pn, step)
    delta = (a_opt - a_now) / a_now * 100 if a_now else 0.0
    saved = run_now["gco2"] - res.expected_g
    where = f" in region '{res.region}'" if res.region != j.home else ""
    pen = f" (includes {res.penalty_g:.0f} g CO2 to move the data)" if res.penalty_g else ""
    if saved >= 0:
        return (f"Delayed {_hhmm(wait_min)} to start{where} at {label(res.start)}: forecast grid intensity "
                f"{a_opt:.0f} vs {a_now:.0f} gCO2/kWh if run now ({delta:+.0f}%), saving about {saved:.0f} g CO2{pen}. "
                f"{_hhmm(slack_min)} of slack remain.")
    return (f"Start{where} at {label(res.start)} after {_hhmm(wait_min)}; expected emissions {res.expected_g:.0f} g CO2{pen}. "
            f"{_hhmm(slack_min)} of slack remain.")


def realized_note(j: Job, base_start: int, actual_i0: float, actual_i1: float, step: int, missed_min: int) -> str:
    s0, s1 = base_start, j.actual_start
    if s1 <= s0:
        why = "Ran at the baseline time: little slack or cluster capacity left no greener window."
    else:
        why = (f"Delayed {(s1 - s0) * step} min: realized intensity {actual_i1:.0f} vs {actual_i0:.0f} gCO2/kWh "
               f"({(actual_i1 - actual_i0) / actual_i0 * 100:+.0f}%).")
    if missed_min > 0:
        why += f" DEADLINE MISSED by {missed_min} min."
    return why
