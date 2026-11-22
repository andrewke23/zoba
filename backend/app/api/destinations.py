"""Destination catalog for a trip: every place the pipeline loaded for its city.

The preferences, compare and itinerary pages all list these, so trip members
vote on the same rows (and IDs) the scheduler later reads.
"""

import json
from collections.abc import Mapping
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_trip_for_member
from app.core.database import get_session
from app.models.entities import Membership, Trip
from app.schemas.destinations import DestinationRead, OpeningWindowRead
from app.services.scheduler import visit_minutes

router = APIRouter(prefix="/trips/{trip_id}")

_DESTINATIONS_SQL = text(
    """
    SELECT d.destination_id,
           d.city_id,
           d.name,
           ST_Y(d.geom::geometry) AS lat,
           ST_X(d.geom::geometry) AS lng,
           d.category,
           d.address,
           d.website,
           d.description,
           d.admission_cost_usd,
           d.est_duration_min,
           d.hours_status,
           COALESCE(h.windows, '[]'::json) AS windows
    FROM destination d
    LEFT JOIN (
        SELECT destination_id,
               json_agg(
                   json_build_object('weekday', weekday, 'open_min', open_min, 'close_min', close_min)
                   ORDER BY weekday, open_min
               ) AS windows
        FROM destination_hours
        GROUP BY destination_id
    ) h ON h.destination_id = d.destination_id
    WHERE d.city_id = :city_id
    ORDER BY d.name
    """
)


def destination_from_row(row: Mapping[str, Any]) -> DestinationRead:
    """Map one `_DESTINATIONS_SQL` row to the frontend's Destination shape."""
    windows = row["windows"]
    if isinstance(windows, str):  # some drivers hand json back undecoded
        windows = json.loads(windows)
    cost = row["admission_cost_usd"]
    return DestinationRead(
        destination_id=row["destination_id"],
        city_id=row["city_id"],
        name=row["name"],
        lat=row["lat"],
        lng=row["lng"],
        category=row["category"],
        address=row["address"],
        website=row["website"],
        description=row["description"],
        admission_cost_usd=float(cost) if cost is not None else None,
        est_duration_min=visit_minutes(row["est_duration_min"], row["category"]),
        hours=[OpeningWindowRead(**w) for w in windows or []],
        hours_status=row["hours_status"],
        # The catalog has no booking flag yet; booking tasks (F15) stay off
        # until the pipeline provides one.
        requires_booking=False,
    )


@router.get("/destinations", response_model=list[DestinationRead])
async def list_destinations(
    access: tuple[Trip, Membership] = Depends(get_trip_for_member),
    session: AsyncSession = Depends(get_session),
) -> list[DestinationRead]:
    trip, _ = access
    rows = (await session.execute(_DESTINATIONS_SQL, {"city_id": trip.city_id})).mappings().all()
    return [destination_from_row(row) for row in rows]
