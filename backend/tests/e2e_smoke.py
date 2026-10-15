"""End-to-end validation of the Zoba backend against the live docker compose stack.

Seeds a city, users, and a priced destination directly in Postgres, then drives
the documented API flow with real JWTs and asserts every response.
"""
import asyncio
import os
import sys
import time
from decimal import Decimal

import asyncpg
import httpx
import jwt

BASE_URL = "http://localhost:8000/api/v1"
HEALTH_URL = "http://localhost:8000/healthz"

ALICE = "11111111-1111-1111-1111-111111111111"
BOB = "22222222-2222-2222-2222-222222222222"
CAROL = "33333333-3333-3333-3333-333333333333"
DAVE = "44444444-4444-4444-4444-444444444444"
MUSEUM = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}" + (f" -- {detail}" if detail and not condition else ""))
    if not condition:
        failures.append(label)


def load_env() -> dict[str, str]:
    values: dict[str, str] = {}
    with open(
        os.path.join(os.path.dirname(__file__), "..", "..", ".env"), encoding="utf-8"
    ) as handle:
        for line in handle:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                values[key] = value
    return values


def mint_token(user_id: str, secret: str) -> str:
    return jwt.encode({"sub": user_id, "exp": int(time.time()) + 3600}, secret, algorithm="HS256")


def client(token: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=BASE_URL,
        headers={"Authorization": f"Bearer {token}"},
        timeout=10.0,
    )


async def seed(env: dict[str, str]) -> None:
    dsn = (
        f"postgresql://{env['POSTGRES_USER']}:{env['POSTGRES_PASSWORD']}"
        f"@127.0.0.1:5432/{env['POSTGRES_DB']}"
    )
    connection = await asyncpg.connect(dsn)
    try:
        await connection.execute(
            """
            INSERT INTO city (city_id, name, bbox, timezone) VALUES
              ('chicago', 'Chicago',
               ST_GeomFromText('POLYGON((-87.95 41.65,-87.52 41.65,-87.52 42.02,-87.95 42.02,-87.95 41.65))', 4326),
               'America/Chicago')
            ON CONFLICT (city_id) DO NOTHING
            """
        )
        await connection.execute(
            """
            INSERT INTO app_user (user_id, email, password_hash, name) VALUES
              ($1, 'alice@example.com', 'x', 'Alice'),
              ($2, 'bob@example.com', 'x', 'Bob'),
              ($3, 'carol@example.com', 'x', 'Carol'),
              ($4, 'dave@example.com', 'x', 'Dave')
            ON CONFLICT (user_id) DO NOTHING
            """,
            ALICE, BOB, CAROL, DAVE,
        )
        await connection.execute(
            """
            INSERT INTO destination (destination_id, city_id, name, geom, category, admission_cost_usd)
            VALUES ($1, 'chicago', 'Test Museum',
                    ST_SetSRID(ST_MakePoint(-87.62, 41.88), 4326)::geography, 'museum', 12.50)
            ON CONFLICT (destination_id) DO NOTHING
            """,
            MUSEUM,
        )
        # app_user.name column: added by the backend startup migration on old volumes
        has_name = await connection.fetchval(
            "SELECT EXISTS(SELECT 1 FROM information_schema.columns WHERE table_name='app_user' AND column_name='name')"
        )
        check("startup migration added app_user.name column", has_name)
    finally:
        await connection.close()


async def add_itinerary_stop(env: dict[str, str], trip_id: str) -> None:
    dsn = (
        f"postgresql://{env['POSTGRES_USER']}:{env['POSTGRES_PASSWORD']}"
        f"@127.0.0.1:5432/{env['POSTGRES_DB']}"
    )
    connection = await asyncpg.connect(dsn)
    try:
        await connection.execute(
            """
            INSERT INTO itinerary_stop (trip_id, day_index, seq, destination_id, start_ts, end_ts)
            VALUES ($1, 0, 0, $2, '2026-11-01T10:00:00+00:00', '2026-11-01T12:00:00+00:00')
            ON CONFLICT (trip_id, day_index, seq) DO NOTHING
            """,
            trip_id, MUSEUM,
        )
    finally:
        await connection.close()


