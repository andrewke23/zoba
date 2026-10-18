import asyncio
import math
from datetime import date, time
from uuid import UUID

import pytest

from app.services import embedder
from app.services.embedder import (
    describe_comparison,
    describe_expense,
    describe_preference,
    describe_trip,
    embed_text,
    record_input_embedding,
)

USER = UUID("00000000-0000-0000-0000-000000000001")


def _cosine(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right))


@pytest.fixture(scope="module")
def model() -> None:
    """Load the embedding model, skipping semantic tests where it is unavailable."""
    pytest.importorskip("fastembed")
    try:
        embedder.warm_up()
    except Exception as error:  # e.g. offline with no cached model
        pytest.skip(f"embedding model unavailable: {error}")


def test_describe_trip() -> None:
    text = describe_trip(
        city_name="Chicago",
        start_date=date(2026, 11, 6),
        end_date=date(2026, 11, 8),
        daily_start_time=time(9, 0),
        daily_end_time=time(21, 0),
    )

    assert text == (
        "Group trip to Chicago: a 3-day trip from Friday November 6 to Sunday November 8, "
        "out each day from 09:00 to 21:00."
    )


def test_describe_one_day_trip() -> None:
    text = describe_trip(
        city_name="Washington, DC",
        start_date=date(2027, 4, 3),
        end_date=date(2027, 4, 3),
        daily_start_time=time(8, 0),
        daily_end_time=time(18, 0),
    )

    assert "a one-day trip" in text


def test_describe_expense_keeps_only_the_description() -> None:
    assert describe_expense(description="  Deep dish pizza dinner ") == "Shared trip expense: Deep dish pizza dinner"


def test_describe_preference_variants() -> None:
    assert describe_preference(destination_name="Field Museum", category="museum", hard_no=True) == (
        "Refuses to visit Field Museum (museum) (hard no)."
    )
    assert describe_preference(destination_name="Navy Pier", points=40, point_budget=100) == (
        "Wants to visit: gave 40 of 100 points to Navy Pier."
    )
    assert describe_preference(destination_name="Navy Pier", rank=2) == "Wants to visit: ranked Navy Pier number 2."


def test_describe_comparison_keeps_direction() -> None:
    assert describe_comparison(chosen_name="Navy Pier", rejected_name="Field Museum") == (
        "Prefers Navy Pier over Field Museum."
    )


def test_record_skips_embedding_when_model_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(_: str) -> list[float]:
        raise RuntimeError("model missing")

    class Session:
        added: list[object] = []

        def add(self, row: object) -> None:
            self.added.append(row)

    monkeypatch.setattr(embedder, "embed_text", broken)
    session = Session()
    result = asyncio.run(
        record_input_embedding(
            session,  # type: ignore[arg-type]
            user_id=USER,
            trip_id=None,
            input_kind="expense",
            source_id="x",
            text="Taxi",
        )
    )

    assert result is None
    assert session.added == []


def test_embedding_is_unit_length(model: None) -> None:
    vector = embed_text(describe_expense(description="Shared dinner downtown"))

    assert len(vector) == 384
    assert math.isclose(math.sqrt(sum(value * value for value in vector)), 1.0, rel_tol=1e-4)


def test_embedding_is_deterministic(model: None) -> None:
    text = describe_expense(description="Shedd Aquarium tickets")

    assert embed_text(text) == embed_text(text)


def test_meaning_matches_without_shared_words(model: None) -> None:
    uber = embed_text(describe_expense(description="Uber to Navy Pier"))
    taxi = embed_text(describe_expense(description="Taxi to O'Hare airport"))
    pizza = embed_text(describe_expense(description="Deep dish pizza dinner"))

    assert _cosine(uber, taxi) > _cosine(uber, pizza)


def test_similar_expenses_are_nearest(model: None) -> None:
    dinner = embed_text(describe_expense(description="Deep dish pizza dinner"))
    lunch = embed_text(describe_expense(description="Pizza lunch at Lou Malnati's"))
    tickets = embed_text(describe_expense(description="Architecture river cruise tickets"))

    assert _cosine(dinner, lunch) > _cosine(dinner, tickets)
