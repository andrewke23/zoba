from datetime import date, datetime, time
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.entities import MembershipRole, MembershipStatus


class TripCreate(BaseModel):
    organizer_id: UUID
    city_id: str = Field(min_length=1, max_length=120)
    name: str = Field(default="", max_length=120)
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
    city_name: str
    my_role: MembershipRole
    member_count: int


class MemberCreate(BaseModel):
    user_id: UUID


class MemberRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: UUID
    role: MembershipRole
    status: MembershipStatus


class TripMemberRead(MemberRead):
    email: str
    display_name: str
