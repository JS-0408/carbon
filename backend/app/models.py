"""API models and validation (Section 5.1). Plain-language messages, ISO-8601 UTC timestamps."""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

WORKLOAD_TYPES = ("model_training", "batch_inference", "realtime_inference", "etl", "other")


class JobIn(BaseModel):
    job_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9._-]+$")
    workload_type: Literal["model_training", "batch_inference", "realtime_inference", "etl", "other"]
    estimated_duration_minutes: float = Field(gt=0, le=4320)
    duration_p90_minutes: Optional[float] = Field(default=None, gt=0, le=4320)
    power_profile_kw: float = Field(gt=0)
    submission_time: Optional[datetime] = None
    sla_deadline: datetime
    priority: Literal["low", "normal", "high"] = "normal"
    preemptible: bool = False
    allowed_regions: list[str] = Field(default_factory=lambda: ["default"])
    fallback_policy: Literal["historical_average", "run_now", "fail"] = "historical_average"
    data_gb: float = Field(default=0.0, ge=0)
    sim_actual_duration_minutes: Optional[float] = Field(default=None, gt=0, le=10000)

    @field_validator("submission_time", "sla_deadline")
    @classmethod
    def _tz(cls, v):
        if v is not None and v.tzinfo is None:
            raise ValueError("timestamps must be ISO 8601 in UTC, for example 2026-10-09T20:00:00Z")
        return v

    @model_validator(mode="after")
    def _p90(self):
        if self.duration_p90_minutes is not None and self.duration_p90_minutes < self.estimated_duration_minutes:
            raise ValueError("duration_p90_minutes must be at least estimated_duration_minutes")
        if self.submission_time is not None and self.sla_deadline <= self.submission_time:
            raise ValueError("sla_deadline must be after submission_time")
        return self


class ClockIn(BaseModel):
    steps: Optional[int] = Field(default=None, ge=1, le=288)
    hours: Optional[float] = Field(default=None, gt=0, le=144)


class ProviderIn(BaseModel):
    provider: str


class SeedIn(BaseModel):
    scenario: str = "weekday_mix"
    seed: int = 0
    jobs_only: bool = False
