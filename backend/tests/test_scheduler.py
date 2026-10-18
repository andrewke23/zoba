from datetime import date
from uuid import UUID

import pytest

from app.services.scheduler import (
    Candidate,
    LockedStop,
    OpeningWindow,
    earliest_feasible_start,
    haversine_km,
    schedule_trip,
    straight_line_estimator,
    visit_minutes,
)

MONDAY = date(2026, 10, 19)
TUESDAY = date(2026, 10, 20)

HOME = (41.5085, -81.6089)  # downtown Cleveland, used as the hotel in these tests

NINE_AM = 9 * 60
SIX_PM = 18 * 60


def _id(tail: int) -> UUID:
    return UUID(f"00000000-0000-0000-0000-{tail:012d}")


def no_travel(origin, destination):
    """Collapses geography so a test can isolate scoring or hours."""
    return 0


def place(tail: int, name: str, score: float, duration: int = 60, *, location=HOME, windows=()):
    return Candidate(
        destination_id=_id(tail),
        name=name,
        score=score,
        location=location,
        duration_min=duration,
        windows=windows,
    )


def test_no_candidates_returns_empty_itinerary():
    itinerary = schedule_trip(
        [],
        days=[MONDAY],
        day_start_minute=NINE_AM,
        day_end_minute=SIX_PM,
        home_base=HOME,
        travel=no_travel,
    )
    assert itinerary.stops == ()
    assert itinerary.total_score == 0


def test_day_end_before_day_start_is_rejected():
    with pytest.raises(ValueError):
        schedule_trip([], days=[MONDAY], day_start_minute=SIX_PM, day_end_minute=NINE_AM, home_base=HOME)


def test_stops_are_sequential_and_do_not_overlap():
    candidates = [place(1, "A", 10), place(2, "B", 9), place(3, "C", 8)]
    itinerary = schedule_trip(
        candidates,
        days=[MONDAY],
        day_start_minute=NINE_AM,
        day_end_minute=SIX_PM,
        home_base=HOME,
        travel=no_travel,
    )
    stops = itinerary.stops_on(0)
    assert [stop.seq for stop in stops] == list(range(len(stops)))
    for earlier, later in zip(stops, stops[1:]):
        assert later.start_minute >= earlier.end_minute


def test_day_budget_is_respected():
    # Four two-hour visits cannot fit into a six-hour day.
    candidates = [place(index, f"P{index}", 10, duration=120) for index in range(1, 5)]
    itinerary = schedule_trip(
        candidates,
        days=[MONDAY],
        day_start_minute=NINE_AM,
        day_end_minute=NINE_AM + 360,
        home_base=HOME,
        travel=no_travel,
    )
    assert len(itinerary.stops) == 3
    assert len(itinerary.unscheduled) == 1
    assert max(stop.end_minute for stop in itinerary.stops) <= NINE_AM + 360


def test_denser_candidate_beats_higher_raw_score():
    # "Quick" scores less in total but far more per minute, so it goes first.
    slow = place(1, "Slow", score=100, duration=300)
    quick = place(2, "Quick", score=60, duration=60)
    itinerary = schedule_trip(
        [slow, quick],
        days=[MONDAY],
        day_start_minute=NINE_AM,
        day_end_minute=SIX_PM,
        home_base=HOME,
        travel=no_travel,
    )
    assert itinerary.stops[0].name == "Quick"


def test_closed_on_that_weekday_is_not_scheduled():
    # Open Tuesdays only; the trip is on a Monday.
    tuesday_only = place(1, "Closed Mondays", 50, windows=(OpeningWindow(weekday=1, open_min=600, close_min=1020),))
    itinerary = schedule_trip(
        [tuesday_only],
        days=[MONDAY],
        day_start_minute=NINE_AM,
        day_end_minute=SIX_PM,
        home_base=HOME,
        travel=no_travel,
    )
    assert itinerary.stops == ()
    assert itinerary.unscheduled == (_id(1),)


