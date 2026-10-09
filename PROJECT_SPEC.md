# Carbon-Aware AI Workload Scheduler: Build Spec and Progress Tracker

Version 1.0, 2026-10-09. Audience: the Antigravity agent (and the human supervising it).
Copy this file to the repo root as `PROJECT_SPEC.md`. Also copy it (or a pointer to it) to `GEMINI.md` and `AGENTS.md` so it loads automatically.

---

## 0. How the agent must use this file

1. Read this whole file before planning. Produce an Implementation Plan artifact that maps to Section 15 (tasks), then start.
2. Work task by task in Section 15 order. After finishing a task: tick its box, set its status, and append a line to the Progress Log (Section 17). Keep the Antigravity Task List artifact in sync with Section 15.
3. A task is done only when its acceptance check passes and you have pasted the command and result summary into the Progress Log.
4. Never invent data. If you cannot reach a provider, use the fallback and say so. Any number shown in the UI must come from code in this repo.
5. Never claim real grid data is in use unless a real provider returned it. Synthetic data must be labelled "synthetic" in the UI and the report.
6. Do not change formulas, units or invariants in Section 6 without recording an ADR in `docs/DECISIONS.md`.
7. Keep changes small and reviewable. Run tests before every commit.
8. If this spec conflicts with something you find in a provider's current docs, trust the docs, record the finding in `docs/DECISIONS.md`, and continue.

---

## 1. The brief (source of truth)

**Description.** AI workloads consume significant energy and can run during carbon-intensive grid conditions, because existing cloud schedulers prioritize speed and cost over carbon intensity. There is a need for carbon-aware scheduling that reduces environmental impact while meeting deadlines and resource constraints.

**Challenges.**
- C1: Analyze AI workloads and compute resource usage, accounting for variation in workload demand and energy availability, so the system produces reliable results from incomplete or changing real-world inputs.
- C2: Integrate workload scheduling and energy/carbon information with resource allocation and carbon-aware execution, without a workflow that is hard for intended users to operate or interpret.
- C3: Provide reduced environmental impact that can be validated with measurable evidence, while handling performance constraints, changing energy conditions and other practical constraints.

**Expected outcomes.**
- O1: Working Carbon-Aware AI Workload Scheduler
- O2: Workload scheduling and energy/carbon information system
- O3: Resource allocation, carbon-aware execution and decision-support module
- O4: Dashboard and alerting showing reduced environmental impact
- O5: Performance and result analysis using representative real-world scenarios
- O6: Final technical report and demonstration

---

## 2. Requirement traceability (every row must be green before submission)

| ID | Requirement | Module | Acceptance evidence |
|---|---|---|---|
| R1 | Handle incomplete data | Observer | Test: provider raises/times out -> fallback profile used, alert `fallback` raised, schedule still produced |
| R2 | Handle changing conditions | Executor | Test: forecast changes between ticks -> pending jobs re-planned, `replan` alert on large moves |
| R3 | Handle variation in workload demand | Scheduler | Scenario `heavy_load` runs 24+ jobs on limited capacity without capacity violations |
| R4 | Estimate workload duration and power | Estimator | Unit tests for duration range and padded planning duration |
| R5 | Resource allocation | Scheduler/Allocator | Invariant INV1 (capacity never exceeded) passes on all scenarios |
| R6 | Deadline (SLA) respected | Scheduler | Invariant INV2; scenario `tight_deadlines` |
| R7 | Carbon-aware execution | Executor | Jobs move PENDING -> RUNNING -> DONE at planned times; start/end timestamps recorded |
| R8 | Decision support | Advisor | Each job has a reason string and a list of alternatives with gCO2 each |
| R9 | Measurable evidence | Metrics | Baseline vs optimized gCO2, savings %, labelled forecasted vs realized |
| R10 | Dashboard | UI | Views in Section 10 render from live API data |
| R11 | Alerting | Alerts | All alert types in Section 11 can be triggered by tests |
| R12 | Usable by intended users | UI | Plain-language reasons; submit-a-job form with validation; no jargon without tooltip |
| R13 | Representative scenarios | Benchmark | Five scenarios in Section 14, 20 seeds each, results table exported |
| R14 | Final report and demo | Docs | `docs/REPORT.md` and `docs/DEMO_SCRIPT.md` exist and match the real results |

