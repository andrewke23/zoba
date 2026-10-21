"""Preference, comparison, and group-ranking endpoints (F04, F06, F07a, F08, F08a)."""

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_trip_for_member
from app.core.database import get_session
from app.models.entities import Comparison, InputEmbedding, Membership, Preference, Trip
from app.schemas.preferences import (
    ComparisonPairRead,
    ComparisonProgressRead,
    GroupResultsRead,
    MemberTopPickRead,
    PreferenceConfigRead,
    PreferenceRead,
    RankingRowRead,
    SavePreferencesRequest,
    SubmitComparisonRequest,
)
from app.services.embedder import describe_comparison, describe_preference, record_input_embedding
from app.services.preference import (
    DEFAULT_CONFIG,
    ComparisonInput,
    PreferenceInput,
    compute_ranking,
    next_pair,
)
from datetime import datetime, timezone

router = APIRouter(prefix="/trips/{trip_id}")

_DESTINATION_IDS_FOR_CITY_SQL = text("SELECT destination_id FROM destination WHERE city_id = :city_id")
_DESTINATION_NAMES_SQL = text(
    "SELECT destination_id, name, category FROM destination WHERE destination_id = ANY(:ids)"
)
_JOINED_MEMBERS_SQL = text("SELECT user_id FROM membership WHERE trip_id = :trip_id AND status = 'joined'")


async def _destinations_for_city(session: AsyncSession, city_id: str) -> list[UUID]:
    rows = await session.execute(_DESTINATION_IDS_FOR_CITY_SQL, {"city_id": city_id})
    return [row[0] for row in rows.all()]


async def _destination_names(session: AsyncSession, ids: list[UUID]) -> dict[UUID, tuple[str, str]]:
    if not ids:
        return {}
    rows = await session.execute(_DESTINATION_NAMES_SQL, {"ids": ids})
    return {row["destination_id"]: (row["name"], row["category"]) for row in rows.mappings()}


async def _joined_members(session: AsyncSession, trip_id: UUID) -> list[UUID]:
    rows = await session.execute(_JOINED_MEMBERS_SQL, {"trip_id": trip_id})
    return [row[0] for row in rows.all()]


async def _trip_preferences(session: AsyncSession, trip_id: UUID) -> list[PreferenceInput]:
    rows = (await session.scalars(select(Preference).where(Preference.trip_id == trip_id))).all()
    return [
        PreferenceInput(
            user_id=row.user_id,
            destination_id=row.destination_id,
            points=row.points or 0,
            hard_no=row.hard_no,
        )
        for row in rows
    ]


async def _trip_comparisons(session: AsyncSession, trip_id: UUID) -> list[ComparisonInput]:
    rows = (await session.scalars(select(Comparison).where(Comparison.trip_id == trip_id))).all()
    return [
        ComparisonInput(user_id=row.user_id, dest_a=row.dest_a, dest_b=row.dest_b, chosen=row.chosen)
        for row in rows
    ]


@router.get("/preferences/config", response_model=PreferenceConfigRead)
async def get_preference_config() -> PreferenceConfigRead:
    return PreferenceConfigRead(
        point_budget=DEFAULT_CONFIG.point_budget,
        point_cap=DEFAULT_CONFIG.point_cap,
        target_comparisons=DEFAULT_CONFIG.target_comparisons,
    )


@router.get("/preferences/me", response_model=list[PreferenceRead])
async def get_my_preferences(
    trip_and_membership: tuple[Trip, Membership] = Depends(get_trip_for_member),
    session: AsyncSession = Depends(get_session),
) -> list[PreferenceRead]:
    _, membership = trip_and_membership
    rows = (
        await session.scalars(
            select(Preference).where(
                Preference.trip_id == membership.trip_id, Preference.user_id == membership.user_id
            )
        )
    ).all()
    return [
        PreferenceRead(destination_id=row.destination_id, points=row.points or 0, rank=row.rank, hard_no=row.hard_no)
        for row in rows
    ]


@router.put("/preferences/me", status_code=status.HTTP_204_NO_CONTENT)
async def save_my_preferences(
    payload: SavePreferencesRequest,
    trip_and_membership: tuple[Trip, Membership] = Depends(get_trip_for_member),
    session: AsyncSession = Depends(get_session),
) -> None:
    trip, membership = trip_and_membership

    valid_ids = set(await _destinations_for_city(session, trip.city_id))
    unknown = [str(p.destination_id) for p in payload.preferences if p.destination_id not in valid_ids]
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Not a destination in this trip's city: {', '.join(unknown)}",
        )

    await session.execute(
        delete(Preference).where(Preference.trip_id == trip.id, Preference.user_id == membership.user_id)
    )
    await session.execute(
        delete(InputEmbedding).where(
            InputEmbedding.input_kind == "preference",
            InputEmbedding.trip_id == trip.id,
            InputEmbedding.user_id == membership.user_id,
        )
    )

    names = await _destination_names(session, [p.destination_id for p in payload.preferences])
    for pref in payload.preferences:
        session.add(
            Preference(
                trip_id=trip.id,
                user_id=membership.user_id,
                destination_id=pref.destination_id,
                points=pref.points,
                rank=pref.rank,
                hard_no=pref.hard_no,
            )
        )
        if pref.points > 0 or pref.hard_no:
            name, category = names.get(pref.destination_id, (str(pref.destination_id), None))
            await record_input_embedding(
                session,
                user_id=membership.user_id,
                trip_id=trip.id,
                input_kind="preference",
                source_id=str(pref.destination_id),
                text=describe_preference(
                    destination_name=name,
                    category=category,
                    points=pref.points,
                    point_budget=DEFAULT_CONFIG.point_budget,
                    rank=pref.rank,
                    hard_no=pref.hard_no,
                ),
            )
    await session.commit()


