from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ItineraryStopRead(BaseModel):
    day_index: int
    seq: int
    destination_id: UUID
    name: str
    start_ts: datetime
    end_ts: datetime
    travel_minutes_in: int
    locked: bool


class ItineraryRead(BaseModel):
    trip_id: UUID
    stops: list[ItineraryStopRead]
    total_score: float
    scheduled_count: int
    unscheduled_count: int
    solver: str = Field(description="Which solver produced this itinerary.")


class GenerateItineraryRequest(BaseModel):
    candidate_limit: int = Field(
        default=60,
        ge=1,
        le=300,
        description="How many top-scoring destinations to consider. Caps solver work on large cities.",
    )
    keep_locked: bool = Field(
        default=True,
        description="Preserve stops a member pinned and schedule around them.",
    )
