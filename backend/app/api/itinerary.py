"""Itinerary generation endpoints.

Loads scored candidates for a trip, runs the scheduler, persists the result to
``itinerary_stop``, and returns it in the shape `frontend/src/api/types.ts`
expects.

Scores currently come from the raw point budgets in the ``preference`` table.
That is a placeholder: the ranking service replaces ``_member_points`` with
Bradley-Terry fits and regret-minimising group aggregation. The scheduler does
not care where a score came from, so that swap touches this module only.
"""

import json
import logging
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Body, Depends, HTTPException, Response, status
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_trip_for_member, require_trip_organizer
from app.core.database import get_session
from app.models.entities import ItineraryStop, Membership, Trip
from app.schemas.itinerary import (
    GenerateItineraryRequest,
    ItineraryDayRead,
    ItineraryRead,
    ItineraryStopRead,
    LockRequest,
    RouteLegRead,
    SolverMetricsRead,
    TopPickStatusRead,
    UnscheduledRead,
)
from app.services.scheduler import (
    Candidate,
    LockedStop,
    OpeningWindow,
    schedule_trip,
    visit_minutes,
)
from app.services.routing import RoutedEstimator, RoutingUnavailable, build_estimator, fetch_route_shapes
from app.services.scheduler_cpsat import SolverUnavailable, schedule_trip_cpsat
from app.services.solver_comparison import compare

router = APIRouter(prefix="/trips/{trip_id}")
logger = logging.getLogger(__name__)

# Travel times come from road-network routes (app/services/routing.py). Each
# leg's minutes and mode are stored with the stop when the itinerary is
# generated, so reads show exactly what the solver budgeted and do not depend
# on the routing service being up.

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

_MEMBER_POINTS_SQL = text(
    """
    SELECT user_id, destination_id, points
    FROM preference
    WHERE trip_id = :trip_id AND NOT hard_no AND points IS NOT NULL AND points > 0
    """
)

_MEMBERS_SQL = text("SELECT user_id FROM membership WHERE trip_id = :trip_id AND status = 'joined'")

_STOPS_SQL = text(
    """
    SELECT s.day_index, s.seq, s.destination_id, s.start_ts, s.end_ts, s.locked, d.name,
           s.travel_min_from_prev, s.travel_mode_from_prev,
           ST_Y(d.geom::geometry) AS latitude, ST_X(d.geom::geometry) AS longitude
    FROM itinerary_stop s
    JOIN destination d ON d.destination_id = s.destination_id
    WHERE s.trip_id = :trip_id
    ORDER BY s.day_index, s.seq
    """
)

_HOME_BASE_SQL = text(
    "SELECT ST_Y(home_base::geometry) AS latitude, ST_X(home_base::geometry) AS longitude "
    "FROM trip WHERE trip_id = :trip_id"
)


async def _estimator(points) -> RoutedEstimator:
    """Road-network travel times between ``points``, or 503 if routing is down."""
    try:
        return await build_estimator(points)
    except RoutingUnavailable as exc:
        logger.warning("Routing unavailable: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Travel times are unavailable right now (routing service unreachable). Try again shortly.",
        ) from exc


def _legs_by_stop(stops, home, estimate: RoutedEstimator) -> dict[tuple[int, int], tuple[int, str]]:
    """(day_index, seq) -> (minutes, mode) for the leg arriving at each stop."""
    legs: dict[tuple[int, int], tuple[int, str]] = {}
    previous: dict[int, tuple[float, float]] = {}
    for day_index, seq, here in sorted(stops, key=lambda stop: (stop[0], stop[1])):
        leg = estimate.leg(previous.get(day_index, home), here)
        legs[(day_index, seq)] = (leg.minutes, leg.mode)
        previous[day_index] = here
    return legs


def _minutes_since_midnight(value) -> int:
    return value.hour * 60 + value.minute


def _parse_windows(raw) -> tuple[OpeningWindow, ...]:
    rows = json.loads(raw) if isinstance(raw, str) else (raw or [])
    return tuple(
        OpeningWindow(weekday=row["weekday"], open_min=row["open_min"], close_min=row["close_min"])
        for row in rows
    )


def _trip_days(trip: Trip) -> list:
    count = (trip.end_date - trip.start_date).days + 1
    return [trip.start_date + timedelta(days=offset) for offset in range(count)]


def _to_timestamp(day, minute: int, tz: ZoneInfo) -> datetime:
    return datetime.combine(day, datetime.min.time(), tzinfo=tz) + timedelta(minutes=minute)


