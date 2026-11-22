"""Voting payloads, in the shapes of frontend/src/api/types.ts (F03–F08a)."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class PreferenceConfigRead(BaseModel):
    point_budget: int
    point_cap: int
    target_comparisons: int


class PreferenceItem(BaseModel):
    """One destination's points, rank, and veto. Used for both reads and writes."""

    destination_id: UUID
    points: int = Field(ge=0)
    rank: int | None = Field(default=None, ge=1)
    hard_no: bool = False


class ComparisonPairRead(BaseModel):
    dest_a: UUID
    dest_b: UUID


class ComparisonProgressRead(BaseModel):
    done: int
    target: int
    # None when no informative pairs remain.
    next: ComparisonPairRead | None


class ComparisonCreate(BaseModel):
    dest_a: UUID
    dest_b: UUID
    chosen: UUID

    @model_validator(mode="after")
    def chosen_is_in_pair(self) -> "ComparisonCreate":
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
