"""Bradley-Terry preference modeling and fairness-aware group ranking.

Covers F04 (pairwise-comparison strength estimation), F06 (fairness-aware group
ranking), F07/F07a (fixed point-budget allocation), and F08/F08a (hard-no vetoes,
raw counts beside weighted scores).

This is a line-for-line port of `frontend/src/api/mock/algorithms.ts`
(`bradleyTerry`, `minMax`, `nextPair`, `computeRanking`): the frontend defined
the contract and the exact numbers the UI was built against, so the real
service reproduces them rather than re-deriving the math independently.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

import numpy as np

POINT_BUDGET = 100
"""Fixed point budget each member allocates across destinations (F07a)."""

POINT_CAP = 40
"""Max points that count toward weight for a single destination (F08a)."""

TARGET_COMPARISONS = 15
"""Comparisons a member should complete before results stabilize."""


@dataclass(frozen=True)
class PreferenceConfig:
    point_budget: int = POINT_BUDGET
    point_cap: int = POINT_CAP
    target_comparisons: int = TARGET_COMPARISONS


DEFAULT_CONFIG = PreferenceConfig()


@dataclass(frozen=True)
class PreferenceInput:
    user_id: UUID
    destination_id: UUID
    points: int
    hard_no: bool = False


@dataclass(frozen=True)
class ComparisonInput:
    user_id: UUID
    dest_a: UUID
    dest_b: UUID
    chosen: UUID


@dataclass(frozen=True)
class RankingRow:
    destination_id: UUID
    rank: int
    raw_points: int
    """Sum of raw points from all members."""
    raw_votes: int
    """Number of members who gave it any points."""
    weighted_points: float
    """Capped, normalized point weight (0..1)."""
    group_score: float
    """Fairness-aware group score (0..1)."""
    min_member_utility: float
    """Lowest single-member utility for this destination (0..1)."""
    vetoed_by: list[UUID]


@dataclass(frozen=True)
class RankingResult:
    rows: list[RankingRow]
    utility: dict[UUID, dict[UUID, float]]
    """user_id -> destination_id -> normalized utility (0..1)."""
    vetoed: set[UUID]
    top_picks: dict[UUID, UUID | None]


def bradley_terry(
    ids: list[UUID], comparisons: list[tuple[UUID, UUID, UUID]], iters: int = 60
) -> dict[UUID, float]:
    """MM-algorithm fit (Hunter, 2004) with a weak prior so unseen items stay finite.

    Returns log-strengths, one per id in `ids`.
    """
    n = len(ids)
    if n == 0:
        return {}
    index = {dest_id: i for i, dest_id in enumerate(ids)}
    wins = np.full(n, 0.5)  # prior: half a win...
    pair_counts: dict[tuple[int, int], int] = {}
    for dest_a, dest_b, winner in comparisons:
        i, j, w = index.get(dest_a), index.get(dest_b), index.get(winner)
        if i is None or j is None or w is None:
            continue
        wins[w] += 1
        key = (i, j) if i < j else (j, i)
        pair_counts[key] = pair_counts.get(key, 0) + 1

    p = np.ones(n)
    for _ in range(iters):
        denom = 1.0 / (p + 1.0)  # ...and one comparison against a virtual average item
        for (i, j), count in pair_counts.items():
            denom[i] += count / (p[i] + p[j])
            denom[j] += count / (p[i] + p[j])
        p = wins / denom
        p = p / p.mean()

    return {dest_id: float(np.log(p[i])) for dest_id, i in index.items()}


def min_max(values: dict[UUID, float]) -> dict[UUID, float]:
    if not values:
        return {}
    xs = list(values.values())
    lo, hi = min(xs), max(xs)
    if hi - lo < 1e-9:
        return {k: 0.5 for k in values}
    return {k: (v - lo) / (hi - lo) for k, v in values.items()}


def next_pair(
    eligible: list[UUID], comparisons: list[ComparisonInput]
) -> tuple[UUID, UUID] | None:
    """Pick the most informative next pair: close in current estimate, under-compared, not repeated."""
    if len(eligible) < 2:
        return None
    theta = bradley_terry(eligible, [(c.dest_a, c.dest_b, c.chosen) for c in comparisons])
    seen: dict[UUID, int] = {}
    pair_count: dict[tuple[UUID, UUID], int] = {}
    for c in comparisons:
        seen[c.dest_a] = seen.get(c.dest_a, 0) + 1
        seen[c.dest_b] = seen.get(c.dest_b, 0) + 1
        key = tuple(sorted((c.dest_a, c.dest_b), key=str))
        pair_count[key] = pair_count.get(key, 0) + 1

    best: tuple[UUID, UUID] | None = None
    best_cost = float("inf")
    for i in range(len(eligible)):
        for j in range(i + 1, len(eligible)):
            a, b = eligible[i], eligible[j]
            key = tuple(sorted((a, b), key=str))
            cost = (
                abs(theta[a] - theta[b])
                + 0.35 * (seen.get(a, 0) + seen.get(b, 0))
                + 10 * pair_count.get(key, 0)
                # tiny deterministic jitter so ties don't always pick the same corner
                + ((ord(str(a)[2]) * 31 + ord(str(b)[2]) * 17 + len(comparisons) * 7) % 13) / 100
            )
            if cost < best_cost:
                best_cost = cost
                best = (b, a) if len(comparisons) % 2 else (a, b)
    return best


def compute_ranking(
    destination_ids: list[UUID],
    member_ids: list[UUID],
    prefs: list[PreferenceInput],
    comps: list[ComparisonInput],
    cfg: PreferenceConfig = DEFAULT_CONFIG,
) -> RankingResult:
    ids = destination_ids
    vetoed = {p.destination_id for p in prefs if p.hard_no}
    utility: dict[UUID, dict[UUID, float]] = {}
    active: list[UUID] = []

    for uid in member_ids:
        my_prefs = [p for p in prefs if p.user_id == uid]
        my_comps = [c for c in comps if c.user_id == uid]
        if not any(p.points > 0 for p in my_prefs) and not my_comps:
            continue
        active.append(uid)
        bt = min_max(
            bradley_terry(ids, [(c.dest_a, c.dest_b, c.chosen) for c in my_comps])
        )
        raw: dict[UUID, float] = {}
        for dest_id in ids:
            pts = next((p.points for p in my_prefs if p.destination_id == dest_id), 0)
            points_weight = min(pts, cfg.point_cap) / cfg.point_cap
            raw[dest_id] = 0.6 * (bt[dest_id] if my_comps else 0.5) + 0.4 * points_weight
        utility[uid] = min_max(raw)

    cap_total = sum(min(p.points, cfg.point_cap) for p in prefs) or 1
    rows: list[RankingRow] = []
    for dest_id in ids:
        us = [utility[uid][dest_id] for uid in active]
        mean = sum(us) / len(us) if us else 0.0
        worst = min(us) if us else 0.0
        for_dest = [p for p in prefs if p.destination_id == dest_id]
        rows.append(
            RankingRow(
                destination_id=dest_id,
                rank=0,
                raw_points=sum(p.points for p in for_dest),
                raw_votes=sum(1 for p in for_dest if p.points > 0),
                weighted_points=sum(min(p.points, cfg.point_cap) for p in for_dest) / cap_total,
                # Fairness-aware: blend average happiness with the least-happy member.
                group_score=0.0 if dest_id in vetoed else 0.5 * mean + 0.5 * worst,
                min_member_utility=worst,
                vetoed_by=[p.user_id for p in for_dest if p.hard_no],
            )
        )
    rows.sort(key=lambda r: (bool(r.vetoed_by), -r.group_score))
    rows = [
        RankingRow(
            destination_id=r.destination_id,
            rank=i + 1,
            raw_points=r.raw_points,
            raw_votes=r.raw_votes,
            weighted_points=r.weighted_points,
            group_score=r.group_score,
            min_member_utility=r.min_member_utility,
            vetoed_by=r.vetoed_by,
        )
        for i, r in enumerate(rows)
    ]

    top_picks: dict[UUID, UUID | None] = {}
    for uid in member_ids:
        u = utility.get(uid)
        if u is None:
            top_picks[uid] = None
            continue
        best: UUID | None = None
        for dest_id in ids:
            if dest_id not in vetoed and (best is None or u[dest_id] > u[best]):
                best = dest_id
        top_picks[uid] = best

    return RankingResult(rows=rows, utility=utility, vetoed=vetoed, top_picks=top_picks)
