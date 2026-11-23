from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class AdmissionCostEstimate:
    per_person_total: Decimal
    itinerary_stop_count: int
    priced_stop_count: int
    unpriced_stop_count: int

    @property
    def is_complete(self) -> bool:
        return self.unpriced_stop_count == 0


def estimate_admission_costs(costs: Iterable[Decimal | None]) -> AdmissionCostEstimate:
    cost_list = list(costs)
    known_costs = [cost for cost in cost_list if cost is not None]
    return AdmissionCostEstimate(
        per_person_total=sum(known_costs, Decimal(0)),
        itinerary_stop_count=len(cost_list),
        priced_stop_count=len(known_costs),
        unpriced_stop_count=len(cost_list) - len(known_costs),
    )


TRANSIT_FARE_USD = Decimal("2.50")
"""One transit ride, per person (a typical US city single fare)."""

TAXI_FARE_PER_PERSON_USD = Decimal("6.00")
"""A ~$15-20 urban cab ride split among the riders in one car."""


@dataclass(frozen=True)
class TransportCostEstimate:
    per_person_total: Decimal
    transit_leg_count: int
    taxi_leg_count: int


def estimate_transport_costs(modes: Iterable[str | None]) -> TransportCostEstimate:
    """Fares for the itinerary's legs, from the mode stored on each stop.

    Walking is free. Legs with no stored mode (itineraries generated before
    modes were stored) are not counted until the itinerary is next read or
    regenerated, which fills them in.
    """
    mode_list = list(modes)
    transit = mode_list.count("transit")
    taxi = mode_list.count("drive")
    return TransportCostEstimate(
        per_person_total=transit * TRANSIT_FARE_USD + taxi * TAXI_FARE_PER_PERSON_USD,
        transit_leg_count=transit,
        taxi_leg_count=taxi,
    )
