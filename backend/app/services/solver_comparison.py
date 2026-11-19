"""Run both solvers on identical input and report how they differ.

The proposal commits to building a greedy heuristic and a constraint solver
and comparing them. This module is that comparison: one function, same
candidates, same constraints, same objective, two answers.

What the numbers mean:
  total_score     collected group utility — higher is better
  stops_scheduled how many destinations made the trip
  travel_min_total minutes spent moving; lower is better for the same score
  runtime_ms      wall clock
  optimality_gap  CP-SAT only. How far the answer could still be from the
                  true optimum. 0.0 means proved optimal — which is the thing
                  the greedy heuristic structurally cannot tell you.
"""

from __future__ import annotations

import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date

from app.services.scheduler import (
    Candidate,
    Coordinate,
    Itinerary,
    LockedStop,
    TravelEstimator,
    schedule_trip,
)
from app.services.scheduler_cpsat import SolverUnavailable, solve_trip


@dataclass(frozen=True)
class SolverRun:
    solver: str
    itinerary: Itinerary
    runtime_ms: int
    feasible: bool
    status: str | None = None
    optimality_gap: float | None = None

    @property
    def total_score(self) -> float:
        return self.itinerary.total_score

    @property
    def stops_scheduled(self) -> int:
        return len(self.itinerary.stops)

    @property
    def travel_min_total(self) -> int:
        return sum(stop.travel_minutes_in for stop in self.itinerary.stops)


def run_greedy(
    candidates: Sequence[Candidate],
    *,
    days: Sequence[date],
    day_start_minute: int,
    day_end_minute: int,
    home_base: Coordinate,
    travel: TravelEstimator | None = None,
    locked: Iterable[LockedStop] = (),
) -> SolverRun:
    started = time.perf_counter()
    itinerary = schedule_trip(
        candidates,
        days=days,
        day_start_minute=day_start_minute,
        day_end_minute=day_end_minute,
        home_base=home_base,
        travel=travel,
        locked=locked,
    )
    elapsed = int((time.perf_counter() - started) * 1000)
    return SolverRun(
        solver="greedy",
        itinerary=itinerary,
        runtime_ms=elapsed,
        feasible=bool(itinerary.stops),
        status="HEURISTIC",
    )


def run_cpsat(
    candidates: Sequence[Candidate],
    *,
    days: Sequence[date],
    day_start_minute: int,
    day_end_minute: int,
    home_base: Coordinate,
    travel: TravelEstimator | None = None,
    locked: Iterable[LockedStop] = (),
    time_limit_seconds: float = 10.0,
) -> SolverRun:
    started = time.perf_counter()
    result = solve_trip(
        candidates,
        days=days,
        day_start_minute=day_start_minute,
        day_end_minute=day_end_minute,
        home_base=home_base,
        travel=travel,
        locked=locked,
        time_limit_seconds=time_limit_seconds,
    )
    elapsed = int((time.perf_counter() - started) * 1000)
    return SolverRun(
        solver="cpsat",
        itinerary=result.itinerary,
        runtime_ms=elapsed,
        feasible=bool(result.itinerary.stops),
        status=result.status,
        optimality_gap=result.optimality_gap,
    )


def compare(
    candidates: Sequence[Candidate],
    *,
    days: Sequence[date],
    day_start_minute: int,
    day_end_minute: int,
    home_base: Coordinate,
    travel: TravelEstimator | None = None,
    locked: Iterable[LockedStop] = (),
    time_limit_seconds: float = 10.0,
) -> list[SolverRun]:
    """Both solvers, same input. Greedy always runs; CP-SAT is skipped if absent."""
    shared = dict(
        days=days,
        day_start_minute=day_start_minute,
        day_end_minute=day_end_minute,
        home_base=home_base,
        travel=travel,
        locked=locked,
    )
    runs = [run_greedy(candidates, **shared)]
    try:
        runs.append(run_cpsat(candidates, time_limit_seconds=time_limit_seconds, **shared))
    except SolverUnavailable:
        pass
    return runs


def improvement(runs: Sequence[SolverRun]) -> float:
    """CP-SAT's score advantage over greedy, as a percentage. 0.0 if greedy tied."""
    by_name = {run.solver: run for run in runs}
    greedy, cpsat = by_name.get("greedy"), by_name.get("cpsat")
    if not greedy or not cpsat or greedy.total_score <= 0:
        return 0.0
    return (cpsat.total_score - greedy.total_score) / greedy.total_score * 100


def format_table(runs: Sequence[SolverRun]) -> str:
    """Markdown table, ready to paste into the report."""
    header = (
        "| solver | score | stops | travel (min) | runtime (ms) | status | gap |\n"
        "|---|---|---|---|---|---|---|"
    )
    rows = []
    for run in runs:
        gap = "—" if run.optimality_gap is None else f"{run.optimality_gap * 100:.2f}%"
        rows.append(
            f"| {run.solver} | {run.total_score:.1f} | {run.stops_scheduled} "
            f"| {run.travel_min_total} | {run.runtime_ms} | {run.status} | {gap} |"
        )
    return "\n".join([header, *rows])
