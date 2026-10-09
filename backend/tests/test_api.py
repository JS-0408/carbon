"""T12: API flow, validation/error format, simulated clock, outage injection, benchmark smoke (R13)."""
import pytest
from fastapi.testclient import TestClient

from backend.app import bench
from backend.app.bench import bench_settings
from backend.app.config import load_settings
from backend.app.main import create_app

JOB = {"job_id": "ai-train-001", "workload_type": "model_training", "estimated_duration_minutes": 120,
       "duration_p90_minutes": 150, "power_profile_kw": 1.5, "submission_time": "2026-10-09T08:00:00Z",
       "sla_deadline": "2026-10-09T20:00:00Z", "priority": "normal", "preemptible": False,
       "allowed_regions": ["default"], "fallback_policy": "historical_average"}


@pytest.fixture
def client():
    app = create_app(load_settings(), db_path=":memory:", seed_demo=False)
    return TestClient(app)


def test_health_and_empty_state(client):
    h = client.get("/health").json()
    assert h["status"] == "ok" and h["provider"] == "mock" and h["synthetic"] is True
    assert client.get("/jobs").json() == []


def test_submit_plan_run_metrics_flow(client):
    r = client.post("/jobs", json=JOB)
    assert r.status_code == 201
    body = r.json()
    assert body["job"]["state"] == "PLANNED" and body["plan"]["alternatives"]
    assert body["job"]["reason"]
    sched = client.get("/schedule").json()
    assert len(sched) == 1
    assert client.get("/jobs/ai-train-001").json()["job"]["job_id"] == "ai-train-001"
    ex = client.get("/explain/ai-train-001").json()
    assert ex["reason"] and len(ex["alternatives"]) >= 2
    client.post("/sim/clock", json={"hours": 30})
    j = client.get("/jobs/ai-train-001").json()["job"]
    assert j["state"] == "DONE" and j["actual_start"] and j["actual_end"]
    m = client.get("/metrics").json()
    assert m["realized"]["basis"] == "realized" and m["forecasted"]["basis"] == "forecasted"


def test_forecast_endpoint_labels_source(client):
    f = client.get("/forecast").json()
    assert f["source"] == "mock" and f["synthetic"] is True and f["unit"] == "gCO2/kWh" and len(f["values"]) == 288
    assert client.get("/forecast", params={"region": "nowhere"}).status_code == 404


@pytest.mark.parametrize("patch,needle", [
    ({"estimated_duration_minutes": 0}, "estimated_duration_minutes"),
    ({"estimated_duration_minutes": 5000}, "estimated_duration_minutes"),
    ({"duration_p90_minutes": 60}, "at least"),
    ({"power_profile_kw": -1}, "power_profile_kw"),
    ({"workload_type": "mining"}, "workload_type"),
    ({"sla_deadline": "2026-10-09T07:00:00Z"}, "after submission_time"),
    ({"sla_deadline": "2026-10-09T20:00:00"}, "UTC"),
    ({"job_id": "bad id!"}, "job_id"),
])
def test_validation_errors_are_plain_and_structured(client, patch, needle):
    r = client.post("/jobs", json={**JOB, **patch})
    assert r.status_code == 422
    b = r.json()
    assert set(b) == {"error", "detail", "fix"} and needle in b["detail"]


def test_power_over_capacity_422(client):
    r = client.post("/jobs", json={**JOB, "power_profile_kw": 50})
    assert r.status_code == 422 and "capacity" in r.json()["detail"] and r.json()["fix"]


def test_infeasible_job_is_accepted_loudly(client):
    r = client.post("/jobs", json={**JOB, "estimated_duration_minutes": 600, "duration_p90_minutes": None,
                                   "sla_deadline": "2026-10-09T09:00:00Z"})
    assert r.status_code == 201 and r.json()["job"]["infeasible"] and r.json()["warnings"]
    assert "infeasible" in {a["type"] for a in client.get("/alerts").json()}


def test_duplicate_404_409(client):
    client.post("/jobs", json=JOB)
    assert client.post("/jobs", json=JOB).status_code == 409
    assert client.get("/jobs/nope").status_code == 404
    assert client.delete("/jobs/ai-train-001").status_code == 200
    assert client.delete("/jobs/ai-train-001").json()["error"] == "not_found"


def test_preview_does_not_commit(client):
    r = client.post("/jobs/preview", json=JOB)
    assert r.status_code == 200 and r.json()["plan"]["alternatives"]
    assert client.get("/jobs").json() == []


