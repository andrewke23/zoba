from datetime import date
from uuid import UUID

import pytest

from app.services.scheduler import Candidate, LockedStop, OpeningWindow, schedule_trip
from app.services.scheduler_cpsat import solve_trip

MONDAY = date(2026, 10, 19)
TUESDAY = date(2026, 10, 20)
HOME = (41.5085, -81.6089)
NINE_AM = 9 * 60
SIX_PM = 18 * 60


def _id(tail: int) -> UUID:
    return UUID(f"00000000-0000-0000-0000-{tail:012d}")


def no_travel(origin, destination):
    return 0


def place(tail, name, score, duration=60, *, location=HOME, windows=()):
    return Candidate(
        destination_id=_id(tail),
        name=name,
        score=score,
        location=location,
        duration_min=duration,
        windows=windows,
    )


def solve(candidates, days=(MONDAY,), start=NINE_AM, end=SIX_PM, travel=no_travel, locked=()):
    return solve_trip(
        candidates,
        days=list(days),
        day_start_minute=start,
        day_end_minute=end,
        home_base=HOME,
        travel=travel,
        locked=locked,
    )


def test_no_candidates_returns_empty_itinerary():
    result = solve([])
    assert result.itinerary.stops == ()
    assert result.is_optimal


def test_day_end_before_day_start_is_rejected():
    with pytest.raises(ValueError):
        solve([place(1, "A", 10)], start=SIX_PM, end=NINE_AM)


def test_stops_do_not_overlap_and_are_sequential():
    result = solve([place(i, f"P{i}", 10) for i in range(1, 5)])
    stops = result.itinerary.stops_on(0)
    assert [s.seq for s in stops] == list(range(len(stops)))
    for earlier, later in zip(stops, stops[1:]):
        assert later.start_minute >= earlier.end_minute


def test_day_budget_is_respected():
    # Four two-hour visits cannot fit a six-hour day.
    result = solve([place(i, f"P{i}", 10, duration=120) for i in range(1, 5)], end=NINE_AM + 360)
    assert len(result.itinerary.stops) == 3
    assert max(s.end_minute for s in result.itinerary.stops) <= NINE_AM + 360


def test_closed_on_that_weekday_is_not_scheduled():
    tuesday_only = place(1, "Closed Mondays", 50, windows=(OpeningWindow(1, 600, 1020),))
    result = solve([tuesday_only])
    assert result.itinerary.stops == ()


def test_visit_waits_for_opening_time():
    late = place(1, "Late", 50, windows=(OpeningWindow(0, 660, 1020),))
    result = solve([late])
    assert result.itinerary.stops[0].start_minute >= 660


def test_travel_time_is_enforced_between_stops():
    far = (41.9, -87.6)  # ~500 km away
    from app.services.scheduler import straight_line_estimator

    result = solve(
        [place(1, "Near", 10), place(2, "Far", 10, location=far)],
        travel=straight_line_estimator(),
    )
    names = {s.name for s in result.itinerary.stops}
    assert "Far" not in names


def test_work_spreads_across_multiple_days():
    result = solve(
        [place(i, f"P{i}", 10, duration=120) for i in range(1, 7)],
        days=(MONDAY, TUESDAY),
        end=NINE_AM + 360,
    )
    assert len(result.itinerary.stops_on(0)) == 3
    assert len(result.itinerary.stops_on(1)) == 3


def test_a_destination_is_never_visited_twice():
    result = solve(
        [place(i, f"P{i}", 10) for i in range(1, 4)],
        days=(MONDAY, TUESDAY),
    )
    ids = [s.destination_id for s in result.itinerary.stops]
    assert len(ids) == len(set(ids))


def test_locked_stop_is_included_and_nothing_overlaps_it():
    locked = LockedStop(
        day_index=0,
        destination_id=_id(99),
        name="Pinned",
        location=HOME,
        start_minute=13 * 60,
        duration_min=60,
    )
    result = solve([place(i, f"P{i}", 10) for i in range(1, 6)], locked=[locked])
    pinned = [s for s in result.itinerary.stops if s.locked]
    assert len(pinned) == 1
    for stop in result.itinerary.stops:
        if not stop.locked:
            assert stop.end_minute <= 13 * 60 or stop.start_minute >= 14 * 60


