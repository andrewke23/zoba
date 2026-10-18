from uuid import UUID

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.security import get_current_user_id
from app.models.entities import Membership, MembershipRole, MembershipStatus, Trip

# Matches the frontend's "3–8 travelers" guidance and the member cap shown in
# trip settings ("X of 8").
MAX_TRIP_MEMBERS = 8


async def get_trip_for_member(
    trip_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
) -> tuple[Trip, Membership]:
    trip = await session.get(Trip, trip_id)
    if trip is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trip not found")

    membership = await session.scalar(
        select(Membership).where(
            Membership.trip_id == trip_id,
            Membership.user_id == user_id,
            Membership.status == MembershipStatus.JOINED,
        )
    )
    if membership is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Trip membership required")
    return trip, membership


async def require_trip_organizer(
    trip_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
) -> tuple[Trip, Membership]:
    trip, membership = await get_trip_for_member(trip_id, user_id, session)
    if membership.role != MembershipRole.ORGANIZER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Trip organizer required")
    return trip, membership
