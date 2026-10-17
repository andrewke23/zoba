from decimal import Decimal

from app.services.cost_estimate import estimate_admission_costs


def test_sums_priced_admissions_and_tracks_unknown_stops() -> None:
    estimate = estimate_admission_costs(
        [Decimal("12.50"), None, Decimal("8.25"), None]
    )

    assert estimate.per_person_total == Decimal("20.75")
    assert estimate.itinerary_stop_count == 4
    assert estimate.priced_stop_count == 2
    assert estimate.unpriced_stop_count == 2
    assert not estimate.is_complete


def test_empty_itinerary_is_a_complete_zero_estimate() -> None:
    estimate = estimate_admission_costs([])

    assert estimate.per_person_total == Decimal(0)
    assert estimate.is_complete
