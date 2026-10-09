"""T08-T11: engine lifecycle, re-planning (R2), executor (R7), advisor (R8) and one test per alert type (R11)."""
import pytest

from backend.app.core import Job
from backend.app.engine import EngineError
from backend.app.executor import KubernetesBackend, job_manifest, k8s_name
from backend.app.models import JobIn
from backend.app.providers import MockProvider
from conftest import ORIGIN, Scripted, make_engine, mk


def flat(v=400.0):
    return lambda now, total: [v] * total


def dip_at(centre):
    def f(now, total):
        v = [600.0] * total
        v[centre] = v[centre + 1] = 100.0
        return v
    return f


def spec(**kw):
    base = dict(job_id="j1", workload_type="batch_inference", estimated_duration_minutes=60,
                power_profile_kw=1.5, sla_deadline="2026-10-09T20:00:00Z", submission_time="2026-10-09T00:00:00Z")
    base.update(kw)
    return JobIn(**base)


# ---------------------------------------------------------------- lifecycle (R7)
def test_job_lifecycle_pending_planned_running_done(settings):
    e = make_engine(settings, Scripted(dip_at(10)))
    j = e.add_job(mk("a", dl=40, n=2), plan_now=False)
    assert j.state == "PENDING"
    e.replan("manual")
    assert j.state == "PLANNED" and j.start == 10
    e.advance(10)
    assert j.state == "PLANNED"
    e.advance(1)
    assert j.state == "RUNNING" and j.actual_start == 10
    e.advance(2)
    assert j.state == "DONE" and j.actual_end == 12


def test_capacity_never_exceeded_while_running(settings):
    e = make_engine(settings, Scripted(flat()))
    for i in range(6):
        e.add_job(mk(f"j{i}", kw=3.0, dl=200, n=4))
    for _ in range(100):
        e.advance(1)
        running = sum(j.kw for j in e.jobs.values() if j.state == "RUNNING")
        assert running <= settings.cap_kw + 1e-9
    assert all(j.state == "DONE" for j in e.jobs.values())


# ---------------------------------------------------------------- re-planning (R2)
def test_replan_when_forecast_changes_and_started_jobs_locked(settings):
    state = {"centre": 20}
    e = make_engine(settings, Scripted(lambda now, total: dip_at(state["centre"])(now, total)))
    movable = e.add_job(mk("movable", dl=80, n=2))
    early = e.add_job(mk("early", dl=15, n=2, sub=0))
    assert movable.start == 20
    state["centre"] = 50
    e.advance(12)                                     # tick -> fresh forecast
    assert movable.start == 50
    assert "replan" in e.alerts.types()               # moved >= 4 steps
    assert early.state == "DONE" or early.state == "RUNNING"   # started job untouched


def test_provider_change_triggers_replan(settings):
    e = make_engine(settings, Scripted(dip_at(10)))
    j = e.add_job(mk("a", dl=60, n=2))
    assert j.start == 10
    e.set_provider(Scripted(dip_at(30)))
    assert j.start == 30


# ---------------------------------------------------------------- alerts (R11): one test per type
def test_alert_fallback(settings):
    p = MockProvider(settings, seed=1)
    e = make_engine(settings, p)
    e.add_job(mk("a", dl=100, n=2))
    p.down = True
    e.replan("provider_change")
    assert "fallback" in e.alerts.types()
    assert e.health()["fallback_active"] and e.jobs["a"].state == "PLANNED"      # INV4: schedule still produced


def test_alert_sla_risk_forced(settings):
    e = make_engine(settings, Scripted(flat()))
    j = e.add_job(mk("a", dl=2, n=3, pn=4))
    assert j.forced and "sla_risk" in e.alerts.types()


def test_alert_sla_risk_low_slack(settings):
    e = make_engine(settings, Scripted(flat()))
    e.add_job(mk("a", dl=10, n=8, pn=10))        # slack = 0 < 10% of duration, but feasible
    assert any(a.type == "sla_risk" and "10%" in a.message for a in e.alerts.items)


def test_alert_infeasible(settings):
    e = make_engine(settings, Scripted(flat()))
    j = e.build_job(spec(estimated_duration_minutes=300, sla_deadline="2026-10-09T01:00:00Z"))
    e.add_job(j)
    assert j.infeasible and "infeasible" in e.alerts.types()


def test_alert_overrun_and_sla_miss(settings):
    e = make_engine(settings, Scripted(flat()))
    j = e.add_job(mk("a", dl=6, n=2, pn=3, an=12))
    e.advance(30)
    assert {"overrun", "sla_miss"} <= e.alerts.types() and j.state == "DONE"


def test_alert_forecast_drift(settings):
    e = make_engine(settings, Scripted(flat(300.0), actual_val=500.0))
    e.add_job(mk("a", dl=100, n=2))
    e.advance(80)
    assert "forecast_drift" in e.alerts.types()


