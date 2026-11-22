from decimal import Decimal
from uuid import UUID

from app.api.destinations import destination_from_row
from app.main import app

DEST_ID = UUID("11111111-1111-1111-1111-111111111111")

# Fields frontend/src/api/types.ts reads from a Destination.
FRONTEND_DESTINATION_FIELDS = {
    "destination_id",
    "city_id",
    "name",
    "lat",
    "lng",
    "category",
    "address",
    "website",
    "description",
    "admission_cost_usd",
    "est_duration_min",
    "hours",
    "hours_status",
    "requires_booking",
}


def row(**overrides):
    base = {
        "destination_id": DEST_ID,
        "city_id": "london",
        "name": "British Museum",
        "lat": 51.5194,
        "lng": -0.127,
        "category": "museum",
        "address": "Great Russell St",
        "website": "https://britishmuseum.org",
        "description": None,
        "admission_cost_usd": Decimal("0.00"),
        "est_duration_min": 150,
        "hours_status": "ok",
        "windows": [{"weekday": 0, "open_min": 600, "close_min": 1020}],
    }
    return {**base, **overrides}


def test_maps_a_catalog_row_to_the_frontend_shape() -> None:
    dest = destination_from_row(row())

    assert set(dest.model_dump()) == FRONTEND_DESTINATION_FIELDS
    assert dest.destination_id == DEST_ID
    assert (dest.lat, dest.lng) == (51.5194, -0.127)
    assert dest.admission_cost_usd == 0.0
    assert dest.est_duration_min == 150
    assert dest.hours[0].model_dump() == {"weekday": 0, "open_min": 600, "close_min": 1020}
    assert dest.requires_booking is False


def test_unknown_price_stays_null() -> None:
    assert destination_from_row(row(admission_cost_usd=None)).admission_cost_usd is None


def test_missing_duration_falls_back_to_the_category_default() -> None:
    dest = destination_from_row(row(est_duration_min=None, category="park"))

    assert dest.est_duration_min > 0


def test_place_without_hours_has_an_empty_list() -> None:
    dest = destination_from_row(row(windows=[], hours_status="missing"))

    assert dest.hours == []
    assert dest.hours_status == "missing"


def test_accepts_hours_json_returned_as_a_string() -> None:
    dest = destination_from_row(row(windows='[{"weekday": 6, "open_min": 0, "close_min": 1500}]'))

    assert dest.hours[0].close_min == 1500


def test_destinations_route_is_registered() -> None:
    paths = app.openapi()["paths"]

    assert "get" in paths["/api/v1/trips/{trip_id}/destinations"]