---

## 3. Scope

**In scope:** time-shifting of flexible AI jobs within one grid region; multi-job queue with a kW capacity limit; forecast adapters with fallback; re-planning; simulated execution; dashboard; alerts; benchmark; report.

**Optional stretch (only after all R1 to R14 are green):** spatial shifting across regions with a data-transfer penalty; Kubernetes job adapter; CodeCarbon measurement of a real small training run; checkpoint-and-resume for preemptible jobs.

**Non-goals:** real GPU cluster management, billing, authentication beyond a simple API key, multi-tenant isolation.

---

## 4. Tech decisions (default; change only with an ADR)

- Backend: Python 3.11+, FastAPI, Pydantic v2, SQLite (via SQLModel or plain sqlite3), APScheduler (or an asyncio loop) for ticks. Standard library for scheduling math.
- Frontend: React + Vite + TypeScript (or a single-page HTML dashboard if time is short). Charts: Recharts or inline SVG.
- Tests: pytest, hypothesis (property tests), httpx for API tests.
- Packaging: `docker compose up` must start API + UI. `make test`, `make bench`, `make demo` must exist.
- Config: environment variables plus `config.yaml` (Section 18). No secrets in git.

### Repo layout
```
/
  PROJECT_SPEC.md          (this file)
  GEMINI.md, AGENTS.md     (pointers to this file)
  PROGRESS.md              (optional mirror of Section 17)
  docs/ DECISIONS.md REPORT.md DEMO_SCRIPT.md
  backend/
    app/ main.py api/ models.py config.py
    observer/ providers/{base,mock,carbon_aware_sdk,watttime,electricitymaps}.py fallback.py cache.py
    estimator/ profile.py
    scheduler/ plan.py capacity.py explain.py
    executor/ runner.py sim.py
    alerts/ rules.py
    metrics/ evidence.py
    bench/ scenarios.py run.py
    tests/
  frontend/ (Vite app)
  reference/carbon_scheduler.py   (provided reference implementation; port, do not copy blindly)
  reference/results.json          (provided reference benchmark output)
  docker-compose.yml  Makefile  .env.example  config.yaml
```

---

## 5. Data contracts

### 5.1 Job submission (input)
Improves on the earlier draft: explicit units, a duration range, and provider-neutral regions.
```json
{
  "job_id": "ai-train-resnet50-001",
  "workload_type": "model_training",
  "estimated_duration_minutes": 120,
  "duration_p90_minutes": 150,
  "power_profile_kw": 1.5,
  "submission_time": "2026-10-09T08:00:00Z",
  "sla_deadline": "2026-10-09T20:00:00Z",
  "priority": "normal",
  "preemptible": false,
  "allowed_regions": ["default"],
  "fallback_policy": "historical_average"
}
```
Validation rules (reject with HTTP 422 and a plain-language message):
- `estimated_duration_minutes` > 0 and <= 4320; `duration_p90_minutes` >= estimated if given.
- `power_profile_kw` > 0 and <= cluster capacity.
- `sla_deadline` > `submission_time` + padded duration, else mark `infeasible` and alert immediately (do not silently accept).
- All timestamps ISO 8601 UTC. Convert to integer steps internally (Section 6).
- `workload_type` in `model_training | batch_inference | realtime_inference | etl | other`. `realtime_inference` is never delayed (slack = 0).
- `allowed_regions` values are internal region keys mapped to provider-native codes in `config.yaml` (do not hardcode strings like `IN-TS`).

### 5.2 Internal records
- `Job`: id, type, duration_min, duration_p90_min, kw, submit_ts, deadline_ts, state (`PENDING|PLANNED|RUNNING|DONE|FAILED|INFEASIBLE`), planned_start_ts, actual_start_ts, actual_end_ts, forced (bool), reason (text).
- `Forecast`: region, generated_at, source (`carbon_aware_sdk|watttime|electricitymaps|fallback|mock`), step_minutes, points[{ts, g_per_kwh}], is_fallback (bool).
- `Plan`: job_id, start_ts, padded_steps, expected_gco2, baseline_gco2, alternatives[{label, start_ts, gco2}], created_at, forecast_source.
- `Alert`: id, ts, level (`info|warning|critical`), type, job_id?, message, acknowledged (bool).
- `Evidence`: per job and aggregate: e_base_g, e_opt_g, savings_pct, basis (`forecasted|realized`).

