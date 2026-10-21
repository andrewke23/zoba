"""Itinerary response models.

These mirror `frontend/src/api/types.ts` exactly. The frontend defined this
contract first, so the field names here are deliberately theirs: if the two
drift, the UI silently falls back to its in-browser mock and the real scheduler
stops being visible.
"""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

SolverKind = Literal["greedy", "cpsat"]
TravelMode = Literal["walk", "drive", "transit"]


class ItineraryStopRead(BaseModel):
    trip_id: UUID
    day_index: int
    seq: int
    destination_id: UUID
    start_ts: datetime
    end_ts: datetime
    locked: bool
    travel_min_from_prev: int
    travel_mode_from_prev: TravelMode


class ItineraryDayRead(BaseModel):
    day_index: int
    date: date
    stops: list[ItineraryStopRead]


class UnscheduledRead(BaseModel):
    destination_id: UUID
    reason: str


class TopPickStatusRead(BaseModel):
    user_id: UUID
    destination_id: UUID | None
    included: bool
    reason: str | None


class SolverMetricsRead(BaseModel):
    solver: SolverKind
    runtime_ms: int
    group_score: float
    min_member_utility: float
    stops_scheduled: int
    travel_min_total: int
    feasible: bool


class ItineraryRead(BaseModel):
    trip_id: UUID
    solver: SolverKind
    generated_at: datetime
    days: list[ItineraryDayRead]
    unscheduled: list[UnscheduledRead]
    top_picks: list[TopPickStatusRead]
    conflicts: list[str]
    metrics: SolverMetricsRead


class LockRequest(BaseModel):
    day_index: int
    start_ts: datetime


class GenerateItineraryRequest(BaseModel):
    solver: SolverKind = "greedy"
    candidate_limit: int = Field(default=60, ge=1, le=300)
