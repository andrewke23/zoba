"""Load canonical destinations + parsed hours into PostGIS (idempotent upserts)."""
from __future__ import annotations

import json

from .categories import ZOBA_CATEGORIES
from .config import DATABASE_URL, City
from .hours import parse_opening_hours


def load_city(city: City, canon: list[dict], dsn: str = DATABASE_URL) -> dict:
    import psycopg

    stats = {"destinations": 0, "hours_ok": 0, "hours_partial": 0, "hours_unparseable": 0, "hours_missing": 0}
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        s, w, n, e = city.bbox
        cur.execute(
            """INSERT INTO city (city_id, name, bbox, timezone)
               VALUES (%s, %s, ST_MakeEnvelope(%s, %s, %s, %s, 4326), %s)
               ON CONFLICT (city_id) DO UPDATE SET name = EXCLUDED.name, bbox = EXCLUDED.bbox,
                                                   timezone = EXCLUDED.timezone""",
            (city.city_id, city.name, w, s, e, n, city.timezone),
        )

        for d in canon:
            hours = parse_opening_hours(d.get("hours_raw"))
            stats[f"hours_{hours.status}"] += 1
            cur.execute(
                """INSERT INTO destination (destination_id, city_id, name, geom, category, address,
                       website, phone, wikidata_id, est_duration_min, hours_raw, hours_status, field_sources)
                   VALUES (%s, %s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography, %s, %s,
                           %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (destination_id) DO UPDATE SET
                       name = EXCLUDED.name, geom = EXCLUDED.geom, category = EXCLUDED.category,
                       address = EXCLUDED.address, website = EXCLUDED.website, phone = EXCLUDED.phone,
                       wikidata_id = EXCLUDED.wikidata_id, hours_raw = EXCLUDED.hours_raw,
                       hours_status = EXCLUDED.hours_status, field_sources = EXCLUDED.field_sources,
                       updated_at = now()
                   WHERE NOT destination.curated""",   # never overwrite hand-curated rows
                (
                    d["destination_id"], city.city_id, d["name"], d["lon"], d["lat"],
                    d.get("category") or "other", d.get("address"), d.get("website"), d.get("phone"),
                    d.get("wikidata_id"), ZOBA_CATEGORIES.get(d.get("category") or "other"),
                    d.get("hours_raw"), hours.status, json.dumps(d["field_sources"]),
                ),
            )
            cur.execute("SELECT curated FROM destination WHERE destination_id = %s", (d["destination_id"],))
            if cur.fetchone()[0]:
                stats["destinations"] += 1
                continue  # curated: leave hours and links alone
            cur.execute("DELETE FROM destination_hours WHERE destination_id = %s", (d["destination_id"],))
            cur.executemany(
                "INSERT INTO destination_hours (destination_id, weekday, open_min, close_min) VALUES (%s,%s,%s,%s)",
                [(d["destination_id"], wd, o, c) for wd, o, c in hours.rows()],
            )
            for m in d["members"]:
                cur.execute(
                    """INSERT INTO destination_source (source, source_id, destination_id, raw)
                       VALUES (%s, %s, %s, %s)
                       ON CONFLICT (source, source_id) DO UPDATE SET
                           destination_id = EXCLUDED.destination_id, raw = EXCLUDED.raw, fetched_at = now()""",
                    (m["source"], m["source_id"], d["destination_id"], json.dumps(m["raw"], default=str)),
                )
            stats["destinations"] += 1
        conn.commit()
    return stats
