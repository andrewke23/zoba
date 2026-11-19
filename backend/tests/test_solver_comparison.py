from datetime import date
from uuid import UUID

import pytest

from app.services.scheduler import Candidate
from app.services.solver_comparison import compare, format_table, improvement

MONDAY = date(2026, 10, 19)
HOME = (41.5085, -81.6089)
NINE_AM = 9 * 60


def _id(tail: int) -> UUID:
    return UUID(f"00000000-0000-0000-0000-{tail:012d}")


def no_travel(origin, destination):
    return 0


def place(tail, name, score, duration=60):
    return Candidate(
        destination_id=_id(tail),
        name=name,
        score=score,
        location=HOME,
        duration_min=duration,
    )


SHARED = dict(
    days=[MONDAY],
    day_start_minute=NINE_AM,
    day_end_minute=NINE_AM + 240,
    home_base=HOME,
    travel=no_travel,
)

# Greedy takes the dense 4-hour stop and fills the day; the optimal answer is
# the three smaller stops, which together score more.
TRAP = [
    place(1, "Big", 50, duration=240),
    place(2, "B", 30, duration=120),
    place(3, "C", 30, duration=120),
]


def test_compare_runs_both_solvers():
    runs = compare(TRAP, **SHARED)
    assert [run.solver for run in runs] == ["greedy", "cpsat"]


def test_every_run_reports_its_totals():
    for run in compare(TRAP, **SHARED):
        assert run.stops_scheduled == len(run.itinerary.stops)
        assert run.total_score == pytest.approx(
            sum(stop.score for stop in run.itinerary.stops)
        )
        assert run.travel_min_total >= 0
        assert run.runtime_ms >= 0


def test_cpsat_never_scores_worse_than_greedy():
    by_name = {run.solver: run for run in compare(TRAP, **SHARED)}
    assert by_name["cpsat"].total_score >= by_name["greedy"].total_score


def test_only_cpsat_reports_an_optimality_gap():
    by_name = {run.solver: run for run in compare(TRAP, **SHARED)}
    assert by_name["greedy"].optimality_gap is None
    assert by_name["cpsat"].optimality_gap is not None


def test_improvement_is_non_negative():
    assert improvement(compare(TRAP, **SHARED)) >= 0


def test_improvement_is_zero_without_a_cpsat_run():
    runs = [run for run in compare(TRAP, **SHARED) if run.solver == "greedy"]
    assert improvement(runs) == 0.0


def test_format_table_has_a_row_per_solver():
    runs = compare(TRAP, **SHARED)
    table = format_table(runs)
    lines = table.splitlines()
    assert len(lines) == 2 + len(runs)
    assert "greedy" in table and "cpsat" in table


def test_empty_candidate_set_is_handled():
    runs = compare([], **SHARED)
    for run in runs:
        assert run.stops_scheduled == 0
        assert run.feasible is False