def test_visit_waits_for_opening_time():
    # Opens at 11:00 even though the group is free from 09:00.
    late_opener = place(1, "Late", 50, windows=(OpeningWindow(weekday=0, open_min=660, close_min=1020),))
    itinerary = schedule_trip(
        [late_opener],
        days=[MONDAY],
        day_start_minute=NINE_AM,
        day_end_minute=SIX_PM,
        home_base=HOME,
        travel=no_travel,
    )
    assert itinerary.stops[0].start_minute == 660


def test_travel_time_consumes_the_day():
    far = (41.9, -87.6)  # ~500 km away
    candidates = [place(1, "Near", 10), place(2, "Far", 10, location=far)]
    itinerary = schedule_trip(
        candidates,
        days=[MONDAY],
        day_start_minute=NINE_AM,
        day_end_minute=SIX_PM,
        home_base=HOME,
        travel=straight_line_estimator(),
    )
    scheduled = {stop.name for stop in itinerary.stops}
    assert "Near" in scheduled
    assert "Far" not in scheduled


def test_work_spreads_across_multiple_days():
    candidates = [place(index, f"P{index}", 10, duration=120) for index in range(1, 7)]
    itinerary = schedule_trip(
        candidates,
        days=[MONDAY, TUESDAY],
        day_start_minute=NINE_AM,
        day_end_minute=NINE_AM + 360,
        home_base=HOME,
        travel=no_travel,
    )
    assert len(itinerary.stops_on(0)) == 3
    assert len(itinerary.stops_on(1)) == 3


def test_locked_stop_anchors_its_day():
    locked = LockedStop(
        day_index=0,
        destination_id=_id(99),
        name="Pinned",
        location=HOME,
        start_minute=13 * 60,
        duration_min=60,
    )
    candidates = [place(index, f"P{index}", 10, duration=60) for index in range(1, 6)]
    itinerary = schedule_trip(
        candidates,
        days=[MONDAY],
        day_start_minute=NINE_AM,
        day_end_minute=SIX_PM,
        home_base=HOME,
        travel=no_travel,
        locked=[locked],
    )
    pinned = [stop for stop in itinerary.stops if stop.locked]
    assert len(pinned) == 1
    assert pinned[0].start_minute == 13 * 60
    assert pinned[0].name == "Pinned"
    # Nothing may overlap the anchor.
    for stop in itinerary.stops:
        if not stop.locked:
            assert stop.end_minute <= 13 * 60 or stop.start_minute >= 14 * 60


def test_results_are_deterministic():
    candidates = [place(index, f"P{index}", 10, duration=60) for index in range(1, 8)]
    first = schedule_trip(
        candidates, days=[MONDAY], day_start_minute=NINE_AM, day_end_minute=SIX_PM,
        home_base=HOME, travel=no_travel,
    )
    second = schedule_trip(
        list(reversed(candidates)), days=[MONDAY], day_start_minute=NINE_AM, day_end_minute=SIX_PM,
        home_base=HOME, travel=no_travel,
    )
    assert [stop.name for stop in first.stops] == [stop.name for stop in second.stops]


def test_total_score_matches_scheduled_stops():
    candidates = [place(1, "A", 10), place(2, "B", 7)]
    itinerary = schedule_trip(
        candidates, days=[MONDAY], day_start_minute=NINE_AM, day_end_minute=SIX_PM,
        home_base=HOME, travel=no_travel,
    )
    assert itinerary.total_score == pytest.approx(sum(stop.score for stop in itinerary.stops))


def test_earliest_feasible_start_returns_none_when_window_too_short():
    candidate = place(1, "Tight", 10, duration=120, windows=(OpeningWindow(0, 600, 660),))
    assert earliest_feasible_start(candidate, arrival_minute=600, latest_end_minute=1440, weekday=0) is None


def test_haversine_matches_known_distance():
    # Cleveland to Chicago is roughly 500 km.
    assert haversine_km(HOME, (41.8781, -87.6298)) == pytest.approx(500, abs=30)


@pytest.mark.parametrize(
    "duration,category,expected",
    [(90, "museum", 90), (None, "museum", 120), (0, "viewpoint", 30), (None, None, 60), (None, "unknown", 60)],
)
def test_visit_minutes_resolution_order(duration, category, expected):
    assert visit_minutes(duration, category) == expected
