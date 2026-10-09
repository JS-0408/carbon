"""T02/T04: cost, capacity, tie-break and property tests for INV1-INV3, INV6."""
import math

from hypothesis import given, settings as hset, strategies as st

from backend.app.core import add_load, baseline, cost, fits, plan, profile_series
from backend.app.estimator import Estimator, n_steps
from conftest import mk


# ----------------------------------------------------------------- unit tests
def test_cost_formula():
    fc = [100.0, 200.0, 300.0, 400.0]
    # P=2kW, dt=30min -> 1 kWh per kW-hour... sum(I)*P*dt/60
    assert cost(fc, 1, 2, 2.0, 30) == (200 + 300) * 2.0 * 0.5


def test_fits_and_capacity():
    load = [0.0] * 10
    add_load(load, 3.0, 2, 4)
    assert fits(load, 5.0, 2, 4, 8.0)
    assert not fits(load, 5.1, 2, 4, 8.0)
    assert fits(load, 8.0, 6, 2, 8.0)


def test_picks_minimum_carbon_window():
    fc = [500] * 20
    fc[8], fc[9] = 100, 100
    j = mk(dl=20, n=2)
    r = plan([j], {"default": fc}, {"default": []}, 0, 8.0, 30)[j.id]
    assert r.start == 8 and not r.forced


def test_tie_break_earliest_start():
    fc = [300.0] * 30
    j = mk(dl=30, n=3)
    assert plan([j], {"default": fc}, {"default": []}, 0, 8.0, 30)[j.id].start == 0


def test_respects_submit_and_now():
    fc = [100.0] * 5 + [500.0] * 20
    j = mk(sub=3, dl=25, n=2)
    assert plan([j], {"default": fc}, {"default": []}, 4, 8.0, 30)[j.id].start == 4


def test_deadline_respected_with_padded_duration():
    fc = [500.0] * 30
    fc[18], fc[19] = 1, 1                       # greenest window ends after the deadline
    j = mk(dl=18, n=2, pn=3)
    r = plan([j], {"default": fc}, {"default": []}, 0, 8.0, 30)[j.id]
    assert r.start + j.pn <= j.dl


def test_forced_start_flagged_when_infeasible():
    j = mk(dl=2, n=3)
    r = plan([j], {"default": [300.0] * 40}, {"default": []}, 0, 8.0, 30)[j.id]
    assert r.forced and r.start == 0


def test_capacity_pushes_second_job_later():
    a, b = mk("a", kw=5.0, dl=10, n=4), mk("b", kw=5.0, dl=40, n=4)
    r = plan([a, b], {"default": [300.0] * 60}, {"default": []}, 0, 8.0, 30)
    assert r["b"].start >= r["a"].start + 4 or r["b"].start + 4 <= r["a"].start


def test_least_slack_goes_first():
    tight, loose = mk("tight", kw=5.0, dl=4, n=4), mk("loose", kw=5.0, dl=60, n=4)
    r = plan([loose, tight], {"default": [300.0] * 80}, {"default": []}, 0, 8.0, 30)
    assert r["tight"].start == 0


def test_realtime_never_delayed():
    fc = [900.0] * 3 + [100.0] * 30
    j = mk(wtype="realtime_inference", dl=30, n=1)
    assert plan([j], {"default": fc}, {"default": []}, 0, 8.0, 30)["j"].start == 0


def test_alternatives_present():
    j = mk(dl=30, n=2)
    r = plan([j], {"default": [400.0] * 40}, {"default": []}, 0, 8.0, 30)["j"]
    labels = {a["label"] for a in r.alternatives}
    assert {"run_now", "optimal", "latest_feasible"} <= labels


def test_spatial_choice_and_transfer_penalty():
    fcs = {"default": [700.0] * 30, "hydro": [200.0] * 30}
    j = mk(dl=30, n=2, kw=2.0, home="default", allowed=["default", "hydro"], data_gb=10)
    cheap = plan([j], fcs, {"default": [], "hydro": []}, 0, 8.0, 30, transfer_g_per_gb=5.0)["j"]
    assert cheap.region == "hydro" and cheap.penalty_g == 50.0
    j2 = mk("j2", dl=30, n=2, kw=2.0, home="default", allowed=["default", "hydro"], data_gb=10_000)
    stay = plan([j2], fcs, {"default": [], "hydro": []}, 0, 8.0, 30, transfer_g_per_gb=5.0)["j2"]
    assert stay.region == "default"


