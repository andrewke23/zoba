"""Constraint-programming itinerary solver, built on OR-Tools CP-SAT.

This is the second of the two solvers promised in the project proposal. The
greedy heuristic in ``scheduler.py`` always returns something feasible fast;
this one searches far more of the space and reports how good its answer is,
but can time out. Both expose the same signature and return the same
``Itinerary``, so ``solver_comparison.py`` can run them head to head on
identical input.

MODEL
-----
The problem is a Team Orienteering Problem with Time Windows: choose a subset
of destinations and sequence them across D days, maximising collected score,
subject to opening hours, travel time between consecutive stops, and a daily
time budget.

Each day is modelled as a circuit over (home base + every candidate). A
node that is "self-looped" is simply not visited that day, which is the
standard CP-SAT trick for optional nodes. Arc literals carry the time
propagation: if the tour goes i -> j, then j cannot start until i has
finished and the traveller has crossed the distance.

A destination may be visited at most once across the whole trip, so the
per-day visit booleans for one destination sum to at most one.

FAIRNESS
--------
Fairness is not a constraint here. It enters upstream: the scores handed to
the solver are already the regret-bounded group utility computed in
``api/itinerary.py``. Keeping the objective identical to the greedy
solver's is what makes the comparison between them meaningful — the two
solvers optimise the same thing, so any difference is search quality, not a
different goal.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from uuid import UUID

from app.services.scheduler import (
    Candidate,
    Coordinate,
    Itinerary,
    LockedStop,
    ScheduledStop,
    TravelEstimator,
    straight_line_estimator,
)

SCORE_SCALE = 1000
"""CP-SAT is integral; scores are floats. Scale, round, and divide back out."""

DEFAULT_TIME_LIMIT_SECONDS = 10.0


class SolverUnavailable(RuntimeError):
    """Raised when OR-Tools is not installed in this environment."""


@dataclass(frozen=True)
class CpSatResult:
    """An itinerary plus what the solver itself reported about the search."""

    itinerary: Itinerary
    status: str
    objective: float
    best_bound: float
    wall_time_s: float

    @property
    def is_optimal(self) -> bool:
        return self.status == "OPTIMAL"

    @property
    def optimality_gap(self) -> float:
        """How far the answer could still be from the true optimum, as a fraction.

        Zero means proved optimal. This is the number that justifies the
        solver existing: the greedy heuristic cannot tell you how good its
        answer is, and this one can.
        """
        if self.objective <= 0:
            return 0.0 if self.best_bound <= 0 else 1.0
        return max(0.0, (self.best_bound - self.objective) / self.objective)


def _require_ortools():
    try:
        from ortools.sat.python import cp_model
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise SolverUnavailable(
            "OR-Tools is not installed. Add 'ortools' to backend/requirements.txt "
            "and reinstall, or use solver='greedy'."
        ) from exc
    return cp_model


def _travel_matrix(
    home: Coordinate, candidates: Sequence[Candidate], travel: TravelEstimator
) -> list[list[int]]:
    """Minutes between every pair. Index 0 is home base, 1..n are candidates."""
    points: list[Coordinate] = [home] + [c.location for c in candidates]
    size = len(points)
    matrix = [[0] * size for _ in range(size)]
    for i in range(size):
        for j in range(size):
            if i != j:
                matrix[i][j] = travel(points[i], points[j])
    return matrix


def solve_trip(
    candidates: Iterable[Candidate],
    *,
    days: Sequence[date],
    day_start_minute: int,
    day_end_minute: int,
    home_base: Coordinate,
    travel: TravelEstimator | None = None,
    locked: Iterable[LockedStop] = (),
    time_limit_seconds: float = DEFAULT_TIME_LIMIT_SECONDS,
    workers: int = 8,
) -> CpSatResult:
    """Build an itinerary with CP-SAT. Same inputs as ``schedule_trip``."""
    cp_model = _require_ortools()

    if day_end_minute <= day_start_minute:
        raise ValueError("day_end_minute must be after day_start_minute")

    estimator = travel or straight_line_estimator()
    locked_stops = list(locked)
    pinned = {stop.destination_id for stop in locked_stops}

    pool = [c for c in candidates if c.destination_id not in pinned]
    pool.sort(key=lambda c: (-c.score, c.name, str(c.destination_id)))

    if not pool and not locked_stops:
        return CpSatResult(Itinerary(), "OPTIMAL", 0.0, 0.0, 0.0)

    n = len(pool)
    n_days = len(days)
    matrix = _travel_matrix(home_base, pool, estimator)

    model = cp_model.CpModel()

    # visit[d][i] - candidate i is visited on day d
    visit = [[model.NewBoolVar(f"v_{d}_{i}") for i in range(n)] for d in range(n_days)]
    # start[d][i] - start minute (local midnight) on that day
    start = [
        [model.NewIntVar(day_start_minute, day_end_minute, f"s_{d}_{i}") for i in range(n)]
        for d in range(n_days)
    ]

    for d, day in enumerate(days):
        weekday = day.weekday()
        arcs = []
        # Depot self-loop lets a day be empty.
        depot_unused = model.NewBoolVar(f"depot_unused_{d}")
        arcs.append((0, 0, depot_unused))

        for i, candidate in enumerate(pool):
            node = i + 1
            arcs.append((node, node, visit[d][i].Not()))

            duration = candidate.duration_min
            windows = candidate.windows_on(weekday)

            if not candidate.windows:
                # Hours unknown: anywhere inside the day is allowed.
                model.Add(start[d][i] + duration <= day_end_minute).OnlyEnforceIf(visit[d][i])
            elif not windows:
                # Hours known and none today: the place is closed.
                model.Add(visit[d][i] == 0)
            else:
                picks = []
                for k, window in enumerate(windows):
                    low = max(day_start_minute, window.open_min)
                    high = min(day_end_minute, window.close_min)
                    if high - low < duration:
                        continue
                    pick = model.NewBoolVar(f"w_{d}_{i}_{k}")
                    model.Add(start[d][i] >= low).OnlyEnforceIf(pick)
                    model.Add(start[d][i] + duration <= high).OnlyEnforceIf(pick)
                    picks.append(pick)
                if not picks:
                    model.Add(visit[d][i] == 0)
                else:
                    model.Add(sum(picks) == 1).OnlyEnforceIf(visit[d][i])
                    model.Add(sum(picks) == 0).OnlyEnforceIf(visit[d][i].Not())

            # Leaving home base for the first stop of the day.
            first = model.NewBoolVar(f"first_{d}_{i}")
            arcs.append((0, node, first))
            model.Add(start[d][i] >= day_start_minute + matrix[0][node]).OnlyEnforceIf(first)
            model.AddImplication(first, visit[d][i])

            # Ending the day after this stop.
            last = model.NewBoolVar(f"last_{d}_{i}")
            arcs.append((node, 0, last))
            model.AddImplication(last, visit[d][i])

        # Travel time between consecutive stops.
        for i in range(n):
            for j in range(n):
                if i == j:
                    continue
                arc = model.NewBoolVar(f"a_{d}_{i}_{j}")
                arcs.append((i + 1, j + 1, arc))
                model.Add(
                    start[d][j] >= start[d][i] + pool[i].duration_min + matrix[i + 1][j + 1]
                ).OnlyEnforceIf(arc)
                model.AddImplication(arc, visit[d][i])
                model.AddImplication(arc, visit[d][j])

        model.AddCircuit(arcs)

        # An empty day means nothing is visited that day.
        for i in range(n):
            model.AddImplication(depot_unused, visit[d][i].Not())

    # Each destination at most once across the whole trip.
    for i in range(n):
        model.Add(sum(visit[d][i] for d in range(n_days)) <= 1)

    # Pinned stops occupy their slot; nothing else may overlap them.
    for stop in locked_stops:
        if not 0 <= stop.day_index < n_days:
            continue
        busy_from = stop.start_minute
        busy_to = stop.start_minute + stop.duration_min
        for i, candidate in enumerate(pool):
            before = model.NewBoolVar(f"pre_{stop.day_index}_{i}")
            model.Add(start[stop.day_index][i] + candidate.duration_min <= busy_from).OnlyEnforceIf(before)
            model.Add(start[stop.day_index][i] >= busy_to).OnlyEnforceIf(before.Not())

    model.Maximize(
        sum(
            int(round(pool[i].score * SCORE_SCALE)) * visit[d][i]
            for d in range(n_days)
            for i in range(n)
        )
    )

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_seconds
    solver.parameters.num_search_workers = workers
    status = solver.Solve(model)

    status_name = solver.StatusName(status)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return CpSatResult(Itinerary(), status_name, 0.0, 0.0, solver.WallTime())

    stops: list[ScheduledStop] = []
    for d in range(n_days):
        placed = [
            (solver.Value(start[d][i]), i)
            for i in range(n)
            if solver.Value(visit[d][i])
        ]
        placed.sort()
        for stop in sorted(
            (s for s in locked_stops if s.day_index == d), key=lambda s: s.start_minute
        ):
            placed.append((stop.start_minute, -1))
        placed.sort()

        previous: Coordinate = home_base
        seq = 0
        for start_minute, index in placed:
            if index == -1:
                anchor = next(
                    s
                    for s in locked_stops
                    if s.day_index == d and s.start_minute == start_minute
                )
                stops.append(
                    ScheduledStop(
                        day_index=d,
                        seq=seq,
                        destination_id=anchor.destination_id,
                        name=anchor.name,
                        start_minute=anchor.start_minute,
                        end_minute=anchor.start_minute + anchor.duration_min,
                        travel_minutes_in=estimator(previous, anchor.location),
                        score=anchor.score,
                        locked=True,
                    )
                )
                previous = anchor.location
            else:
                candidate = pool[index]
                stops.append(
                    ScheduledStop(
                        day_index=d,
                        seq=seq,
                        destination_id=candidate.destination_id,
                        name=candidate.name,
                        start_minute=start_minute,
                        end_minute=start_minute + candidate.duration_min,
                        travel_minutes_in=estimator(previous, candidate.location),
                        score=candidate.score,
                    )
                )
                previous = candidate.location
            seq += 1

    scheduled_ids = {stop.destination_id for stop in stops}
    itinerary = Itinerary(
        stops=tuple(stops),
        unscheduled=tuple(c.destination_id for c in pool if c.destination_id not in scheduled_ids),
        total_score=sum(stop.score for stop in stops),
    )

    return CpSatResult(
        itinerary=itinerary,
        status=status_name,
        objective=solver.ObjectiveValue() / SCORE_SCALE,
        best_bound=solver.BestObjectiveBound() / SCORE_SCALE,
        wall_time_s=solver.WallTime(),
    )


def schedule_trip_cpsat(
    candidates: Iterable[Candidate],
    *,
    days: Sequence[date],
    day_start_minute: int,
    day_end_minute: int,
    home_base: Coordinate,
    travel: TravelEstimator | None = None,
    locked: Iterable[LockedStop] = (),
    time_limit_seconds: float = DEFAULT_TIME_LIMIT_SECONDS,
) -> Itinerary:
    """Drop-in replacement for ``schedule_trip`` that discards solver detail."""
    return solve_trip(
        candidates,
        days=days,
        day_start_minute=day_start_minute,
        day_end_minute=day_end_minute,
        home_base=home_base,
        travel=travel,
        locked=locked,
        time_limit_seconds=time_limit_seconds,
    ).itinerary
