"""T_REAL: Integration tests using REAL UK Carbon Intensity API data.

The UK Carbon Intensity API (https://api.carbonintensity.org.uk) is:
  - Free and keyless (no registration required)
  - CC BY 4.0 licensed
  - Returns actual + forecast half-hourly intensity (gCO2/kWh) for Great Britain

These tests verify end-to-end scheduling with real data:
  1. Snapshot load + validation (snapshot fetched by scripts/fetch_uk_live.py)
  2. Planning uses real intensities (not synthetic)
  3. Observer returns uk_replay source label, not fallback
  4. INV1/INV3/INV5 hold on real GB data
  5. Savings calculated from real intensity values
  6. Live network fetch (opt-in via -m network)

Data source: https://api.carbonintensity.org.uk/intensity/{from}/{to}
License: CC BY 4.0, National Energy System Operator (NESO)
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path

import pytest

from backend.app.core import Job, PlanResult, add_load, baseline, cost, fits, plan
from backend.app.observer import Observer
from backend.app.providers import UKReplayProvider
from backend.app.providers.base import ProviderError

# ---------------------------------------------------------------------------
SNAPSHOT = Path(__file__).parent.parent.parent / "backend" / "data" / "uk_snapshot.json"
ORIGIN = datetime(2026, 10, 9, 0, 0, 0, tzinfo=timezone.utc)

# shared helper
def _mk(dl=200, n=4, kw=1.0, sub=0, wtype="batch_inference"):
    return Job(id="j", wtype=wtype, kw=kw, sub=sub, dl=dl, n_est=n, pn=n, an=n, home="uk", allowed=["uk"])


# ============================================================ fixtures
@pytest.fixture(scope="module")
def uk_snap():
    """Load the committed uk_snapshot.json (fetched from real API)."""
    assert SNAPSHOT.exists(), (
        f"Snapshot not found at {SNAPSHOT}.\n"
        "Run:  python scripts/fetch_uk_live.py"
    )
    data = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    assert data["points"], "Snapshot has no points"
    return data


@pytest.fixture(scope="module")
def uk_provider(uk_snap, tmp_path_factory):
    """UKReplayProvider forced to use the committed snapshot (offline-safe)."""
    import backend.app.providers.uk as uk_mod

    snap_copy = tmp_path_factory.mktemp("uk") / "snap.json"
    snap_copy.write_text(json.dumps(uk_snap), encoding="utf-8")
    original = uk_mod.SNAPSHOT
    uk_mod.SNAPSHOT = snap_copy
    p = UKReplayProvider(force_snapshot=True)
    yield p
    uk_mod.SNAPSHOT = original


# ============================================================ snapshot sanity
class TestUKSnapshotData:
    def test_snapshot_has_sufficient_points(self, uk_snap):
        """Must have at least 240 half-hourly points (5 days)."""
        pts = uk_snap["points"]
        assert len(pts) >= 240, f"Only {len(pts)} points – need >= 240"

    def test_all_values_are_real_gco2_kwh(self, uk_snap):
        """Every non-null value must be a positive finite float in plausible range."""
        bad = []
        for p in uk_snap["points"]:
            for key in ("forecast", "actual"):
                v = p.get(key)
                if v is None:
                    continue
                if not (isinstance(v, (int, float)) and math.isfinite(v) and 0 < v < 2000):
                    bad.append((p["from"], key, v))
        assert not bad, f"Invalid intensities: {bad[:5]}"

    def test_timestamps_are_iso_half_hourly(self, uk_snap):
        """Timestamps should be 30-minute aligned UTC."""
        for p in uk_snap["points"][:10]:
            ts = p["from"]
            assert ts.endswith("Z") or "+" in ts, f"Not UTC: {ts}"
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            assert dt.minute in (0, 30), f"Not half-hourly: {ts}"

    def test_source_metadata_present(self, uk_snap):
        """The snapshot must have been fetched from the live API."""
        assert uk_snap.get("fetched_at"), "No fetched_at timestamp in snapshot"
        assert uk_snap.get("from") and uk_snap.get("to"), "Missing from/to in snapshot"

    def test_intensity_range_realistic_for_gb(self, uk_snap):
        """GB carbon intensity is typically 18–500 gCO2/kWh. Catch encoding errors."""
        values = [
            p["forecast"] if p["forecast"] is not None else p["actual"]
            for p in uk_snap["points"]
            if p["forecast"] is not None or p["actual"] is not None
        ]
        assert min(values) >= 10, f"Suspiciously low min: {min(values)}"
        assert max(values) <= 800, f"Suspiciously high max: {max(values)}"
        print(f"\n[REAL DATA] {len(values)} points, range: {min(values)}–{max(values)} gCO2/kWh")


# ============================================================ provider layer
class TestUKProviderWithRealData:
    def test_series_forecast_returns_288_steps(self, uk_provider):
        fc = uk_provider.series_forecast("uk", 10, 288, 30)
        assert len(fc) == 288

    def test_actual_series_returns_positive_finite_values(self, uk_provider):
        act = uk_provider.actual("uk", 288, 30)
        assert all(math.isfinite(v) and v > 0 for v in act), "Non-positive or NaN actuals"

    def test_past_steps_use_actual_not_forecast(self, uk_provider):
        now = 50
        fc = uk_provider.series_forecast("uk", now, 288, 30)
        act = uk_provider.actual("uk", 288, 30)
        assert fc[:now] == act[:now], "Past steps must use actuals"

    def test_provider_marked_not_synthetic(self, uk_provider):
        assert uk_provider.synthetic is False

    def test_wrong_region_raises(self, uk_provider):
        with pytest.raises(ProviderError):
            uk_provider.actual("default", 288, 30)

    def test_wrong_step_raises(self, uk_provider):
        with pytest.raises(ProviderError):
            uk_provider.actual("uk", 288, 15)


# ============================================================ observer layer
class TestObserverWithRealData:
    def test_observer_returns_uk_replay_source(self, uk_provider, settings):
        obs = Observer(settings, uk_provider, ORIGIN, backoff_s=0)
        fc = obs.get_forecast("uk", 0, 288)
        assert fc.source == "uk_replay", f"Expected uk_replay, got {fc.source}"
        assert not fc.is_fallback, "Should NOT be fallback with real data"
        assert not fc.synthetic, "Should NOT be synthetic"

    def test_inv5_all_forecast_values_positive_finite(self, uk_provider, settings):
        """INV5: all stored intensities are gCO2/kWh, finite, positive."""
        obs = Observer(settings, uk_provider, ORIGIN, backoff_s=0)
        fc = obs.get_forecast("uk", 0, 288)
        bad = [v for v in fc.values if not (math.isfinite(v) and v > 0)]
        assert not bad, f"INV5 violated: {bad[:5]}"

    def test_cache_returns_same_object(self, uk_provider, settings):
        obs = Observer(settings, uk_provider, ORIGIN, backoff_s=0)
        a = obs.get_forecast("uk", 0, 288)
        b = obs.get_forecast("uk", 0, 288)
        assert a is b, "Cache miss on identical key"


# ============================================================ scheduler on real data
class TestSchedulerWithRealIntensity:
    def test_inv1_capacity_never_exceeded(self, uk_provider):
        """INV1: planned load never exceeds CAP at any step."""
        fc = uk_provider.series_forecast("uk", 0, 288, 30)
        cap = 8.0
        jobs = [Job(id=f"j{i}", wtype="batch_inference", kw=2.0, sub=0, dl=288,
                    n_est=4, pn=4, an=4, home="uk", allowed=["uk"]) for i in range(4)]
        result = plan(jobs, {"uk": fc}, {"uk": []}, 0, cap, 30)
        load = [0.0] * 288
        for j, r in zip(jobs, result.values()):
            for k in range(j.pn):
                load[r.start + k] += j.kw
        violations = [(t, load[t]) for t in range(288) if load[t] > cap + 1e-9]
        assert not violations, f"INV1 violated at steps: {violations[:3]}"

    def test_inv3_optimized_le_baseline(self, uk_provider):
        """INV3: with real forecast, scheduled cost <= immediate-start cost."""
        fc = uk_provider.series_forecast("uk", 0, 288, 30)
        j = _mk(dl=200, n=8, kw=1.5)
        result = plan([j], {"uk": fc}, {"uk": []}, 0, 8.0, 30)
        r = result[j.id]
        e_opt = cost(fc, r.start, j.pn, j.kw, 30)
        e_base = r.baseline_g  # cost at the run-now step (PlanResult.baseline_g)
        assert e_opt <= e_base + 1e-6, f"INV3 violated: opt={e_opt:.2f} > base={e_base:.2f}"

    def test_scheduler_exploits_real_diurnal_pattern(self, uk_provider):
        """Scheduler should pick a window with lower intensity than a naive immediate start."""
        fc = uk_provider.series_forecast("uk", 0, 288, 30)
        # Give ample slack so the scheduler has room to optimize
        j = _mk(dl=288, n=4, kw=1.0)
        result = plan([j], {"uk": fc}, {"uk": []}, 0, 8.0, 30)
        r = result[j.id]
        # The chosen window must be at most 5% worse than the global minimum
        min_cost = min(cost(fc, s, j.pn, j.kw, 30) for s in range(288 - j.pn + 1))
        chosen_cost = cost(fc, r.start, j.pn, j.kw, 30)
        assert chosen_cost <= min_cost * 1.05 + 0.1, (
            f"Scheduler chose {chosen_cost:.1f} but global min is {min_cost:.1f}"
        )

    def test_real_data_shows_meaningful_variation(self, uk_provider):
        """Real GB data must show diurnal intensity variation (not flat)."""
        fc = uk_provider.series_forecast("uk", 0, 288, 30)
        variation = max(fc) - min(fc)
        assert variation > 20, (
            f"Too little variation in real data: max={max(fc):.1f}, min={min(fc):.1f}"
        )
        print(f"\n[REAL DATA] Intensity range: {min(fc):.0f}–{max(fc):.0f} gCO2/kWh "
              f"(variation={variation:.0f})")


# ============================================================ savings with real data
class TestSavingsWithRealData:
    def test_forecasted_savings_are_finite_and_plausible(self, uk_provider):
        """Savings% must be a finite number; may be negative on some real datasets."""
        from backend.app.evidence import evaluate

        fc = uk_provider.series_forecast("uk", 0, 288, 30)
        act = uk_provider.actual("uk", 288, 30)
        jobs = [Job(id=f"j{i}", wtype="batch_inference", kw=1.5, sub=0, dl=200,
                    n_est=6, pn=6, an=6, home="uk", allowed=["uk"]) for i in range(3)]
        # plan jobs
        load = {"uk": []}
        result = plan(jobs, {"uk": fc}, load, 0, 8.0, 30)
        for j in jobs:
            r = result[j.id]
            j.plan = r
            j.state = "DONE"
            j.actual_start = r.start
            j.actual_end = r.start + j.an
            j.region = r.region
        ev = evaluate(jobs, 8.0, 30, {"uk": fc}, {"uk": act}, transfer_g_per_gb=0.0)
        assert ev["forecasted"] is not None, "No forecasted evidence produced"
        pct = ev["forecasted"]["savings_pct"]
        assert math.isfinite(pct), f"savings_pct is not finite: {pct}"
        assert -100 <= pct <= 100, f"savings_pct out of range: {pct}"
        print(f"\n[REAL DATA] Forecasted savings: {pct:.1f}% "
              f"(base={ev['forecasted']['e_base_g']}g, opt={ev['forecasted']['e_opt_g']}g)")

    def test_realized_savings_use_actual_intensity(self, uk_provider):
        """Realized savings are calculated using actual (not forecast) intensities."""
        from backend.app.evidence import evaluate

        fc = uk_provider.series_forecast("uk", 0, 288, 30)
        act = uk_provider.actual("uk", 288, 30)
        j = Job(id="j0", wtype="batch_inference", kw=2.0, sub=0, dl=200,
                n_est=6, pn=6, an=6, home="uk", allowed=["uk"])
        result = plan([j], {"uk": fc}, {"uk": []}, 0, 8.0, 30)
        r = result[j.id]
        j.plan = r
        j.state = "DONE"
        j.actual_start = r.start
        j.actual_end = r.start + j.an
        j.region = r.region
        ev = evaluate([j], 8.0, 30, {"uk": fc}, {"uk": act}, transfer_g_per_gb=0.0)
        assert ev["realized"] is not None, "No realized evidence"
        assert ev["realized"]["e_base_g"] > 0
        assert ev["realized"]["e_opt_g"] > 0


# ============================================================ live network tests (opt-in)
@pytest.mark.network
class TestLiveNetworkFetch:
    """Hit the real UK Carbon Intensity API. Opt-in: pytest -m network"""

    def test_live_api_returns_data(self, tmp_path, monkeypatch):
        import backend.app.providers.uk as uk_mod
        monkeypatch.setattr(uk_mod, "SNAPSHOT", tmp_path / "snap.json")
        p = UKReplayProvider(timeout=25.0, force_snapshot=False)
        p.load()
        assert p.meta["live"] is True, "Should have fetched live data"
        assert len(p.fc) >= 240, f"Too few points: {len(p.fc)}"
        assert all(v > 0 for v in p.fc), "Non-positive forecast values from live API"
        print(f"\n[LIVE] {p.meta['points']} points, from={p.meta['from']}, to={p.meta['to']}")

    def test_live_snapshot_saved_correctly(self, tmp_path, monkeypatch):
        import backend.app.providers.uk as uk_mod
        snap = tmp_path / "snap.json"
        monkeypatch.setattr(uk_mod, "SNAPSHOT", snap)
        p = UKReplayProvider(timeout=25.0, use_snapshot=True, force_snapshot=False)
        p.load()
        assert snap.exists(), "Snapshot not written"
        data = json.loads(snap.read_text())
        assert data["fetched_at"] and data["points"]
