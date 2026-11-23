"""Compare the greedy and CP-SAT solvers on a real trip from the database.

Produces the results table for the final report.

    cd backend
    DATABASE_URL="postgresql://zoba:PASSWORD@localhost:5432/zoba" \
        python scripts/benchmark_solvers.py --trip-id <uuid>

Add --sweep to repeat the comparison at several candidate limits, which shows
how the two solvers diverge as the problem gets bigger.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg  # noqa: E402

from app.services.scheduler import (  # noqa: E402
    Candidate,
    OpeningWindow,
    visit_minutes,
)
from app.services.routing import build_estimator  # noqa: E402
from app.services.solver_comparison import compare, format_table, improvement  # noqa: E402

CANDIDATE_SQL = """
SELECT d.destination_id, d.name, d.category, d.est_duration_min,
       ST_Y(d.geom::geometry) AS latitude,
       ST_X(d.geom::geometry) AS longitude,
       COALESCE(p.points_total, 0) AS points_total,
       COALESCE(h.windows, '[]'::json) AS windows
FROM destination d
LEFT JOIN (
    SELECT destination_id, SUM(points) AS points_total
    FROM preference
    WHERE trip_id = %(trip_id)s AND NOT hard_no AND points IS NOT NULL
    GROUP BY destination_id
) p ON p.destination_id = d.destination_id
LEFT JOIN (
    SELECT destination_id,
           json_agg(json_build_object('weekday', weekday,
                                      'open_min', open_min,
                                      'close_min', close_min)) AS windows
    FROM destination_hours GROUP BY destination_id
) h ON h.destination_id = d.destination_id
WHERE d.city_id = %(city_id)s
ORDER BY points_total DESC, d.name
LIMIT %(limit)s
"""

TRIP_SQL = """
SELECT city_id, start_date, end_date, day_start, day_end,
       ST_Y(home_base::geometry) AS latitude,
       ST_X(home_base::geometry) AS longitude
FROM trip WHERE trip_id = %(trip_id)s
"""


def minutes(value) -> int:
    return value.hour * 60 + value.minute


def load(conn, trip_id: str, limit: int):
    with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute(TRIP_SQL, {"trip_id": trip_id})
        trip = cur.fetchone()
        if trip is None:
            raise SystemExit(f"No trip {trip_id}")

        cur.execute(
            CANDIDATE_SQL,
            {"trip_id": trip_id, "city_id": trip["city_id"], "limit": limit},
        )
        rows = cur.fetchall()

    candidates = []
    for row in rows:
        raw = row["windows"]
        windows = json.loads(raw) if isinstance(raw, str) else (raw or [])
        candidates.append(
            Candidate(
                destination_id=row["destination_id"],
                name=row["name"],
                # Flat scores when nobody has voted yet would make every
                # itinerary tie, so fall back to 1.0 per place: the solvers
                # then compete on how many stops they can fit.
                score=float(row["points_total"]) or 1.0,
                location=(float(row["latitude"]), float(row["longitude"])),
                duration_min=visit_minutes(row["est_duration_min"], row["category"]),
                windows=tuple(
                    OpeningWindow(w["weekday"], w["open_min"], w["close_min"]) for w in windows
                ),
            )
        )

    days = [
        trip["start_date"] + timedelta(days=offset)
        for offset in range((trip["end_date"] - trip["start_date"]).days + 1)
    ]
    return candidates, days, trip


def main() -> None:
    parser = argparse.ArgumentParser(description="Greedy vs CP-SAT on a real trip")
    parser.add_argument("--trip-id", required=True)
    parser.add_argument("--limit", type=int, default=60)
    parser.add_argument("--time-limit", type=float, default=10.0)
    parser.add_argument("--sweep", action="store_true", help="repeat at 20/40/60/80 candidates")
    args = parser.parse_args()

    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise SystemExit("Set DATABASE_URL (use the plain postgresql:// form, not +asyncpg)")

    limits = [20, 40, 60, 80] if args.sweep else [args.limit]

    with psycopg.connect(dsn) as conn:
        for limit in limits:
            candidates, days, trip = load(conn, args.trip_id, limit)
            home = (float(trip["latitude"]), float(trip["longitude"]))
            # Road-network times, fetched once per run from the configured OSRM servers.
            travel = asyncio.run(build_estimator([home] + [c.location for c in candidates]))
            runs = compare(
                candidates,
                days=days,
                day_start_minute=minutes(trip["day_start"]),
                day_end_minute=minutes(trip["day_end"]),
                home_base=home,
                travel=travel,
                time_limit_seconds=args.time_limit,
            )
            print(f"\n### {len(candidates)} candidates, {len(days)} days\n")
            print(format_table(runs))
            print(f"\nCP-SAT improvement over greedy: {improvement(runs):+.2f}%")

            # Loud about the degenerate case: with no votes in the database
            # every place scores 1.0, so "score" collapses to "number of
            # stops" and the comparison stops measuring preference quality.
            # Numbers from this state should not go in the report unlabelled.
            if {c.score for c in candidates} == {1.0}:
                print(
                    "\n[!] Every candidate scored 1.0 - no preference data in this trip. "
                    "Score here is just stop count; seed votes before quoting these numbers."
                )


if __name__ == "__main__":
    main()
