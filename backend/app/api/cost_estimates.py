from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_trip_for_member
from app.core.database import get_session
from app.models.entities import Destination, ItineraryStop, Membership, Trip
from app.schemas.expenses import CostEstimateRead
from app.services.cost_estimate import estimate_admission_costs

router = APIRouter(prefix="/trips/{trip_id}")


@router.get("/cost-estimate", response_model=CostEstimateRead)
async def read_cost_estimate(
    trip_and_membership: tuple[Trip, Membership] = Depends(get_trip_for_member),
    session: AsyncSession = Depends(get_session),
) -> CostEstimateRead:
    trip, _ = trip_and_membership
    admission_costs = (
        await session.scalars(
            select(Destination.admission_cost_usd)
            .join(ItineraryStop, ItineraryStop.destination_id == Destination.id)
            .where(ItineraryStop.trip_id == trip.id)
        )
    ).all()
    estimate = estimate_admission_costs(admission_costs)
    return CostEstimateRead(
        trip_id=trip.id,
        currency="USD",
        per_person_total=estimate.per_person_total,
        itinerary_stop_count=estimate.itinerary_stop_count,
        priced_stop_count=estimate.priced_stop_count,
        unpriced_stop_count=estimate.unpriced_stop_count,
        is_complete=estimate.is_complete,
    )