async def _timezone(session: AsyncSession, city_id: str) -> ZoneInfo:
    name = await session.scalar(text("SELECT timezone FROM city WHERE city_id = :city_id"), {"city_id": city_id})
    return ZoneInfo(name or "UTC")


async def _home_base(session: AsyncSession, trip: Trip) -> tuple[float, float]:
    row = (await session.execute(_HOME_BASE_SQL, {"trip_id": trip.id})).mappings().one()
    return float(row["latitude"]), float(row["longitude"])


async def _load_candidates(session: AsyncSession, trip: Trip, limit: int) -> list[Candidate]:
    result = await session.execute(
        _CANDIDATE_SQL, {"trip_id": trip.id, "city_id": trip.city_id, "candidate_limit": limit}
    )
    return [
        Candidate(
            destination_id=row["destination_id"],
            name=row["name"],
            score=float(row["points_total"]),
            location=(float(row["latitude"]), float(row["longitude"])),
            duration_min=visit_minutes(row["est_duration_min"], row["category"]),
            windows=_parse_windows(row["windows"]),
        )
        for row in result.mappings()
    ]


async def _member_points(session: AsyncSession, trip_id: UUID) -> dict[UUID, dict[UUID, float]]:
    """Per-member point allocations, used for fairness metrics and top picks."""
    rows = await session.execute(_MEMBER_POINTS_SQL, {"trip_id": trip_id})
    points: dict[UUID, dict[UUID, float]] = defaultdict(dict)
    for row in rows.mappings():
        points[row["user_id"]][row["destination_id"]] = float(row["points"])
    return points


async def _joined_members(session: AsyncSession, trip_id: UUID) -> list[UUID]:
    rows = await session.execute(_MEMBERS_SQL, {"trip_id": trip_id})
    return [row[0] for row in rows.all()]


