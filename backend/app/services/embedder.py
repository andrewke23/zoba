"""Embed member inputs as fixed-length vectors for later analysis.

Every input a member submits (trip setup, preference allocations, pairwise
comparisons, expenses) is turned into a flat feature dict and projected into
``EMBEDDING_DIM`` dimensions with the signed hashing trick (each feature
spread over ``HASHES_PER_FEATURE`` buckets), then L2-normalized.
The projection is deterministic and needs no trained model, so vectors written
today stay comparable with vectors written later under the same
``EMBEDDER_VERSION``. Bump the version whenever feature extraction changes.

Vectors are stored with a pointer back to the source row (``input_kind`` +
``source_id``) rather than a copy of the raw input, so deleting the source row
is enough to remove its readable content.
"""

import hashlib
import math
import re
from collections.abc import Mapping
from datetime import date, datetime, time
from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import InputEmbedding

EMBEDDING_DIM = 512
HASHES_PER_FEATURE = 3
EMBEDDER_VERSION = "hash-v3"

# Relative weight of each feature's contribution; unlisted features weigh 1.
# Free text carries what the input is about, so it outweighs context such as
# when an expense happened, which would otherwise pull unrelated inputs
# together just for sharing a weekday.
FEATURE_WEIGHTS: dict[str, float] = {
    "description": 3.0,
    "spent_hour": 0.5,
    "spent_weekday": 0.5,
}

FeatureValue = str | bool | int | float | Decimal
_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset({"a", "an", "and", "at", "for", "from", "in", "of", "on", "s", "the", "to", "with"})


def _buckets(key: str) -> list[tuple[int, float]]:
    """``HASHES_PER_FEATURE`` (index, sign) pairs for ``key``.

    Spreading each feature over several buckets means a collision between two
    unrelated features only shares a fraction of their weight.
    """
    digest = hashlib.blake2b(key.encode("utf-8"), digest_size=8 * HASHES_PER_FEATURE).digest()
    buckets = []
    for offset in range(0, len(digest), 8):
        value = int.from_bytes(digest[offset : offset + 8], "big")
        buckets.append((value % EMBEDDING_DIM, 1.0 if (value >> 63) else -1.0))
    return buckets


def _add(vector: list[float], key: str, weight: float) -> None:
    share = weight / math.sqrt(HASHES_PER_FEATURE)
    for index, sign in _buckets(key):
        vector[index] += sign * share


def tokenize(text: str) -> list[str]:
    return [token for token in _TOKEN_PATTERN.findall(text.lower()) if token not in _STOPWORDS]


def embed_features(features: Mapping[str, FeatureValue]) -> list[float]:
    """Project named features into a unit vector of ``EMBEDDING_DIM`` floats.

    Numbers and booleans contribute their value to the bucket of the feature
    name. Strings contribute to the bucket of ``name=token`` for each token,
    scaled so a whole text weighs the same however many words it has. Each
    feature is then scaled by its ``FEATURE_WEIGHTS`` entry.
    """
    vector = [0.0] * EMBEDDING_DIM
    for name, value in features.items():
        feature_weight = FEATURE_WEIGHTS.get(name, 1.0)
        if isinstance(value, str):
            tokens = tokenize(value)
            if not tokens:
                continue
            weight = feature_weight / math.sqrt(len(tokens))
            for token in tokens:
                _add(vector, f"{name}={token}", weight)
        else:
            _add(vector, name, feature_weight * float(value))

    norm = math.sqrt(sum(component * component for component in vector))
    if norm == 0:
        return vector
    return [component / norm for component in vector]


def _minutes(value: time) -> int:
    return value.hour * 60 + value.minute


def trip_features(
    *,
    city_id: str,
    start_date: date,
    end_date: date,
    daily_start_time: time,
    daily_end_time: time,
    home_base_lat: float,
    home_base_lon: float,
) -> dict[str, FeatureValue]:
    """Organizer trip setup (F02)."""
    return {
        "city": city_id,
        "trip_days": math.log1p((end_date - start_date).days + 1),
        "start_weekday": f"d{start_date.weekday()}",
        "start_month": f"m{start_date.month}",
        "day_start_hours": _minutes(daily_start_time) / 60 / 24,
        "day_window_hours": (_minutes(daily_end_time) - _minutes(daily_start_time)) / 60 / 24,
        "home_lat": home_base_lat / 90,
        "home_lon": home_base_lon / 180,
    }


def expense_features(
    *,
    description: str,
    amount: Decimal,
    split_count: int,
    spent_at: datetime,
) -> dict[str, FeatureValue]:
    """Shared expense entry (F17)."""
    return {
        "description": description,
        "log_amount": math.log1p(float(amount)) / 10,
        "split_count": split_count / 8,
        "spent_hour": f"h{spent_at.hour}",
        "spent_weekday": f"d{spent_at.weekday()}",
    }


def preference_features(
    *,
    destination_id: UUID,
    category: str | None = None,
    points: int | None = None,
    point_budget: int | None = None,
    rank: int | None = None,
    hard_no: bool = False,
) -> dict[str, FeatureValue]:
    """Point allocation, rank, or veto for one destination (F07a, F08)."""
    features: dict[str, FeatureValue] = {"destination": destination_id.hex, "hard_no": hard_no}
    if category:
        features["category"] = category
    if points is not None:
        features["points_share"] = points / point_budget if point_budget else float(points)
    if rank is not None:
        features["inverse_rank"] = 1 / rank
    return features


def comparison_features(
    *,
    chosen_id: UUID,
    rejected_id: UUID,
    chosen_category: str | None = None,
    rejected_category: str | None = None,
) -> dict[str, FeatureValue]:
    """One this-or-that choice (F03)."""
    features: dict[str, FeatureValue] = {"chosen": chosen_id.hex, "rejected": rejected_id.hex}
    if chosen_category:
        features["chosen_category"] = chosen_category
    if rejected_category:
        features["rejected_category"] = rejected_category
    return features


def record_input_embedding(
    session: AsyncSession,
    *,
    user_id: UUID,
    trip_id: UUID | None,
    input_kind: str,
    source_id: str,
    features: Mapping[str, FeatureValue],
) -> InputEmbedding:
    """Add an embedding row to ``session``; the caller's commit persists it."""
    embedding = InputEmbedding(
        user_id=user_id,
        trip_id=trip_id,
        input_kind=input_kind,
        source_id=source_id,
        embedder_version=EMBEDDER_VERSION,
        vector=embed_features(features),
    )
    session.add(embedding)
    return embedding
