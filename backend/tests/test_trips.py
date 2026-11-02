import asyncio
from datetime import date, datetime, time, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import httpx

from app.core.database import get_session
from app.core.security import get_current_user_id
from app.api.dependencies import get_trip_for_member
from app.main import app


def test_get_trips_returns_joined_trip_summaries() -> None:
    user_id = UUID("00000000-0000-0000-0000-000000000011")
    trip_id = UUID("00000000-0000-0000-0000-000000000010")
    trip = SimpleNamespace(
        id=trip_id,
        organizer_id=user_id,
        city_id="chicago",
        name="Chicago weekend",
        start_date=date(2026, 11, 1),
        end_date=date(2026, 11, 3),
        daily_start_time=time(9),
        daily_end_time=time(18),
        home_base_label="Downtown",
        invite_token="invite-token",
        created_at=datetime(2026, 10, 20, tzinfo=timezone.utc),
    )
    session = AsyncMock()
    session.execute.return_value = SimpleNamespace(
        all=lambda: [(trip, "Chicago", "organizer", 2, 41.88, -87.63)]
    )

    async def exercise_endpoint() -> httpx.Response:
        async def override_user_id() -> UUID:
            return user_id

        async def override_session() -> AsyncMock:
            return session

        app.dependency_overrides[get_current_user_id] = override_user_id
        app.dependency_overrides[get_session] = override_session
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                return await client.get("/api/v1/trips")
        finally:
            app.dependency_overrides.clear()

    response = asyncio.run(exercise_endpoint())

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": str(trip_id),
            "organizer_id": str(user_id),
            "city_id": "chicago",
            "name": "Chicago weekend",
            "start_date": "2026-11-01",
            "end_date": "2026-11-03",
            "daily_start_time": "09:00:00",
            "daily_end_time": "18:00:00",
            "home_base_lat": 41.88,
            "home_base_lon": -87.63,
            "home_base_label": "Downtown",
            "invite_token": "invite-token",
            "created_at": "2026-10-20T00:00:00Z",
            "city_name": "Chicago",
            "my_role": "organizer",
            "member_count": 2,
        }
    ]


def test_get_cities_returns_pipeline_cities() -> None:
    session = AsyncMock()
    session.execute.return_value = SimpleNamespace(
        all=lambda: [("chicago", "Chicago", -87.63, 41.88, "America/Chicago")]
    )

    async def exercise_endpoint() -> httpx.Response:
        async def override_session() -> AsyncMock:
            return session

        app.dependency_overrides[get_session] = override_session
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                return await client.get("/api/v1/cities")
        finally:
            app.dependency_overrides.clear()

    response = asyncio.run(exercise_endpoint())

    assert response.status_code == 200
    assert response.json() == [
        {
            "city_id": "chicago",
            "name": "Chicago",
            "center": [-87.63, 41.88],
            "timezone": "America/Chicago",
        }
    ]


def test_get_trip_members_returns_member_details() -> None:
    trip_id = UUID("00000000-0000-0000-0000-000000000010")
    user_id = UUID("00000000-0000-0000-0000-000000000011")
    trip = SimpleNamespace(id=trip_id)
    membership = SimpleNamespace(
        trip_id=trip_id,
        user_id=user_id,
        role="organizer",
        status="joined",
    )
    session = AsyncMock()
    session.execute.return_value = SimpleNamespace(
        all=lambda: [(membership, "organizer@example.com", "Organizer")]
    )

    async def exercise_endpoint() -> httpx.Response:
        async def override_trip_membership() -> tuple[SimpleNamespace, SimpleNamespace]:
            return trip, membership

        async def override_session() -> AsyncMock:
            return session

        app.dependency_overrides[get_trip_for_member] = override_trip_membership
        app.dependency_overrides[get_session] = override_session
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                return await client.get(f"/api/v1/trips/{trip_id}/members")
        finally:
            app.dependency_overrides.clear()

    response = asyncio.run(exercise_endpoint())

    assert response.status_code == 200
    assert response.json() == [
        {
            "user_id": str(user_id),
            "email": "organizer@example.com",
            "display_name": "Organizer",
            "role": "organizer",
            "status": "joined",
        }
    ]


def test_get_settlement_returns_balances_and_transfers() -> None:
    trip_id = UUID("00000000-0000-0000-0000-000000000010")
    payer_id = UUID("00000000-0000-0000-0000-000000000011")
    debtor_id = UUID("00000000-0000-0000-0000-000000000012")
    trip = SimpleNamespace(id=trip_id)
    membership = SimpleNamespace(trip_id=trip_id, user_id=payer_id)
    session = AsyncMock()
    session.scalars.return_value = SimpleNamespace(all=lambda: [payer_id, debtor_id])
    session.execute.side_effect = [
        [(payer_id, 10_000)],
        [(payer_id, 5_000), (debtor_id, 5_000)],
    ]

    async def exercise_endpoint() -> httpx.Response:
        async def override_trip_membership() -> tuple[SimpleNamespace, SimpleNamespace]:
            return trip, membership

        async def override_session() -> AsyncMock:
            return session

        app.dependency_overrides[get_trip_for_member] = override_trip_membership
        app.dependency_overrides[get_session] = override_session
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                return await client.get(f"/api/v1/trips/{trip_id}/settlement")
        finally:
            app.dependency_overrides.clear()

    response = asyncio.run(exercise_endpoint())

    assert response.status_code == 200
    assert response.json() == {
        "balances": [
            {
                "user_id": str(payer_id),
                "paid_cents": 10_000,
                "owed_cents": 5_000,
                "net_cents": 5_000,
            },
            {
                "user_id": str(debtor_id),
                "paid_cents": 0,
                "owed_cents": 5_000,
                "net_cents": -5_000,
            },
        ],
        "transfers": [{"from_user": str(debtor_id), "to_user": str(payer_id), "amount": "50.00"}],
    }
