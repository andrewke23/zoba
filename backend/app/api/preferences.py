"""Voting endpoints: preference config, point allocations, this-or-that comparisons,
and the group ranking (F03–F08a).

Everything is stored per trip member in ``preference``, ``comparison`` and
``preference_submission``. The itinerary generator reads the same
``preference`` rows.
"""

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_trip_for_member
from app.core.database import get_session
from app.models.entities import (
    Comparison,
    Membership,
    MembershipStatus,
    Preference,
    PreferenceSubmission,
    Trip,
)
from app.schemas.preferences import (
    ComparisonCreate,
    ComparisonPairRead,
    ComparisonProgressRead,
    GroupResultsRead,
    MemberTopPickRead,
    PreferenceConfigRead,
    PreferenceItem,
    RankingRowRead,
)
from app.services import ranking
from app.services.embedder import describe_comparison, describe_preference, record_input_embedding

router = APIRouter(prefix="/trips/{trip_id}")

PREFERENCE_CONFIG = PreferenceConfigRead(
    point_budget=ranking.POINT_BUDGET,
    point_cap=ranking.POINT_CAP,
    target_comparisons=ranking.TARGET_COMPARISONS,
)


async def _catalog(session: AsyncSession, city_id: str) -> dict[UUID, tuple[str, str]]:
    """destination_id -> (name, category) for the city, in a stable (name) order."""
    rows = await session.execute(
        text("SELECT destination_id, name, category FROM destination WHERE city_id = :city_id ORDER BY name, destination_id"),
        {"city_id": city_id},
    )
    return {row.destination_id: (row.name, row.category) for row in rows}


async def _joined_member_ids(session: AsyncSession, trip_id: UUID) -> list[UUID]:
    return list(
        (
            await session.scalars(
                select(Membership.user_id)
                .where(Membership.trip_id == trip_id, Membership.status == MembershipStatus.JOINED)
                .order_by(Membership.user_id)
            )
        ).all()
    )


async def _preferences(session: AsyncSession, trip_id: UUID, user_id: UUID | None = None) -> list[Preference]:
    query = select(Preference).where(Preference.trip_id == trip_id)
    if user_id is not None:
        query = query.where(Preference.user_id == user_id)
    return list((await session.scalars(query.order_by(Preference.destination_id))).all())


async def _comparisons(session: AsyncSession, trip_id: UUID, user_id: UUID | None = None) -> list[Comparison]:
    query = select(Comparison).where(Comparison.trip_id == trip_id)
    if user_id is not None:
        query = query.where(Comparison.user_id == user_id)
    return list((await session.scalars(query.order_by(Comparison.id))).all())


def _comparison_inputs(rows: list[Comparison]) -> list[ranking.ComparisonInput]:
    return [ranking.ComparisonInput(user_id=c.user_id, dest_a=c.dest_a, dest_b=c.dest_b, chosen=c.chosen) for c in rows]


async def _progress(session: AsyncSession, trip: Trip, user_id: UUID) -> ComparisonProgressRead:
    catalog = await _catalog(session, trip.city_id)
    vetoed_by_me = {p.destination_id for p in await _preferences(session, trip.id, user_id) if p.hard_no}
    eligible = [dest for dest in catalog if dest not in vetoed_by_me]
    mine = await _comparisons(session, trip.id, user_id)
    pair = ranking.next_pair(eligible, _comparison_inputs(mine))
    return ComparisonProgressRead(
        done=len(mine),
        target=ranking.TARGET_COMPARISONS,
        next=ComparisonPairRead(dest_a=pair[0], dest_b=pair[1]) if pair else None,
    )


@router.get("/preference-config", response_model=PreferenceConfigRead)
async def read_preference_config(
    _: tuple[Trip, Membership] = Depends(get_trip_for_member),
) -> PreferenceConfigRead:
    return PREFERENCE_CONFIG


@router.get("/preferences/me", response_model=list[PreferenceItem])
async def read_my_preferences(
    access: tuple[Trip, Membership] = Depends(get_trip_for_member),
    session: AsyncSession = Depends(get_session),
) -> list[PreferenceItem]:
    trip, membership = access
    return [
        PreferenceItem(destination_id=p.destination_id, points=p.points or 0, rank=p.rank, hard_no=p.hard_no)
        for p in await _preferences(session, trip.id, membership.user_id)
    ]


def _validate_preferences(items: list[PreferenceItem], catalog: dict[UUID, tuple[str, str]]) -> None:
    ids = [item.destination_id for item in items]
    if len(ids) != len(set(ids)):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Each destination may appear only once.")
    if any(dest not in catalog for dest in ids):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Every destination must be in this trip's city."
        )
    total = sum(item.points for item in items if not item.hard_no)
    if total > ranking.POINT_BUDGET:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"You can allocate at most {ranking.POINT_BUDGET} points.",
        )


