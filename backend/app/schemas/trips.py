from datetime import date, datetime, time
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.entities import MembershipRole, MembershipStatus


def _validate_window(
    start_date: date | None,
    end_date: date | None,
    daily_start_time: time | None,
    daily_end_time: time | None,
) -> None:
    """Validate whichever parts of the trip window are present."""
    if start_date is not None and end_date is not None and end_date < start_date:
        raise ValueError("end_date must be on or after start_date")
    if (
        daily_start_time is not None
        and daily_end_time is not None
        and daily_end_time <= daily_start_time
    ):
        raise ValueError("daily_end_time must be after daily_start_time")
    for value in (daily_start_time, daily_end_time):
        if value is not None and value.utcoffset() is not None:
            raise ValueError("daily times must not include a timezone")


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
        _validate_window(self.start_date, self.end_date, self.daily_start_time, self.daily_end_time)
        return self


class TripUpdate(BaseModel):
    """Partial trip update; omitted fields keep their current values."""

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
    def validate_trip_window(self) -> "TripUpdate":
        _validate_window(
            self.start_date, self.end_date, self.daily_start_time, self.daily_end_time
        )
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


class InviteRead(BaseModel):
    trip: TripRead
    city_name: str
    organizer_name: str
