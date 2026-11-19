"""Seed cumulative-voting preferences for a trip, so the solvers have something
real to optimise.

WHY THIS EXISTS
---------------
The scheduler maximises a group-preference score. With no rows in
``preference`` every destination scores the same, the objective degenerates
into "fit as many stops as possible", and the greedy-vs-CP-SAT comparison
stops measuring anything about preference quality. This script fills that gap
for local development, benchmarking and demos.

It is a LOCAL FIXTURE, not product code. It writes only to ``preference`` (and,
with --synthesize-members, to ``app_user``/``membership`` using clearly fake
@zoba.local addresses). The real voting UI is a separate component; nothing
here is meant to ship or to stand in for it.

VOTING MODEL
------------
Cumulative voting, as specified in the project proposal: each member receives a
fixed budget of points and spreads it over the destinations they care about.
Spending more on one place necessarily means spending less elsewhere, so the
numbers carry intensity of preference rather than a flat ranking.

To make the members actually disagree -- which is the whole point of a *group*
planner, and what makes the fairness metric non-trivial -- each synthetic voter
is given a taste profile over the Zoba category taxonomy. One member favours
museums and galleries, another nightlife, another parks and viewpoints. Points
are then allocated in proportion to taste, with a little jitter.

USAGE
-----
    cd backend
    DATABASE_URL="postgresql://zoba:PASSWORD@localhost:5432/zoba" \
        python scripts/seed_preferences.py --trip-id <uuid>

Re-running is safe: existing preference rows for the trip are replaced. Pass
--seed to change the random draw, or keep the default for reproducible numbers
in the report.
"""

from __future__ import annotations

import argparse
import os
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg  # noqa: E402

DEFAULT_BUDGET = 100
DEFAULT_SPREAD = 12  # how many destinations one member spends points on

# Taste profiles over the Zoba category taxonomy. Weight 0 means "never picks
# this"; higher weights get proportionally more of the member's budget.
TASTE_PROFILES: list[tuple[str, dict[str, float]]] = [
    ("museum-goer", {"museum": 5.0, "gallery": 4.0, "landmark": 2.5, "theater": 2.0, "park": 1.0}),
    ("outdoorsy", {"park": 5.0, "viewpoint": 4.5, "landmark": 2.0, "zoo": 2.0, "market": 1.0}),
    ("foodie", {"restaurant": 5.0, "cafe": 4.0, "market": 3.5, "bar": 2.5, "shop": 1.0}),
    ("nightlife", {"bar": 5.0, "theater": 3.0, "restaurant": 2.5, "landmark": 1.5, "cafe": 1.0}),
    ("sightseer", {"landmark": 5.0, "viewpoint": 4.0, "museum": 2.5, "park": 2.0, "shop": 1.5}),
    ("family", {"zoo": 5.0, "aquarium": 4.5, "park": 3.0, "museum": 2.0, "market": 1.5}),
]

FALLBACK_WEIGHT = 0.4  # categories outside a profile still get a little love

TRIP_SQL = "SELECT city_id, organizer_id FROM trip WHERE trip_id = %(trip_id)s"

MEMBERS_SQL = """
SELECT m.user_id, u.email
FROM membership m JOIN app_user u ON u.user_id = m.user_id
WHERE m.trip_id = %(trip_id)s AND m.status = 'joined'
ORDER BY u.email
"""

DESTINATIONS_SQL = """
SELECT destination_id, category
FROM destination
WHERE city_id = %(city_id)s
ORDER BY name
LIMIT %(pool)s
"""

UPSERT_SQL = """
INSERT INTO preference (trip_id, user_id, destination_id, points, hard_no)
VALUES (%(trip_id)s, %(user_id)s, %(destination_id)s, %(points)s, %(hard_no)s)
ON CONFLICT (trip_id, user_id, destination_id)
DO UPDATE SET points = EXCLUDED.points, hard_no = EXCLUDED.hard_no
"""


