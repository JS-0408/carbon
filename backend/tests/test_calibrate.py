"""Test CodeCarbon calibration module (Stretch S3)."""
from pathlib import Path
from backend.app.calibrate import calibrate, run_benchmark_workload


def test_workload_runs():
    ops = run_benchmark_workload(duration_seconds=1)
    assert ops > 0


def test_calibrate_returns_valid_contract(tmp_path):
    res = calibrate(duration_seconds=1, output_dir=tmp_path)
    assert "status" in res
    assert "note" in res
    if res["measured"]:
        assert res["measured_power_kw"] > 0
    else:
        assert res["declared_power_kw"] > 0
