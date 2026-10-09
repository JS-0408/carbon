"""FastAPI app (Section 8). Errors are always {error, detail, fix}. OpenAPI docs at /docs."""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import bench as benchmod
from .config import ROOT, Settings, load_settings
from .demo import build_demo_engine, scenario_list
from .engine import Engine, EngineError
from .executor import KubernetesBackend, SimBackend
from .models import ClockIn, JobIn, ProviderIn, SeedIn
from .providers import PROVIDERS, MockProvider, make_provider
from .store import Store

FRONTEND = ROOT / "frontend"


class State:
    def __init__(self, settings: Settings, store: Store):
        self.s, self.store = settings, store
        self.lock = threading.RLock()
        self.engine = self._new(settings.provider)

    def _new(self, provider_name: str, seed: int = 0) -> Engine:
        prov = make_provider(provider_name, self.s, seed=seed)
        return Engine(self.s, provider=prov, seed=seed, store=self.store)

    def reset(self, provider_name: str | None = None, seed: int = 0) -> Engine:
        self.engine = self._new(provider_name or self.engine.provider.name, seed)
        return self.engine


def create_app(settings: Settings | None = None, db_path: str | None = None, seed_demo: bool | None = None) -> FastAPI:
    s = settings or load_settings()
    path = db_path if db_path is not None else os.environ.get("DB_PATH", str(ROOT / "data" / "audit.sqlite"))
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    st = State(s, Store(path))
    if seed_demo is None:
        seed_demo = os.environ.get("AUTO_SEED", "1") == "1"
    if seed_demo:
        st.engine = build_demo_engine(s, "weekday_mix", 0, store=st.store)
        st.engine.replan("tick")
    app = FastAPI(title="Carbon-aware AI workload scheduler", version="1.0",
                  description="Shifts flexible AI jobs to lower-carbon windows within deadline and capacity limits.")
    app.state.st = st

    def auth(x_api_key: str | None = Header(default=None)):
        if s.api_key and x_api_key != s.api_key:
            raise EngineError("unauthorized", "Missing or wrong X-API-Key header.", "Send the header X-API-Key with the configured key.", 401)

    # ------------------------------------------------------------------ errors
    @app.exception_handler(EngineError)
    async def _engine_err(_: Request, e: EngineError):
        return JSONResponse({"error": e.error, "detail": e.detail, "fix": e.fix}, status_code=e.status)

    @app.exception_handler(RequestValidationError)
    async def _val_err(_: Request, e: RequestValidationError):
        msgs = []
        for x in e.errors():
            loc = ".".join(str(p) for p in x["loc"] if p != "body")
            msgs.append(f"{loc}: {x['msg'].removeprefix('Value error, ')}")
        return JSONResponse({"error": "validation_error", "detail": "; ".join(msgs),
                             "fix": "Correct the listed fields and submit again. See /docs for the schema."}, status_code=422)

    @app.exception_handler(HTTPException)
    async def _http_err(_: Request, e: HTTPException):
        return JSONResponse({"error": "http_error", "detail": str(e.detail), "fix": "Check the request path and method."},
                            status_code=e.status_code)

    @app.exception_handler(Exception)
    async def _any_err(_: Request, e: Exception):
        return JSONResponse({"error": "internal_error", "detail": f"{type(e).__name__}: {e}",
                             "fix": "This is a bug; check the server log."}, status_code=500)

    def eng() -> Engine:
        return st.engine

    # ------------------------------------------------------------------ core endpoints
    @app.get("/health")
    def health():
        with st.lock:
            return eng().health()

    @app.post("/jobs", status_code=201, dependencies=[Depends(auth)])
    def post_job(spec: JobIn):
        with st.lock:
            j = eng().submit(spec)
            return {"job": eng().job_view(j), "plan": eng().plan_view(j),
                    "warnings": (["This job cannot meet its deadline even if started now; it will start at the earliest slot."]
                                 if j.infeasible else []) + (["No green window fits; forced start with SLA risk."] if j.forced and not j.infeasible else [])}

    @app.post("/jobs/preview", dependencies=[Depends(auth)])
    def preview(spec: JobIn):
        with st.lock:
            j, res = eng().preview(spec)
            return {"job": eng().job_view(j), "plan": eng().plan_view(j)}

    @app.get("/jobs")
    def list_jobs(state: str | None = None):
        with st.lock:
            v = eng().jobs_view()
            return [j for j in v if not state or j["state"] == state.upper()]

    @app.get("/jobs/{job_id}")
    def get_job(job_id: str):
        with st.lock:
            j = eng().jobs.get(job_id)
            if not j:
                raise EngineError("not_found", f"No job '{job_id}'.", "List jobs with GET /jobs.", 404)
            return {"job": next(v for v in eng().jobs_view() if v["job_id"] == job_id), "plan": eng().plan_view(j)}

    @app.delete("/jobs/{job_id}", dependencies=[Depends(auth)])
    def del_job(job_id: str):
        with st.lock:
            eng().cancel(job_id)
            return {"cancelled": job_id}

    @app.get("/schedule")
    def schedule():
        with st.lock:
            e = eng()
            views = {v["job_id"]: v for v in e.jobs_view()}
            return [{"job": views[j.id], "plan": e.plan_view(j)} for j in e.jobs.values()
                    if j.state in ("PENDING", "PLANNED", "RUNNING")]

    @app.post("/replan", dependencies=[Depends(auth)])
    def replan():
        with st.lock:
            return eng().replan("manual")

    @app.get("/forecast")
    def forecast(region: str | None = None):
        with st.lock:
            return eng().forecast_view(region)

    @app.get("/explain/{job_id}")
    def explain(job_id: str):
        with st.lock:
            e = eng()
            j = e.jobs.get(job_id)
            if not j:
                raise EngineError("not_found", f"No job '{job_id}'.", "List jobs with GET /jobs.", 404)
            if j.plan is None:
                return {"job_id": job_id, "reason": "Not planned yet.", "alternatives": []}
            p = e.plan_view(j)
            return {"job_id": job_id, "reason": j.reason, "alternatives": p["alternatives"],
                    "forced": j.forced, "infeasible": j.infeasible, "region": j.region}

    @app.get("/metrics")
    def metrics():
        with st.lock:
            return eng().metrics()

    @app.get("/alerts")
    def alerts(include_acknowledged: bool = True):
        with st.lock:
            return [a for a in eng().alerts.as_list() if include_acknowledged or not a["acknowledged"]][::-1]

    @app.post("/alerts/{alert_id}/ack", dependencies=[Depends(auth)])
    def ack(alert_id: int):
        with st.lock:
            a = eng().alerts.ack(alert_id)
            if not a:
                raise EngineError("not_found", f"No alert {alert_id}.", "List alerts with GET /alerts.", 404)
            return a.as_dict()

    @app.get("/timeline")
    def timeline():
        with st.lock:
            return eng().timeline()

    # ------------------------------------------------------------------ simulation controls
    @app.post("/sim/clock", dependencies=[Depends(auth)])
    def clock(c: ClockIn):
        with st.lock:
            e = eng()
            n = c.steps if c.steps else int(round((c.hours or 1) * 60 / s.step_min))
            n = min(n, max(0, e.total - e.now - 1))
            e.advance(n)
            return {"advanced_steps": n, "sim_time": e.ts(e.now), "now_step": e.now, "label": e.label(e.now)}

    @app.post("/sim/fail", dependencies=[Depends(auth)])
    def sim_fail(down: bool = True):
        """Demo: force the (mock) provider down or back up, then re-plan. Shows fallback + banner."""
        with st.lock:
            p = eng().provider
            if not isinstance(p, MockProvider):
                raise EngineError("not_supported", "Outage injection only works with the mock provider.",
                                  "Switch provider to 'mock' first (POST /provider).", 409)
            p.down = down
            out = eng().replan("provider_change")
            return {**out, "provider_down": down}

    @app.post("/sim/reset", dependencies=[Depends(auth)])
    def sim_reset():
        with st.lock:
            e = st.reset()
            return e.health()

    @app.post("/provider", dependencies=[Depends(auth)])
    def set_provider(p: ProviderIn):
        with st.lock:
            if p.provider not in PROVIDERS:
                raise EngineError("unknown_provider", f"Unknown provider '{p.provider}'.", f"Choose one of {', '.join(PROVIDERS)}.", 422)
            e = st.reset(p.provider)
            e.replan("provider_change")
            return e.health()

    @app.get("/regions")
    def regions():
        with st.lock:
            return [{"key": k, "label": s.regions[k].label, "synthetic": s.regions[k].synthetic}
                    for k in eng().regions]

    @app.get("/scenarios")
    def scenarios():
        return scenario_list()

    @app.post("/demo/seed", dependencies=[Depends(auth)])
    def demo_seed(b: SeedIn):
        with st.lock:
            try:
                st.engine = build_demo_engine(s, b.scenario, b.seed, store=st.store)
            except KeyError:
                raise EngineError("unknown_scenario", f"Unknown scenario '{b.scenario}'.",
                                  f"Choose one of {', '.join(x['name'] for x in scenario_list())}.", 422)
            st.engine.replan("tick")
            return {"scenario": b.scenario, "jobs": len(st.engine.jobs), **st.engine.health()}

    # ------------------------------------------------------------------ benchmark
    @app.post("/bench/run", dependencies=[Depends(auth)])
    def bench_run(scenario: str = Query("all"), seeds: int = Query(20, ge=1, le=50)):
        names = [n for n, _, _ in benchmod.SCENARIOS]
        if scenario != "all" and scenario not in names:
            raise EngineError("unknown_scenario", f"Unknown scenario '{scenario}'.", f"Choose all or one of {', '.join(names)}.", 422)
        bs = benchmod.bench_settings(s)
        picks = names if scenario == "all" else [scenario]
        res = benchmod.run_all(seeds, bs) if scenario == "all" else \
            {"seeds": seeds, "data": "synthetic (mock provider)",
             "scenarios": [benchmod.run_scenario(n, seeds, bs) for n in picks]}
        if scenario == "all":
            (ROOT / "bench").mkdir(exist_ok=True)
            (ROOT / "bench" / "results.json").write_text(json.dumps(res), encoding="utf-8")
            (ROOT / "bench" / "results.md").write_text(benchmod.markdown_table(res) + "\n", encoding="utf-8")
            st.store.save_bench("all", res)
        return res

    @app.get("/bench/latest")
    def bench_latest():
        res = st.store.latest_bench("all")
        if res is None:
            f = ROOT / "bench" / "results.json"
            if f.exists():
                res = json.loads(f.read_text(encoding="utf-8"))
        return res or {"scenarios": [], "data": "none yet. POST /bench/run or run `make bench`."}

    @app.get("/executor")
    def executor_info():
        e = eng()
        return {"backend": e.backend.name, "manifests": getattr(e.backend, "manifests", [])}

    # ------------------------------------------------------------------ UI
    if FRONTEND.exists():
        app.mount("/static", StaticFiles(directory=str(FRONTEND)), name="static")

        @app.get("/", include_in_schema=False)
        def index():
            return FileResponse(FRONTEND / "index.html")

    return app


app = create_app()
