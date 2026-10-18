"""Invite links: the organizer shares /join/{token}, anyone signed in can join.

GET /invites/{token} is intentionally unauthenticated so the join page can show
trip details before the visitor logs in. The unguessable token is the
authorization: it is the shareable link itself.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import MAX_TRIP_MEMBERS, count_joined_members
from app.api.trips import trip_read
from app.core.database import get_session
from app.core.security import get_current_user_id
from app.models.entities import City, Membership, MembershipRole, MembershipStatus, Trip, User
from app.schemas.trips import InviteRead, MemberRead

router = APIRouter(prefix="/invites")


async def _trip_for_token(session: AsyncSession, token: str) -> Trip:
    trip = await session.scalar(select(Trip).where(Trip.invite_token == token))
    if trip is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invite not found")
    return trip


@router.get("/{token}", response_model=InviteRead)
async def read_invite(
    token: str,
    session: AsyncSession = Depends(get_session),
) -> InviteRead:
    trip = await _trip_for_token(session, token)
    city_name = await session.scalar(select(City.name).where(City.city_id == trip.city_id))
    organizer = await session.get(User, trip.organizer_id)
    return InviteRead(
        trip=await trip_read(session, trip),
        city_name=city_name or "",
        organizer_name=organizer.name if organizer else "",
    )


@router.post("/{token}/join", response_model=MemberRead)
async def join_via_invite(
    token: str,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
) -> MemberRead:
    trip = await _trip_for_token(session, token)
    user = await session.get(User, user_id)

    membership = await session.get(Membership, (trip.id, user_id))
    if membership is not None:
        if membership.status == MembershipStatus.INVITED:
            membership.status = MembershipStatus.JOINED
            await session.commit()
        return MemberRead(
            user_id=user_id,
            email=user.email if user else "",
            display_name=user.name if user else "",
            role=membership.role,
            status=membership.status,
        )

    if await count_joined_members(session, trip.id) >= MAX_TRIP_MEMBERS:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Trip is full")

    membership = Membership(
        trip_id=trip.id,
        user_id=user_id,
        role=MembershipRole.MEMBER,
        status=MembershipStatus.JOINED,
    )
    session.add(membership)
    await session.commit()
    return MemberRead(
        user_id=user_id,
        email=user.email if user else "",
        display_name=user.name if user else "",
        role=membership.role,
        status=membership.status,
    )