def test_profile_series_positive_and_diurnal():
    p = profile_series({"base": 700, "dip": 170, "dip_c": 13, "dip_w": 3.2, "peak": 90, "peak_c": 20, "peak_w": 1.8}, 96, 30)
    assert all(v > 0 and math.isfinite(v) for v in p)
    assert min(p[:48]) < max(p[:48])


def test_estimator_padding(settings):
    e = Estimator(settings, adaptive=False)
    assert e.planned_steps("batch_inference", 90) == math.ceil(90 * 1.25 / 30)        # 4
    assert e.planned_steps("model_training", 120) == math.ceil(120 * 1.6 / 30)        # per-type pad
    assert e.planned_steps("etl", 60, p90_min=100) == n_steps(100, 30)                # p90 wins
    assert e.duration_range("etl", 60, 100) == (60, 120)


def test_estimator_adapts_but_never_lowers(settings):
    e = Estimator(settings, adaptive=True)
    base = e.pad("batch_inference")
    for _ in range(10):
        e.observe("batch_inference", 60, 120)       # runs twice as long as estimated
    assert e.pad("batch_inference") > base
    e2 = Estimator(settings, adaptive=True)
    for _ in range(10):
        e2.observe("batch_inference", 60, 30)
    assert e2.pad("batch_inference") == base


# ----------------------------------------------------------------- property tests
job_s = st.builds(
    lambda i, wt, kw, sub, extra, n: (i, wt, kw, sub, extra, n),
    st.integers(0, 10**6), st.sampled_from(["batch_inference", "model_training", "etl", "realtime_inference"]),
    st.sampled_from([0.5, 1.0, 1.5, 2.0, 3.0]), st.integers(0, 30), st.integers(0, 40), st.integers(1, 12))


def _jobs(raw):
    out = []
    for k, (i, wt, kw, sub, extra, n) in enumerate(raw):
        out.append(mk(f"j{k}", wt, kw, sub, sub + n + extra, n))
    return out


fc_s = st.lists(st.floats(50, 1000, allow_nan=False), min_size=120, max_size=160)


@hset(max_examples=600, deadline=None)
@given(st.lists(job_s, min_size=1, max_size=8), fc_s, st.integers(0, 10))
def test_inv1_inv2_inv6(raw, fc, now):
    jobs = _jobs(raw)
    cap = 8.0
    res = plan(jobs, {"default": fc}, {"default": []}, now, cap, 30)
    load = {}
    for j in jobs:
        r = res[j.id]
        assert r.start >= max(now, j.sub)
        for k in range(j.pn):
            load[r.start + k] = load.get(r.start + k, 0.0) + j.kw
        finish = r.start + j.pn
        # INV2: not forced <=> meets deadline with the padded duration
        assert r.forced == (finish > j.dl)
        if j.wtype == "realtime_inference":      # INV6
            run_now = next(a for a in r.alternatives if a["label"] == "run_now")
            assert r.start == run_now["start"]
    assert all(v <= cap + 1e-9 for v in load.values())      # INV1


@hset(max_examples=500, deadline=None)
@given(st.lists(job_s, min_size=1, max_size=6), fc_s)
def test_inv3_perfect_forecast_nonbinding_capacity(raw, fc):
    jobs = _jobs(raw)
    res = plan(jobs, {"default": fc}, {"default": []}, 0, 1e9, 30)
    for j in jobs:
        assert res[j.id].expected_g <= res[j.id].baseline_g + 1e-6


def test_baseline_respects_capacity():
    jobs = [mk("a", kw=5, sub=0, n=4), mk("b", kw=5, sub=0, n=4)]
    b = baseline(jobs, 8.0)
    assert b["a"] == 0 and b["b"] == 4