def allocate(rng: random.Random, destinations, profile: dict[str, float], budget: int, spread: int):
    """Spread one member's point budget over destinations they like.

    Returns (allocations, hard_nos). Weighted sampling without replacement
    picks which places the member bothers to vote on at all; the budget is
    then split between them in proportion to taste.
    """
    pool = list(destinations)
    weights = [profile.get(d["category"], FALLBACK_WEIGHT) for d in pool]
    if not any(weights):
        return [], []

    chosen: list[dict] = []
    chosen_weights: list[float] = []
    for _ in range(min(spread, len(pool))):
        total = sum(weights)
        if total <= 0:
            break
        pick = rng.uniform(0, total)
        running = 0.0
        for i, w in enumerate(weights):
            running += w
            if running >= pick:
                chosen.append(pool[i])
                chosen_weights.append(w)
                weights[i] = 0.0  # without replacement
                break

    if not chosen:
        return [], []

    # Proportional split with jitter, then fix rounding drift on the top pick.
    jittered = [w * rng.uniform(0.7, 1.3) for w in chosen_weights]
    total = sum(jittered)
    points = [max(1, int(round(budget * j / total))) for j in jittered]
    drift = budget - sum(points)
    points[points.index(max(points))] += drift

    allocations = [
        (d["destination_id"], p) for d, p in zip(chosen, points) if p > 0
    ]

    # A couple of hard vetoes per member, drawn from places they did not back.
    remaining = [d for d in pool if d not in chosen]
    hard_nos = [
        d["destination_id"] for d in rng.sample(remaining, min(2, len(remaining)))
    ]
    return allocations, hard_nos


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trip-id", required=True)
    parser.add_argument("--budget", type=int, default=DEFAULT_BUDGET,
                        help="points each member gets to spend (default 100)")
    parser.add_argument("--spread", type=int, default=DEFAULT_SPREAD,
                        help="how many destinations each member votes on (default 12)")
    parser.add_argument("--pool", type=int, default=400,
                        help="how many of the city's destinations are votable (default 400)")
    parser.add_argument("--seed", type=int, default=395,
                        help="RNG seed; keep fixed for reproducible report numbers")
    parser.add_argument("--synthesize-members", type=int, default=0, metavar="N",
                        help="create N fake @zoba.local teammates and join them to the "
                             "trip, for when real teammates have not signed up locally")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise SystemExit("Set DATABASE_URL (inline on this command, do not export it).")

    rng = random.Random(args.seed)

    with psycopg.connect(dsn) as conn:
        with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
            cur.execute(TRIP_SQL, {"trip_id": args.trip_id})
            trip = cur.fetchone()
            if trip is None:
                raise SystemExit(f"No trip {args.trip_id}")

            if args.synthesize_members:
                for i in range(args.synthesize_members):
                    email = f"seed+member{i + 1}@zoba.local"
                    cur.execute(
                        "INSERT INTO app_user (email, password_hash) VALUES (%s, 'seed-only-not-a-login') "
                        "ON CONFLICT (email) DO NOTHING RETURNING user_id",
                        (email,),
                    )
                    row = cur.fetchone()
                    if row is None:
                        cur.execute("SELECT user_id FROM app_user WHERE email = %s", (email,))
                        row = cur.fetchone()
                    cur.execute(
                        "INSERT INTO membership (trip_id, user_id, role, status) "
                        "VALUES (%s, %s, 'member', 'joined') "
                        "ON CONFLICT (trip_id, user_id) DO UPDATE SET status = 'joined'",
                        (args.trip_id, row["user_id"]),
                    )

            cur.execute(MEMBERS_SQL, {"trip_id": args.trip_id})
            members = cur.fetchall()
            if not members:
                raise SystemExit(
                    "No joined members on this trip. Re-run with --synthesize-members 5 "
                    "to create local stand-ins."
                )

            cur.execute(DESTINATIONS_SQL, {"city_id": trip["city_id"], "pool": args.pool})
            destinations = cur.fetchall()
            if not destinations:
                raise SystemExit(
                    f"No destinations for city {trip['city_id']}. Run the data pipeline first."
                )

            if len(members) < 2:
                print(
                    "[!] Only one joined member. Fairness metrics need disagreement to mean "
                    "anything -- consider --synthesize-members 5."
                )

            cur.execute("DELETE FROM preference WHERE trip_id = %(trip_id)s",
                        {"trip_id": args.trip_id})

            written = 0
            for i, member in enumerate(members):
                label, profile = TASTE_PROFILES[i % len(TASTE_PROFILES)]
                allocations, hard_nos = allocate(
                    rng, destinations, profile, args.budget, args.spread
                )
                for destination_id, points in allocations:
                    if not args.dry_run:
                        cur.execute(UPSERT_SQL, {
                            "trip_id": args.trip_id, "user_id": member["user_id"],
                            "destination_id": destination_id, "points": points,
                            "hard_no": False,
                        })
                    written += 1
                for destination_id in hard_nos:
                    if not args.dry_run:
                        cur.execute(UPSERT_SQL, {
                            "trip_id": args.trip_id, "user_id": member["user_id"],
                            "destination_id": destination_id, "points": 0,
                            "hard_no": True,
                        })
                print(
                    f"  {member['email']:<34} {label:<12} "
                    f"{len(allocations):>2} votes / {args.budget} pts, {len(hard_nos)} vetoes"
                )

            if args.dry_run:
                conn.rollback()
                print(f"\nDry run: {written} preference rows NOT written.")
            else:
                conn.commit()
                print(f"\nSeeded {written} preference rows across {len(members)} members.")
                print("Now re-run scripts/benchmark_solvers.py for real comparison numbers.")


if __name__ == "__main__":
    main()
