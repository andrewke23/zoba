"""Itinerary generation endpoints.

Loads scored candidates for a trip, runs the scheduler, persists the result to
``itinerary_stop``, and returns it in the shape `frontend/src/api/types.ts`
expects.

Scores come from ``app.services.preference.compute_ranking``: Bradley-Terry
fits over each member's comparisons, blended with their capped point
allocations, then combined into a fairness-aware group score (mean and
worst-off member, weighted equally) with hard-no vetoes excluded entirely.
The scheduler does not care where a score came from, so this module is the
only place that needed to change when the raw-points placeholder was replaced.
"""

import json
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
    SolverMetricsRead,
    TopPickStatusRead,
    UnscheduledRead,
)
from app.services.preference import ComparisonInput, PreferenceInput, RankingResult, compute_ranking
from app.services.scheduler import (
    Candidate,
    LockedStop,
    OpeningWindow,
    haversine_km,
    schedule_trip,
    straight_line_estimator,
    visit_minutes,
)

router = APIRouter(prefix="/trips/{trip_id}")

TRAVEL_MODE = "walk"
"""Only walking is estimated today. Real OSRM routing adds drive and transit."""

# When an itinerary was generated is not yet a column on itinerary_stop, so it
# is remembered per process. Reads after a restart report the read time. Replace
# with a stored column when the schema next changes.
_GENERATED_AT: dict[UUID, datetime] = {}

_DESTINATIONS_SQL = text(
    """
    SELECT d.destination_id,
           d.name,
           d.category,
           d.est_duration_min,
           ST_Y(d.geom::geometry) AS latitude,
           ST_X(d.geom::geometry) AS longitude,
           COALESCE(h.windows, '[]'::json) AS windows
    FROM destination d
    LEFT JOIN (
        SELECT destination_id,
               json_agg(json_build_object('weekday', weekday, 'open_min', open_min, 'close_min', close_min)) AS windows
        FROM destination_hours
        GROUP BY destination_id
    ) h ON h.destination_id = d.destination_id
    WHERE d.city_id = :city_id
    """
)

_PREFERENCES_SQL = text(
    "SELECT user_id, destination_id, points, hard_no FROM preference WHERE trip_id = :trip_id"
)

_COMPARISONS_SQL = text("SELECT user_id, dest_a, dest_b, chosen FROM comparison WHERE trip_id = :trip_id")

_MEMBERS_SQL = text("SELECT user_id FROM membership WHERE trip_id = :trip_id AND status = 'joined'")

