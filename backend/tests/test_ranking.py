from uuid import UUID

from app.services.ranking import (
    POINT_CAP,
    ComparisonInput,
    PreferenceInput,
    bradley_terry,
    compute_ranking,
    next_pair,
)

A = UUID("aaaaaaaa-0000-0000-0000-000000000001")
B = UUID("bbbbbbbb-0000-0000-0000-000000000002")
C = UUID("cccccccc-0000-0000-0000-000000000003")
D = UUID("dddddddd-0000-0000-0000-000000000004")
ALICE = UUID("10000000-0000-0000-0000-000000000001")
BOB = UUID("20000000-0000-0000-0000-000000000002")
DESTS = [A, B, C, D]


def pref(user, dest, points=0, hard_no=False):
    return PreferenceInput(user_id=user, destination_id=dest, points=points, hard_no=hard_no)


def comp(user, a, b, chosen):
    return ComparisonInput(user_id=user, dest_a=a, dest_b=b, chosen=chosen)


def test_bradley_terry_ranks_winners_above_losers() -> None:
    theta = bradley_terry(DESTS, [(A, B, A), (A, C, A), (B, C, B)])

    assert theta[A] > theta[B] > theta[C]
    # D was never compared, so the prior keeps it finite.
    assert abs(theta[D]) < 10


def test_bradley_terry_without_comparisons_is_flat() -> None:
    theta = bradley_terry(DESTS, [])

    assert len(set(round(v, 9) for v in theta.values())) == 1


def test_next_pair_needs_two_places() -> None:
    assert next_pair([A], []) is None
    assert next_pair([], []) is None


def test_next_pair_avoids_repeating_a_pair() -> None:
    first = next_pair([A, B, C], [])
    assert first is not None
    answered = [comp(ALICE, first[0], first[1], first[0])]

    second = next_pair([A, B, C], answered)

    assert second is not None
    assert set(second) != set(first)


def test_points_drive_the_ranking() -> None:
    result = compute_ranking(DESTS, [ALICE, BOB], [pref(ALICE, C, 40), pref(BOB, C, 30), pref(BOB, A, 10)], [])

    assert result.rows[0].destination_id == C
    assert [row.rank for row in result.rows] == [1, 2, 3, 4]
    top = result.rows[0]
    assert top.raw_points == 70
    assert top.raw_votes == 2


def test_points_above_the_cap_do_not_count_extra() -> None:
    result = compute_ranking(DESTS, [ALICE], [pref(ALICE, A, 90), pref(ALICE, B, POINT_CAP)], [])
    by_id = {row.destination_id: row for row in result.rows}

    assert by_id[A].weighted_points == by_id[B].weighted_points
    assert by_id[A].raw_points == 90


def test_a_hard_no_vetoes_and_sinks_a_destination() -> None:
    result = compute_ranking(DESTS, [ALICE, BOB], [pref(ALICE, A, 50), pref(BOB, A, hard_no=True)], [])
    last = result.rows[-1]

    assert last.destination_id == A
    assert last.group_score == 0
    assert last.vetoed_by == [BOB]
    assert result.top_picks[ALICE] != A


def test_members_who_have_not_voted_get_no_top_pick() -> None:
    result = compute_ranking(DESTS, [ALICE, BOB], [pref(ALICE, B, 20)], [])

    assert result.top_picks == {ALICE: B, BOB: None}
    # Bob's silence doesn't pull scores down.
    assert result.rows[0].min_member_utility == 1


def test_comparisons_alone_produce_a_ranking() -> None:
    result = compute_ranking(DESTS, [ALICE], [], [comp(ALICE, D, A, D), comp(ALICE, D, B, D), comp(ALICE, D, C, D)])

    assert result.rows[0].destination_id == D
    assert result.top_picks[ALICE] == D


def test_votes_from_non_members_are_ignored() -> None:
    stranger = UUID("90000000-0000-0000-0000-000000000009")
    result = compute_ranking(DESTS, [ALICE], [pref(stranger, A, hard_no=True), pref(ALICE, A, 10)], [])

    assert result.vetoed == set()
    assert result.rows[0].destination_id == A