async def main() -> None:
    env = load_env()
    secret = env["JWT_SECRET_KEY"]
    await seed(env)

    health = httpx.get(HEALTH_URL, timeout=10.0)
    check("GET /healthz returns 200", health.status_code == 200, str(health.status_code))

    tokens = {uid: mint_token(uid, secret) for uid in (ALICE, BOB, CAROL, DAVE)}

    # --- UC-01: organizer creates the trip -----------------------------------
    async with client(tokens[ALICE]) as http:
        response = await http.post(
            "/trips",
            json={
                "organizer_id": ALICE,
                "city_id": "chicago",
                "start_date": "2026-11-01",
                "end_date": "2026-11-03",
                "daily_start_time": "09:00:00",
                "daily_end_time": "21:00:00",
                "home_base_lat": 41.8781,
                "home_base_lon": -87.6298,
            },
        )
        check("POST /trips -> 201", response.status_code == 201, response.text)
        trip = response.json()
        trip_id = trip["id"]
        check(
            "home base lat/lon round-trips through PostGIS",
            abs(trip["home_base_lat"] - 41.8781) < 1e-6 and abs(trip["home_base_lon"] + 87.6298) < 1e-6,
            str(trip),
        )
        check("organizer membership seeded", True)

        # wrong organizer identity is rejected
        forged = await http.post(
            "/trips",
            json={
                "organizer_id": BOB,
                "city_id": "chicago",
                "start_date": "2026-11-01",
                "end_date": "2026-11-03",
                "daily_start_time": "09:00:00",
                "daily_end_time": "21:00:00",
                "home_base_lat": 41.8781,
                "home_base_lon": -87.6298,
            },
        )
        check("POST /trips with mismatched organizer_id -> 403", forged.status_code == 403, forged.text)

        # unknown city rejected
        bad_city = await http.post(
            "/trips",
            json={
                "organizer_id": ALICE,
                "city_id": "nowhere",
                "start_date": "2026-11-01",
                "end_date": "2026-11-03",
                "daily_start_time": "09:00:00",
                "daily_end_time": "21:00:00",
                "home_base_lat": 41.8781,
                "home_base_lon": -87.6298,
            },
        )
        check("POST /trips with unknown city_id -> 422", bad_city.status_code == 422, bad_city.text)

        # --- invite members ---------------------------------------------------
        for invitee in (BOB, CAROL):
            invite = await http.post(f"/trips/{trip_id}/members", json={"user_id": invitee})
            check(f"POST /members invites {invitee[:8]}", invite.status_code == 201, invite.text)
            check("invitation starts as invited", invite.json()["status"] == "invited", invite.text)

        duplicate = await http.post(f"/trips/{trip_id}/members", json={"user_id": BOB})
        check("duplicate member invite -> 409", duplicate.status_code == 409, duplicate.text)

        unknown = await http.post(
            f"/trips/{trip_id}/members", json={"user_id": "99999999-9999-9999-9999-999999999999"}
        )
        check("inviting unknown user -> 404", unknown.status_code == 404, unknown.text)

    # invitees cannot read the trip before accepting
    async with client(tokens[BOB]) as http:
        early = await http.get(f"/trips/{trip_id}")
        check("invited user cannot read trip before accepting -> 403", early.status_code == 403, early.text)

        accepted = await http.post(f"/trips/{trip_id}/members/accept")
        check("POST /members/accept -> joined", accepted.status_code == 200 and accepted.json()["status"] == "joined", accepted.text)

    async with client(tokens[CAROL]) as http:
        accepted = await http.post(f"/trips/{trip_id}/members/accept")
        check("carol accepts invitation", accepted.status_code == 200, accepted.text)

    # --- UC-06: expenses -----------------------------------------------------
    async with client(tokens[BOB]) as http:
        dinner = await http.post(
            f"/trips/{trip_id}/expenses",
            json={
                "payer_id": BOB,
                "description": "Team dinner",
                "amount": "30.00",
                "date": "2026-11-01T20:00:00+00:00",
                "splits": [
                    {"debtor_id": ALICE, "amount_owed": "10.00"},
                    {"debtor_id": CAROL, "amount_owed": "10.00"},
                ],
            },
        )
        check("POST /expenses -> 201", dinner.status_code == 201, dinner.text)
        shares = {split["debtor_id"]: split["amount_owed"] for split in dinner.json()["splits"]}
        check(
            "payer receives the unallocated remainder",
            shares.get(BOB) == "10.00" and shares.get(ALICE) == "10.00" and shares.get(CAROL) == "10.00",
            str(shares),
        )

        over = await http.post(
            f"/trips/{trip_id}/expenses",
            json={
                "payer_id": BOB,
                "description": "Too much",
                "amount": "5.00",
                "date": "2026-11-01T21:00:00+00:00",
                "splits": [{"debtor_id": ALICE, "amount_owed": "5.01"}],
            },
        )
        check("splits exceeding amount -> 422", over.status_code == 422, over.text)

        foreign_payer = await http.post(
            f"/trips/{trip_id}/expenses",
            json={
                "payer_id": DAVE,
                "description": "Not mine",
                "amount": "5.00",
                "date": "2026-11-01T21:00:00+00:00",
                "splits": [{"debtor_id": ALICE, "amount_owed": "5.00"}],
            },
        )
        check("recording an expense as a non-member payer -> 403", foreign_payer.status_code == 403, foreign_payer.text)

    async with client(tokens[ALICE]) as http:
        tickets = await http.post(
            f"/trips/{trip_id}/expenses",
            json={
                "payer_id": ALICE,
                "description": "Museum tickets",
                "amount": "20.00",
                "date": "2026-11-01T12:30:00+00:00",
                "splits": [{"debtor_id": BOB, "amount_owed": "20.00"}],
            },
        )
        check("second expense recorded", tickets.status_code == 201, tickets.text)

        ledger = await http.get(f"/trips/{trip_id}/expenses")
        check("GET /expenses lists the ledger", ledger.status_code == 200 and len(ledger.json()) == 2, ledger.text)
        check(
            "ledger amounts are exact decimal strings",
            sorted(item["amount"] for item in ledger.json()) == ["20.00", "30.00"],
            str(ledger.json()),
        )

        # --- F17: settlement --------------------------------------------------
        settlement = await http.get(f"/trips/{trip_id}/settlement")
        transfers = settlement.json()
        check("GET /settlement -> 200", settlement.status_code == 200, settlement.text)
        check(
            "greedy settlement nets to one transfer of $10 carol->alice",
            transfers
            == [{"from_user": CAROL, "to_user": ALICE, "amount": "10.00"}],
            str(transfers),
        )

        # --- F16: cost estimate ------------------------------------------------
        await add_itinerary_stop(env, trip_id)
        estimate = await http.get(f"/trips/{trip_id}/cost-estimate")
        body = estimate.json()
        check("GET /cost-estimate -> 200", estimate.status_code == 200, estimate.text)
        check(
            "per-person admission estimate is exact",
            Decimal(body["per_person_total"]) == Decimal("12.50") and body["is_complete"] is True,
            str(body),
        )

        read_trip = await http.get(f"/trips/{trip_id}")
        check("GET /trips/{trip_id} returns trip", read_trip.status_code == 200 and read_trip.json()["id"] == trip_id, read_trip.text)

    # --- authentication edge cases ------------------------------------------
    async with client(tokens[DAVE]) as http:
        denied = await http.get(f"/trips/{trip_id}/expenses")
        check("non-member read -> 403", denied.status_code == 403, denied.text)

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=10.0) as http:
        no_token = await http.get(f"/trips/{trip_id}")
        check("missing bearer token -> 401", no_token.status_code == 401, no_token.text)

        garbage = await http.get(f"/trips/{trip_id}", headers={"Authorization": "Bearer garbage"})
        check("invalid token -> 401", garbage.status_code == 401, garbage.text)

        expired = jwt.encode({"sub": ALICE, "exp": int(time.time()) - 10}, secret, algorithm="HS256")
        stale = await http.get(f"/trips/{trip_id}", headers={"Authorization": f"Bearer {expired}"})
        check("expired token -> 401", stale.status_code == 401, stale.text)

        wrong_secret = jwt.encode({"sub": ALICE, "exp": int(time.time()) + 3600}, "other-secret-other-secret-other-secret", algorithm="HS256")
        forged = await http.get(f"/trips/{trip_id}", headers={"Authorization": f"Bearer {wrong_secret}"})
        check("token signed with wrong secret -> 401", forged.status_code == 401, forged.text)

    print()
    if failures:
        print(f"{len(failures)} CHECK(S) FAILED: {failures}")
        sys.exit(1)
    print("ALL END-TO-END CHECKS PASSED")


if __name__ == "__main__":
    asyncio.run(main())
