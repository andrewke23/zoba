"""Group ranking from point allocations and pairwise comparisons (F03–F08a).

Pure functions, no database access, so they are easy to test. This is a port of
the frontend mock (frontend/src/api/mock/algorithms.ts), so demo mode and the
real backend rank the same inputs the same way.
"""

import math
from collections import defaultdict
from dataclasses import dataclass, field
from uuid import UUID

POINT_BUDGET = 100
"""Points each member allocates across destinations (F07a)."""
POINT_CAP = 40
"""Most points that count toward weight for one destination (F08a)."""
TARGET_COMPARISONS = 15
"""This-or-that choices each member is asked to make (SRS §8 open question)."""

# How much comparisons and points each contribute to a member's utility.
_COMPARISON_WEIGHT = 0.6
_POINTS_WEIGHT = 0.4


@dataclass(frozen=True)
class PreferenceInput:
    user_id: UUID
    destination_id: UUID
    points: int
    hard_no: bool


@dataclass(frozen=True)
class ComparisonInput:
    user_id: UUID
    dest_a: UUID
    dest_b: UUID
    chosen: UUID


@dataclass
class RankingRow:
    destination_id: UUID
    rank: int
    raw_points: int
    raw_votes: int
    weighted_points: float
    group_score: float
    min_member_utility: float
    vetoed_by: list[UUID]


@dataclass
class RankingResult:
    rows: list[RankingRow]
    utility: dict[UUID, dict[UUID, float]] = field(default_factory=dict)
    vetoed: set[UUID] = field(default_factory=set)
    top_picks: dict[UUID, UUID | None] = field(default_factory=dict)


def bradley_terry(
    ids: list[UUID], comparisons: list[tuple[UUID, UUID, UUID]], iterations: int = 60
) -> dict[UUID, float]:
    """Log-strengths from (a, b, winner) triples, by the MM algorithm (Hunter 2004).

    A weak prior (half a win and one game against a virtual average item) keeps
    never-compared items finite and at the middle.
    """
    index = {dest: i for i, dest in enumerate(ids)}
    n = len(ids)
    if n == 0:
        return {}
    wins = [0.5] * n
    pair_counts: dict[tuple[int, int], int] = defaultdict(int)
    for a, b, winner in comparisons:
        i, j, w = index.get(a), index.get(b), index.get(winner)
        if i is None or j is None or w is None:
            continue
        wins[w] += 1
        pair_counts[(min(i, j), max(i, j))] += 1

    strength = [1.0] * n
    for _ in range(iterations):
        denominators = [1 / (s + 1) for s in strength]
        for (i, j), count in pair_counts.items():
            shared = count / (strength[i] + strength[j])
            denominators[i] += shared
            denominators[j] += shared
        updated = [wins[i] / denominators[i] for i in range(n)]
        mean = sum(updated) / n
        strength = [value / mean for value in updated]
    return {dest: math.log(strength[i]) for dest, i in index.items()}


def _min_max(values: dict[UUID, float]) -> dict[UUID, float]:
    if not values:
        return {}
    low, high = min(values.values()), max(values.values())
    if high - low < 1e-9:
        return {key: 0.5 for key in values}
    return {key: (value - low) / (high - low) for key, value in values.items()}


def _jitter(a: UUID, b: UUID, done: int) -> float:
    """Small deterministic tie-breaker, same formula as the mock."""
    return ((ord(str(a)[2]) * 31 + ord(str(b)[2]) * 17 + done * 7) % 13) / 100


def next_pair(eligible: list[UUID], comparisons: list[ComparisonInput]) -> tuple[UUID, UUID] | None:
    """The most informative next pair for one member.

    It prefers places whose current estimates are close, that have been compared
    less, and that have not already been shown together.
    """
    if len(eligible) < 2:
        return None
    theta = bradley_terry(eligible, [(c.dest_a, c.dest_b, c.chosen) for c in comparisons])
    seen: dict[UUID, int] = defaultdict(int)
    pair_seen: dict[frozenset[UUID], int] = defaultdict(int)
    for c in comparisons:
        seen[c.dest_a] += 1
        seen[c.dest_b] += 1
        pair_seen[frozenset((c.dest_a, c.dest_b))] += 1

    done = len(comparisons)
    best: tuple[UUID, UUID] | None = None
    best_cost = math.inf
    for i, a in enumerate(eligible):
        for b in eligible[i + 1 :]:
            cost = (
                abs(theta[a] - theta[b])
                + 0.35 * (seen[a] + seen[b])
                + 10 * pair_seen[frozenset((a, b))]
                + _jitter(a, b, done)
            )
            if cost < best_cost:
                best_cost = cost
                # Alternate sides so one place doesn't always appear on the left.
                best = (b, a) if done % 2 else (a, b)
    return best