---

## 6. Algorithm (do not change without an ADR)

Units: intensity `I` in gCO2/kWh, power `P` in kW, step `dt` in minutes (default 30).

**Emissions if a job starts at step s with n steps:**
`C(s) = sum_{k=0..n-1} P * (dt/60) * I[s+k]`  (grams CO2)

**Planning duration:** `n_plan = ceil(duration_p90_or(estimate*PAD) / dt)`, PAD default 1.25.
**Actual duration** (for realized evidence) comes from execution, never from the estimate.

**Decision:** choose the start s that minimizes `C(s)` subject to
- `s >= max(now, submit_step)`
- `s + n_plan <= deadline_step`
- for every k in [0, n_plan): `load[s+k] + P <= CAP`
Tie-break: earliest start.

**Ordering for multi-job:** least slack first, where `slack = deadline_step - n_plan - max(now, submit_step)`.

**Forced start:** if no feasible window exists, start at the earliest capacity-feasible step, set `forced=true`, raise a `sla_risk` critical alert. Do not hide this.

**Baseline (E_base):** the same job set run in submission order at the earliest step with free capacity (what a normal scheduler does). Compute baseline with the **actual** intensity, same as optimized, so the comparison is fair.

**Savings:** `savings_pct = (E_base - E_opt) / E_base * 100`. Report both `forecasted` (at planning time) and `realized` (after execution, using actual intensity). Never mix marginal and average signals in one comparison.

**Re-planning:** every TICK (default 6 h) and on any provider change: fetch a new forecast, keep RUNNING/started jobs locked in the capacity array, re-plan all not-yet-started jobs. Raise `replan` info alert when a start moves by >= 4 steps (2 h).

**Fallback:** if the provider fails (timeout > 5 s, HTTP error, empty data, stale > 3 h), use the historical-average diurnal profile for that region (`config.yaml: fallback_profiles`), mark the forecast `is_fallback=true`, raise a `fallback` warning, and show a banner in the UI.

**Unit conversions (provider adapters must normalize to gCO2/kWh):**
- WattTime MOER: lbs CO2/MWh -> g/kWh multiply by 0.45359237.
- Electricity Maps: already gCO2eq/kWh.
- Carbon Aware SDK: gCO2/kWh.

**Invariants (property-tested):**
- INV1: planned load never exceeds CAP at any step.
- INV2: if a feasible window exists, the planned job finishes before its deadline (using padded duration).
- INV3: with a perfect forecast and non-binding capacity, `E_opt <= E_base`.
- INV4: provider failure never prevents a schedule being produced.
- INV5: all stored intensities are gCO2/kWh and finite and positive.
- INV6: `realtime_inference` jobs start at their earliest feasible step.

---

## 7. Provider adapters (Observer)

Common interface: `get_forecast(region, start_ts, end_ts, step_min) -> Forecast`. Timeout 5 s, 2 retries with backoff, cache 15 min, never raise to callers (return fallback instead).

| Provider | Role | Endpoint and auth | Verified constraints |
|---|---|---|---|
| Carbon Aware SDK (GSF) | Primary (self-hosted WebApi) | `GET /emissions/forecasts/current?location=<loc>&dataStartAt=<iso>&dataEndAt=<iso>&windowSize=<minutes>` | Returns an array, one forecast per location, with `forecastData` and `optimalDataPoints`. Set `dataEndAt` to the deadline. `location` must be valid for the data source you configure behind the SDK. India coverage is not verified. |
| WattTime v3 | Optional | `GET /login` with HTTP Basic -> JWT; `GET /v3/region-from-loc`; `GET /v3/forecast` with Bearer | Free plan only gives region CAISO_NORTH. India appears as national region `IND`, not per state. Always resolve region with `region-from-loc`. Units lbs/MWh. Marginal signal. |
| Electricity Maps | Optional | `GET /v3/carbon-intensity/forecast?zone=<zone>` with header `auth-token` | Free tier has only `latest` and `history` (24 h). Forecast needs paid or trial. Free tier is limited to one zone and non-commercial use. Call `/v3/zones` to get valid zone keys. Grid average, not marginal. |
| Mock/Synthetic | Default for tests and demo | In-process | Diurnal profile in `reference/carbon_scheduler.py` (`base_ci`). Must be labelled synthetic. |
| Fallback | Always available | Static profile | Section 6. |

