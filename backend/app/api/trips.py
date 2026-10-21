import secrets
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from geoalchemy2.elements import WKTElement
from geoalchemy2.types import Geometry
from sqlalchemy import cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.api.dependencies import get_trip_for_member, require_trip_organizer
from app.core.database import get_session
from app.core.security import get_current_user_id
from app.models.entities import City, Membership, MembershipRole, MembershipStatus, Trip, User
from app.schemas.trips import (
    MemberCreate,
    MemberRead,
    TripCreate,
    TripMemberRead,
    TripRead,
    TripSummaryRead,
)
from app.schemas.trips import MemberCreate, MemberRead, TripCreate, TripRead, TripSummaryRead
from app.services.embedder import describe_trip, record_input_embedding

router = APIRouter(prefix="/trips")


@router.get("", response_model=list[TripSummaryRead])
async def list_trips(
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
) -> list[TripSummaryRead]:
    my_membership = aliased(Membership)
    joined_member_count = (
        select(func.count(Membership.user_id))
        .where(
            Membership.trip_id == Trip.id,
            Membership.status == MembershipStatus.JOINED,
        )
        .correlate(Trip)
        .scalar_subquery()
    )
    result = await session.execute(
        select(
            Trip,
            City.name,
            my_membership.role,
            joined_member_count,
            func.ST_Y(cast(Trip.home_base, Geometry(srid=4326))),
            func.ST_X(cast(Trip.home_base, Geometry(srid=4326))),
        )
        .join(City, City.city_id == Trip.city_id)
        .join(my_membership, my_membership.trip_id == Trip.id)
        .where(
            my_membership.user_id == user_id,
            my_membership.status == MembershipStatus.JOINED,
        )
        .order_by(Trip.created_at.desc(), Trip.id.desc())
    )

    return [
        TripSummaryRead(
            id=trip.id,
            organizer_id=trip.organizer_id,
            city_id=trip.city_id,
            name=trip.name,
            start_date=trip.start_date,
            end_date=trip.end_date,
            daily_start_time=trip.daily_start_time,
            daily_end_time=trip.daily_end_time,
            home_base_lat=latitude,
            home_base_lon=longitude,
            home_base_label=trip.home_base_label,
            invite_token=trip.invite_token,
            created_at=trip.created_at,
            city_name=city_name,
            my_role=role,
            member_count=member_count,
        )
        for trip, city_name, role, member_count, latitude, longitude in result.all()
    ]


@router.post("", response_model=TripRead, status_code=status.HTTP_201_CREATED)
async def create_trip(
    payload: TripCreate,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
) -> TripRead:
    if user_id != payload.organizer_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the authenticated organizer can create this trip",
        )
    city_name = await session.scalar(select(City.name).where(City.city_id == payload.city_id))
    if city_name is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unknown city_id")

    trip = Trip(
        organizer_id=user_id,
        city_id=payload.city_id,
        name=payload.name,
        start_date=payload.start_date,
        end_date=payload.end_date,
        daily_start_time=payload.daily_start_time,
        daily_end_time=payload.daily_end_time,
        home_base_label=payload.home_base_label,
        home_base=WKTElement(
            f"POINT({payload.home_base_lon} {payload.home_base_lat})",
            srid=4326,
        ),
        home_base_label=payload.home_base_label,
        invite_token=secrets.token_urlsafe(18),
    )
    session.add(trip)
    await session.flush()
    session.add(
        Membership(
            trip_id=trip.id,
            user_id=user_id,
            role=MembershipRole.ORGANIZER,
            status=MembershipStatus.JOINED,
        )
    )
    await record_input_embedding(
        session,
        user_id=user_id,
        trip_id=trip.id,
        input_kind="trip",
        source_id=str(trip.id),
        text=describe_trip(
            city_name=city_name,
            start_date=payload.start_date,
            end_date=payload.end_date,
            daily_start_time=payload.daily_start_time,
            daily_end_time=payload.daily_end_time,
        ),
    )
    await session.commit()
    return await trip_read(session, trip)


