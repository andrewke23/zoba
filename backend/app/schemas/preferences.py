"""Preference, comparison, and group-ranking payloads (F04, F06, F07a, F08, F08a).

These mirror `frontend/src/api/types.ts` exactly, the same convention the
itinerary schemas follow: the frontend defined this contract first.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.services.preference import DEFAULT_CONFIG


class PreferenceIn(BaseModel):
    destination_id: UUID
    points: int = Field(ge=0)
    rank: int | None = Field(default=None, ge=1)
    hard_no: bool = False


class PreferenceRead(BaseModel):
    destination_id: UUID
    points: int
    rank: int | None
    hard_no: bool


class SavePreferencesRequest(BaseModel):
    preferences: list[PreferenceIn]

    @model_validator(mode="after")
    def validate_budget(self) -> "SavePreferencesRequest":
        destination_ids = [p.destination_id for p in self.preferences]
        if len(destination_ids) != len(set(destination_ids)):
            raise ValueError("A destination may only appear once")
        spent = sum(p.points for p in self.preferences if not p.hard_no)
        if spent > DEFAULT_CONFIG.point_budget:
            raise ValueError(f"Total points cannot exceed the {DEFAULT_CONFIG.point_budget}-point budget")
        return self


class PreferenceConfigRead(BaseModel):
    point_budget: int
    point_cap: int
    target_comparisons: int


class ComparisonPairRead(BaseModel):
    dest_a: UUID
    dest_b: UUID


class ComparisonProgressRead(BaseModel):
    done: int
    target: int
    next: ComparisonPairRead | None


class SubmitComparisonRequest(BaseModel):
    dest_a: UUID
    dest_b: UUID
    chosen: UUID

    @model_validator(mode="after")
    def validate_chosen(self) -> "SubmitComparisonRequest":
        if self.dest_a == self.dest_b:
            raise ValueError("dest_a and dest_b must be different destinations")
        if self.chosen not in (self.dest_a, self.dest_b):
            raise ValueError("chosen must be dest_a or dest_b")
        return self


class RankingRowRead(BaseModel):
    destination_id: UUID
    rank: int
    raw_points: int
    raw_votes: int
    weighted_points: float
    group_score: float
    min_member_utility: float
    vetoed_by: list[UUID]


class MemberTopPickRead(BaseModel):
    user_id: UUID
    destination_id: UUID | None


class GroupResultsRead(BaseModel):
    rows: list[RankingRowRead]
    top_picks: list[MemberTopPickRead]
    config: PreferenceConfigRead
    computed_at: datetime