async def _load_locked(session: AsyncSession, trip: Trip, tz: ZoneInfo) -> list[LockedStop]:
    rows = await session.execute(_STOPS_SQL, {"trip_id": trip.id})
    locked: list[LockedStop] = []
    for row in rows.mappings():
        if not row["locked"]:
            continue
        locked.append(
            LockedStop(
                day_index=row["day_index"],
                destination_id=row["destination_id"],
                name=row["name"],
                location=(float(row["latitude"]), float(row["longitude"])),
                start_minute=_minutes_since_midnight(row["start_ts"].astimezone(tz)),
                duration_min=int((row["end_ts"] - row["start_ts"]).total_seconds() // 60),
            )
        )
    return locked


def _fairness(
    scheduled_ids: set[UUID],
    member_points: dict[UUID, dict[UUID, float]],
    members: list[UUID],
) -> tuple[float, list[TopPickStatusRead]]:
    """Worst individual outcome, plus whether each member's favourite made the trip.

    The minimum is what the regret-bounded objective in the proposal protects.
    Reporting it every run is how we tell whether fairness is actually working
    rather than asserting it in a report.
    """
    utilities: list[float] = []
    top_picks: list[TopPickStatusRead] = []

    for user_id in members:
        allocations = member_points.get(user_id, {})
        total = sum(allocations.values())
        earned = sum(points for dest, points in allocations.items() if dest in scheduled_ids)
        utilities.append(earned / total if total else 0.0)

        if not allocations:
            top_picks.append(
                TopPickStatusRead(
                    user_id=user_id, destination_id=None, included=False, reason="No preferences submitted"
                )
            )
            continue

        favourite = max(allocations, key=lambda dest: (allocations[dest], str(dest)))
        included = favourite in scheduled_ids
        top_picks.append(
            TopPickStatusRead(
                user_id=user_id,
                destination_id=favourite,
                included=included,
                reason=None if included else "Did not fit the schedule",
            )
        )

    return (min(utilities) if utilities else 0.0), top_picks


async def _read_itinerary(session: AsyncSession, trip: Trip) -> ItineraryRead | None:
    """Rebuild the response from persisted stops."""
    solver = trip.itinerary_solver or "greedy"
    tz = await _timezone(session, trip.city_id)
    rows = (await session.execute(_STOPS_SQL, {"trip_id": trip.id})).mappings().all()
    if not rows:
        return None

    days = _trip_days(trip)
    legs = {
        (row["day_index"], row["seq"]): (row["travel_min_from_prev"], row["travel_mode_from_prev"])
        for row in rows
    }
    if any(minutes is None or mode is None for minutes, mode in legs.values()):
        # Stops saved before travel legs were stored: route them once and keep the result.
        home = await _home_base(session, trip)
        stops = [(row["day_index"], row["seq"], (float(row["latitude"]), float(row["longitude"]))) for row in rows]
        estimate = await _estimator([home] + [here for _, _, here in stops])
        legs = _legs_by_stop(stops, home, estimate)
        for (day_index, seq), (minutes, mode) in legs.items():
            await session.execute(
                text(
                    "UPDATE itinerary_stop SET travel_min_from_prev = :minutes, travel_mode_from_prev = :mode "
                    "WHERE trip_id = :trip_id AND day_index = :day_index AND seq = :seq"
                ),
                {"minutes": minutes, "mode": mode, "trip_id": trip.id, "day_index": day_index, "seq": seq},
            )
        await session.commit()

    by_day: dict[int, list[ItineraryStopRead]] = defaultdict(list)
    travel_total = 0

    for row in rows:
        day_index = row["day_index"]
        minutes, mode = legs[(day_index, row["seq"])]
        travel_total += minutes
        by_day[day_index].append(
            ItineraryStopRead(
                trip_id=trip.id,
                day_index=day_index,
                seq=row["seq"],
                destination_id=row["destination_id"],
                # In the city's local time: the UI shows the wall-clock part of
                # the timestamp, so UTC here would display 9 AM as 3 PM.
                start_ts=row["start_ts"].astimezone(tz),
                end_ts=row["end_ts"].astimezone(tz),
                locked=row["locked"],
                travel_min_from_prev=minutes,
                travel_mode_from_prev=mode,
            )
        )

    scheduled_ids = {row["destination_id"] for row in rows}
    member_points = await _member_points(session, trip.id)
    members = await _joined_members(session, trip.id)
    min_utility, top_picks = _fairness(scheduled_ids, member_points, members)
    group_score = sum(
        sum(points for dest, points in allocations.items() if dest in scheduled_ids)
        for allocations in member_points.values()
    )

    return ItineraryRead(
        trip_id=trip.id,
        solver=solver,
        generated_at=trip.itinerary_generated_at or datetime.now(timezone.utc),
        days=[
            ItineraryDayRead(day_index=index, date=days[index], stops=by_day.get(index, []))
            for index in range(len(days))
        ],
        unscheduled=[],
        top_picks=top_picks,
        conflicts=[],
        metrics=SolverMetricsRead(
            solver=solver,
            runtime_ms=0,
            group_score=group_score,
            min_member_utility=min_utility,
            stops_scheduled=len(rows),
            travel_min_total=travel_total,
            feasible=True,
        ),
    )


@router.post("/itinerary", response_model=ItineraryRead, status_code=status.HTTP_201_CREATED)
async def generate_itinerary(
    payload: GenerateItineraryRequest | None = None,
    trip_and_membership: tuple[Trip, Membership] = Depends(require_trip_organizer),
    session: AsyncSession = Depends(get_session),
) -> ItineraryRead:
    trip, _ = trip_and_membership
    options = payload or GenerateItineraryRequest()

    tz = await _timezone(session, trip.city_id)
    home = await _home_base(session, trip)
    candidates = await _load_candidates(session, trip, options.candidate_limit)
    if not candidates:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No candidate destinations for this city. Run the data pipeline first.",
        )

    locked = await _load_locked(session, trip, tz)
    days = _trip_days(trip)
    estimate = await _estimator(
        [home] + [candidate.location for candidate in candidates] + [stop.location for stop in locked]
    )

    solver_kwargs = dict(
        days=days,
        day_start_minute=_minutes_since_midnight(trip.daily_start_time),
        day_end_minute=_minutes_since_midnight(trip.daily_end_time),
        home_base=home,
        travel=estimate,
        locked=locked,
    )

    started = time.perf_counter()
    if options.solver == "cpsat":
        try:
            itinerary = schedule_trip_cpsat(candidates, **solver_kwargs)
        except SolverUnavailable as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
            ) from exc
    else:
        itinerary = schedule_trip(candidates, **solver_kwargs)
    runtime_ms = int((time.perf_counter() - started) * 1000)

    locations = {candidate.destination_id: candidate.location for candidate in candidates}
    locations.update({stop.destination_id: stop.location for stop in locked})
    legs = _legs_by_stop(
        [(stop.day_index, stop.seq, locations[stop.destination_id]) for stop in itinerary.stops], home, estimate
    )

    await session.execute(delete(ItineraryStop).where(ItineraryStop.trip_id == trip.id))
    for stop in itinerary.stops:
        minutes, mode = legs[(stop.day_index, stop.seq)]
        session.add(
            ItineraryStop(
                trip_id=trip.id,
                day_index=stop.day_index,
                seq=stop.seq,
                destination_id=stop.destination_id,
                start_ts=_to_timestamp(days[stop.day_index], stop.start_minute, tz),
                end_ts=_to_timestamp(days[stop.day_index], stop.end_minute, tz),
                locked=stop.locked,
                travel_min_from_prev=minutes,
                travel_mode_from_prev=mode,
            )
        )
    trip.itinerary_solver = options.solver
    trip.itinerary_generated_at = datetime.now(timezone.utc)
    await session.commit()

    response = await _read_itinerary(session, trip)
    assert response is not None  # we just wrote the stops

    names = {candidate.destination_id: candidate.name for candidate in candidates}
    response.unscheduled = [
        UnscheduledRead(destination_id=dest_id, reason="Did not fit the schedule")
        for dest_id in itinerary.unscheduled
        if dest_id in names
    ]
    response.metrics.runtime_ms = runtime_ms
    response.metrics.feasible = bool(itinerary.stops)
    return response


