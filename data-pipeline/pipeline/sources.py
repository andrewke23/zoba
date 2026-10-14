"""Ingestion: pull raw places for a city and normalize to one record shape.

Normalized record (dict):
  source, source_id, name, lat, lon, category, address, website, phone,
  hours_raw, wikidata_id, raw
"""
from __future__ import annotations

import json
from pathlib import Path

from . import categories
from .config import FSQ_PLACES_PATH, OVERPASS_URL, City, raw_dir

# ---------------------------------------------------------------------------
# OpenStreetMap via Overpass
# ---------------------------------------------------------------------------

OVERPASS_QUERY = """
[out:json][timeout:180];
(
  nwr["tourism"~"^(attraction|museum|gallery|viewpoint|zoo|aquarium|theme_park)$"]["name"]({bbox});
  nwr["amenity"~"^(theatre|arts_centre|restaurant|cafe|bar|pub)$"]["name"]({bbox});
  nwr["leisure"~"^(park|garden)$"]["name"]({bbox});
  nwr["historic"]["name"]({bbox});
);
out center tags;
"""


def fetch_osm(city: City) -> Path:
    import requests

    bbox = ",".join(str(x) for x in city.bbox)  # south,west,north,east
    resp = requests.post(
        OVERPASS_URL,
        data={"data": OVERPASS_QUERY.format(bbox=bbox)},
        headers={"User-Agent": "zoba-csds395/0.1 (student project)"},
        timeout=300,
    )
    resp.raise_for_status()
    path = raw_dir(city.city_id) / "osm.json"
    path.write_text(resp.text)
    return path


def normalize_osm(path: Path) -> list[dict]:
    data = json.loads(path.read_text())
    out = []
    for el in data.get("elements", []):
        tags = el.get("tags", {})
        if "lat" in el:
            lat, lon = el["lat"], el["lon"]
        elif "center" in el:
            lat, lon = el["center"]["lat"], el["center"]["lon"]
        else:
            continue
        addr = " ".join(
            filter(None, [tags.get("addr:housenumber"), tags.get("addr:street"), tags.get("addr:city")])
        ) or None
        out.append(
            {
                "source": "osm",
                "source_id": f"{el['type'][0]}{el['id']}",  # n123 / w456 / r789
                "name": tags.get("name"),
                "lat": lat,
                "lon": lon,
                "category": categories.from_osm_tags(tags),
                "address": addr,
                "website": tags.get("website") or tags.get("contact:website"),
                "phone": tags.get("phone") or tags.get("contact:phone"),
                "hours_raw": tags.get("opening_hours"),
                "wikidata_id": tags.get("wikidata"),
                "raw": tags,
            }
        )
    return out


# ---------------------------------------------------------------------------
# Foursquare Open Source Places (parquet via DuckDB)
# Note: the open dataset has no opening hours — hours come from OSM.
# ---------------------------------------------------------------------------

FSQ_SQL = """
SELECT fsq_place_id, name, latitude, longitude, address, locality,
       website, tel, fsq_category_labels
FROM read_parquet(?)
WHERE latitude BETWEEN ? AND ?
  AND longitude BETWEEN ? AND ?
  AND date_closed IS NULL
  AND name IS NOT NULL
"""


def fetch_fsq(city: City, parquet_path: str = FSQ_PLACES_PATH) -> Path:
    import duckdb

    if not parquet_path:
        raise SystemExit("Set FSQ_PLACES_PATH to the Foursquare OS Places parquet (local path or s3:// glob).")
    con = duckdb.connect()
    if parquet_path.startswith("s3://"):
        con.execute("INSTALL httpfs; LOAD httpfs;")
    s, w, n, e = city.bbox
    df = con.execute(FSQ_SQL, [parquet_path, s, n, w, e]).df()
    path = raw_dir(city.city_id) / "fsq.parquet"
    df.to_parquet(path, index=False)
    return path


def normalize_fsq(path: Path) -> list[dict]:
    import pandas as pd

    df = pd.read_parquet(path)
    out = []
    for r in df.itertuples(index=False):
        labels = list(r.fsq_category_labels) if r.fsq_category_labels is not None else []
        cat = categories.from_fsq_labels(labels)
        out.append(
            {
                "source": "fsq",
                "source_id": r.fsq_place_id,
                "name": r.name,
                "lat": float(r.latitude),
                "lon": float(r.longitude),
                "category": cat,
                "address": " ".join(filter(None, [r.address, r.locality])) or None,
                "website": r.website,
                "phone": r.tel,
                "hours_raw": None,
                "wikidata_id": None,
                "raw": {"labels": labels},
            }
        )
    # The FSQ catalog is huge; keep only categories Zoba schedules.
    return [o for o in out if o["category"] != "other"]


def write_jsonl(records: list[dict], path: Path) -> None:
    with path.open("w") as f:
        for r in records:
            f.write(json.dumps(r, default=str) + "\n")


def read_jsonl(path: Path) -> list[dict]:
    with path.open() as f:
        return [json.loads(line) for line in f if line.strip()]
