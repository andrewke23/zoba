"""Greedy itinerary scheduler.

Selects a subset of candidate destinations and orders them across the days of a
trip, respecting each destination's opening hours, the travel time between
consecutive stops, and a per-day time budget.

This is the baseline solver described in the project proposal. It always
returns a feasible itinerary, which is what makes it the safety net for the
constraint-programming solver added later: CP-SAT is allowed to time out,
because this module is guaranteed to produce an answer.

The algorithm is a greedy insertion heuristic. Within each day it repeatedly
picks the feasible candidate with the highest *score density* -- the group
score divided by the total minutes that visiting it would consume (travel to
it, waiting for it to open, and the visit itself) -- and stops when nothing
else fits. Density rather than raw score matters in practice: a slightly worse
museum ten minutes away beats a marginally better one an hour across town.

Minutes are counted from local midnight on the day in question, matching the
``destination_hours`` table in ``data-pipeline/db/schema.sql``.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date
from uuid import UUID

Coordinate = tuple[float, float]
"""(latitude, longitude) in degrees."""

TravelEstimator = Callable[[Coordinate, Coordinate], int]
"""Returns whole minutes of travel between two coordinates."""

DEFAULT_VISIT_MINUTES = 60
"""Fallback when a destination has no duration prior at all."""

CATEGORY_VISIT_MINUTES: dict[str, int] = {
    "museum": 120,
    "gallery": 90,
    "park": 60,
    "viewpoint": 30,
    "landmark": 45,
    "restaurant": 75,
    "cafe": 45,
    "bar": 90,
    "market": 60,
    "shop": 45,
    "theater": 150,
    "zoo": 180,
    "aquarium": 120,
}
"""Visit-duration priors by category, used when ``est_duration_min`` is NULL.

