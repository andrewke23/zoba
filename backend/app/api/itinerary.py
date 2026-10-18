"""Itinerary generation endpoints.

Loads scored candidates for a trip, runs the scheduler, and persists the
result to ``itinerary_stop``.

Scores currently come from the raw point budgets in the ``preference`` table.
That is a placeholder: the ranking service replaces ``_candidate_scores`` with
Bradley-Terry fits and regret-minimising group aggregation. The scheduler does
not care where a score came from, so that swap touches this module only.
"""

import json
from datetime import datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_trip_for_member, require_trip_organizer
from app.core.database import get_session
from app.models.entities import ItineraryStop, Membership, Trip
from app.schemas.itinerary import GenerateItineraryRequest, ItineraryRead, ItineraryStopRead
from app.services.scheduler import (
    Candidate,
    LockedStop,
    OpeningWindow,
    schedule_trip,
    straight_line_estimator,
    visit_minutes,
)

router = APIRouter(prefix="/trips/{trip_id}")

SOLVER_NAME = "greedy-insertion-v1"

_CANDIDATE_SQL = text(
    """
    SELECT d.destination_id,
           d.name,
           d.category,
           d.est_duration_min,
           ST_Y(d.geom::geometry) AS latitude,
           ST_X(d.geom::geometry) AS longitude,
           COALESCE(p.points_total, 0) AS points_total,
           COALESCE(h.windows, '[]'::json) AS windows
    FROM destination d
    LEFT JOIN (
        SELECT destination_id, SUM(points) AS points_total
        FROM preference
        WHERE trip_id = :trip_id AND NOT hard_no AND points IS NOT NULL
        GROUP BY destination_id
    ) p ON p.destination_id = d.destination_id
    LEFT JOIN (
        SELECT destination_id,
               json_agg(json_build_object('weekday', weekday, 'open_min', open_min, 'close_min', close_min)) AS windows
        FROM destination_hours
        GROUP BY destination_id
    ) h ON h.destination_id = d.destination_id
    WHERE d.city_id = :city_id
      AND NOT EXISTS (
          SELECT 1 FROM preference x
          WHERE x.trip_id = :trip_id AND x.destination_id = d.destination_id AND x.hard_no
      )
    ORDER BY points_total DESC, d.name
    LIMIT :candidate_limit
    """
)

_HOME_BASE_SQL = text(
    "SELECT ST_Y(home_base::geometry) AS latitude, ST_X(home_base::geometry) AS longitude "
    "FROM trip WHERE trip_id = :trip_id"
)


def _minutes_since_midnight(value) -> int:
    return value.hour * 60 + value.minute


def _parse_windows(raw) -> tuple[OpeningWindow, ...]:
    rows = json.loads(raw) if isinstance(raw, str) else (raw or [])
    return tuple(
        OpeningWindow(weekday=row["weekday"], open_min=row["open_min"], close_min=row["close_min"])
        for row in rows
    )


async def _load_candidates(session: AsyncSession, trip: Trip, limit: int) -> list[Candidate]:
    result = await session.execute(
        _CANDIDATE_SQL, {"trip_id": trip.id, "city_id": trip.city_id, "candidate_limit": limit}
    )
    candidates: list[Candidate] = []
    for row in result.mappings():
        candidates.append(
            Candidate(
                destination_id=row["destination_id"],
                name=row["name"],
                score=float(row["points_total"]),
                location=(float(row["latitude"]), float(row["longitude"])),
                duration_min=visit_minutes(row["est_duration_min"], row["category"]),
                windows=_parse_windows(row["windows"]),
            )
        )
    return [candidate for candidate in candidates if candidate.score > 0] or candidates


