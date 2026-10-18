"""Exercise the input embedder against the live docker compose stack.

Loads the frontend's demo scenario (Chicago and DC trips, a group of friends
and their shared expenses) through the real API, then reads the vectors the
backend stored in input_embedding and prints which inputs ended up closest to
each other. Safe to re-run: every run registers fresh users.

    python backend/tests/embedder_demo.py
"""
import asyncio
import math
import os
import sys
import uuid

import asyncpg
import httpx

BASE_URL = "http://localhost:8000/api/v1"
PASSWORD = "correct horse battery staple"
RUN_ID = uuid.uuid4().hex[:8]

CITIES = """
INSERT INTO city (city_id, name, bbox, timezone) VALUES
  ('chicago', 'Chicago',
   ST_GeomFromText('POLYGON((-87.95 41.65,-87.52 41.65,-87.52 42.02,-87.95 42.02,-87.95 41.65))', 4326),
   'America/Chicago'),
  ('dc', 'Washington, DC',
   ST_GeomFromText('POLYGON((-77.12 38.79,-76.91 38.79,-76.91 38.99,-77.12 38.99,-77.12 38.79))', 4326),
   'America/New_York')
ON CONFLICT (city_id) DO NOTHING
"""

TRIPS = {
    "Chicago weekend": {
        "city_id": "chicago",
        "start_date": "2026-11-06",
        "end_date": "2026-11-08",
        "daily_start_time": "09:00:00",
        "daily_end_time": "21:00:00",
        "home_base_lat": 41.8881,
        "home_base_lon": -87.6298,
    },
    "Chicago long weekend": {
        "city_id": "chicago",
        "start_date": "2026-11-13",
        "end_date": "2026-11-16",
        "daily_start_time": "10:00:00",
        "daily_end_time": "22:00:00",
        "home_base_lat": 41.8920,
        "home_base_lon": -87.6250,
    },
    "DC museum day": {
        "city_id": "dc",
        "start_date": "2027-04-03",
        "end_date": "2027-04-03",
        "daily_start_time": "08:00:00",
        "daily_end_time": "18:00:00",
        "home_base_lat": 38.8977,
        "home_base_lon": -77.0365,
    },
}

# (payer, description, amount, local time) on the Chicago weekend trip.
EXPENSES = [
    ("Bob", "Deep dish pizza dinner", "84.00", "2026-11-06T19:30:00-06:00"),
    ("Carol", "Pizza lunch at Lou Malnati's", "46.50", "2026-11-07T12:15:00-06:00"),
    ("Alice", "Shedd Aquarium tickets", "135.00", "2026-11-07T09:30:00-06:00"),
    ("Bob", "Field Museum admission tickets", "90.00", "2026-11-07T14:00:00-06:00"),
    ("Carol", "Uber to Navy Pier", "18.20", "2026-11-07T17:45:00-06:00"),
    ("Alice", "Taxi to O'Hare airport", "52.00", "2026-11-08T16:00:00-06:00"),
    ("Bob", "Architecture river cruise tickets", "156.00", "2026-11-08T10:00:00-06:00"),
]


def load_env() -> dict[str, str]:
    values: dict[str, str] = {}
    with open(os.path.join(os.path.dirname(__file__), "..", "..", ".env"), encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                values[key] = value
    return values


def cosine(left: list[float], right: list[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right))
    norms = math.sqrt(sum(a * a for a in left)) * math.sqrt(sum(b * b for b in right))
    return dot / norms if norms else 0.0


def client(token: str | None = None) -> httpx.AsyncClient:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return httpx.AsyncClient(base_url=BASE_URL, headers=headers, timeout=10.0)


async def register(name: str) -> tuple[str, str]:
    async with client() as http:
        response = await http.post(
            "/auth/register",
            json={"email": f"{name.lower()}-{RUN_ID}@example.com", "name": name, "password": PASSWORD},
        )
    response.raise_for_status()
    body = response.json()
    return body["access_token"], body["user"]["id"]


async def main() -> None:
    env = load_env()
    dsn = (
        f"postgresql://{env['POSTGRES_USER']}:{env['POSTGRES_PASSWORD']}"
        f"@127.0.0.1:{env.get('POSTGRES_HOST_PORT', '5432')}/{env['POSTGRES_DB']}"
    )
    connection = await asyncpg.connect(dsn)
    try:
        await connection.execute(CITIES)

        users = {name: await register(name) for name in ("Alice", "Bob", "Carol")}
        alice_token, alice_id = users["Alice"]

        labels: dict[str, str] = {}
        trip_ids: dict[str, str] = {}
        async with client(alice_token) as http:
            for label, body in TRIPS.items():
                response = await http.post("/trips", json={"organizer_id": alice_id, **body})
                response.raise_for_status()
                trip_ids[label] = response.json()["id"]
                labels[trip_ids[label]] = f"trip: {label}"

            weekend = trip_ids["Chicago weekend"]
            for name in ("Bob", "Carol"):
                response = await http.post(f"/trips/{weekend}/members", json={"user_id": users[name][1]})
                response.raise_for_status()
        for name in ("Bob", "Carol"):
            async with client(users[name][0]) as http:
                (await http.post(f"/trips/{weekend}/members/accept")).raise_for_status()

        for payer, description, amount, spent_at in EXPENSES:
            token, payer_id = users[payer]
            others = [user_id for name, (_, user_id) in users.items() if name != payer]
            share = f"{float(amount) / 3:.2f}"
            async with client(token) as http:
                response = await http.post(
                    f"/trips/{weekend}/expenses",
                    json={
                        "payer_id": payer_id,
                        "description": description,
                        "amount": amount,
                        "date": spent_at,
                        "splits": [{"debtor_id": user_id, "amount_owed": share} for user_id in others],
                    },
                )
            response.raise_for_status()
            labels[response.json()["id"]] = f"expense: {description}"

        rows = await connection.fetch(
            """
            SELECT input_kind, source_id, embedder_version, vector
            FROM input_embedding
            WHERE source_id = ANY($1::text[])
            ORDER BY embedding_id
            """,
            list(labels),
        )
    finally:
        await connection.close()

    print(f"\n{len(rows)} embeddings stored for {len(labels)} inputs (run {RUN_ID})")
    if len(rows) != len(labels):
        print("FAIL: some inputs were not embedded. Was the backend rebuilt with `docker compose up --build`?")
        sys.exit(1)
    first = rows[0]
    print(f"embedder {first['embedder_version']}, {len(first['vector'])} dimensions")
    print(f"first vector (truncated): {[round(value, 3) for value in first['vector'][:8]]} ...\n")

    for kind in ("trip", "expense"):
        group = [row for row in rows if row["input_kind"] == kind]
        print(f"Nearest neighbour for each {kind} (cosine similarity):")
        for row in group:
            score, nearest = max(
                (
                    (cosine(row["vector"], other["vector"]), other)
                    for other in group
                    if other["source_id"] != row["source_id"]
                ),
                key=lambda pair: pair[0],
            )
            print(f"  {labels[row['source_id']]:<45} -> {labels[nearest['source_id']]:<45} {score:+.2f}")
        print()


if __name__ == "__main__":
    asyncio.run(main())