@router.get("/itinerary", response_model=ItineraryRead | None)
async def read_itinerary(
    response: Response,
    trip_and_membership: tuple[Trip, Membership] = Depends(get_trip_for_member),
    session: AsyncSession = Depends(get_session),
) -> ItineraryRead | None:
    trip, _ = trip_and_membership
    itinerary = await _read_itinerary(session, trip)
    if itinerary is None:
        response.status_code = status.HTTP_204_NO_CONTENT
    return itinerary


@router.get("/itinerary/routes", response_model=list[RouteLegRead])
async def read_itinerary_routes(
    trip_and_membership: tuple[Trip, Membership] = Depends(get_trip_for_member),
    session: AsyncSession = Depends(get_session),
) -> list[RouteLegRead]:
    """Street paths for every leg of every day, including the ride back to the hotel.

    The stops' travel modes are the ones stored at generation time; the return
    leg's mode is chosen the same way. Shapes come from OSRM (walking on the foot
    network, taxi and transit on the street network).
    """
    trip, _ = trip_and_membership
    itinerary = await _read_itinerary(session, trip)  # also fills in any missing leg modes
    if itinerary is None:
        return []

    rows = (await session.execute(_STOPS_SQL, {"trip_id": trip.id})).mappings().all()
    home = await _home_base(session, trip)
    location = {row["destination_id"]: (float(row["latitude"]), float(row["longitude"])) for row in rows}

    legs: list[dict] = []
    last_stops: list[tuple[float, float]] = []
    for day in itinerary.days:
        previous_id, previous_at = None, home
        for seq, stop in enumerate(day.stops):
            here = location[stop.destination_id]
            legs.append(
                dict(
                    day_index=day.day_index,
                    seq=seq,
                    from_destination_id=previous_id,
                    to_destination_id=stop.destination_id,
                    mode=stop.travel_mode_from_prev,
                    minutes=stop.travel_min_from_prev,
                    origin=previous_at,
                    destination=here,
                )
            )
            previous_id, previous_at = stop.destination_id, here
        if day.stops:
            last_stops.append(previous_at)
            legs.append(
                dict(
                    day_index=day.day_index,
                    seq=len(day.stops),
                    from_destination_id=previous_id,
                    to_destination_id=None,
                    mode=None,
                    minutes=None,
                    origin=previous_at,
                    destination=home,
                )
            )

    if last_stops:
        estimate = await _estimator([home, *last_stops])
        for leg in legs:
            if leg["mode"] is None:
                back = estimate.leg(leg["origin"], leg["destination"])
                leg["mode"], leg["minutes"] = back.mode, back.minutes

    try:
        shapes = await fetch_route_shapes([(leg["mode"], leg["origin"], leg["destination"]) for leg in legs])
    except RoutingUnavailable as exc:
        logger.warning("Route shapes unavailable: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Route lines are unavailable right now (routing service unreachable). Try again shortly.",
        ) from exc

    return [
        RouteLegRead(
            day_index=leg["day_index"],
            seq=leg["seq"],
            from_destination_id=leg["from_destination_id"],
            to_destination_id=leg["to_destination_id"],
            mode=leg["mode"],
            minutes=leg["minutes"],
            coordinates=list(shape),
        )
        for leg, shape in zip(legs, shapes)
    ]


