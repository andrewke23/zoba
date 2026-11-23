from typing import Literal
from uuid import UUID

from pydantic import BaseModel

HoursStatus = Literal["ok", "partial", "unparseable", "missing"]


class OpeningWindowRead(BaseModel):
    # 0 = Monday. Minutes since local midnight; close_min may pass 1440.
    weekday: int
    open_min: int
    close_min: int


class DestinationRead(BaseModel):
    """One catalog place, in the `Destination` shape of frontend/src/api/types.ts."""

    destination_id: UUID
    city_id: str
    name: str
    lat: float
    lng: float
    category: str
    address: str | None
    website: str | None
    description: str | None
    admission_cost_usd: float | None
    est_duration_min: int
    hours: list[OpeningWindowRead]
    hours_status: HoursStatus
    requires_booking: bool
