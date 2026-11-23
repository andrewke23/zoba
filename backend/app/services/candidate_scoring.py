"""Score itinerary candidates with the group ranking instead of raw points.

Pure function, no database access. The itinerary endpoints load candidates
from the database, then pass them through here so the scheduler optimizes the
same fairness-aware group score that the Group results page shows.
"""

from dataclasses import replace
from uuid import UUID

from app.services.scheduler import Candidate


def apply_group_scores(
    candidates: list[Candidate], group_scores: dict[UUID, float], limit: int
) -> list[Candidate]:
    """Replace each candidate's score with its group score, keep the best ``limit``.

    ``group_scores`` maps destination_id -> group score from
    ``ranking.compute_ranking``. An empty mapping means nobody has voted yet, so
    the candidates keep their existing scores and order. Destinations missing
    from a non-empty mapping (vetoed ones) are dropped.
    """
    if not group_scores:
        return candidates[:limit]
    rescored = [
        replace(candidate, score=group_scores[candidate.destination_id])
        for candidate in candidates
        if candidate.destination_id in group_scores
    ]
    rescored.sort(key=lambda c: (-c.score, c.name, str(c.destination_id)))
    return rescored[:limit]
