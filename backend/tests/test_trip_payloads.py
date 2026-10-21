from datetime import date, datetime, time, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.main import app
from app.schemas.trips import TripCreate, TripRead

ORGANIZER = UUID("00000000-0000-0000-0000-000000000001")

# The body the frontend's TripForm sends (frontend/src/api/http.ts tripBody).
FRONTEND_BODY = {
    "organizer_id": str(ORGANIZER),
    "city_id": "chicago",
    "name": "Chicago weekend",
    "start_date": "2026-11-06",
    "end_date": "2026-11-08",
    "daily_start_time": "09:00",
    "daily_end_time": "21:00",
    "home_base_lat": 41.88,
    "home_base_lon": -87.63,
    "home_base_label": "Hotel near the Loop",
}

# Fields frontend/src/api/http.ts reads from a trip response (WireTrip).
FRONTEND_TRIP_FIELDS = {
    "id",
    "organizer_id",
    "city_id",
    "name",
    "start_date",
    "end_date",
    "daily_start_time",
    "daily_end_time",
    "home_base_lat",
    "home_base_lon",
    "home_base_label",
    "invite_token",
    "created_at",
}


def test_trip_create_accepts_the_frontend_form_body() -> None:
    payload = TripCreate.model_validate(FRONTEND_BODY)

    assert payload.name == "Chicago weekend"
    assert payload.home_base_label == "Hotel near the Loop"


def test_trip_create_requires_a_name() -> None:
    body = {key: value for key, value in FRONTEND_BODY.items() if key != "name"}

    with pytest.raises(ValidationError, match="name"):
        TripCreate.model_validate(body)


def test_home_base_label_is_optional() -> None:
    body = {key: value for key, value in FRONTEND_BODY.items() if key != "home_base_label"}

    assert TripCreate.model_validate(body).home_base_label == ""


def test_trip_read_has_every_field_the_frontend_reads() -> None:
    trip = TripRead(
        id=UUID("00000000-0000-0000-0000-0000000000aa"),
        organizer_id=ORGANIZER,
        city_id="chicago",
        name="Chicago weekend",
        start_date=date(2026, 11, 6),
        end_date=date(2026, 11, 8),
        daily_start_time=time(9, 0),
        daily_end_time=time(21, 0),
        home_base_lat=41.88,
        home_base_lon=-87.63,
        home_base_label="Hotel near the Loop",
        invite_token="token",
        created_at=datetime(2026, 10, 20, tzinfo=timezone.utc),
    )

    assert FRONTEND_TRIP_FIELDS <= set(trip.model_dump(mode="json"))


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/v1/cities"),
        ("GET", "/api/v1/trips"),
        ("POST", "/api/v1/trips"),
        ("GET", "/api/v1/trips/{trip_id}"),
        ("GET", "/api/v1/trips/{trip_id}/members"),
    ],
)
def test_create_trip_flow_routes_are_registered(method: str, path: str) -> None:
    paths = app.openapi()["paths"]

    assert method.lower() in paths.get(path, {})
