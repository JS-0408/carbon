# Architecture Decision Records (ADRs)

This document records key architectural decisions, rationale, and findings during the development of the Carbon-Aware AI Workload Scheduler.

---

### ADR-001: Electricity Maps API v4 Migration
- **Context:** Section 7 of the spec referenced Electricity Maps v3 endpoints. Modern Electricity Maps documentation designates v4 as the canonical API.
- **Decision:** Implemented `ElectricityMapsProvider` pointing to `/v4/carbon-intensity/forecast` with query parameters `zone` and `horizonHours`, authenticated via the `auth-token` header.
- **Consequences:** Free tier limitations (no forecast endpoint, latest/history only, single zone) return a descriptive `ProviderAccessError` informing users of required paid/trial tier rather than crashing.

---

### ADR-002: WattTime Free Plan Regional Scope Handling
- **Context:** Free tier WattTime accounts only grant access to region `CAISO_NORTH` and signal `co2_moer`. Querying Indian zones (`IND`) on a basic plan results in HTTP 403.
- **Decision:** Implemented coordinate resolution via `/v3/region-from-loc`. When HTTP 403 is received on unpermitted regions, the adapter raises `ProviderAccessError` with clear messaging, prompting automatic fallback to diurnal regional historical profiles.
- **Consequences:** Ensures zero system disruption (Invariant INV4) while remaining completely honest about provider availability.

---

### ADR-003: Self-Calculated Emissions from Carbon Aware SDK `forecastData`
- **Context:** Carbon Aware SDK WebAPI `/emissions/forecasts/current` returns both `forecastData` points and pre-computed `optimalDataPoints` based on window averages.
- **Decision:** We extract granular timestamped values from `forecastData` and compute exact energy-weighted kilowatt-hour emissions $C(s) = \sum P \cdot (\Delta t/60) \cdot I[s+k]$ in our scheduler core.
- **Consequences:** Prevents discrepancies between provider-specific averaging rules and our internal cost function, ensuring rigorous baseline vs. optimized comparisons.

---

### ADR-004: Keyless Real-Data Replay via UK Carbon Intensity API
- **Context:** Spec Section 7 suggested an optional keyless public provider to prove end-to-end real forecast processing without private keys.
- **Decision:** Integrated `UKReplayProvider` querying `https://api.carbonintensity.org.uk/intensity/{from}/{to}`. It feeds real half-hourly forecast and actual figures into the scheduler for region `uk`.
- **Consequences:** Real-world validation is readily demonstrable without requiring paid external API subscriptions. Region is explicitly labelled "Great Britain (real data)" in the UI and report.

---

### ADR-005: Workload-Specific Duration Padding & Overrun Resilience (T18)
- **Context:** Reference code used a flat 1.25x padding (`PAD = 1.25`). In scenario `overrun_cloudy` (where training jobs run 45% longer), deadline hit rate plummeted from 99.6% to 89-92%.
- **Decision:** Configured `pad_by_type: {model_training: 1.6}` in `config.yaml` and implemented adaptive estimation in `Estimator.observe()` based on runtime execution history.
- **Consequences:** Benchmark results verified: `overrun_cloudy` deadline compliance improved from 89% to 99%, successfully addressing the reference implementation weakness.

---

### ADR-006: Lightweight Zero-Dependency UI Served by FastAPI
- **Context:** Section 4 allowed React/Vite or a single-page HTML/JS dashboard. To guarantee instantaneous local deployment without external Node toolchain friction, a single-page architecture was chosen.
- **Decision:** Built a modern responsive dashboard in `frontend/index.html` featuring vanilla CSS variables, dark/light themes, pure SVG timeline rendering with live forecast curves, job bars, deadline diamonds, alert feeds, decision explanations, and benchmark charts.
- **Consequences:** Single command `uvicorn` serves both API and interactive UI, completely accessible, responsive, and dependency-free.

---

### ADR-007: CodeCarbon Hardware Power Calibration (Stretch S3)
- **Context:** `power_profile_kw` is typically declared by users. The spec invited real measurement via CodeCarbon.
- **Decision:** Implemented `backend/app/calibrate.py` running a standard compute matrix benchmark tracked by CodeCarbon's `EmissionsTracker`, calculating real average kilowatt draw with clear fallback if hardware telemetry is unsupported.
- **Consequences:** Ground-truth power data can be measured on supported GPUs/CPUs or estimated honestly when running virtualized.

---

### ADR-008: Kubernetes Job Manifest Adapter (Stretch S2)
- **Context:** Spec Section 9 specified an optional Kubernetes adapter behind a clean interface.
- **Decision:** Created `KubernetesBackend` in `backend/app/executor.py` generating `batch/v1` Job manifests annotated with planned carbon start times and power allocations, with optional dry-run and `kubectl apply` execution modes.
- **Consequences:** Demonstrates real cloud-native execution readiness without enforcing heavy cluster dependencies in unit testing.

---

### ADR-009: Spatial Shifting with Transfer Penalty (Stretch S1)
- **Context:** Moving workloads between regions can access cleaner grids but incurs carbon emissions from network data transfers.
- **Decision:** Added `transfer_g_per_gb` (default 5.0 gCO2/GB) in `core.py` and evaluated total carbon $C_{total} = C_{compute} + \text{data\_gb} \times \text{penalty}$.
- **Consequences:** Scheduler automatically shifts large data jobs only when the grid difference exceeds the transport cost.
