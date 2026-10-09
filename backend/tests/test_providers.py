"""T05-T07: providers, fallback, unit conversion, INV4/INV5. Fixtures are HAND-WRITTEN from the documented
response shapes (not recorded from live services); live calls are skipped unless credentials are set."""
import json
import math
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from hypothesis import given, settings as hset, strategies as st

from backend.app.observer import Observer
from backend.app.providers import (CarbonAwareSDKProvider, ElectricityMapsProvider, MockProvider,
                                   UKReplayProvider, WattTimeProvider, lbs_mwh_to_g_kwh, make_provider)
from backend.app.providers.base import ProviderAccessError, ProviderError, PointProvider, SeriesProvider, resample
from conftest import ORIGIN, Scripted


def test_unit_conversion_watttime():
    assert lbs_mwh_to_g_kwh(1000) == pytest.approx(453.59237)
    assert lbs_mwh_to_g_kwh(1) == pytest.approx(0.4536, abs=1e-4)


def test_mock_is_deterministic_and_synthetic(settings):
    a = MockProvider(settings, seed=3).series_forecast("default", 5, 288, 30)
    b = MockProvider(settings, seed=3).series_forecast("default", 5, 288, 30)
    assert a == b and MockProvider(settings).synthetic


def test_mock_forecast_equals_actual_in_the_past(settings):
    p = MockProvider(settings, seed=1)
    act, fc = p.actual("default", 288, 30), p.series_forecast("default", 20, 288, 30)
    assert fc[:20] == act[:20] and fc[40] != act[40]


def test_observer_fallback_on_provider_error(settings):
    obs = Observer(settings, Scripted(lambda n, t: [], fail=True), ORIGIN, backoff_s=0)
    f = obs.get_forecast("default", 0, 288)
    assert f.is_fallback and f.source == "fallback" and len(f.values) == 288 and obs.last_error


def test_observer_falls_back_on_empty_and_invalid(settings):
    for bad in ([], [float("nan")] * 288, [-5.0] * 288, [0.0] * 288):
        obs = Observer(settings, Scripted(lambda n, t, b=bad: b), ORIGIN, backoff_s=0)
        assert obs.get_forecast("default", 0, 288).is_fallback


def test_observer_cache_ttl(settings):
    calls = []
    def fc(n, t):
        calls.append(n)
        return [400.0] * t
    clock = [0.0]
    obs = Observer(settings, Scripted(fc), ORIGIN, clock=lambda: clock[0], backoff_s=0)
    obs.get_forecast("default", 0, 288); obs.get_forecast("default", 0, 288)
    assert len(calls) == 1
    clock[0] += settings.cache_ttl_min * 60 + 1
    obs.get_forecast("default", 0, 288)
    assert len(calls) == 2


def test_observer_retries_then_succeeds(settings):
    state = {"n": 0}
    def fc(now, t):
        state["n"] += 1
        if state["n"] < 3:
            raise ProviderError("flaky")
        return [300.0] * t
    obs = Observer(settings, Scripted(fc), ORIGIN, backoff_s=0)
    assert not obs.get_forecast("default", 0, 288).is_fallback and state["n"] == 3


@hset(max_examples=200, deadline=None)
@given(st.one_of(st.just(None), st.lists(st.floats(allow_nan=True, allow_infinity=True), max_size=300)),
       st.sampled_from(["raise", "return", "weird"]))
def test_inv4_inv5_never_raises_and_values_valid(vals, mode):
    from backend.app.bench import bench_settings
    s = bench_settings()
    class P(SeriesProvider):
        name = "p"
        def series_forecast(self, region, now, total, step_min):
            if mode == "raise":
                raise RuntimeError("boom")
            if mode == "weird":
                return "not a list"
            return vals or []
    f = Observer(s, P(), ORIGIN, backoff_s=0, retries=0).get_forecast("default", 0, 288)   # INV4: no exception
    assert len(f.values) == 288 and all(math.isfinite(v) and v > 0 for v in f.values)      # INV5