These are deliberate guesses, not measurements. The duration model replaces
them once it has real visit data; until then they are what keeps the scheduler
from assuming every stop takes the same hour.
"""


@dataclass(frozen=True)
class OpeningWindow:
    """One continuous open period, mirroring a ``destination_hours`` row.

    ``weekday`` is 0=Monday..6=Sunday. ``close_min`` may exceed 1440 for windows
    that run past midnight, exactly as the database stores them.
    """

    weekday: int
    open_min: int
    close_min: int


@dataclass(frozen=True)
class Candidate:
    """A destination the scheduler may place, with everything it needs to decide."""

    destination_id: UUID
    name: str
    score: float
    location: Coordinate
    duration_min: int = DEFAULT_VISIT_MINUTES
    windows: tuple[OpeningWindow, ...] = ()
    """Empty means hours are unknown; the destination is treated as always open."""

    def windows_on(self, weekday: int) -> tuple[OpeningWindow, ...]:
        return tuple(window for window in self.windows if window.weekday == weekday)


@dataclass(frozen=True)
class LockedStop:
    """A stop a member pinned to a specific day and time.

    The scheduler treats these as fixed anchors and fills the gaps around them,
    which is how re-solving after a manual override works.
    """

    day_index: int
    destination_id: UUID
    name: str
    location: Coordinate
    start_minute: int
    duration_min: int
    score: float = 0.0


@dataclass(frozen=True)
class ScheduledStop:
    day_index: int
    seq: int
    destination_id: UUID
    name: str
    start_minute: int
    end_minute: int
    travel_minutes_in: int
    score: float
    locked: bool = False


@dataclass(frozen=True)
class Itinerary:
    stops: tuple[ScheduledStop, ...] = ()
    unscheduled: tuple[UUID, ...] = ()
    total_score: float = 0.0

    def stops_on(self, day_index: int) -> tuple[ScheduledStop, ...]:
        return tuple(stop for stop in self.stops if stop.day_index == day_index)


# ---------------------------------------------------------------------------
# Travel time
# ---------------------------------------------------------------------------

EARTH_RADIUS_KM = 6371.0088


def haversine_km(origin: Coordinate, destination: Coordinate) -> float:
    """Great-circle distance in kilometres."""
    lat1, lon1 = math.radians(origin[0]), math.radians(origin[1])
    lat2, lon2 = math.radians(destination[0]), math.radians(destination[1])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def straight_line_estimator(speed_kmh: float = 4.5, detour_factor: float = 1.3) -> TravelEstimator:
    """Travel-time estimator for when no routing matrix is available.

    Straight-line distance inflated by ``detour_factor`` to approximate real
    street routing. This is the stand-in until OSRM is deployed and the
    ``travel_time`` table is populated; it is good enough to keep the scheduler
    honest about geography, and wrong enough that it should not ship to users.
    """

    def estimate(origin: Coordinate, destination: Coordinate) -> int:
        km = haversine_km(origin, destination) * detour_factor
        return max(1, round(km / speed_kmh * 60))

    return estimate


def matrix_estimator(
    matrix: dict[tuple[UUID, UUID], int],
    ids_by_location: dict[Coordinate, UUID],
    fallback: TravelEstimator | None = None,
) -> TravelEstimator:
    """Estimator backed by cached ``travel_time`` rows, falling back when a pair is missing."""
    backup = fallback or straight_line_estimator()

    def estimate(origin: Coordinate, destination: Coordinate) -> int:
        origin_id = ids_by_location.get(origin)
        dest_id = ids_by_location.get(destination)
        if origin_id is not None and dest_id is not None:
            seconds = matrix.get((origin_id, dest_id))
            if seconds is not None:
                return max(1, round(seconds / 60))
        return backup(origin, destination)

    return estimate


# ---------------------------------------------------------------------------
# Scheduling
# ---------------------------------------------------------------------------


def earliest_feasible_start(
    candidate: Candidate,
    arrival_minute: int,
    latest_end_minute: int,
    weekday: int,
) -> int | None:
    """Earliest minute the visit can start, or None if it cannot happen that day."""
    if not candidate.windows:
        # No hours data at all: assume open and let the day budget decide.
        start = arrival_minute
        return start if start + candidate.duration_min <= latest_end_minute else None

    windows = candidate.windows_on(weekday)
    if not windows:
        # Hours are known and none fall on this weekday, so it is closed today.
        return None

    starts: list[int] = []
    for window in windows:
        start = max(arrival_minute, window.open_min)
        end = start + candidate.duration_min
        if end <= min(window.close_min, latest_end_minute):
            starts.append(start)
    return min(starts) if starts else None


@dataclass
class _Placement:
    candidate: Candidate
    start_minute: int
    end_minute: int
    travel_minutes: int

    @property
    def density(self) -> float:
        consumed = self.end_minute - self.start_minute + self.travel_minutes
        return self.candidate.score / consumed if consumed > 0 else 0.0


def _fill_segment(
    pool: list[Candidate],
    *,
    start_minute: int,
    end_minute: int,
    start_location: Coordinate,
    end_location: Coordinate | None,
    weekday: int,
    travel: TravelEstimator,
) -> list[_Placement]:
    """Greedily fill one open stretch of a day, left to right.

    ``end_location`` is where the traveller must be by ``end_minute`` (the next
    pinned stop). When it is None the segment simply ends at ``end_minute``.
    """
    placements: list[_Placement] = []
    cursor = start_minute
    position = start_location

    while pool:
        best: _Placement | None = None
        for candidate in pool:
            travel_minutes = travel(position, candidate.location)
            arrival = cursor + travel_minutes
            latest_end = end_minute
            if end_location is not None:
                latest_end -= travel(candidate.location, end_location)
            start = earliest_feasible_start(candidate, arrival, latest_end, weekday)
            if start is None:
                continue
            placement = _Placement(
                candidate=candidate,
                start_minute=start,
                end_minute=start + candidate.duration_min,
                travel_minutes=travel_minutes,
            )
            if best is None or _better(placement, best):
                best = placement

        if best is None:
            break

        placements.append(best)
        pool.remove(best.candidate)
        cursor = best.end_minute
        position = best.candidate.location

    return placements


def _better(challenger: _Placement, incumbent: _Placement) -> bool:
    """Higher density wins; ties break deterministically so runs are reproducible."""
    if challenger.density != incumbent.density:
        return challenger.density > incumbent.density
    challenger_key = (challenger.candidate.name, str(challenger.candidate.destination_id))
    incumbent_key = (incumbent.candidate.name, str(incumbent.candidate.destination_id))
    return challenger_key < incumbent_key


def schedule_trip(
    candidates: Iterable[Candidate],
    *,
    days: Sequence[date],
    day_start_minute: int,
    day_end_minute: int,
    home_base: Coordinate,
    travel: TravelEstimator | None = None,
    locked: Iterable[LockedStop] = (),
) -> Itinerary:
    """Build a feasible multi-day itinerary from scored candidates.

    Args:
        candidates: destinations in play, each already carrying a group score.
        days: the trip's dates, in order; index i becomes ``day_index`` i.
        day_start_minute: when the group starts each day, from local midnight.
        day_end_minute: when the group stops each day.
        home_base: where each day starts (the hotel).
        travel: travel-time estimator; defaults to straight-line walking.
        locked: stops a member pinned, which anchor their day.

    Returns:
        An Itinerary whose stops are ordered by (day_index, seq).
    """
    if day_end_minute <= day_start_minute:
        raise ValueError("day_end_minute must be after day_start_minute")

    estimator = travel or straight_line_estimator()
    pool = sorted(candidates, key=lambda c: (-c.score, c.name, str(c.destination_id)))
    locked_stops = sorted(locked, key=lambda s: (s.day_index, s.start_minute))

    pinned_ids = {stop.destination_id for stop in locked_stops}
    pool = [candidate for candidate in pool if candidate.destination_id not in pinned_ids]

    stops: list[ScheduledStop] = []

    for day_index, day in enumerate(days):
        weekday = day.weekday()
        anchors = [stop for stop in locked_stops if stop.day_index == day_index]

        cursor = day_start_minute
        position = home_base
        seq = 0

        for anchor in anchors:
            placements = _fill_segment(
                pool,
                start_minute=cursor,
                end_minute=anchor.start_minute,
                start_location=position,
                end_location=anchor.location,
                weekday=weekday,
                travel=estimator,
            )
            for placement in placements:
                stops.append(_to_stop(placement, day_index, seq))
                seq += 1

            anchor_end = anchor.start_minute + anchor.duration_min
            stops.append(
                ScheduledStop(
                    day_index=day_index,
                    seq=seq,
                    destination_id=anchor.destination_id,
                    name=anchor.name,
                    start_minute=anchor.start_minute,
                    end_minute=anchor_end,
                    travel_minutes_in=estimator(position, anchor.location),
                    score=anchor.score,
                    locked=True,
                )
            )
            seq += 1
            cursor = anchor_end
            position = anchor.location

        for placement in _fill_segment(
            pool,
            start_minute=cursor,
            end_minute=day_end_minute,
            start_location=position,
            end_location=None,
            weekday=weekday,
            travel=estimator,
        ):
            stops.append(_to_stop(placement, day_index, seq))
            seq += 1

    return Itinerary(
        stops=tuple(stops),
        unscheduled=tuple(candidate.destination_id for candidate in pool),
        total_score=sum(stop.score for stop in stops),
    )


def _to_stop(placement: _Placement, day_index: int, seq: int) -> ScheduledStop:
    return ScheduledStop(
        day_index=day_index,
        seq=seq,
        destination_id=placement.candidate.destination_id,
        name=placement.candidate.name,
        start_minute=placement.start_minute,
        end_minute=placement.end_minute,
        travel_minutes_in=placement.travel_minutes,
        score=placement.candidate.score,
    )


def visit_minutes(est_duration_min: int | None, category: str | None) -> int:
    """Resolve a visit duration from the destination row, then category, then default."""
    if est_duration_min and est_duration_min > 0:
        return est_duration_min
    if category:
        return CATEGORY_VISIT_MINUTES.get(category.lower(), DEFAULT_VISIT_MINUTES)
    return DEFAULT_VISIT_MINUTES
