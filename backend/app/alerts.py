"""Alert engine (Section 11). Every alert type is raised through `AlertStore.add` and is test-reachable."""
from __future__ import annotations

from dataclasses import asdict, dataclass

ALERT_TYPES = {
    "fallback": "warning", "sla_risk": "critical", "sla_miss": "critical", "overrun": "warning",
    "replan": "info", "infeasible": "critical", "forecast_drift": "warning", "capacity": "warning",
}


@dataclass
class Alert:
    id: int
    ts: str
    step: int
    level: str
    type: str
    job_id: str | None
    message: str
    acknowledged: bool = False

    def as_dict(self) -> dict:
        return asdict(self)


class AlertStore:
    def __init__(self, on_add=None):
        self.items: list[Alert] = []
        self._seen: set = set()
        self._next = 1
        self.on_add = on_add

    def add(self, step: int, ts: str, type_: str, message: str, job_id: str | None = None,
            level: str | None = None, dedupe: bool = True) -> Alert | None:
        key = (type_, job_id, message)
        if dedupe and key in self._seen:
            return None
        self._seen.add(key)
        a = Alert(self._next, ts, step, level or ALERT_TYPES[type_], type_, job_id, message)
        self._next += 1
        self.items.append(a)
        if self.on_add:
            self.on_add(a)
        return a

    def ack(self, alert_id: int) -> Alert | None:
        for a in self.items:
            if a.id == alert_id:
                a.acknowledged = True
                return a
        return None

    def types(self) -> set:
        return {a.type for a in self.items}

    def as_list(self) -> list:
        return [a.as_dict() for a in self.items]


def drift_exceeded(forecast_mean: float, actual_mean: float, threshold: float = 0.20) -> bool:
    return forecast_mean > 0 and abs(actual_mean - forecast_mean) / forecast_mean > threshold