def test_alert_capacity(settings):
    e = make_engine(settings, Scripted(flat()))
    for i in range(4):
        e.add_job(mk(f"big{i}", kw=3.0, dl=200, n=14))
    assert "capacity" in e.alerts.types()


def test_alert_replan_levels_and_ack(settings):
    state = {"c": 20}
    e = make_engine(settings, Scripted(lambda n, t: dip_at(state["c"])(n, t)))
    e.add_job(mk("a", dl=80, n=2))
    state["c"] = 50
    e.advance(12)
    a = next(x for x in e.alerts.items if x.type == "replan")
    assert a.level == "info" and not a.acknowledged
    assert e.alerts.ack(a.id).acknowledged


# ---------------------------------------------------------------- advisor (R8)
def test_every_planned_job_has_reason_and_alternatives(settings):
    e = make_engine(settings, MockProvider(settings, seed=2))
    for i in range(5):
        e.add_job(mk(f"j{i}", dl=60 + i, n=3, pn=4, sub=i))
    for j in e.jobs.values():
        assert j.reason and len(j.plan.alternatives) >= 2
        assert all("gco2" in a for a in j.plan.alternatives)


def test_reason_mentions_delay_and_intensity(settings):
    e = make_engine(settings, Scripted(dip_at(10)))
    j = e.add_job(mk("a", dl=40, n=2))
    assert "Delayed" in j.reason and "gCO2/kWh" in j.reason


# ---------------------------------------------------------------- submission API semantics
def test_preview_has_no_side_effects(settings):
    e = make_engine(settings, Scripted(dip_at(10)))
    j, res = e.preview(spec())
    assert res.start >= 0 and e.jobs == {} and len(e.alerts.items) == 0


def test_validation_power_over_capacity(settings):
    e = make_engine(settings, Scripted(flat()))
    with pytest.raises(EngineError) as x:
        e.build_job(spec(power_profile_kw=99))
    assert x.value.status == 422 and "capacity" in x.value.detail


def test_duplicate_and_cancel(settings):
    e = make_engine(settings, Scripted(flat()))
    e.submit(spec())
    with pytest.raises(EngineError):
        e.submit(spec())
    e.cancel("j1")
    assert "j1" not in e.jobs


def test_cannot_cancel_running(settings):
    e = make_engine(settings, Scripted(flat()))
    e.add_job(mk("a", dl=20, n=4))
    e.advance(2)
    with pytest.raises(EngineError):
        e.cancel("a")


def test_spatial_engine_moves_job_to_cleaner_region(settings):
    s = settings.copy(regions={k: v for k, v in __import__("backend.app.config", fromlist=["x"]).load_settings().regions.items()
                               if k in ("default", "hydro")})
    e = make_engine(s, MockProvider(s, seed=1))
    j = e.add_job(mk("a", dl=100, n=4, kw=2.0, home="default", allowed=["default", "hydro"], data_gb=1))
    assert j.region == "hydro"


# ---------------------------------------------------------------- evidence (R9)
def test_metrics_forecasted_and_realized_labelled(settings):
    e = make_engine(settings, MockProvider(settings, seed=5))
    for i in range(6):
        e.add_job(mk(f"j{i}", dl=90, n=3, pn=4, sub=i))
    m0 = e.metrics()
    assert m0["forecasted"]["basis"] == "forecasted" and m0["realized"] is None
    e.advance(150)
    m = e.metrics()
    assert m["realized"]["basis"] == "realized" and m["realized"]["jobs"] == 6
    assert m["deadlines"]["opt_pct"] == 100.0
    assert m["synthetic"] is True


def test_realized_uses_actual_not_forecast(settings):
    e = make_engine(settings, Scripted(dip_at(10), actual_val=500.0))
    e.add_job(mk("a", kw=2.0, dl=40, n=2))
    e.advance(40)
    m = e.metrics()
    # actual is flat, so delaying to the forecast dip saves nothing in reality
    assert m["forecasted"]["savings_pct"] > 0 and m["realized"]["savings_pct"] == pytest.approx(0.0)


# ---------------------------------------------------------------- Kubernetes adapter (S2, dry-run only)
def test_k8s_manifest_and_backend_dry_run(settings):
    j = mk("Train_ResNet 50", wtype="model_training", kw=3.0, an=6)
    j.region = "default"
    m = job_manifest(j, "2026-10-09T10:00:00Z")
    assert m["kind"] == "Job" and m["metadata"]["name"] == k8s_name("Train_ResNet 50")
    assert m["metadata"]["annotations"]["carbon-scheduler/declared-power-kw"] == "3.0"
    b = KubernetesBackend()
    e = make_engine(settings, Scripted(flat()), backend=b)
    e.add_job(mk("a", dl=20, n=2))
    e.advance(5)
    assert len(b.manifests) == 1 and b.manifests[0]["metadata"]["name"] == "cas-a"
