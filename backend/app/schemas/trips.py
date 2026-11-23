from datetime import date, datetime, time
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.entities import MembershipRole, MembershipStatus


class TripCreate(BaseModel):
    organizer_id: UUID
    city_id: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=120)
    start_date: date
    end_date: date
    daily_start_time: time
    daily_end_time: time
    home_base_lat: float = Field(ge=-90, le=90)
    home_base_lon: float = Field(ge=-180, le=180)
    home_base_label: str = Field(default="", max_length=200)

    @model_validator(mode="after")
    def validate_trip_window(self) -> "TripCreate":
        if self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        if self.daily_end_time <= self.daily_start_time:
            raise ValueError("daily_end_time must be after daily_start_time")
        if self.daily_start_time.utcoffset() is not None or self.daily_end_time.utcoffset() is not None:
            raise ValueError("daily times must not include a timezone")
        return self


class TripUpdate(BaseModel):
    """Partial trip edit; omitted fields keep their current values."""

    city_id: str | None = Field(default=None, min_length=1, max_length=120)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    start_date: date | None = None
    end_date: date | None = None
    daily_start_time: time | None = None
    daily_end_time: time | None = None
    home_base_lat: float | None = Field(default=None, ge=-90, le=90)
    home_base_lon: float | None = Field(default=None, ge=-180, le=180)
    home_base_label: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def validate_home_base_pair(self) -> "TripUpdate":
        if (self.home_base_lat is None) != (self.home_base_lon is None):
            raise ValueError("home_base_lat and home_base_lon must be provided together")
        return self


class TripRead(BaseModel):
    id: UUID
    organizer_id: UUID
    city_id: str
    name: str
    start_date: date
    end_date: date
    daily_start_time: time
    daily_end_time: time
    home_base_lat: float
    home_base_lon: float
    home_base_label: str
    invite_token: str | None
    created_at: datetime


class TripSummaryRead(TripRead):
    """A trip as listed for one member: trip fields plus listing context."""

    city_name: str
    my_role: MembershipRole
    member_count: int


class MemberCreate(BaseModel):
    user_id: UUID


class MemberRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: UUID
    email: str
    display_name: str
    role: MembershipRole
    status: MembershipStatus
    # Voting progress (F07a, F03); only the members list fills these in.
    preferences_submitted: bool = False
    comparisons_done: int = 0


class InviteRead(BaseModel):
    trip: TripRead
    city_name: str
    organizer_name: str
