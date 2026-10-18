import math
from datetime import date, datetime, time, timezone
from decimal import Decimal
from uuid import UUID

from app.services.embedder import (
    EMBEDDING_DIM,
    comparison_features,
    embed_features,
    expense_features,
    preference_features,
    trip_features,
)

MUSEUM = UUID("00000000-0000-0000-0000-00000000000a")
PARK = UUID("00000000-0000-0000-0000-00000000000b")


def _cosine(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right))


def test_embedding_is_fixed_length_unit_vector() -> None:
    vector = embed_features({"description": "Shared dinner downtown", "log_amount": 0.4})

    assert len(vector) == EMBEDDING_DIM
    assert math.isclose(math.sqrt(sum(value * value for value in vector)), 1.0)


def test_embedding_is_deterministic() -> None:
    features = {"city": "chicago", "trip_days": 1.2}

    assert embed_features(features) == embed_features(dict(features))


def test_empty_features_embed_to_zero_vector() -> None:
    assert embed_features({"description": "   "}) == [0.0] * EMBEDDING_DIM


def test_text_is_case_and_punctuation_insensitive() -> None:
    assert embed_features({"description": "Taxi to O'Hare!"}) == embed_features({"description": "taxi to o hare"})


def test_similar_inputs_are_closer_than_different_ones() -> None:
    dinner = embed_features({"description": "group dinner at pizza place"})
    pizza = embed_features({"description": "pizza dinner"})
    museum = embed_features({"description": "art institute tickets"})

    assert _cosine(dinner, pizza) > _cosine(dinner, museum)


def test_trip_features_embed() -> None:
    features = trip_features(
        city_id="chicago",
        start_date=date(2026, 11, 6),
        end_date=date(2026, 11, 8),
        daily_start_time=time(9, 0),
        daily_end_time=time(21, 0),
        home_base_lat=41.88,
        home_base_lon=-87.63,
    )

    assert features["city"] == "chicago"
    assert math.isclose(features["day_window_hours"], 0.5)
    assert len(embed_features(features)) == EMBEDDING_DIM


def test_expense_features_embed() -> None:
    features = expense_features(
        description="Shared dinner",
        amount=Decimal("20.50"),
        split_count=2,
        spent_at=datetime(2026, 10, 15, 19, 30, tzinfo=timezone.utc),
    )

    assert features["spent_hour"] == "h19"
    assert len(embed_features(features)) == EMBEDDING_DIM


def test_veto_differs_from_allocation_for_same_destination() -> None:
    liked = embed_features(preference_features(destination_id=MUSEUM, category="museum", points=40, point_budget=100))
    vetoed = embed_features(preference_features(destination_id=MUSEUM, category="museum", hard_no=True))

    assert liked != vetoed


def test_comparison_direction_matters() -> None:
    museum_wins = embed_features(comparison_features(chosen_id=MUSEUM, rejected_id=PARK))
    park_wins = embed_features(comparison_features(chosen_id=PARK, rejected_id=MUSEUM))

    assert museum_wins != park_wins