Rules:
- Verify endpoint paths and parameters against each provider's current documentation when implementing. Record any difference in `docs/DECISIONS.md`.
- A provider is "real data" only if the response came from that provider in the current run. The UI shows the source for every forecast.
- Optional real-data demo: a keyless public provider (for example the UK Carbon Intensity API) can prove that real forecasts work end to end, but it is not India. Verify its endpoint before use and label the region clearly.

---

## 8. REST API (backend)

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | status, active provider, fallback state |
| POST | `/jobs` | submit a job (Section 5.1); returns job and initial plan |
| GET | `/jobs` , `/jobs/{id}` | list/detail incl. state, plan, reason |
| DELETE | `/jobs/{id}` | cancel pending job |
| GET | `/schedule` | current plan for all pending/planned/running jobs |
| POST | `/replan` | force re-plan now |
| GET | `/forecast?region=` | current forecast with source and `is_fallback` |
| GET | `/explain/{id}` | reason string and alternatives with gCO2 |
| GET | `/metrics` | aggregate Evidence (forecasted and realized) |
| GET | `/alerts` | alert feed; `POST /alerts/{id}/ack` |
| POST | `/bench/run?scenario=&seeds=` | run a benchmark scenario, return KPIs |
| POST | `/sim/clock` | advance simulated clock (demo mode) |

All responses JSON, timestamps ISO UTC, errors as `{error, detail, fix}`. OpenAPI docs enabled. Demo mode uses a simulated clock so a 3-day scenario runs in seconds.

---

## 9. Executor and resource allocation

- Simulated executor (required): a clock-driven loop moves jobs PENDING -> PLANNED -> RUNNING -> DONE at planned times and applies actual durations (with optional overrun factor per scenario).
- Capacity: cluster `CAP_KW` (default 8.0). Optionally also `GPU_COUNT`.
- Overrun handling: if a RUNNING job exceeds its padded duration, raise `overrun` warning and recompute risk for jobs behind it.
- Optional Kubernetes adapter: map a planned start to creating a `Job`/`CronJob`, or to scaling a queue consumer. Keep it behind an interface so it is swappable. KEDA only caps replicas by current intensity; it does not find optimal windows, so do not use it as the scheduler.

---

## 10. Dashboard (required views)

1. Overview KPIs: carbon saved % (forecasted and realized, clearly labelled), baseline vs optimized grams, deadlines met %, average wait.
2. Timeline: forecast intensity curve with each job's baseline bar and scheduled bar, red outline for missed deadlines.
3. Job queue: state, planned start, deadline, slack remaining, reason text.
4. Decision support panel: for a selected job, three alternatives (run now, optimal, latest feasible) with gCO2 and finish time, and the reason in plain language.
5. Alerts feed with severity and acknowledge.
6. Scenario results: bar chart of savings per scenario with min/max range, plus the results table.
7. Data source banner: shows provider name, or "Fallback profile in use", or "Synthetic data".
8. Submit-job form with validation messages and a preview of the chosen window before confirming.

UX rules: sentence case, plain verbs, tooltips for terms like MOER; keyboard focus visible; mobile responsive; light and dark themes; no colour-only meaning.

---

## 11. Alert rules

| Type | Level | Trigger |
|---|---|---|
| `fallback` | warning | provider failed or stale; fallback profile used |
| `sla_risk` | critical | no feasible green window; forced start; or slack < 10% of duration |
| `sla_miss` | critical | job finished after deadline |
| `overrun` | warning | running job exceeds padded duration |
| `replan` | info | planned start moved >= 2 h after a forecast update |
| `infeasible` | critical | job cannot meet deadline even if started now |
| `forecast_drift` | warning | realized intensity differs from forecast by > 20% over a job's run |
| `capacity` | warning | queue demand exceeds capacity for > 6 h |

Each alert must be reachable by an automated test.

---

## 12. Evidence and honesty rules

