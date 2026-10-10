# Neumorphic frontend: integration guide for Antigravity

These files replace the current single-file `frontend/index.html` UI. They are plain HTML, CSS and JS (no build step, no dependencies) and render static demo data from `js/data.js`.

## Files
| File | Purpose |
|---|---|
| `index.html` | Page structure: header, nav, banner, four views (Overview, Jobs, Alerts, Results) |
| `css/neumorphism.css` | Design system: tokens (light and dark), surfaces, buttons, inputs, switch, chips, ring gauge |
| `css/layout.css` | Page layout and chart styling, using only tokens from `neumorphism.css` |
| `js/data.js` | Static demo data (`window.CARBON_DATA`). Times are hours from day 1, 00:00 |
| `js/app.js` | Renders the data. Navigation, theme, KPIs, timeline, jobs, alerts, results, submit preview |

## Step 1: drop in (static mode)
1. Back up the current `frontend/index.html` as `frontend/legacy.html`.
2. Copy `index.html`, `css/`, `js/` into `frontend/`.
3. Serve `frontend/` the same way the current page is served. Open it and check all four views and the theme switch.

## Design rules (do not break)
- Use only the CSS variables in `neumorphism.css`. No new colours, no new shadow values.
- Raised = clickable or container. Inset = input, selected or pressed state.
- State must never rely on colour alone. Chips carry a text label (done, running, forced, Critical).
- Keep the visible focus ring (`:focus-visible`). Neumorphism hides edges, so focus must stay loud.
- Keep contrast: body text on `--bg` must stay at 4.5:1 or better in both themes.
- No gradients, glass or neon. Keep it flat, soft and quiet.

## Step 2: go live (optional, after static mode works)
Keep the rendering code in `app.js` unchanged. Add `js/live.js` that fetches the API and builds an object in the exact `CARBON_DATA` shape, then loads before `app.js`. Mapping, derived from reading the existing `frontend/index.html` (not tested against a running API):

| Static field | Source |
|---|---|
| `meta.source`, banner text | `GET /health` (`fallback_active`, `synthetic`, `last_provider_error`) and `timeline.forecast.source`, `.label` |
| `meta.now` | `GET /timeline` `now` (a step index) |
| `series.forecast` | `timeline.forecast.values` |
| `series.actual` | `timeline.forecast.actual` |
| `jobs[].id, type, start, base, dl, state, forced` | `timeline.jobs[]` (`id, type, start, base_start, dl, state, forced, missed`) |
| `jobs[].dur`, `pad` | `n_actual or n_plan`, `n_plan` (steps) |
| `jobs[].kw`, `reason` | `GET /jobs` (`power_kw`, `reason`) |
| `jobs[].alts` | `GET /explain/{id}` `alternatives[]` (`label`, `gco2`, `label_start`) |
| `kpi.forecasted.pct`, `kpi.realized.pct` | `GET /metrics` `forecasted.savings_pct`, `realized.savings_pct` |
| `kpi.realized.baseG/optG` | `metrics.realized.e_base_g`, `e_opt_g` (fall back to forecasted if null) |
| `kpi.deadlinesOptPct/BasePct` | `metrics.deadlines.opt_pct`, `base_pct` |
| `kpi.waitOptH/BaseH` | `metrics.wait.opt_min / 60`, `base_min / 60` |
| `alerts[]` | `GET /alerts` (`id, level, type, message, acknowledged`); acknowledge with `POST /alerts/{id}/ack` |
| `bench[]` | `GET /bench/latest` `scenarios[].kpi` (`savings_mean, savings_min, savings_max`, deadlines and wait fields) |
| Submit preview | `POST /jobs/preview`; submit with `POST /jobs` using the field names in the old `formBody()` |

Time units: the API uses steps (`timeline.forecast.step_minutes`, `timeline.steps_per_day`), not hours. Generalise `lab()`, the x-axis (`X1`) and the duration widths in `app.js` to steps, or resample to hours.

## Acceptance checks
- Static mode: all four views render, no console errors, theme switch works, Preview schedule gives a result.
- Live mode: every number on screen traces to an API field in the table above. Synthetic data keeps the "Demo data" or "Synthetic" label. Fallback data shows a visible banner.
- Keyboard: every control reachable with Tab, with a visible focus ring.
- Screenshots of each view (light and dark) saved to `docs/screens/`. This also closes task T15.

## Prompt to paste into Antigravity
> Read frontend/INTEGRATION.md. Back up the old frontend, copy in the new files, and verify static mode in a browser. Then implement live mode as js/live.js following the mapping table, without changing the design tokens or adding colours. Run the tests, take light and dark screenshots of all four views into docs/screens/, and update PROJECT_SPEC.md task T15 and the Progress Log.