_STOPS_SQL = text(
    """
    SELECT s.day_index, s.seq, s.destination_id, s.start_ts, s.end_ts, s.locked, d.name,
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


async def _joined_members(session: AsyncSession, trip_id: UUID) -> list[UUID]:
    rows = await session.execute(_MEMBERS_SQL, {"trip_id": trip_id})
    return [row[0] for row in rows.all()]


async def _load_ranking(session: AsyncSession, trip: Trip) -> RankingResult:
    """Fairness-aware group ranking (F06, F08a) over every destination in the trip's city.

    Scoring lives in ``app.services.preference``; this just gathers the rows it
    needs (destinations, joined members, point allocations, pairwise
    comparisons) and hands them over.
    """
    destination_rows = (await session.execute(_DESTINATIONS_SQL, {"city_id": trip.city_id})).mappings().all()
    destination_ids = [row["destination_id"] for row in destination_rows]
    members = await _joined_members(session, trip.id)

    pref_rows = (await session.execute(_PREFERENCES_SQL, {"trip_id": trip.id})).mappings().all()
    prefs = [
        PreferenceInput(
            user_id=row["user_id"],
            destination_id=row["destination_id"],
            points=row["points"] or 0,
            hard_no=row["hard_no"],
        )
        for row in pref_rows
    ]

    comp_rows = (await session.execute(_COMPARISONS_SQL, {"trip_id": trip.id})).mappings().all()
    comps = [
        ComparisonInput(user_id=row["user_id"], dest_a=row["dest_a"], dest_b=row["dest_b"], chosen=row["chosen"])
        for row in comp_rows
    ]

    return compute_ranking(destination_ids, members, prefs, comps)


async def _load_candidates(session: AsyncSession, trip: Trip, limit: int) -> list[Candidate]:
    destination_rows = (await session.execute(_DESTINATIONS_SQL, {"city_id": trip.city_id})).mappings().all()
    ranking = await _load_ranking(session, trip)
    scores = {row.destination_id: row.group_score for row in ranking.rows}

    candidates = [
        Candidate(
            destination_id=row["destination_id"],
            name=row["name"],
            score=scores.get(row["destination_id"], 0.0),
            location=(float(row["latitude"]), float(row["longitude"])),
            duration_min=visit_minutes(row["est_duration_min"], row["category"]),
            windows=_parse_windows(row["windows"]),
        )
        for row in destination_rows
        if row["destination_id"] not in ranking.vetoed
    ]
    candidates.sort(key=lambda c: c.score, reverse=True)
    return candidates[:limit]


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
    ranking: RankingResult,
    members: list[UUID],
) -> tuple[float, list[TopPickStatusRead]]:
    """Worst individual outcome, plus whether each member's favourite made the trip.

    "Outcome" is the share of a member's normalized Bradley-Terry/points
    utility (``app.services.preference.compute_ranking``) that ended up
    scheduled, not raw points -- so a member who only did pairwise comparisons
    is weighed the same as one who only spent their point budget. The minimum
    across members is what the regret-bounded objective in the proposal
    protects. Reporting it every run is how we tell whether fairness is
    actually working rather than asserting it in a report.
    """
    utilities: list[float] = []
    top_picks: list[TopPickStatusRead] = []

    for user_id in members:
        destination_utility = ranking.utility.get(user_id)
        if not destination_utility:
            utilities.append(0.0)
            top_picks.append(
                TopPickStatusRead(
                    user_id=user_id, destination_id=None, included=False, reason="No preferences submitted"
                )
            )
            continue

        total = sum(destination_utility.values())
        earned = sum(value for dest, value in destination_utility.items() if dest in scheduled_ids)
        utilities.append(earned / total if total else 0.0)

        favourite = ranking.top_picks.get(user_id)
        included = favourite in scheduled_ids if favourite else False
        top_picks.append(
            TopPickStatusRead(
                user_id=user_id,
                destination_id=favourite,
                included=included,
                reason=None if included else "Did not fit the schedule",
            )
        )

    return (min(utilities) if utilities else 0.0), top_picks


async def _read_itinerary(
    session: AsyncSession, trip: Trip, solver: str = "greedy"
) -> ItineraryRead | None:
    """Rebuild the response from persisted stops."""
    tz = await _timezone(session, trip.city_id)
    rows = (await session.execute(_STOPS_SQL, {"trip_id": trip.id})).mappings().all()
    if not rows:
        return None

    days = _trip_days(trip)
    home = await _home_base(session, trip)
    estimate = straight_line_estimator()

    by_day: dict[int, list[ItineraryStopRead]] = defaultdict(list)
    travel_total = 0
    previous_location: dict[int, tuple[float, float]] = {}

    for row in rows:
        day_index = row["day_index"]
        here = (float(row["latitude"]), float(row["longitude"]))
        origin = previous_location.get(day_index, home)
        travel = estimate(origin, here)
        travel_total += travel
        previous_location[day_index] = here
        by_day[day_index].append(
            ItineraryStopRead(
                trip_id=trip.id,
                day_index=day_index,
                seq=row["seq"],
                destination_id=row["destination_id"],
                start_ts=row["start_ts"],
                end_ts=row["end_ts"],
                locked=row["locked"],
                travel_min_from_prev=travel,
                travel_mode_from_prev=TRAVEL_MODE,
            )
        )

    scheduled_ids = {row["destination_id"] for row in rows}
    ranking = await _load_ranking(session, trip)
    members = await _joined_members(session, trip.id)
    min_utility, top_picks = _fairness(scheduled_ids, ranking, members)
    group_score = sum(row.group_score for row in ranking.rows if row.destination_id in scheduled_ids)

    return ItineraryRead(
        trip_id=trip.id,
        solver=solver,
        generated_at=_GENERATED_AT.get(trip.id, datetime.now(timezone.utc)),
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

    if options.solver == "cpsat":
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="The CP-SAT solver is not implemented yet. Use solver='greedy'.",
        )

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

    started = time.perf_counter()
    itinerary = schedule_trip(
        candidates,
        days=days,
        day_start_minute=_minutes_since_midnight(trip.daily_start_time),
        day_end_minute=_minutes_since_midnight(trip.daily_end_time),
        home_base=home,
        travel=straight_line_estimator(),
        locked=locked,
    )
    runtime_ms = int((time.perf_counter() - started) * 1000)

    await session.execute(delete(ItineraryStop).where(ItineraryStop.trip_id == trip.id))
    for stop in itinerary.stops:
        session.add(
            ItineraryStop(
                trip_id=trip.id,
                day_index=stop.day_index,
                seq=stop.seq,
                destination_id=stop.destination_id,
                start_ts=_to_timestamp(days[stop.day_index], stop.start_minute, tz),
                end_ts=_to_timestamp(days[stop.day_index], stop.end_minute, tz),
                locked=stop.locked,
            )
        )
    await session.commit()
    _GENERATED_AT[trip.id] = datetime.now(timezone.utc)

    response = await _read_itinerary(session, trip, solver=options.solver)
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
                "start_ts": lock.start_ts,
                "end_ts": lock.start_ts + timedelta(minutes=duration),
            },
        )
    await session.commit()

    return await generate_itinerary(
        payload=GenerateItineraryRequest(),
        trip_and_membership=trip_and_membership,
        session=session,
    )


@router.get("/itinerary/solver-comparison", response_model=list[SolverMetricsRead])
async def compare_solvers(
    trip_and_membership: tuple[Trip, Membership] = Depends(get_trip_for_member),
    session: AsyncSession = Depends(get_session),
) -> list[SolverMetricsRead]:
    """Metrics per solver. Only greedy exists today; CP-SAT joins this list in November."""
    trip, _ = trip_and_membership
    itinerary = await _read_itinerary(session, trip)
    return [itinerary.metrics] if itinerary else []
