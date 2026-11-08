from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class IncubationHistoryItemSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    profile_id: int
    session_id: int | None
    project_id: int
    project_name: str | None
    worker_id: str | None
    trace_id: str | None = None
    previous_session_id: int | None = None
    stage: str
    session_status: str
    duration_seconds: int
    cookies_stored_count: int
    collected_sources: list[str] = Field(
        default_factory=list, description="Домены, посещённые в рамках сессии обслуживания"
    )
    visited_url: str
    error_type: str | None
    recorded_at: datetime


class AnalyticsTargets(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    target_bounce_rate: float = Field(ge=0, le=1)
    target_page_depth: float = Field(ge=1, le=5)

    @model_validator(mode="after")
    def attainable_depth(self) -> "AnalyticsTargets":
        if self.target_bounce_rate == 1 and self.target_page_depth != 1:
            raise ValueError("При 100% отказов глубина просмотра должна быть равна 1")
        return self


class AnalyticsRoute(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    session_behavior_pattern: Literal["PATTERN_A", "PATTERN_B", "PATTERN_C"]
    max_depth_limit: int = Field(ge=1, le=400001)

    @model_validator(mode="after")
    def consistent_depth(self) -> "AnalyticsRoute":
        if (self.session_behavior_pattern == "PATTERN_C") != (self.max_depth_limit >= 2):
            raise ValueError("Only PATTERN_C may have a depth greater than one")
        return self
