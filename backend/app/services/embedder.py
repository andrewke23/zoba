"""Embed member inputs as semantic vectors for later analysis.

Every input a member submits (trip setup, preference allocations, pairwise
comparisons, expenses) is rendered as a short English sentence and embedded
with a local sentence-embedding model (fastembed, ONNX on CPU). Inputs that
mean similar things land close together even when they share no words, e.g.
"Uber to Navy Pier" and "Taxi to O'Hare airport". The model runs in-process,
so member text never leaves the server.

Vectors are stored with a pointer back to the source row (``input_kind`` +
``source_id``) rather than a copy of the raw input, so deleting the source row
is enough to remove its readable content. ``embedder_version`` records the
model, and only vectors with the same version are comparable.
"""

import asyncio
import logging
import threading
from datetime import date, time
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.entities import InputEmbedding

if TYPE_CHECKING:
    from fastembed import TextEmbedding

logger = logging.getLogger(__name__)

_model: "TextEmbedding | None" = None
_model_lock = threading.Lock()


def embedder_version() -> str:
    return get_settings().embedding_model


def _get_model() -> "TextEmbedding":
    global _model
    with _model_lock:
        if _model is None:
            from fastembed import TextEmbedding

            # Cache location comes from FASTEMBED_CACHE_PATH; the Docker image
            # pre-downloads the model there so containers never fetch it.
            _model = TextEmbedding(embedder_version())
        return _model


def warm_up() -> None:
    """Load the model now so the first request does not pay for it."""
    _get_model()


def embed_text(text: str) -> list[float]:
    """Embed one text as a unit-length vector (384 floats for bge-small)."""
    (vector,) = _get_model().embed([text])
    return [float(component) for component in vector]


def _clock(value: time) -> str:
    return value.strftime("%H:%M")


def _day(value: date) -> str:
    return f"{value:%A} {value:%B} {value.day}"


def describe_trip(
    *,
    city_name: str,
    start_date: date,
    end_date: date,
    daily_start_time: time,
    daily_end_time: time,
) -> str:
    """Organizer trip setup (F02)."""
    days = (end_date - start_date).days + 1
    length = "a one-day trip" if days == 1 else f"a {days}-day trip"
    return (
        f"Group trip to {city_name}: {length} from {_day(start_date)} to {_day(end_date)}, "
        f"out each day from {_clock(daily_start_time)} to {_clock(daily_end_time)}."
    )


def describe_expense(*, description: str) -> str:
    """Shared expense entry (F17).

    Only the description is embedded: amount, payer and date are already
    structured columns on the expense row, and including them would pull every
    expense towards every other one.
    """
    return f"Shared trip expense: {description.strip()}"


def _place(name: str, category: str | None) -> str:
    return f"{name} ({category})" if category else name


def describe_preference(
    *,
    destination_name: str,
    category: str | None = None,
    points: int | None = None,
    point_budget: int | None = None,
    rank: int | None = None,
    hard_no: bool = False,
) -> str:
    """Point allocation, rank, or veto for one destination (F07a, F08)."""
    place = _place(destination_name, category)
    if hard_no:
        return f"Refuses to visit {place} (hard no)."
    parts = []
    if points is not None:
        parts.append(f"gave {points} of {point_budget} points to {place}" if point_budget else f"gave {points} points to {place}")
    if rank is not None:
        parts.append(f"ranked {place} number {rank}")
    return ("Wants to visit: " + " and ".join(parts) + ".") if parts else f"Wants to visit {place}."


def describe_comparison(
    *,
    chosen_name: str,
    rejected_name: str,
    chosen_category: str | None = None,
    rejected_category: str | None = None,
) -> str:
    """One this-or-that choice (F03)."""
    return f"Prefers {_place(chosen_name, chosen_category)} over {_place(rejected_name, rejected_category)}."


async def record_input_embedding(
    session: AsyncSession,
    *,
    user_id: UUID,
    trip_id: UUID | None,
    input_kind: str,
    source_id: str,
    text: str,
) -> InputEmbedding | None:
    """Embed ``text`` and add the row to ``session``; the caller's commit persists it.

    Embeddings only feed later analysis, so a model failure is logged and the
    member's request still succeeds without one.
    """
    try:
        vector = await asyncio.to_thread(embed_text, text)
    except Exception:
        logger.exception("Could not embed %s input %s", input_kind, source_id)
        return None
    embedding = InputEmbedding(
        user_id=user_id,
        trip_id=trip_id,
        input_kind=input_kind,
        source_id=source_id,
        embedder_version=embedder_version(),
        vector=vector,
    )
    session.add(embedding)
    return embedding