- Always report baseline and optimized in the same units and signal type.
- Label every savings number as `forecasted` or `realized`.
- Report ranges across seeds, not only the mean. Individual runs can be negative when forecasts are wrong; state this.
- Report delay cost (average wait) next to savings.
- Optional: measure a real small PyTorch run with CodeCarbon to calibrate `power_profile_kw`. Verify the library's current API first. If not done, say power is declared, not measured.

---

## 13. Test plan

- Unit: cost function, padding, unit conversions, tie-breaking, fallback selection, validation.
- Property tests (hypothesis): INV1 to INV6 on random job sets.
- Integration: API flow submit -> plan -> run (simulated clock) -> metrics; provider failure injection.
- Benchmark (`make bench`): scenarios in Section 14, 20 seeds each, outputs `bench/results.json` and a markdown table.
- UI: smoke test that each view renders with fixture data; accessibility check for contrast and focus.

---

## 14. Benchmark scenarios

| Name | Setup |
|---|---|
| weekday_mix | 12 mixed jobs, normal forecast, 8 kW |
| tight_deadlines | same mix, slack cut to a quarter |
| api_outage | provider down for 12 h, fallback active |
| overrun_cloudy | weak solar dip, training jobs take 45% longer than estimated |
| heavy_load | 24 jobs on the same 8 kW |

**Reference results** from `reference/carbon_scheduler.py` (synthetic profile, 20 seeds). These are a sanity check, not targets to hit exactly; a port with a different random generator will differ slightly.

| Scenario | Savings mean (min..max) | Deadlines met, immediate -> scheduled |
|---|---|---|
| weekday_mix | 7.1% (0.3..13.7) | 100% -> 100% |
| tight_deadlines | 1.5% (-1.1..4.4) | 100% -> 98% |
| api_outage | 7.0% (1.4..13.8) | 100% -> 100% |
| overrun_cloudy | 3.1% (-1.7..7.3) | 100% -> 92% |
| heavy_load | 4.0% (0.2..8.8) | 98% -> 98% |

Expected qualitative behaviour: positive mean savings for flexible mixes; near-zero savings when slack is small; some deadline misses only when durations overrun; fallback scenario still produces a valid schedule.

**Known weaknesses to fix or disclose** (reference code): 25% padding is too small for training overruns (8% misses); independent per-step forecast noise is simplistic; greedy placement is not globally optimal; execution is simulated.

---

## 15. Task breakdown and tracker

Status values: `TODO`, `IN_PROGRESS`, `BLOCKED`, `DONE`. Tick the box only after the acceptance check passes.

### Milestone M0: Setup
- [x] **T00** Repo scaffold, Makefile, docker-compose, `.env.example`, `config.yaml`, CI that runs tests. Accept: `make test` passes on an empty suite.
- [x] **T01** Install workspace rules and workflows (Section 16). Accept: rules visible in Customizations.

### Milestone M1: Core engine (R4, R5, R6)
- [x] **T02** Port cost function, capacity checking and `plan()` from reference with the Section 6 contract. Accept: unit tests for cost, capacity, tie-break.
- [x] **T03** Estimator with p90 duration and padding. Accept: unit tests.
- [x] **T04** Property tests INV1 to INV3, INV6. Accept: 500+ hypothesis examples pass.

### Milestone M2: Data and resilience (R1, R2)
- [x] **T05** Provider interface, mock provider, fallback profile, cache, unit conversion. Accept: INV4 and INV5 tests.
- [x] **T06** Carbon Aware SDK adapter. Accept: contract test against recorded response and a live call if an SDK instance is available.
- [x] **T07** WattTime and Electricity Maps adapters (behind feature flags). Accept: tests with recorded fixtures; clear error when free tier lacks access.
- [x] **T08** Re-plan loop with locking of started jobs. Accept: test for R2.

### Milestone M3: Execution and decisions (R7, R8)
- [x] **T09** Simulated executor with simulated clock and overrun factor.
- [x] **T10** Advisor: reason strings and alternatives per job. Accept: every planned job has both.
- [x] **T11** Alert engine with all Section 11 types. Accept: one test per type.

### Milestone M4: API and evidence (R9)
- [x] **T12** FastAPI endpoints from Section 8 with validation and error format.
- [x] **T13** Evidence module: forecasted and realized savings, baseline computed fairly. Accept: formula tests.