async def _load_locked(session: AsyncSession, trip: Trip, timezone: ZoneInfo) -> list[LockedStop]:
    rows = await session.execute(
        text(
            """
            SELECT s.day_index, s.destination_id, s.start_ts, s.end_ts, d.name,
                   ST_Y(d.geom::geometry) AS latitude, ST_X(d.geom::geometry) AS longitude
            FROM itinerary_stop s
            JOIN destination d ON d.destination_id = s.destination_id
            WHERE s.trip_id = :trip_id AND s.locked
            ORDER BY s.day_index, s.seq
            """
        ),
        {"trip_id": trip.id},
    )
    locked: list[LockedStop] = []
    for row in rows.mappings():
        start_local = row["start_ts"].astimezone(timezone)
        duration = int((row["end_ts"] - row["start_ts"]).total_seconds() // 60)
        locked.append(
            LockedStop(
                day_index=row["day_index"],
                destination_id=row["destination_id"],
                name=row["name"],
                location=(float(row["latitude"]), float(row["longitude"])),
                start_minute=_minutes_since_midnight(start_local),
                duration_min=duration,
            )
        )
    return locked


@router.post("/itinerary", response_model=ItineraryRead, status_code=status.HTTP_201_CREATED)
async def generate_itinerary(
    payload: GenerateItineraryRequest | None = None,
    trip_and_membership: tuple[Trip, Membership] = Depends(require_trip_organizer),
    session: AsyncSession = Depends(get_session),
) -> ItineraryRead:
    trip, _ = trip_and_membership
    options = payload or GenerateItineraryRequest()

    timezone_name = await session.scalar(
        text("SELECT timezone FROM city WHERE city_id = :city_id"), {"city_id": trip.city_id}
    )
    timezone = ZoneInfo(timezone_name or "UTC")

    home_row = (await session.execute(_HOME_BASE_SQL, {"trip_id": trip.id})).mappings().one()
    home_base = (float(home_row["latitude"]), float(home_row["longitude"]))

    candidates = await _load_candidates(session, trip, options.candidate_limit)
    if not candidates:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No candidate destinations for this city. Run the data pipeline first.",
        )

    locked = await _load_locked(session, trip, timezone) if options.keep_locked else []

    day_count = (trip.end_date - trip.start_date).days + 1
    days = [trip.start_date + timedelta(days=offset) for offset in range(day_count)]

    itinerary = schedule_trip(
        candidates,
        days=days,
        day_start_minute=_minutes_since_midnight(trip.daily_start_time),
        day_end_minute=_minutes_since_midnight(trip.daily_end_time),
        home_base=home_base,
        travel=straight_line_estimator(),
        locked=locked,
    )

    await session.execute(delete(ItineraryStop).where(ItineraryStop.trip_id == trip.id))
    for stop in itinerary.stops:
        session.add(
            ItineraryStop(
                trip_id=trip.id,
                day_index=stop.day_index,
                seq=stop.seq,
                destination_id=stop.destination_id,
                start_ts=_to_timestamp(days[stop.day_index], stop.start_minute, timezone),
                end_ts=_to_timestamp(days[stop.day_index], stop.end_minute, timezone),
                locked=stop.locked,
            )
        )
    await session.commit()

    return ItineraryRead(
        trip_id=trip.id,
        stops=[
            ItineraryStopRead(
                day_index=stop.day_index,
                seq=stop.seq,
                destination_id=stop.destination_id,
                name=stop.name,
                start_ts=_to_timestamp(days[stop.day_index], stop.start_minute, timezone),
                end_ts=_to_timestamp(days[stop.day_index], stop.end_minute, timezone),
                travel_minutes_in=stop.travel_minutes_in,
                locked=stop.locked,
            )
            for stop in itinerary.stops
        ],
        total_score=itinerary.total_score,
        scheduled_count=len(itinerary.stops),
        unscheduled_count=len(itinerary.unscheduled),
        solver=SOLVER_NAME,
    )


@router.get("/itinerary", response_model=ItineraryRead)
async def read_itinerary(
    trip_and_membership: tuple[Trip, Membership] = Depends(get_trip_for_member),
    session: AsyncSession = Depends(get_session),
) -> ItineraryRead:
    trip, _ = trip_and_membership
    rows = await session.execute(
        text(
            """
            SELECT s.day_index, s.seq, s.destination_id, s.start_ts, s.end_ts, s.locked, d.name
            FROM itinerary_stop s
            JOIN destination d ON d.destination_id = s.destination_id
            WHERE s.trip_id = :trip_id
            ORDER BY s.day_index, s.seq
            """
        ),
        {"trip_id": trip.id},
    )
    stops = [
        ItineraryStopRead(
            day_index=row["day_index"],
            seq=row["seq"],
            destination_id=row["destination_id"],
            name=row["name"],
            start_ts=row["start_ts"],
            end_ts=row["end_ts"],
            travel_minutes_in=0,
            locked=row["locked"],
        )
        for row in rows.mappings()
    ]
    return ItineraryRead(
        trip_id=trip.id,
        stops=stops,
        total_score=0.0,
        scheduled_count=len(stops),
        unscheduled_count=0,
        solver=SOLVER_NAME,
    )


def _to_timestamp(day, minute: int, timezone: ZoneInfo) -> datetime:
    """Convert minutes-since-local-midnight into an aware timestamp."""
    return datetime.combine(day, datetime.min.time(), tzinfo=timezone) + timedelta(minutes=minute)
