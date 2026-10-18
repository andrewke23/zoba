from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from geoalchemy2.elements import WKTElement
from geoalchemy2.types import Geometry
from sqlalchemy import cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_trip_for_member, require_trip_organizer
from app.core.database import get_session
from app.core.security import get_current_user_id
from app.models.entities import City, Membership, MembershipRole, MembershipStatus, Trip, User
from app.schemas.trips import MemberCreate, MemberRead, TripCreate, TripRead
from app.services.embedder import describe_trip, record_input_embedding

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
    city_name = await session.scalar(select(City.name).where(City.city_id == payload.city_id))
    if city_name is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unknown city_id")

    trip = Trip(
        organizer_id=user_id,
        city_id=payload.city_id,
        start_date=payload.start_date,
        end_date=payload.end_date,
        daily_start_time=payload.daily_start_time,
        daily_end_time=payload.daily_end_time,
        home_base=WKTElement(
            f"POINT({payload.home_base_lon} {payload.home_base_lat})",
            srid=4326,
        ),
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


@router.get("/{trip_id}", response_model=TripRead)
async def read_trip(
    trip_and_membership: tuple[Trip, Membership] = Depends(get_trip_for_member),
    session: AsyncSession = Depends(get_session),
) -> TripRead:
    trip, _ = trip_and_membership
    return await trip_read(session, trip)


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
    return MemberRead(
        user_id=membership.user_id,
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
    return MemberRead(user_id=membership.user_id, role=membership.role, status=membership.status)


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
        start_date=trip.start_date,
        end_date=trip.end_date,
        daily_start_time=trip.daily_start_time,
        daily_end_time=trip.daily_end_time,
        home_base_lat=latitude,
        home_base_lon=longitude,
    )