# ------------------------------------------------------------------ live adapters with fake transports
def _now_pts(n=96, base=300):
    t0 = ORIGIN
    return [(t0 + timedelta(minutes=30 * i), base + i) for i in range(n)]


def test_resample_stops_at_coverage():
    pts = _now_pts(10)
    vals = resample(pts, ORIGIN, 30, 2, 288)
    assert len(vals) == 8 and vals[0] == 302


def test_carbon_aware_sdk_contract(settings):
    body = [{"location": "centralindia", "generatedAt": "2026-10-09T00:00:00Z", "windowSize": 30,
             "forecastData": [{"timestamp": (ORIGIN + timedelta(minutes=30 * i)).isoformat().replace("+00:00", "Z"),
                               "duration": 30, "value": 400 + i} for i in range(48)],
             "optimalDataPoints": []}]
    seen = {}
    def handler(req: httpx.Request):
        seen["url"], seen["q"] = req.url.path, dict(req.url.params)
        return httpx.Response(200, json=body)
    p = CarbonAwareSDKProvider("http://sdk", transport=httpx.MockTransport(handler))
    pts, gen = p.fetch_points(settings.regions["default"], ORIGIN, ORIGIN + timedelta(days=1))
    assert seen["url"] == "/emissions/forecasts/current"
    assert seen["q"]["location"] == "centralindia" and "dataEndAt" in seen["q"] and "windowSize" in seen["q"]
    assert len(pts) == 48 and pts[0][1] == 400.0 and gen is not None


def test_carbon_aware_sdk_empty_raises(settings):
    p = CarbonAwareSDKProvider("http://sdk", transport=httpx.MockTransport(lambda r: httpx.Response(200, json=[{"forecastData": []}])))
    with pytest.raises(ProviderError):
        p.fetch_points(settings.regions["default"], ORIGIN, ORIGIN + timedelta(days=1))


def test_watttime_flow_and_units(settings):
    calls = []
    def handler(req: httpx.Request):
        calls.append(req.url.path)
        if req.url.path == "/login":
            assert req.headers["authorization"].startswith("Basic ")
            return httpx.Response(200, json={"token": "jwt"})
        assert req.headers["authorization"] == "Bearer jwt"
        if req.url.path == "/v3/region-from-loc":
            return httpx.Response(200, json={"region": "CAISO_NORTH"})
        if req.url.path == "/v3/forecast":
            assert req.url.params["region"] == "CAISO_NORTH" and req.url.params["signal_type"] == "co2_moer"
            return httpx.Response(200, json={"data": [{"point_time": (ORIGIN + timedelta(minutes=5 * i)).isoformat().replace("+00:00", "Z"),
                                                         "value": 1000.0} for i in range(300)],
                                              "meta": {"generated_at": "2026-10-09T00:00:00Z"}})
        return httpx.Response(404)
    p = WattTimeProvider("u", "p", transport=httpx.MockTransport(handler))
    pts, _ = p.fetch_points(settings.regions["default"], ORIGIN, ORIGIN + timedelta(days=1))
    assert pts[0][1] == pytest.approx(453.59237)
    assert "/v3/region-from-loc" in calls and "/v3/forecast" in calls


def test_watttime_free_tier_403_is_clear(settings):
    def handler(req):
        if req.url.path == "/login":
            return httpx.Response(200, json={"token": "t"})
        if req.url.path == "/v3/region-from-loc":
            return httpx.Response(200, json={"region": "IND"})
        return httpx.Response(403, json={"message": "forbidden"})
    p = WattTimeProvider("u", "p", transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderAccessError) as e:
        p.fetch_points(settings.regions["default"], ORIGIN, ORIGIN + timedelta(days=1))
    assert "CAISO_NORTH" in str(e.value)