@router.get("/comparisons/progress", response_model=ComparisonProgressRead)
async def get_comparison_progress(
    trip_and_membership: tuple[Trip, Membership] = Depends(get_trip_for_member),
    session: AsyncSession = Depends(get_session),
) -> ComparisonProgressRead:
    trip, membership = trip_and_membership
    destination_ids = await _destinations_for_city(session, trip.city_id)
    vetoed_by_me = {
        row.destination_id
        for row in (
            await session.scalars(
                select(Preference).where(
                    Preference.trip_id == trip.id,
                    Preference.user_id == membership.user_id,
                    Preference.hard_no.is_(True),
                )
            )
        ).all()
    }
    eligible = [dest_id for dest_id in destination_ids if dest_id not in vetoed_by_me]
    mine = [
        ComparisonInput(user_id=row.user_id, dest_a=row.dest_a, dest_b=row.dest_b, chosen=row.chosen)
        for row in (
            await session.scalars(
                select(Comparison).where(Comparison.trip_id == trip.id, Comparison.user_id == membership.user_id)
            )
        ).all()
    ]
    pair = next_pair(eligible, mine)
    return ComparisonProgressRead(
        done=len(mine),
        target=DEFAULT_CONFIG.target_comparisons,
        next=ComparisonPairRead(dest_a=pair[0], dest_b=pair[1]) if pair else None,
    )


@router.post("/comparisons", response_model=ComparisonProgressRead, status_code=status.HTTP_201_CREATED)
async def submit_comparison(
    payload: SubmitComparisonRequest,
    trip_and_membership: tuple[Trip, Membership] = Depends(get_trip_for_member),
    session: AsyncSession = Depends(get_session),
) -> ComparisonProgressRead:
    trip, membership = trip_and_membership

    valid_ids = set(await _destinations_for_city(session, trip.city_id))
    if payload.dest_a not in valid_ids or payload.dest_b not in valid_ids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Both destinations must belong to this trip's city",
        )

    session.add(
        Comparison(
            trip_id=trip.id,
            user_id=membership.user_id,
            dest_a=payload.dest_a,
            dest_b=payload.dest_b,
            chosen=payload.chosen,
        )
    )
    names = await _destination_names(session, [payload.dest_a, payload.dest_b])
    rejected = payload.dest_b if payload.chosen == payload.dest_a else payload.dest_a
    chosen_name, chosen_category = names.get(payload.chosen, (str(payload.chosen), None))
    rejected_name, rejected_category = names.get(rejected, (str(rejected), None))
    await record_input_embedding(
        session,
        user_id=membership.user_id,
        trip_id=trip.id,
        input_kind="comparison",
        source_id=f"{payload.dest_a}:{payload.dest_b}:{membership.user_id}",
        text=describe_comparison(
            chosen_name=chosen_name,
            rejected_name=rejected_name,
            chosen_category=chosen_category,
            rejected_category=rejected_category,
        ),
    )
    await session.commit()
    return await get_comparison_progress(trip_and_membership=trip_and_membership, session=session)


@router.get("/results", response_model=GroupResultsRead)
async def get_group_results(
    trip_and_membership: tuple[Trip, Membership] = Depends(get_trip_for_member),
    session: AsyncSession = Depends(get_session),
) -> GroupResultsRead:
    trip, _ = trip_and_membership
    destination_ids = await _destinations_for_city(session, trip.city_id)
    members = await _joined_members(session, trip.id)
    prefs = await _trip_preferences(session, trip.id)
    comps = await _trip_comparisons(session, trip.id)

    ranking = compute_ranking(destination_ids, members, prefs, comps)

    return GroupResultsRead(
        rows=[
            RankingRowRead(
                destination_id=row.destination_id,
                rank=row.rank,
                raw_points=row.raw_points,
                raw_votes=row.raw_votes,
                weighted_points=row.weighted_points,
                group_score=row.group_score,
                min_member_utility=row.min_member_utility,
                vetoed_by=row.vetoed_by,
            )
            for row in ranking.rows
        ],
        top_picks=[
            MemberTopPickRead(user_id=user_id, destination_id=destination_id)
            for user_id, destination_id in ranking.top_picks.items()
        ],
        config=PreferenceConfigRead(
            point_budget=DEFAULT_CONFIG.point_budget,
            point_cap=DEFAULT_CONFIG.point_cap,
            target_comparisons=DEFAULT_CONFIG.target_comparisons,
        ),
        computed_at=datetime.now(timezone.utc),
    )