@router.put("/preferences/me", status_code=status.HTTP_204_NO_CONTENT)
async def save_my_preferences(
    items: list[PreferenceItem],
    access: tuple[Trip, Membership] = Depends(get_trip_for_member),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Replace the caller's allocation and mark their preferences as submitted."""
    trip, membership = access
    user_id = membership.user_id
    catalog = await _catalog(session, trip.city_id)
    _validate_preferences(items, catalog)

    previous = {
        p.destination_id: (p.points or 0, p.rank, p.hard_no) for p in await _preferences(session, trip.id, user_id)
    }
    # A vetoed place carries no points, and rows that say nothing aren't stored.
    kept = [
        PreferenceItem(
            destination_id=item.destination_id,
            points=0 if item.hard_no else item.points,
            rank=item.rank,
            hard_no=item.hard_no,
        )
        for item in items
        if item.points > 0 or item.hard_no or item.rank is not None
    ]

    await session.execute(delete(Preference).where(Preference.trip_id == trip.id, Preference.user_id == user_id))
    for item in kept:
        session.add(
            Preference(
                trip_id=trip.id,
                user_id=user_id,
                destination_id=item.destination_id,
                points=item.points,
                rank=item.rank,
                hard_no=item.hard_no,
            )
        )
    await session.execute(
        insert(PreferenceSubmission)
        .values(trip_id=trip.id, user_id=user_id)
        .on_conflict_do_nothing(index_elements=["trip_id", "user_id"])
    )

    # Embed only what changed, so re-saving the same allocation adds nothing.
    for item in kept:
        if previous.get(item.destination_id) == (item.points, item.rank, item.hard_no):
            continue
        name, category = catalog[item.destination_id]
        await record_input_embedding(
            session,
            user_id=user_id,
            trip_id=trip.id,
            input_kind="preference",
            source_id=f"{trip.id}:{user_id}:{item.destination_id}",
            text=describe_preference(
                destination_name=name,
                category=category,
                points=item.points or None,
                point_budget=ranking.POINT_BUDGET,
                rank=item.rank,
                hard_no=item.hard_no,
            ),
        )
    await session.commit()


@router.get("/comparisons/progress", response_model=ComparisonProgressRead)
async def read_comparison_progress(
    access: tuple[Trip, Membership] = Depends(get_trip_for_member),
    session: AsyncSession = Depends(get_session),
) -> ComparisonProgressRead:
    trip, membership = access
    return await _progress(session, trip, membership.user_id)


@router.post("/comparisons", response_model=ComparisonProgressRead, status_code=status.HTTP_201_CREATED)
async def submit_comparison(
    payload: ComparisonCreate,
    access: tuple[Trip, Membership] = Depends(get_trip_for_member),
    session: AsyncSession = Depends(get_session),
) -> ComparisonProgressRead:
    """Record one this-or-that choice and return the caller's next pair."""
    trip, membership = access
    catalog = await _catalog(session, trip.city_id)
    if payload.dest_a not in catalog or payload.dest_b not in catalog:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Both destinations must be in this trip's city."
        )

    comparison = Comparison(
        trip_id=trip.id,
        user_id=membership.user_id,
        dest_a=payload.dest_a,
        dest_b=payload.dest_b,
        chosen=payload.chosen,
    )
    session.add(comparison)
    await session.flush()

    rejected = payload.dest_b if payload.chosen == payload.dest_a else payload.dest_a
    chosen_name, chosen_category = catalog[payload.chosen]
    rejected_name, rejected_category = catalog[rejected]
    await record_input_embedding(
        session,
        user_id=membership.user_id,
        trip_id=trip.id,
        input_kind="comparison",
        source_id=str(comparison.id),
        text=describe_comparison(
            chosen_name=chosen_name,
            rejected_name=rejected_name,
            chosen_category=chosen_category,
            rejected_category=rejected_category,
        ),
    )
    await session.commit()
    return await _progress(session, trip, membership.user_id)


@router.get("/group-results", response_model=GroupResultsRead)
async def read_group_results(
    access: tuple[Trip, Membership] = Depends(get_trip_for_member),
    session: AsyncSession = Depends(get_session),
) -> GroupResultsRead:
    trip, _ = access
    catalog = await _catalog(session, trip.city_id)
    members = await _joined_member_ids(session, trip.id)
    result = ranking.compute_ranking(
        list(catalog),
        members,
        [
            ranking.PreferenceInput(
                user_id=p.user_id, destination_id=p.destination_id, points=p.points or 0, hard_no=p.hard_no
            )
            for p in await _preferences(session, trip.id)
        ],
        _comparison_inputs(await _comparisons(session, trip.id)),
    )
    return GroupResultsRead(
        rows=[RankingRowRead(**vars(row)) for row in result.rows],
        top_picks=[MemberTopPickRead(user_id=user, destination_id=dest) for user, dest in result.top_picks.items()],
        config=PREFERENCE_CONFIG,
        computed_at=datetime.now(timezone.utc),
    )
