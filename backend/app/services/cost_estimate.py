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
