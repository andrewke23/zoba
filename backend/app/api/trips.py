import secrets
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from geoalchemy2.elements import WKTElement
from geoalchemy2.types import Geometry
from sqlalchemy import cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import (
    MAX_TRIP_MEMBERS,
    count_joined_members,
    get_trip_for_member,
    require_trip_organizer,
)
from app.core.database import get_session
from app.core.security import get_current_user_id
from app.models.entities import City, Membership, MembershipRole, MembershipStatus, Trip, User
from app.schemas.trips import (
    MemberCreate,
    MemberRead,
    TripCreate,
    TripRead,
    TripSummaryRead,
    TripUpdate,
)

router = APIRouter(prefix="/trips")


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
    city_exists = await session.scalar(select(City.city_id).where(City.city_id == payload.city_id))
    if city_exists is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unknown city_id")

    trip = Trip(
        organizer_id=user_id,
        city_id=payload.city_id,
        name=payload.name,
        start_date=payload.start_date,
        end_date=payload.end_date,
        daily_start_time=payload.daily_start_time,
        daily_end_time=payload.daily_end_time,
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
            .where(
                Membership.user_id == user_id,
                Membership.status == MembershipStatus.JOINED,
            )
            .order_by(Trip.created_at.desc())
        )
    ).all()
    if not rows:
        return []
    member_counts = {
        trip_id: count
        for trip_id, count in (
            await session.execute(
                select(Membership.trip_id, func.count())
                .where(
                    Membership.trip_id.in_([trip.id for trip, _, _ in rows]),
                    Membership.status == MembershipStatus.JOINED,
                )
                .group_by(Membership.trip_id)
            )
        ).all()
    }
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


@router.put("/{trip_id}", response_model=TripRead)
async def update_trip(
    payload: TripUpdate,
    trip_and_membership: tuple[Trip, Membership] = Depends(require_trip_organizer),
    session: AsyncSession = Depends(get_session),
) -> TripRead:
    trip, _ = trip_and_membership

    start_date = payload.start_date or trip.start_date
    end_date = payload.end_date or trip.end_date
    if end_date < start_date:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="end_date must be on or after start_date"
        )
    daily_start_time = payload.daily_start_time or trip.daily_start_time
    daily_end_time = payload.daily_end_time or trip.daily_end_time
    if daily_end_time <= daily_start_time:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="daily_end_time must be after daily_start_time"
        )

    if payload.city_id is not None and payload.city_id != trip.city_id:
        city_exists = await session.scalar(select(City.city_id).where(City.city_id == payload.city_id))
        if city_exists is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unknown city_id")
        trip.city_id = payload.city_id
    if payload.name is not None:
        trip.name = payload.name
    trip.start_date = start_date
    trip.end_date = end_date
    trip.daily_start_time = daily_start_time
    trip.daily_end_time = daily_end_time
    if payload.home_base_lat is not None or payload.home_base_lon is not None:
        current_lat, current_lon = await trip_coordinates(session, trip.id)
        latitude = payload.home_base_lat if payload.home_base_lat is not None else current_lat
        longitude = payload.home_base_lon if payload.home_base_lon is not None else current_lon
        trip.home_base = WKTElement(f"POINT({longitude} {latitude})", srid=4326)
    if payload.home_base_label is not None:
        trip.home_base_label = payload.home_base_label

    await session.commit()
    return await trip_read(session, trip)


@router.get("/{trip_id}/members", response_model=list[MemberRead])
async def list_members(
    trip_and_membership: tuple[Trip, Membership] = Depends(get_trip_for_member),
    session: AsyncSession = Depends(get_session),
) -> list[MemberRead]:
    trip, _ = trip_and_membership
    return await trip_members(session, trip.id)


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

    if await count_joined_members(session, trip.id) >= MAX_TRIP_MEMBERS:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Trip is full")

    membership = Membership(
        trip_id=trip.id,
        user_id=payload.user_id,
        role=MembershipRole.MEMBER,
        status=MembershipStatus.INVITED,
    )
    session.add(membership)
    await session.commit()
    return MemberRead(
        user_id=membership.user_id,
        email=user.email,
        display_name=user.name,
        role=membership.role,
        status=membership.status,
    )


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
    return MemberRead(
        user_id=membership.user_id,
        email=user.email if user else "",
        display_name=user.name if user else "",
        role=membership.role,
        status=membership.status,
    )


@router.delete("/{trip_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    user_id: UUID,
    trip_and_membership: tuple[Trip, Membership] = Depends(require_trip_organizer),
    session: AsyncSession = Depends(get_session),
) -> None:
    trip, _ = trip_and_membership
    membership = await session.get(Membership, (trip.id, user_id))
    if membership is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User is not a trip member")
    if membership.role == MembershipRole.ORGANIZER:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="The organizer cannot be removed"
        )
    await session.delete(membership)
    await session.commit()


async def trip_coordinates(session: AsyncSession, trip_id: UUID) -> tuple[float, float]:
    coordinates = await session.execute(
        select(
            func.ST_Y(cast(Trip.home_base, Geometry(srid=4326))),
            func.ST_X(cast(Trip.home_base, Geometry(srid=4326))),
        ).where(Trip.id == trip_id)
    )
    latitude, longitude = coordinates.one()
    return latitude, longitude


async def trip_read(session: AsyncSession, trip: Trip) -> TripRead:
    latitude, longitude = await trip_coordinates(session, trip.id)
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


async def trip_members(session: AsyncSession, trip_id: UUID) -> list[MemberRead]:
    rows = (
        await session.execute(
            select(Membership, User)
            .join(User, User.id == Membership.user_id)
            .where(Membership.trip_id == trip_id)
            .order_by(Membership.role, User.name)
        )
    ).all()
    return [
        MemberRead(
            user_id=membership.user_id,
            email=user.email,
            display_name=user.name,
            role=membership.role,
            status=membership.status,
        )
        for membership, user in rows
    ]
