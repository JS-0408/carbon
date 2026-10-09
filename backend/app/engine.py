"""Engine: observer -> estimator -> scheduler -> executor -> advisor/alerts/evidence on a simulated clock.

Clock: integer steps from `origin` (step = STEP_MIN minutes). Jobs move PENDING -> PLANNED -> RUNNING -> DONE.
Re-planning: every TICK_STEPS and on any provider change or overrun. Started jobs are locked in the
capacity array; only not-yet-started jobs are re-planned.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Optional

from . import advisor, evidence
from .alerts import AlertStore, drift_exceeded
from .config import Settings
from .core import Job, PlanResult, add_load, baseline, fc_at, plan
from .estimator import Estimator, n_steps
from .executor import SimBackend
from .models import JobIn
from .observer import Observer
from .providers import MockProvider
from .providers.base import ProviderError, iso


class EngineError(Exception):
    def __init__(self, error: str, detail: str, fix: str, status: int = 422):
        super().__init__(detail)
        self.error, self.detail, self.fix, self.status = error, detail, fix, status


def _midnight_utc() -> datetime:
    return datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)


class Engine:
    def __init__(self, settings: Settings, provider=None, seed: int = 0, auto_replan: bool = True,
                 origin: Optional[datetime] = None, backend=None, store=None, adaptive_pad: bool = True):
        self.s = settings
        self.seed = seed
        self.provider = provider or MockProvider(settings, seed=seed)
        self.origin = origin or _midnight_utc()
        self.total = settings.timeline_steps
        self.auto_replan = auto_replan
        self.backend = backend or SimBackend()
        self.store = store
        self.estimator = Estimator(settings, adaptive=adaptive_pad)
        self.alerts = AlertStore(on_add=(lambda a: store.log("alert", a.as_dict())) if store else None)
        self.now = 0
        self.jobs: dict[str, Job] = {}
        self.loads: dict[str, list] = {}
        self.forecasts: dict = {}
        self.actual: dict = {}
        self.replans = 0
        self._fb_seen: set = set()
        self._pending_replan = False
        self._init_provider()

    # ------------------------------------------------------------------ provider / regions
    def _init_provider(self) -> None:
        p = self.provider
        if p.kind == "series" and p.name == "mock":
            self.regions = [k for k, r in self.s.regions.items() if r.synthetic]
        elif p.name == "uk_replay":
            self.regions = ["uk"] if "uk" in self.s.regions else [next(iter(self.s.regions))]
            try:
                p.load()
                self.origin = datetime.fromisoformat(p.meta["from"].replace("Z", "+00:00"))
            except ProviderError:
                pass
        else:
            self.regions = [k for k, r in self.s.regions.items() if p.name in r.codes] or [next(iter(self.s.regions))]
        self.primary = self.regions[0]
        self.observer = Observer(self.s, p, self.origin, backoff_s=0.0 if p.kind == "series" else 0.2)
        self.loads = {r: [] for r in self.regions}
        self.actual = {}
        for r in self.regions:
            try:
                self.actual[r] = list(p.actual(r, self.total, self.s.step_min)) if hasattr(p, "actual") else None
            except ProviderError:
                self.actual[r] = None

    def set_provider(self, provider) -> None:
        """Swap provider (keeps jobs). Invalidates cache and re-plans (provider change)."""
        running = {j.id: j for j in self.jobs.values() if j.state == "RUNNING"}
        self.provider = provider
        self._init_provider()
        for j in running.values():
            add_load(self.loads.setdefault(j.region, []), j.kw, j.actual_start, j.an)
        self.replan("provider_change")

    # ------------------------------------------------------------------ time helpers
    def ts(self, step: int) -> str:
        return iso(self.origin + timedelta(minutes=step * self.s.step_min))

    def label(self, step: int) -> str:
        spd = self.s.spd
        m = (step % spd) * self.s.step_min
        return f"D{step // spd + 1} {m // 60:02d}:{m % 60:02d}"

    def step_of(self, dt: datetime) -> int:
        return math.floor((dt - self.origin).total_seconds() / 60 / self.s.step_min + 1e-9)

    # ------------------------------------------------------------------ forecasts
    def _forecasts(self, alert: bool = True) -> dict:
        fcs = {}
        for r in self.regions:
            fc = self.observer.get_forecast(r, self.now, self.total)
            self.forecasts[r] = fc
            fcs[r] = fc.values
            if alert and fc.is_fallback and (r, self.now) not in self._fb_seen:
                self._fb_seen.add((r, self.now))
                self.alerts.add(self.now, self.ts(self.now), "fallback",
                                f"Carbon data unavailable for {r} ({self.label(self.now)}). Using historical-average profile.",
                                dedupe=False)
        return fcs

    # ------------------------------------------------------------------ job creation
    def build_job(self, spec: JobIn) -> Job:
        if spec.power_profile_kw > self.s.cap_kw:
            raise EngineError("power_exceeds_capacity",
                              f"power_profile_kw {spec.power_profile_kw} is higher than the cluster capacity of {self.s.cap_kw} kW.",
                              f"Use a value of {self.s.cap_kw} kW or less, or split the job.")
        if spec.job_id in self.jobs:
            raise EngineError("duplicate_job", f"Job '{spec.job_id}' already exists.", "Choose a different job_id.", 409)
        sub = max(0, self.step_of(spec.submission_time)) if spec.submission_time else self.now
        dl = self.step_of(spec.sla_deadline)
        regs = [r for r in spec.allowed_regions if r in self.regions] or [self.primary]
        est = spec.estimated_duration_minutes
        act = spec.sim_actual_duration_minutes or est * float(self.s.overrun_by_type.get(spec.workload_type, 1.0))
        j = Job(id=spec.job_id, wtype=spec.workload_type, kw=spec.power_profile_kw, sub=sub, dl=dl,
                n_est=self.estimator.estimate_steps(est),
                pn=self.estimator.planned_steps(spec.workload_type, est, spec.duration_p90_minutes),
                an=n_steps(act, self.s.step_min), home=regs[0], allowed=regs, data_gb=spec.data_gb,
                priority=spec.priority, preemptible=spec.preemptible)
        j.meta.update(est_min=est, act_min=act, fallback_policy=spec.fallback_policy)
        if max(self.now, sub) + j.n_est > dl:
            j.infeasible = True
        return j

    def add_job(self, j: Job, plan_now: bool = True) -> Job:
        if j.id in self.jobs:
            raise EngineError("duplicate_job", f"Job '{j.id}' already exists.", "Choose a different job_id.", 409)
        self.jobs[j.id] = j
        j.state = "PENDING"
        if plan_now:
            self._plan_jobs([j])
        self._log(j)
        return j

    def submit(self, spec: JobIn, plan_now: bool = True) -> Job:
        return self.add_job(self.build_job(spec), plan_now)

    def preview(self, spec: JobIn) -> tuple[Job, PlanResult]:
        """Plan without committing anything (no state change, no alerts)."""
        j = self.build_job(spec)
        fcs = self._forecasts(alert=False)
        res = plan([j], fcs, self._planned_load(), self.now, self.s.cap_kw, self.s.step_min, self.s.transfer_g_per_gb)[j.id]
        j.reason = advisor.explain(j, res, self.now, self.s.step_min, self.label)
        j.plan, j.start, j.region, j.forced = res, res.start, res.region, res.forced
        return j, res

    def cancel(self, job_id: str) -> Job:
        j = self.jobs.get(job_id)
        if not j:
            raise EngineError("not_found", f"No job '{job_id}'.", "List jobs with GET /jobs.", 404)
        if j.state not in ("PENDING", "PLANNED"):
            raise EngineError("cannot_cancel", f"Job '{job_id}' is {j.state} and can no longer be cancelled.",
                              "Only pending or planned jobs can be cancelled.", 409)
        del self.jobs[job_id]
        self._log(j, kind="job_cancelled")
        return j

    # ------------------------------------------------------------------ planning
    def _locked(self) -> dict:
        return {r: list(v) for r, v in self.loads.items()}

    def _planned_load(self, exclude: set | None = None) -> dict:
        loads = self._locked()
        for j in self.jobs.values():
            if j.state == "PLANNED" and (not exclude or j.id not in exclude) and j.start is not None:
                add_load(loads.setdefault(j.region, []), j.kw, j.start, j.pn)
        return loads

    def _plan_jobs(self, js: list[Job]) -> None:
        fcs = self._forecasts()
        res = plan(js, fcs, self._planned_load({j.id for j in js}), self.now, self.s.cap_kw, self.s.step_min,
                   self.s.transfer_g_per_gb)
        for j in js:
            self._apply(j, res[j.id], fcs)

    def _apply(self, j: Job, res: PlanResult, fcs: dict) -> None:
        prev = j.start if j.state == "PLANNED" else None
        j.plan, j.start, j.region, j.forced, j.state = res, res.start, res.region, res.forced, "PLANNED"
        j.fc_at_plan = fcs[res.region][res.start:res.start + j.pn]
        j.meta["fcs"] = fcs
        j.reason = advisor.explain(j, res, self.now, self.s.step_min, self.label)
        t, step = self.ts(self.now), self.s.step_min
        if j.infeasible:
            self.alerts.add(self.now, t, "infeasible",
                            f"{j.id}: cannot meet its deadline even if started now. Starting at earliest slot.", j.id)
        elif res.forced:
            self.alerts.add(self.now, t, "sla_risk",
                            f"{j.id}: no feasible window before deadline. Starting at earliest slot.", j.id)
        elif j.dl - j.pn - max(self.now, j.sub) < 0.1 * j.n_est:
            self.alerts.add(self.now, t, "sla_risk",
                            f"{j.id}: less than 10% of its duration is left as slack before the deadline.", j.id)
        if res.wait_cap_steps >= 12:
            self.alerts.add(self.now, t, "capacity",
                            f"{j.id}: queue demand exceeds cluster capacity; earliest start delayed {res.wait_cap_steps * step // 60} h.",
                            j.id)
        if prev is not None and abs(prev - res.start) >= self.s.replan_alert_steps:
            self.alerts.add(self.now, t, "replan",
                            f"{j.id}: start moved {self.label(prev)} -> {self.label(res.start)} after forecast update.",
                            j.id, dedupe=False)

    def replan(self, trigger: str = "manual") -> dict:
        """Re-plan all not-yet-started jobs against a fresh forecast; started jobs stay locked."""
        self.observer.invalidate() if trigger in ("provider_change", "manual", "overrun") else None
        fcs = self._forecasts()
        pend = [j for j in self.jobs.values() if j.state in ("PENDING", "PLANNED")]
        self.replans += 1
        if pend:
            res = plan(pend, fcs, self._locked(), self.now, self.s.cap_kw, self.s.step_min, self.s.transfer_g_per_gb)
            for j in sorted(pend, key=lambda x: x.id):
                self._apply(j, res[j.id], fcs)
                self._log(j)
        return {"trigger": trigger, "replanned": len(pend), "now": self.ts(self.now),
                "fallback": any(f.is_fallback for f in self.forecasts.values())}

    # ------------------------------------------------------------------ execution
    def advance(self, steps: int = 1) -> None:
        for _ in range(steps):
            self._step()

    def _step(self) -> None:
        now, t = self.now, self.ts(self.now)
        running = [j for j in self.jobs.values() if j.state == "RUNNING"]
        for j in running:
            if j.actual_start + j.an <= now:
                self._finish(j)
        for j in [j for j in self.jobs.values() if j.state == "RUNNING"]:
            if not j.overrun_flagged and now - j.actual_start >= j.pn:
                j.overrun_flagged = True
                self.alerts.add(now, t, "overrun",
                                f"{j.id} is running longer than its padded estimate; recomputing risk for jobs behind it.",
                                j.id)
                self._pending_replan = True
        for j in sorted([j for j in self.jobs.values() if j.state == "PLANNED" and j.start is not None and j.start <= now],
                        key=lambda x: (x.start, x.id)):
            load = self.loads.setdefault(j.region, [])
            if not self._free_now(load, j):
                j.start = now + 1                    # capacity still held by an overrunning job: wait a step
                j.meta["deferred"] = j.meta.get("deferred", 0) + 1
                continue
            j.state, j.actual_start = "RUNNING", now
            add_load(load, j.kw, now, j.an)
            self.backend.on_start(j, t)
            self._log(j)
        self.now += 1
        if self._pending_replan or (self.auto_replan and self.now % self.s.tick_steps == 0):
            trig = "overrun" if self._pending_replan else "tick"
            self._pending_replan = False
            self.replan(trig)

    def _free_now(self, load: list, j: Job) -> bool:
        return (load[self.now] if self.now < len(load) else 0.0) + j.kw <= self.s.cap_kw + 1e-9

    def _finish(self, j: Job) -> None:
        j.state, j.actual_end = "DONE", j.actual_start + j.an
        t = self.ts(self.now)
        self.estimator.observe(j.wtype, j.meta.get("est_min", j.n_est * self.s.step_min), j.an * self.s.step_min)
        if j.actual_end > j.dl:
            late = (j.actual_end - j.dl) * self.s.step_min
            self.alerts.add(self.now, t, "sla_miss", f"{j.id} missed deadline by {late} min (duration overran estimate).", j.id)
        act = self.actual.get(j.region)
        if act is not None and j.fc_at_plan:
            f_mean = sum(j.fc_at_plan[:j.an]) / len(j.fc_at_plan[:j.an])
            a_mean = sum(fc_at(act, j.actual_start + k) for k in range(j.an)) / j.an
            if drift_exceeded(f_mean, a_mean):
                self.alerts.add(self.now, t, "forecast_drift",
                                f"{j.id}: realized intensity {a_mean:.0f} differs from forecast {f_mean:.0f} gCO2/kWh by more than 20%.",
                                j.id)
        self.backend.on_finish(j, t)
        self._log(j)

    # ------------------------------------------------------------------ views
    def _log(self, j: Job, kind: str = "job") -> None:
        if self.store:
            self.store.log(kind, {"id": j.id, "state": j.state, "start": j.start, "region": j.region})

    def job_view(self, j: Job, base_start: int | None = None) -> dict:
        step = self.s.step_min
        plan_start = j.actual_start if j.actual_start is not None else j.start
        slack = None if plan_start is None else (j.dl - plan_start - j.pn) * step
        return {
            "job_id": j.id, "workload_type": j.wtype, "state": j.state, "power_kw": j.kw,
            "region": j.region or j.home, "home_region": j.home, "priority": j.priority,
            "submission_time": self.ts(j.sub), "sla_deadline": self.ts(j.dl),
            "planned_start": self.ts(j.start) if j.start is not None else None,
            "actual_start": self.ts(j.actual_start) if j.actual_start is not None else None,
            "actual_end": self.ts(j.actual_end) if j.actual_end is not None else None,
            "planned_minutes": j.pn * step, "estimated_minutes": j.n_est * step,
            "actual_minutes": j.an * step if j.state == "DONE" else None,
            "slack_minutes": slack, "forced": j.forced, "infeasible": j.infeasible,
            "deadline_missed": bool(j.actual_end is not None and j.actual_end > j.dl),
            "reason": j.reason,
            "baseline_start": self.ts(base_start) if base_start is not None else None,
            "label_start": self.label(plan_start) if plan_start is not None else None,
        }

    def plan_view(self, j: Job) -> dict | None:
        if j.plan is None:
            return None
        p = j.plan
        return {"job_id": j.id, "start": self.ts(p.start), "region": p.region, "padded_steps": j.pn,
                "expected_gco2": round(p.expected_g, 1), "baseline_gco2": round(p.baseline_g, 1),
                "forced": p.forced, "forecast_source": self.forecasts[p.region].source if p.region in self.forecasts else None,
                "alternatives": [{**a, "start": self.ts(a["start"]), "finish": self.ts(a["finish"]),
                                  "label_start": self.label(a["start"])} for a in p.alternatives]}

    def jobs_view(self) -> list:
        base = baseline(list(self.jobs.values()), self.s.cap_kw) if self.jobs else {}
        return [self.job_view(j, base.get(j.id)) for j in sorted(self.jobs.values(), key=lambda x: (x.sub, x.id))]

    def forecast_view(self, region: str | None = None) -> dict:
        r = region or self.primary
        if r not in self.regions:
            raise EngineError("unknown_region", f"Region '{r}' is not available for provider '{self.provider.name}'.",
                              f"Use one of: {', '.join(self.regions)}.", 404)
        fc = self.observer.get_forecast(r, self.now, self.total)
        self.forecasts[r] = fc
        cfg = self.s.regions[r]
        return {"region": r, "label": cfg.label, "source": fc.source, "is_fallback": fc.is_fallback,
                "synthetic": fc.synthetic, "partial": fc.partial, "generated_at": fc.generated_at,
                "step_minutes": fc.step_minutes, "unit": "gCO2/kWh", "note": fc.note,
                "origin": iso(self.origin), "now_step": self.now,
                "values": [round(v, 1) for v in fc.values],
                "actual": [round(v, 1) for v in self.actual[r]] if self.actual.get(r) else None}

    def metrics(self) -> dict:
        self._forecasts(alert=False)
        fcs = {r: f.values for r, f in self.forecasts.items()}
        ev = evidence.evaluate(list(self.jobs.values()), self.s.cap_kw, self.s.step_min, fcs, self.actual,
                               self.s.transfer_g_per_gb) if self.jobs else {"forecasted": None, "realized": None,
                                                                            "jobs": [], "deadlines": None, "wait": None}
        counts: dict = {}
        for j in self.jobs.values():
            counts[j.state] = counts.get(j.state, 0) + 1
        ev["counts"] = counts
        ev["synthetic"] = any(f.synthetic for f in self.forecasts.values())
        return ev

    def timeline(self) -> dict:
        step = self.s.step_min
        fv = self.forecast_view()
        base = baseline(list(self.jobs.values()), self.s.cap_kw) if self.jobs else {}
        rows = []
        for j in sorted(self.jobs.values(), key=lambda x: (x.sub, x.id)):
            s1 = j.actual_start if j.actual_start is not None else j.start
            rows.append({"id": j.id, "type": j.wtype, "kw": j.kw, "sub": j.sub, "dl": j.dl, "state": j.state,
                         "base_start": base.get(j.id), "start": s1, "n_plan": j.pn,
                         "n_actual": j.an if j.state == "DONE" else None, "n_est": j.n_est,
                         "region": j.region or j.home, "forced": j.forced,
                         "missed": bool(j.actual_end is not None and j.actual_end > j.dl),
                         "n_base": j.an})
        return {"forecast": fv, "jobs": rows, "now": self.now, "step_minutes": step, "steps_per_day": self.s.spd,
                "cap_kw": self.s.cap_kw}

    def health(self) -> dict:
        fb = [r for r, f in self.forecasts.items() if f.is_fallback]
        return {"status": "ok", "provider": self.provider.name, "synthetic": bool(getattr(self.provider, "synthetic", False)),
                "fallback_active": bool(fb), "fallback_regions": fb, "regions": self.regions,
                "sim_time": self.ts(self.now), "now_step": self.now, "executor": self.backend.name,
                "last_provider_error": self.observer.last_error}