@router.put("/itinerary/stops/{destination_id}/lock", response_model=ItineraryRead)
async def set_stop_lock(
    destination_id: UUID,
    lock: LockRequest | None = Body(default=None),
    trip_and_membership: tuple[Trip, Membership] = Depends(get_trip_for_member),
    session: AsyncSession = Depends(get_session),
) -> ItineraryRead:
    """Pin a stop to a day and time, or unpin it, then re-solve around the change."""
    trip, _ = trip_and_membership
    tz = await _timezone(session, trip.city_id)

    if lock is None:
        await session.execute(
            text(
                "UPDATE itinerary_stop SET locked = false "
                "WHERE trip_id = :trip_id AND destination_id = :destination_id"
            ),
            {"trip_id": trip.id, "destination_id": destination_id},
        )
    else:
        existing = await session.scalar(
            text(
                "SELECT EXTRACT(EPOCH FROM (end_ts - start_ts)) / 60 FROM itinerary_stop "
                "WHERE trip_id = :trip_id AND destination_id = :destination_id"
            ),
            {"trip_id": trip.id, "destination_id": destination_id},
        )
        duration = int(existing) if existing else 60
        # The UI sends a wall-clock time with no offset; it means local time in the trip's city.
        start_ts = lock.start_ts if lock.start_ts.tzinfo else lock.start_ts.replace(tzinfo=tz)
        await session.execute(
            text(
                """
                INSERT INTO itinerary_stop (trip_id, day_index, seq, destination_id, start_ts, end_ts, locked)
                VALUES (:trip_id, :day_index, 999, :destination_id, :start_ts, :end_ts, true)
                ON CONFLICT (trip_id, day_index, seq)
                DO UPDATE SET destination_id = EXCLUDED.destination_id,
                              start_ts = EXCLUDED.start_ts,
                              end_ts = EXCLUDED.end_ts,
                              locked = true
                """
            ),
            {
                "trip_id": trip.id,
                "day_index": lock.day_index,
                "destination_id": destination_id,
                "start_ts": start_ts,
                "end_ts": start_ts + timedelta(minutes=duration),
            },
        )
    await session.commit()

    return await generate_itinerary(
        # Re-solve with the method that produced the current itinerary.
        payload=GenerateItineraryRequest(solver=trip.itinerary_solver or "greedy"),
        trip_and_membership=trip_and_membership,
        session=session,
    )


@router.get("/itinerary/solver-comparison", response_model=list[SolverMetricsRead])
async def compare_solvers(
    candidate_limit: int = 60,
    trip_and_membership: tuple[Trip, Membership] = Depends(get_trip_for_member),
    session: AsyncSession = Depends(get_session),
) -> list[SolverMetricsRead]:
    """Run both solvers on this trip and report each one's metrics.

    Nothing is persisted. This exists so the quality of the greedy heuristic
    can be measured against the constraint solver on real data rather than
    asserted.
    """
    trip, _ = trip_and_membership
    tz = await _timezone(session, trip.city_id)
    home = await _home_base(session, trip)
    candidates = await _load_candidates(session, trip, candidate_limit)
    if not candidates:
        return []

    locked = await _load_locked(session, trip, tz)
    member_points = await _member_points(session, trip.id)
    members = await _joined_members(session, trip.id)

    runs = compare(
        candidates,
        days=_trip_days(trip),
        day_start_minute=_minutes_since_midnight(trip.daily_start_time),
        day_end_minute=_minutes_since_midnight(trip.daily_end_time),
        home_base=home,
        travel=await _estimator(
            [home] + [candidate.location for candidate in candidates] + [stop.location for stop in locked]
        ),
        locked=locked,
    )

    metrics: list[SolverMetricsRead] = []
    for run in runs:
        scheduled = {stop.destination_id for stop in run.itinerary.stops}
        min_utility, _ = _fairness(scheduled, member_points, members)
        metrics.append(
            SolverMetricsRead(
                solver=run.solver,
                runtime_ms=run.runtime_ms,
                group_score=run.total_score,
                min_member_utility=min_utility,
                stops_scheduled=run.stops_scheduled,
                travel_min_total=run.travel_min_total,
                feasible=run.feasible,
            )
        )
    return metrics