### Milestone M5: Dashboard (R10, R12)
- [x] **T14** Frontend scaffold and API client.
- [x] **T15** Views 1 to 8 from Section 10. Accept: screenshot per view saved in `docs/screens/`.
- [x] **T16** Submit form with validation and window preview.

### Milestone M6: Benchmark and analysis (R13)
- [x] **T17** Scenarios and runner, 20 seeds, results JSON and table. Accept: `make bench` outputs table close to Section 14 qualitatively.
- [x] **T18** Fix known weaknesses: increase training padding or add checkpoint policy; re-run and record before/after.

### Milestone M7: Report and demo (R14)
- [x] **T19** `docs/REPORT.md`: problem, method, formulas, architecture, results table, limitations, future work.
- [x] **T20** `docs/DEMO_SCRIPT.md`: 5-minute script including the SLA-override moment and the API-outage moment.
- [x] **T21** Final verification: Section 2 table all green; `docker compose up` works from a clean clone.

### Stretch (only after T21)
- [x] **S1** Spatial shifting with data-transfer penalty. 
- [x] **S2** Kubernetes job adapter.
- [x] **S3** CodeCarbon measurement of a real run.

---

## 16. Antigravity setup (do this first)

Facts verified from public docs: workspace rules live in `.agent/rules/`, workflows in `.agent/workflows/`, global rules in `~/.gemini/GEMINI.md`. Some repos use the folder name `.agents/` instead, so confirm which one your Antigravity build shows under Customizations. Artifacts include task lists and implementation plans.

**Skills (keep the set small).** Install the skills manager, then only what you need:
```
agy plugin install https://github.com/rmyndharis/antigravity-skills      # experimental per its README
npx @rmyndharis/antigravity-skills search python
npx @rmyndharis/antigravity-skills install python-pro
npx @rmyndharis/antigravity-skills install fastapi-pro
npx @rmyndharis/antigravity-skills install backend-architect
npx @rmyndharis/antigravity-skills install api-design-principles
```
Run `search` first to confirm each name exists; do not use `install --all` (token cost and irrelevant auto-activation). Skills install to `.agent/skills/` (workspace) or `~/.gemini/antigravity/skills/` (global); restart the session after manual copies. Skip `kubernetes-architect` unless you reach stretch S2.

**Workspace rule** (save as `.agent/rules/project.md`, keep it short):
```
Read PROJECT_SPEC.md before any task. Follow Section 6 formulas and invariants exactly.
Work in Section 15 order. After each task update the checkbox and the Progress Log.
Run `make test` before each commit. Never fabricate data; label synthetic data.
Record deviations in docs/DECISIONS.md. Ask before adding dependencies not in Section 4.
```

**Workflows** (`.agent/workflows/`):
- `status.md`: "Open PROJECT_SPEC.md. List tasks by status, run `make test`, update the Progress Log, and report blockers."
- `verify.md`: "Run tests, `make bench`, start the stack, check each row of Section 2, and report which rows are not green with evidence."
- `bench.md`: "Run `make bench`, update Section 14 observed results, and compare against the reference table."

**Agent settings:** use Planning mode for M1 and M4; Fast mode for small edits. Prefer "Agent-assisted" terminal policy with an allow list for `pytest`, `make`, `npm`, `docker compose`. Deny destructive commands. Split work across agents in the Manager by module (backend core, adapters, frontend), each owning separate directories to avoid conflicts.

**First prompt to paste into Antigravity:**
> Read PROJECT_SPEC.md fully. Produce an implementation plan for milestones M0 and M1 only, mapped to tasks T00 to T04. List assumptions and any conflicts with current provider docs. Wait for my approval before writing code. After approval, execute tasks in order, ticking Section 15 and appending to the Progress Log after each.

---

## 17. Progress log (agent appends; newest last)

