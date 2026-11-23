from uuid import UUID

from app.services.candidate_scoring import apply_group_scores
from app.services.scheduler import Candidate, schedule_trip


def no_travel(origin, destination) -> int:
    return 0

A = UUID("aaaaaaaa-0000-0000-0000-000000000001")
B = UUID("bbbbbbbb-0000-0000-0000-000000000002")
C = UUID("cccccccc-0000-0000-0000-000000000003")


def cand(dest, name, score=0.0):
    return Candidate(destination_id=dest, name=name, score=score, location=(41.88, -87.63), duration_min=60)


def test_no_votes_keeps_existing_scores_and_order() -> None:
    cands = [cand(A, "A", 5), cand(B, "B", 3)]
    assert apply_group_scores(cands, {}, 10) == cands


def test_group_score_replaces_raw_points_and_reorders() -> None:
    # Raw points favor A, but the group ranking favors B.
    cands = [cand(A, "A", 90), cand(B, "B", 10)]
    out = apply_group_scores(cands, {A: 0.2, B: 0.9}, 10)
    assert [c.destination_id for c in out] == [B, A]
    assert [c.score for c in out] == [0.9, 0.2]


def test_places_missing_from_ranking_are_dropped() -> None:
    cands = [cand(A, "A"), cand(B, "B"), cand(C, "C")]
    out = apply_group_scores(cands, {A: 0.5, C: 0.4}, 10)  # B vetoed
    assert {c.destination_id for c in out} == {A, C}


def test_limit_keeps_the_best_group_scores() -> None:
    cands = [cand(A, "A"), cand(B, "B"), cand(C, "C")]
    out = apply_group_scores(cands, {A: 0.1, B: 0.8, C: 0.5}, 2)
    assert [c.destination_id for c in out] == [B, C]


def test_scheduler_picks_the_higher_group_score_when_only_one_fits() -> None:
    from datetime import date

    cands = apply_group_scores([cand(A, "A", 90), cand(B, "B", 10)], {A: 0.2, B: 0.9}, 10)
    itinerary = schedule_trip(
        cands,
        days=[date(2026, 12, 5)],
        day_start_minute=9 * 60,
        day_end_minute=10 * 60 + 30,  # room for one 60-minute visit
        home_base=(41.88, -87.63),
        travel=no_travel,
    )
    assert [stop.destination_id for stop in itinerary.stops] == [B]