def test_prefers_higher_total_score_when_only_one_fits():
    # Only one 5-hour visit fits a 6-hour day; it should take the better one.
    result = solve(
        [place(1, "Low", 10, duration=300), place(2, "High", 90, duration=300)],
        end=NINE_AM + 360,
    )
    assert [s.name for s in result.itinerary.stops] == ["High"]


def test_cpsat_is_at_least_as_good_as_greedy():
    """The whole point of the second solver: it should never score worse.

    Greedy commits to the best-looking stop at each step; CP-SAT searches
    combinations. On the same input with the same objective, CP-SAT's total
    must be >= greedy's, and this test is what lets the report claim that
    rather than assume it.
    """
    candidates = [
        place(1, "A", 50, duration=240),
        place(2, "B", 30, duration=120),
        place(3, "C", 30, duration=120),
        place(4, "D", 25, duration=120),
    ]
    kwargs = dict(
        days=[MONDAY],
        day_start_minute=NINE_AM,
        day_end_minute=NINE_AM + 240,
        home_base=HOME,
        travel=no_travel,
    )
    greedy = schedule_trip(candidates, **kwargs)
    optimal = solve_trip(candidates, **kwargs)
    assert optimal.itinerary.total_score >= greedy.total_score


def test_reports_optimality_gap():
    result = solve([place(i, f"P{i}", 10 + i) for i in range(1, 5)])
    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert result.optimality_gap >= 0
    if result.is_optimal:
        assert result.optimality_gap == pytest.approx(0.0, abs=1e-6)


def test_objective_matches_scheduled_score():
    candidates = [place(1, "A", 12.5), place(2, "B", 7.5)]
    result = solve(candidates)
    assert result.objective == pytest.approx(result.itinerary.total_score, abs=0.01)


def test_warm_start_never_loses_to_greedy_at_scale():
    """Regression test for the cold-start failure found in the Nov benchmark.

    Without the greedy hint, CP-SAT spent its entire time budget on 40+
    candidate instances and returned a *worse* itinerary than the heuristic
    it was supposed to improve on. The hint makes greedy's answer the search's
    floor, so this must hold at any instance size.
    """
    candidates = [
        place(
            i,
            f"P{i}",
            score=1.0 + (i % 7),
            duration=45 + (i % 4) * 15,
            location=(41.50 + (i % 9) * 0.01, -81.60 + (i % 11) * 0.01),
        )
        for i in range(1, 41)
    ]
    from app.services.scheduler import straight_line_estimator

    kwargs = dict(
        days=[MONDAY, TUESDAY],
        day_start_minute=NINE_AM,
        day_end_minute=SIX_PM,
        home_base=HOME,
        travel=straight_line_estimator(),
    )
    greedy = schedule_trip(candidates, **kwargs)
    warm = solve_trip(candidates, **kwargs, time_limit_seconds=3.0, warm_start=True)

    assert warm.itinerary.total_score >= greedy.total_score


def test_warm_start_hint_produces_a_feasible_itinerary():
    """A bad hint is silently dropped by CP-SAT, which would hide a broken
    seed. Assert the warm-started answer is actually schedulable."""
    candidates = [place(i, f"P{i}", score=float(i), duration=60) for i in range(1, 13)]
    kwargs = dict(
        days=[MONDAY],
        day_start_minute=NINE_AM,
        day_end_minute=SIX_PM,
        home_base=HOME,
        travel=no_travel,
    )
    result = solve_trip(candidates, **kwargs, warm_start=True)

    assert result.status in ("OPTIMAL", "FEASIBLE")
    for stop in result.itinerary.stops:
        assert NINE_AM <= stop.start_minute
        assert stop.end_minute <= SIX_PM
