"""Shared test helpers."""
from datetime import datetime, timezone

import pytest

from backend.app.bench import bench_settings
from backend.app.core import Job
from backend.app.engine import Engine
from backend.app.providers.base import ProviderError, SeriesProvider

ORIGIN = datetime(2026, 10, 9, tzinfo=timezone.utc)


@pytest.fixture
def settings():
    return bench_settings()


def mk(id="j", wtype="batch_inference", kw=1.0, sub=0, dl=100, n=2, pn=None, an=None, **kw2):
    return Job(id=id, wtype=wtype, kw=kw, sub=sub, dl=dl, n_est=n, pn=pn or n, an=an or n, **kw2)


class Scripted(SeriesProvider):
    """Test provider: forecast comes from fn(now) -> list, actual is flat unless given."""
    name = "scripted"
    synthetic = True

    def __init__(self, fc_fn, actual_val=500.0, fail=False):
        self.fc_fn, self.actual_val, self.fail = fc_fn, actual_val, fail

    def actual(self, region, total, step_min):
        return [self.actual_val] * total

    def series_forecast(self, region, now, total, step_min):
        if self.fail:
            raise ProviderError("down")
        return self.fc_fn(now, total)


def make_engine(settings, provider=None, **kw):
    return Engine(settings, provider=provider, origin=ORIGIN, adaptive_pad=False, **kw)