def test_watttime_without_credentials(settings):
    with pytest.raises(ProviderError):
        WattTimeProvider(None, None).fetch_points(settings.regions["default"], ORIGIN, ORIGIN)


def test_electricity_maps_contract_and_403(settings):
    def ok(req: httpx.Request):
        assert req.headers["auth-token"] == "tok" and req.url.params["zone"] == "IN-SO"
        return httpx.Response(200, json={"zone": "IN-SO", "updatedAt": "2026-10-09T00:00:00Z",
                                         "forecast": [{"carbonIntensity": 500 + i,
                                                       "datetime": (ORIGIN + timedelta(hours=i)).isoformat().replace("+00:00", "Z")}
                                                      for i in range(48)]})
    p = ElectricityMapsProvider("tok", "https://x/v4", transport=httpx.MockTransport(ok))
    pts, _ = p.fetch_points(settings.regions["default"], ORIGIN, ORIGIN + timedelta(days=1))
    assert pts[0][1] == 500.0 and len(pts) == 48
    denied = ElectricityMapsProvider("tok", "https://x/v4", transport=httpx.MockTransport(lambda r: httpx.Response(403)))
    with pytest.raises(ProviderAccessError) as e:
        denied.fetch_points(settings.regions["default"], ORIGIN, ORIGIN + timedelta(days=1))
    assert "paid or trial" in str(e.value)


def test_point_provider_partial_coverage_filled_by_fallback(settings):
    class Short(PointProvider):
        name = "short"
        def fetch_points(self, cfg, start, end):
            return _now_pts(20, 250), datetime.now(timezone.utc)
    obs = Observer(settings, Short(), ORIGIN, backoff_s=0, retries=0)
    f = obs.get_forecast("default", 0, 288)
    assert not f.is_fallback and f.partial and len(f.values) == 288 and f.values[0] == 250


def test_stale_forecast_triggers_fallback(settings):
    class Old(PointProvider):
        name = "old"
        def fetch_points(self, cfg, start, end):
            return _now_pts(96), datetime.now(timezone.utc) - timedelta(hours=5)
    assert Observer(settings, Old(), ORIGIN, backoff_s=0, retries=0).get_forecast("default", 0, 288).is_fallback


def test_adapter_failure_never_reaches_caller(settings):
    p = WattTimeProvider("u", "p", transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    f = Observer(settings, p, ORIGIN, backoff_s=0, retries=1).get_forecast("default", 0, 288)
    assert f.is_fallback


def test_uk_replay_parses_real_api_shape(settings, tmp_path, monkeypatch):
    import backend.app.providers.uk as uk
    monkeypatch.setattr(uk, "SNAPSHOT", tmp_path / "snap.json")
    data = [{"from": (ORIGIN + timedelta(minutes=30 * i)).strftime("%Y-%m-%dT%H:%MZ"),
             "to": "x", "intensity": {"forecast": 100 + i, "actual": (90 + i) if i < 250 else None, "index": "low"}}
            for i in range(288)]
    p = UKReplayProvider(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"data": data})))
    fc = p.series_forecast("uk", 10, 288, 30)
    act = p.actual("uk", 288, 30)
    assert fc[5] == act[5] == 95 and fc[20] == 120 and act[260] == 100 + 260   # null actual falls back to forecast
    assert p.meta["live"]
    with pytest.raises(ProviderError):
        p.actual("default", 288, 30)


def test_uk_replay_unavailable_without_snapshot(settings, tmp_path, monkeypatch):
    import backend.app.providers.uk as uk
    monkeypatch.setattr(uk, "SNAPSHOT", tmp_path / "none.json")
    def boom(r):
        raise httpx.ConnectError("offline")
    p = UKReplayProvider(transport=httpx.MockTransport(boom))
    with pytest.raises(ProviderError):
        p.load()


def test_factory_rejects_unknown(settings):
    with pytest.raises(ValueError):
        make_provider("nope", settings)
