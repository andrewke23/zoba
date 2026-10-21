from uuid import UUID

import pytest

from app.services.preference import (
    ComparisonInput,
    PreferenceInput,
    bradley_terry,
    compute_ranking,
    min_max,
    next_pair,
)


def _id(tail: int) -> UUID:
    return UUID(f"00000000-0000-0000-0000-{tail:012d}")

ALICE = _id(1)
BOB = _id(2)
CAROL = _id(3)
D1 = _id(101)
D2 = _id(102)
D3 = _id(103)


# ---------------------------------------------------------------------------
# bradley_terry (F04)
# ---------------------------------------------------------------------------


def test_bradley_terry_ranks_consistent_winner_higher() -> None:
    theta = bradley_terry([D1, D2], [(D1, D2, D1)] * 5)
    assert theta[D1] > theta[D2]


def test_bradley_terry_with_no_comparisons_is_symmetric() -> None:
    theta = bradley_terry([D1, D2, D3], [])
    assert theta[D1] == theta[D2] == theta[D3]


def test_bradley_terry_empty_ids_returns_empty() -> None:
    assert bradley_terry([], []) == {}


# ---------------------------------------------------------------------------
# min_max
# ---------------------------------------------------------------------------


def test_min_max_scales_to_unit_interval() -> None:
    scaled = min_max({D1: 0.0, D2: 5.0, D3: 10.0})
    assert scaled[D1] == pytest.approx(0.0)
    assert scaled[D2] == pytest.approx(0.5)
    assert scaled[D3] == pytest.approx(1.0)


def test_min_max_identical_values_fall_back_to_half() -> None:
    scaled = min_max({D1: 3.0, D2: 3.0})
    assert scaled == {D1: 0.5, D2: 0.5}


def test_min_max_empty_returns_empty() -> None:
    assert min_max({}) == {}


# ---------------------------------------------------------------------------
# next_pair
# ---------------------------------------------------------------------------


def test_next_pair_needs_at_least_two_eligible() -> None:
    assert next_pair([D1], []) is None
    assert next_pair([], []) is None


def test_next_pair_returns_a_pair_from_eligible_destinations() -> None:
    pair = next_pair([D1, D2, D3], [])
    assert pair is not None
    a, b = pair
    assert a != b
    assert {a, b} <= {D1, D2, D3}


def test_next_pair_avoids_repeating_a_fully_compared_pair() -> None:
    # D1 vs D2 already compared many times; D3 is unseen, so it should be preferred.
    comps = [ComparisonInput(user_id=ALICE, dest_a=D1, dest_b=D2, chosen=D1)] * 10
    pair = next_pair([D1, D2, D3], comps)
    assert pair is not None
    assert D3 in pair


# ---------------------------------------------------------------------------
# compute_ranking (F06, F07a, F08, F08a)
# ---------------------------------------------------------------------------


def _ranking():
    prefs = [
        PreferenceInput(user_id=ALICE, destination_id=D1, points=40),
        PreferenceInput(user_id=ALICE, destination_id=D2, points=0),
        PreferenceInput(user_id=ALICE, destination_id=D3, points=0),
        PreferenceInput(user_id=BOB, destination_id=D1, points=0, hard_no=True),
        PreferenceInput(user_id=BOB, destination_id=D2, points=40),
        PreferenceInput(user_id=BOB, destination_id=D3, points=0),
    ]
    return compute_ranking([D1, D2, D3], [ALICE, BOB, CAROL], prefs, [])


def test_hard_no_zeroes_the_group_score_and_sorts_last() -> None:
    result = _ranking()
    rows = {row.destination_id: row for row in result.rows}

    assert rows[D1].group_score == 0.0
    assert rows[D1].vetoed_by == [BOB]
    assert rows[D1].rank == 3  # vetoed destinations always sort after eligible ones
    assert D1 in result.vetoed


def test_group_score_blends_mean_and_worst_off_member() -> None:
    rows = {row.destination_id: row for row in _ranking().rows}
    # Alice loves D1 (utility 1.0) and is indifferent to D2 (0.0); Bob is the reverse.
    # D2's group score = 0.5*mean(0.0, 1.0) + 0.5*min(0.0, 1.0) = 0.25.
    assert rows[D2].group_score == pytest.approx(0.25)
    assert rows[D2].rank == 1


def test_raw_points_and_votes_count_all_members_including_hard_no_rows() -> None:
    rows = {row.destination_id: row for row in _ranking().rows}
    assert rows[D1].raw_points == 40  # Alice's 40 + Bob's 0 (hard no)
    assert rows[D1].raw_votes == 1  # only Alice gave points > 0
    assert rows[D3].raw_points == 0
    assert rows[D3].raw_votes == 0


def test_weighted_points_are_capped_and_normalized() -> None:
    rows = {row.destination_id: row for row in _ranking().rows}
    # point_cap=40 means neither allocation gets reduced here; weighted points
    # are each member's capped spend on that destination over everyone's capped total.
    assert rows[D1].weighted_points == pytest.approx(0.5)
    assert rows[D2].weighted_points == pytest.approx(0.5)
    assert rows[D3].weighted_points == 0.0


def test_member_with_no_input_is_not_active_and_has_no_top_pick() -> None:
    result = _ranking()
    assert CAROL not in result.utility
    assert result.top_picks[CAROL] is None


def test_top_pick_excludes_vetoed_destinations() -> None:
    result = _ranking()
    # Both members' favourite destination excluding the hard-no'd D1 is D2.
    assert result.top_picks[ALICE] == D2
    assert result.top_picks[BOB] == D2