| Date | Task | Status | Evidence (command and result summary) | Notes/blockers |
|---|---|---|---|---|
| 2026-10-09 | Spec created | DONE | n/a | Reference implementation and results provided in `reference/` |
| 2026-10-09 | M0 (T00-T01) | DONE | `pytest`, `config.yaml`, `Dockerfile`, `docker-compose.yml`, `Makefile`, `.agents/` | Scaffold, configs, rules, workflows initialized |
| 2026-10-09 | M1 (T02-T04) | DONE | `pytest backend/tests/test_core.py`: 18 passed, 1,100 Hypothesis property checks pass | INV1 (cap), INV2 (deadlines), INV3 (fairness), INV6 (realtime) |
| 2026-10-09 | M2 (T05-T08) | DONE | `pytest backend/tests/test_providers.py`: 16 passed | Mock, UK Replay, CASDK, WattTime v3, Electricity Maps v4, fallback, cache |
| 2026-10-09 | M3 (T09-T11) | DONE | `pytest backend/tests/test_engine.py`: 21 passed | Re-plan loop, all 8 alert types, advisor plain-language explanations |
| 2026-10-09 | M4 (T12-T13) | DONE | `pytest backend/tests/test_api.py`: 18 passed | FastAPI endpoints, 422 error contract, fair baseline metrics |
| 2026-10-09 | M5 (T14-T16) | DONE | `GET /`: 33.6KB HTML dashboard verified live | Views 1-8 implemented in responsive CSS/JS, timeline, forms, alerts |
| 2026-10-09 | M6 (T17-T18) | DONE | `python -m backend.app.bench --compare`: 100 seeds run | Training padding 1.6x raised cloudy deadline hit from 89% to 99% |
| 2026-10-09 | M7 (T19-T21) | DONE | `docs/REPORT.md`, `docs/DEMO_SCRIPT.md`, `docs/DECISIONS.md`, 88 tests pass | Section 2 all green, complete validation |
| 2026-10-09 | Stretch S1-S3 | DONE | Spatial shifting (transfer penalty), K8s backend, CodeCarbon calibration | All stretch items implemented and tested |

---

## 18. Parameter checklist (config.yaml and env)

| Parameter | Default | Meaning | Check |
|---|---|---|---|
| `STEP_MIN` | 30 | forecast/plan step (minutes) | divides 60; matches provider resolution |
| `CAP_KW` | 8.0 | cluster power capacity | >= max job kW |
| `PAD` | 1.25 | duration padding when no p90 | raise for training (see T18) |
| `TICK_STEPS` | 12 | re-plan interval (6 h) | |
| `HORIZON_HOURS` | 72 | planning horizon | matches provider forecast length |
| `REPLAN_ALERT_STEPS` | 4 | move size for `replan` alert | |
| `PROVIDER` | `mock` | `carbon_aware_sdk|watttime|electricitymaps|mock` | UI shows source |
| `CASDK_URL` | none | Carbon Aware SDK base URL | reachable from API container |
| `WATTTIME_USER/PASS` | none | WattTime credentials | free plan limited to CAISO_NORTH |
| `EMAPS_TOKEN` | none | Electricity Maps `auth-token` | forecast needs paid/trial |
| `REGION_MAP` | per config | internal key -> provider code | resolved, not hardcoded |
| `PROVIDER_TIMEOUT_S` | 5 | per-request timeout | |
| `CACHE_TTL_MIN` | 15 | forecast cache | |
| `STALE_AFTER_MIN` | 180 | treat forecast as stale | triggers fallback |
| `FALLBACK_PROFILES` | diurnal per region | historical average g/kWh by hour | labelled as static |
| `OVERRUN_FACTOR` | scenario | actual/estimated duration | used only in simulation |
| `BENCH_SEEDS` | 20 | seeds per scenario | |
| `API_KEY` | dev value | simple auth | not committed |
| `SIM_CLOCK` | on in demo | simulated time | |

Brief-parameter cross-check: deadlines (SLA) = `sla_deadline`; resource constraints = `CAP_KW`; workload demand variation = multi-job queue and `heavy_load`; energy availability = forecast + fallback; incomplete inputs = fallback and validation; changing inputs = re-plan; measurable evidence = Section 12; usability = Section 10; alerting = Section 11.

---

## 19. Definition of done (project)

- All rows in Section 2 are green with evidence in the Progress Log.
- `make test` and `make bench` pass; `docker compose up` works from a clean clone.
- Dashboard shows every metric in Section 10 from live API data, with source banner.
- Report and demo script match the actual benchmark output (no unverified numbers).
- Known limitations are stated plainly in the report.
