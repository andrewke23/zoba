"""End-to-end validation of the Zoba backend against the live docker compose stack.

Seeds a city and a priced destination directly in Postgres, then drives the
documented API flow with real registered users and app-issued JWTs.
"""
import asyncio
import os
import sys
import time
import uuid
from decimal import Decimal

import asyncpg
import httpx
import jwt

BASE_URL = "http://localhost:8000/api/v1"
HEALTH_URL = "http://localhost:8000/healthz"

# Unique per run so the script can be re-run against the same database.
RUN_ID = uuid.uuid4().hex[:8]

# Dave exists only as a pipeline-style row: his password_hash is not bcrypt.
DAVE = "44444444-4444-4444-4444-444444444444"
MUSEUM = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
PASSWORD = "correct horse battery staple"

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


def mint_expired_token(user_id: str, secret: str) -> str:
    return jwt.encode({"sub": user_id, "exp": int(time.time()) - 10}, secret, algorithm="HS256")


def mint_token(user_id: str, secret: str) -> str:
    return jwt.encode({"sub": user_id, "exp": int(time.time()) + 3600}, secret, algorithm="HS256")


def client(token: str | None = None) -> httpx.AsyncClient:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return httpx.AsyncClient(base_url=BASE_URL, headers=headers, timeout=10.0)


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
            INSERT INTO destination (destination_id, city_id, name, geom, category, admission_cost_usd)
            VALUES ($1, 'chicago', 'Test Museum',
                    ST_SetSRID(ST_MakePoint(-87.62, 41.88), 4326)::geography, 'museum', 12.50)
            ON CONFLICT (destination_id) DO NOTHING
            """,
            MUSEUM,
        )
        await connection.execute(
            """
            INSERT INTO app_user (user_id, email, password_hash, name) VALUES
              ($1, 'dave@example.com', 'x', 'Dave')
            ON CONFLICT (user_id) DO NOTHING
            """,
            DAVE,
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


async def register_user(http: httpx.AsyncClient, email: str, name: str) -> tuple[str, str]:
    response = await http.post(
        "/auth/register", json={"email": email, "name": name, "password": PASSWORD}
    )
    assert response.status_code == 201, response.text
    body = response.json()
    return body["access_token"], body["user"]["id"]


async def main() -> None:
    env = load_env()
    secret = env["JWT_SECRET_KEY"]
    await seed(env)

    health = httpx.get(HEALTH_URL, timeout=10.0)
    check("GET /healthz returns 200", health.status_code == 200, str(health.status_code))

    # --- auth ---------------------------------------------------------------
    alice_email = f"alice-{RUN_ID}@example.com"
    async with client() as http:
        alice_token, alice_id = await register_user(http, f"  {alice_email.upper()} ", "Alice")
        check("POST /auth/register -> 201 with bearer token", bool(alice_token), "no token returned")

        duplicate = await http.post(
            "/auth/register",
            json={"email": alice_email, "name": "Alice Again", "password": PASSWORD},
        )
        check("duplicate email register -> 409", duplicate.status_code == 409, duplicate.text)

        weak = await http.post(
            "/auth/register",
            json={"email": "weak@example.com", "name": "Weak", "password": "short"},
        )
        check("weak password register -> 422", weak.status_code == 422, weak.text)

        bad_email = await http.post(
            "/auth/register",
            json={"email": "not-an-email", "name": "Nope", "password": PASSWORD},
        )
        check("invalid email register -> 422", bad_email.status_code == 422, bad_email.text)

    async with client(alice_token) as http:
        me = await http.get("/auth/me")
        check(
            "GET /auth/me returns the registered user",
            me.status_code == 200
            and me.json()["email"] == alice_email
            and me.json()["id"] == alice_id
            and me.json()["name"] == "Alice",
            me.text,
        )

    async with client() as http:
        bob_token, bob_id = await register_user(http, f"bob-{RUN_ID}@example.com", "Bob")
        carol_token, carol_id = await register_user(http, f"carol-{RUN_ID}@example.com", "Carol")
        check("multiple users can register", bool(bob_token) and bool(carol_token))

        login = await http.post(
            "/auth/login", json={"email": alice_email.upper(), "password": PASSWORD}
        )
        check("POST /auth/login -> 200 with fresh token", login.status_code == 200, login.text)
        check("login token authenticates", bool(login.json().get("access_token")))

        wrong_password = await http.post(
            "/auth/login", json={"email": alice_email, "password": "wrong password"}
        )
        check("login with wrong password -> 401", wrong_password.status_code == 401, wrong_password.text)

        unknown_email = await http.post(
            "/auth/login", json={"email": "ghost@example.com", "password": PASSWORD}
        )
        check("login with unknown email -> 401", unknown_email.status_code == 401, unknown_email.text)

        legacy_row = await http.post(
            "/auth/login", json={"email": "dave@example.com", "password": PASSWORD}
        )
        check("login against non-bcrypt legacy hash -> 401", legacy_row.status_code == 401, legacy_row.text)

    # --- UC-01: organizer creates the trip -----------------------------------
    async with client(alice_token) as http:
        response = await http.post(
            "/trips",
            json={
                "organizer_id": alice_id,
                "city_id": "chicago",
                "name": "Smoke test trip",
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

        forged = await http.post(
            "/trips",
            json={
                "organizer_id": bob_id,
                "city_id": "chicago",
                "name": "Smoke test trip",
                "start_date": "2026-11-01",
                "end_date": "2026-11-03",
                "daily_start_time": "09:00:00",
                "daily_end_time": "21:00:00",
                "home_base_lat": 41.8781,
                "home_base_lon": -87.6298,
            },
        )
        check("POST /trips with mismatched organizer_id -> 403", forged.status_code == 403, forged.text)

        bad_city = await http.post(
            "/trips",
            json={
                "organizer_id": alice_id,
                "city_id": "nowhere",
                "name": "Smoke test trip",
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
        for invitee in (bob_id, carol_id):
            invite = await http.post(f"/trips/{trip_id}/members", json={"user_id": invitee})
            check(f"POST /members invites {invitee[:8]}", invite.status_code == 201, invite.text)
            check("invitation starts as invited", invite.json()["status"] == "invited", invite.text)

        duplicate = await http.post(f"/trips/{trip_id}/members", json={"user_id": bob_id})
        check("duplicate member invite -> 409", duplicate.status_code == 409, duplicate.text)

        unknown = await http.post(
            f"/trips/{trip_id}/members", json={"user_id": "99999999-9999-9999-9999-999999999999"}
        )
        check("inviting unknown user -> 404", unknown.status_code == 404, unknown.text)

    # invitees cannot read the trip before accepting
    async with client(bob_token) as http:
        early = await http.get(f"/trips/{trip_id}")
        check("invited user cannot read trip before accepting -> 403", early.status_code == 403, early.text)

        accepted = await http.post(f"/trips/{trip_id}/members/accept")
        check("POST /members/accept -> joined", accepted.status_code == 200 and accepted.json()["status"] == "joined", accepted.text)

    async with client(carol_token) as http:
        accepted = await http.post(f"/trips/{trip_id}/members/accept")
        check("carol accepts invitation", accepted.status_code == 200, accepted.text)

    # --- UC-06: expenses -----------------------------------------------------
    async with client(bob_token) as http:
        dinner = await http.post(
            f"/trips/{trip_id}/expenses",
            json={
                "payer_id": bob_id,
                "description": "Team dinner",
                "amount": "30.00",
                "date": "2026-11-01T20:00:00+00:00",
                "splits": [
                    {"debtor_id": alice_id, "amount_owed": "10.00"},
                    {"debtor_id": carol_id, "amount_owed": "10.00"},
                ],
            },
        )
        check("POST /expenses -> 201", dinner.status_code == 201, dinner.text)
        shares = {split["debtor_id"]: split["amount_owed"] for split in dinner.json()["splits"]}
        check(
            "payer receives the unallocated remainder",
            shares.get(bob_id) == "10.00" and shares.get(alice_id) == "10.00" and shares.get(carol_id) == "10.00",
            str(shares),
        )

        over = await http.post(
            f"/trips/{trip_id}/expenses",
            json={
                "payer_id": bob_id,
                "description": "Too much",
                "amount": "5.00",
                "date": "2026-11-01T21:00:00+00:00",
                "splits": [{"debtor_id": alice_id, "amount_owed": "5.01"}],
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
                "splits": [{"debtor_id": alice_id, "amount_owed": "5.00"}],
            },
        )
        check("recording an expense as a non-member payer -> 403", foreign_payer.status_code == 403, foreign_payer.text)

    async with client(alice_token) as http:
        tickets = await http.post(
            f"/trips/{trip_id}/expenses",
            json={
                "payer_id": alice_id,
                "description": "Museum tickets",
                "amount": "20.00",
                "date": "2026-11-01T12:30:00+00:00",
                "splits": [{"debtor_id": bob_id, "amount_owed": "20.00"}],
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
        settlement_body = settlement.json()
        check("GET /settlement -> 200", settlement.status_code == 200, settlement.text)
        check(
            "greedy settlement nets to one transfer of $10 carol->alice",
            settlement_body["transfers"]
            == [{"from_user": carol_id, "to_user": alice_id, "amount": "10.00"}],
            str(settlement_body),
        )
        check(
            "settlement includes per-member balances",
            {balance["user_id"] for balance in settlement_body["balances"]}
            == {alice_id, bob_id, carol_id},
            str(settlement_body),
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
    async with client(mint_token(DAVE, secret)) as http:
        denied = await http.get(f"/trips/{trip_id}/expenses")
        check("non-member read -> 403", denied.status_code == 403, denied.text)

    async with client() as http:
        no_token = await http.get(f"/trips/{trip_id}")
        check("missing bearer token -> 401", no_token.status_code == 401, no_token.text)

        garbage = await http.get(f"/trips/{trip_id}", headers={"Authorization": "Bearer garbage"})
        check("invalid token -> 401", garbage.status_code == 401, garbage.text)

        stale = await http.get(
            f"/trips/{trip_id}", headers={"Authorization": f"Bearer {mint_expired_token(alice_id, secret)}"}
        )
        check("expired token -> 401", stale.status_code == 401, stale.text)

        forged = await http.get(
            f"/trips/{trip_id}",
            headers={
                "Authorization": f"Bearer {mint_token(alice_id, 'other-secret-other-secret-other-secret')}"
            },
        )
        check("token signed with wrong secret -> 401", forged.status_code == 401, forged.text)

    print()
    if failures:
        print(f"{len(failures)} CHECK(S) FAILED: {failures}")
        sys.exit(1)
    print("ALL END-TO-END CHECKS PASSED")


if __name__ == "__main__":
    asyncio.run(main())