def test_outage_fallback_banner_and_still_scheduled(client):
    client.post("/jobs", json=JOB)
    r = client.post("/sim/fail", params={"down": True}).json()
    assert r["fallback"] is True
    h = client.get("/health").json()
    assert h["fallback_active"] is True
    assert client.get("/forecast").json()["is_fallback"] is True
    assert client.get("/jobs/ai-train-001").json()["job"]["state"] == "PLANNED"          # INV4
    assert any(a["type"] == "fallback" for a in client.get("/alerts").json())
    client.post("/sim/fail", params={"down": False})
    assert client.get("/health").json()["fallback_active"] is False


def test_alert_ack(client):
    client.post("/sim/fail", params={"down": True})
    a = client.get("/alerts").json()[0]
    assert client.post(f"/alerts/{a['id']}/ack").json()["acknowledged"] is True
    assert client.post("/alerts/9999/ack").status_code == 404


def test_demo_seed_and_scenarios(client):
    assert {"weekday_mix", "heavy_load", "spatial_demo", "uk_real_data"} <= {s["name"] for s in client.get("/scenarios").json()}
    r = client.post("/demo/seed", json={"scenario": "heavy_load", "seed": 1})
    assert r.status_code == 200 and r.json()["jobs"] == 24
    assert client.post("/demo/seed", json={"scenario": "zzz"}).status_code == 422
    client.post("/sim/clock", json={"hours": 72})
    tl = client.get("/timeline").json()
    assert len(tl["jobs"]) == 24 and tl["forecast"]["values"]
    m = client.get("/metrics").json()
    assert m["realized"]["jobs"] >= 20


def test_spatial_demo_uses_second_region(client):
    client.post("/demo/seed", json={"scenario": "spatial_demo", "seed": 1})
    regions = {j["region"] for j in client.get("/jobs").json()}
    assert "hydro" in regions


def test_provider_switch_and_unknown(client):
    assert client.post("/provider", json={"provider": "nope"}).status_code == 422
    h = client.post("/provider", json={"provider": "watttime"}).json()      # no credentials -> fallback, loudly
    assert h["provider"] == "watttime" and h["fallback_active"] is True
    assert "WATTTIME" in (h["last_provider_error"] or "")
    assert client.post("/sim/fail").status_code == 409


def test_api_key_enforced_when_configured():
    s = bench_settings().copy(api_key="secret")
    c = TestClient(create_app(s, db_path=":memory:", seed_demo=False))
    assert c.post("/jobs", json=JOB).status_code == 401
    assert c.post("/jobs", json=JOB, headers={"X-API-Key": "secret"}).status_code == 201
    assert c.get("/jobs").status_code == 200       # reads stay open


def test_ui_served():
    c = TestClient(create_app(bench_settings(), db_path=":memory:", seed_demo=False))
    r = c.get("/")
    assert r.status_code == 200 and "<h1" in r.text


# ---------------------------------------------------------------- benchmark (R13)
def test_bench_runs_and_is_deterministic():
    s = bench_settings()
    a = bench.run_once(s, bench.SCENARIO_MAP["weekday_mix"][1], 7)
    b = bench.run_once(s, bench.SCENARIO_MAP["weekday_mix"][1], 7)
    assert a == b and a["done"] == a["jobs"] == 12


def test_bench_qualitative_behaviour():
    s = bench_settings()
    res = {n: bench.run_scenario(n, seeds=6, settings=s, index=i) for i, (n, _, _) in enumerate(bench.SCENARIOS)}
    k = {n: r["kpi"] for n, r in res.items()}
    assert k["weekday_mix"]["savings_mean"] > 1.0                                    # flexible mix saves carbon
    assert k["tight_deadlines"]["savings_mean"] < k["weekday_mix"]["savings_mean"]   # little slack, little saving
    assert k["api_outage"]["savings_mean"] > 0 and k["api_outage"]["hit_opt"] >= 90  # fallback still valid
    assert k["heavy_load"]["hit_opt"] >= 85
    assert all(r["seed0"]["jobs"] for r in res.values())
    assert "fallback" in res["api_outage"]["seed0"]["alerts"][0]["type"] or any(
        a["type"] == "fallback" for a in res["api_outage"]["seed0"]["alerts"])


def test_bench_endpoint(client):
    r = client.post("/bench/run", params={"scenario": "weekday_mix", "seeds": 2})
    assert r.status_code == 200 and r.json()["scenarios"][0]["kpi"]["seeds"] == 2
    assert client.post("/bench/run", params={"scenario": "zzz"}).status_code == 422