def compute_ranking(
    destination_ids: list[UUID],
    member_ids: list[UUID],
    preferences: list[PreferenceInput],
    comparisons: list[ComparisonInput],
) -> RankingResult:
    """Fairness-aware group ranking.

    Each member's utility blends their Bradley-Terry fit with their capped
    points, then is normalized per member so a member who made more comparisons
    doesn't count for more. A destination's group score averages the mean and
    the lowest member utility, so the least happy member counts too. Any hard
    no vetoes the destination.
    """
    members = set(member_ids)
    prefs = [p for p in preferences if p.user_id in members]
    comps = [c for c in comparisons if c.user_id in members]
    vetoed = {p.destination_id for p in prefs if p.hard_no}

    prefs_by_member: dict[UUID, list[PreferenceInput]] = defaultdict(list)
    for p in prefs:
        prefs_by_member[p.user_id].append(p)
    comps_by_member: dict[UUID, list[ComparisonInput]] = defaultdict(list)
    for c in comps:
        comps_by_member[c.user_id].append(c)

    utility: dict[UUID, dict[UUID, float]] = {}
    for user_id in member_ids:
        my_prefs = prefs_by_member[user_id]
        my_comps = comps_by_member[user_id]
        if not any(p.points > 0 for p in my_prefs) and not my_comps:
            continue  # this member hasn't voted, so they don't drag scores down
        fitted = _min_max(bradley_terry(destination_ids, [(c.dest_a, c.dest_b, c.chosen) for c in my_comps]))
        points = {p.destination_id: p.points for p in my_prefs}
        raw = {
            dest: _COMPARISON_WEIGHT * (fitted[dest] if my_comps else 0.5)
            + _POINTS_WEIGHT * min(points.get(dest, 0), POINT_CAP) / POINT_CAP
            for dest in destination_ids
        }
        utility[user_id] = _min_max(raw)

    prefs_by_dest: dict[UUID, list[PreferenceInput]] = defaultdict(list)
    for p in prefs:
        prefs_by_dest[p.destination_id].append(p)
    capped_total = sum(min(p.points, POINT_CAP) for p in prefs) or 1

    rows: list[RankingRow] = []
    for dest in destination_ids:
        utilities = [member_utility[dest] for member_utility in utility.values()]
        mean = sum(utilities) / len(utilities) if utilities else 0.0
        lowest = min(utilities) if utilities else 0.0
        for_dest = prefs_by_dest[dest]
        rows.append(
            RankingRow(
                destination_id=dest,
                rank=0,
                raw_points=sum(p.points for p in for_dest),
                raw_votes=sum(1 for p in for_dest if p.points > 0),
                weighted_points=sum(min(p.points, POINT_CAP) for p in for_dest) / capped_total,
                group_score=0.0 if dest in vetoed else 0.5 * mean + 0.5 * lowest,
                min_member_utility=lowest,
                vetoed_by=[p.user_id for p in for_dest if p.hard_no],
            )
        )
    # Vetoed places sink to the bottom; the rest sort by score (stable on ties).
    rows.sort(key=lambda row: (bool(row.vetoed_by), -row.group_score))
    for position, row in enumerate(rows, start=1):
        row.rank = position

    top_picks: dict[UUID, UUID | None] = {}
    for user_id in member_ids:
        member_utility = utility.get(user_id)
        best: UUID | None = None
        if member_utility is not None:
            for dest in destination_ids:
                if dest not in vetoed and (best is None or member_utility[dest] > member_utility[best]):
                    best = dest
        top_picks[user_id] = best

    return RankingResult(rows=rows, utility=utility, vetoed=vetoed, top_picks=top_picks)