@router.get("", response_model=list[TripSummaryRead])
async def list_trips(
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
) -> list[TripSummaryRead]:
    """Trips the authenticated user has joined, newest first."""
    rows = (
        await session.execute(
            select(Trip, City.name, Membership.role)
            .join(Membership, Membership.trip_id == Trip.id)
            .join(City, City.city_id == Trip.city_id)
            .where(Membership.user_id == user_id, Membership.status == MembershipStatus.JOINED)
            .order_by(Trip.created_at.desc())
        )
    ).all()
    if not rows:
        return []
    member_counts = dict(
        (
            await session.execute(
                select(Membership.trip_id, func.count())
                .where(
                    Membership.trip_id.in_([trip.id for trip, _, _ in rows]),
                    Membership.status == MembershipStatus.JOINED,
                )
                .group_by(Membership.trip_id)
            )
        ).all()
    )
    return [
        TripSummaryRead(
            **(await trip_read(session, trip)).model_dump(),
            city_name=city_name,
            my_role=role,
            member_count=member_counts.get(trip.id, 0),
        )
        for trip, city_name, role in rows
    ]


@router.get("/{trip_id}", response_model=TripRead)
async def read_trip(
    trip_and_membership: tuple[Trip, Membership] = Depends(get_trip_for_member),
    session: AsyncSession = Depends(get_session),
) -> TripRead:
    trip, _ = trip_and_membership
    return await trip_read(session, trip)


@router.get("/{trip_id}/members", response_model=list[TripMemberRead])
async def list_trip_members(
    trip_and_membership: tuple[Trip, Membership] = Depends(get_trip_for_member),
    session: AsyncSession = Depends(get_session),
) -> list[TripMemberRead]:
    trip, _ = trip_and_membership
    rows = (
        await session.execute(
            select(Membership, User.email, User.name)
            .join(User, User.id == Membership.user_id)
            .where(Membership.trip_id == trip.id)
            .order_by(Membership.role, User.name, User.email)
        )
    ).all()
    return [
        TripMemberRead(
            user_id=membership.user_id,
            email=email,
            display_name=name,
            role=membership.role,
            status=membership.status,
        )
        for membership, email, name in rows
    ]
@router.get("/{trip_id}/members", response_model=list[MemberRead])
async def list_members(
    trip_and_membership: tuple[Trip, Membership] = Depends(get_trip_for_member),
    session: AsyncSession = Depends(get_session),
) -> list[MemberRead]:
    trip, _ = trip_and_membership
    rows = (
        await session.execute(
            select(Membership, User)
            .join(User, User.id == Membership.user_id)
            .where(Membership.trip_id == trip.id)
            .order_by(Membership.role, User.name)
        )
    ).all()
    return [member_read(membership, user) for membership, user in rows]


@router.post(
    "/{trip_id}/members",
    response_model=MemberRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_member(
    payload: MemberCreate,
    trip_and_membership: tuple[Trip, Membership] = Depends(require_trip_organizer),
    session: AsyncSession = Depends(get_session),
) -> MemberRead:
    trip, _ = trip_and_membership
    user = await session.get(User, payload.user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    existing = await session.get(Membership, (trip.id, payload.user_id))
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="User is already a trip member")

    membership = Membership(
        trip_id=trip.id,
        user_id=payload.user_id,
        role=MembershipRole.MEMBER,
        status=MembershipStatus.INVITED,
    )
    session.add(membership)
    await session.commit()
    return member_read(membership, user)


@router.post("/{trip_id}/members/accept", response_model=MemberRead)
async def accept_invitation(
    trip_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
) -> MemberRead:
    membership = await session.get(Membership, (trip_id, user_id))
    if membership is None or membership.status != MembershipStatus.INVITED:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pending trip invitation not found")

    membership.status = MembershipStatus.JOINED
    await session.commit()
    user = await session.get(User, user_id)
    return member_read(membership, user)


def member_read(membership: Membership, user: User) -> MemberRead:
    return MemberRead(
        user_id=membership.user_id,
        email=user.email,
        display_name=user.name,
        role=membership.role,
        status=membership.status,
    )


async def trip_read(session: AsyncSession, trip: Trip) -> TripRead:
    coordinates = await session.execute(
        select(
            func.ST_Y(cast(Trip.home_base, Geometry(srid=4326))),
            func.ST_X(cast(Trip.home_base, Geometry(srid=4326))),
        ).where(Trip.id == trip.id)
    )
    latitude, longitude = coordinates.one()
    return TripRead(
        id=trip.id,
        organizer_id=trip.organizer_id,
        city_id=trip.city_id,
        name=trip.name,
        start_date=trip.start_date,
        end_date=trip.end_date,
        daily_start_time=trip.daily_start_time,
        daily_end_time=trip.daily_end_time,
        home_base_lat=latitude,
        home_base_lon=longitude,
        home_base_label=trip.home_base_label,
        invite_token=trip.invite_token,
        created_at=trip.created_at,
    )
