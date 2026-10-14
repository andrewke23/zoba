"""Entity resolution: merge OSM + Foursquare records that describe the same place.

Pipeline:
  1. Block    — only compare records within RADIUS_M of each other (grid buckets)
  2. Score    — name similarity + distance + exact-ID/website/phone signals
  3. Cluster  — union-find over pairs scoring >= threshold, max one record per source
  4. Merge    — build one canonical record per cluster with per-field provenance

Tune `threshold` and the weights with eval.py against a hand-labeled sample.
"""
from __future__ import annotations

import math
import re
import unicodedata
import uuid
from collections import defaultdict
from urllib.parse import urlparse

from rapidfuzz import fuzz

RADIUS_M = 150.0
DEFAULT_THRESHOLD = 0.75
WEIGHTS = {"name": 0.65, "dist": 0.35}

_STOP = {"the", "a", "an", "of", "and", "at"}
_NAMESPACE = uuid.UUID("6f1c2a8e-6b0e-4c55-9a8b-2b7d3c0e5a11")

# Which source to trust first for each canonical field
FIELD_PRIORITY = {
    "name": ["osm", "fsq"],
    "category": ["fsq", "osm"],
    "address": ["fsq", "osm"],
    "website": ["osm", "fsq"],
    "phone": ["fsq", "osm"],
    "hours_raw": ["osm", "fsq"],
    "wikidata_id": ["osm", "fsq"],
}


# ---------------------------------------------------------------------------
# Features
# ---------------------------------------------------------------------------

def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def normalize_name(name: str | None) -> str:
    if not name:
        return ""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    s = s.lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return " ".join(t for t in s.split() if t not in _STOP)


def _domain(url: str | None) -> str | None:
    if not url:
        return None
    if "://" not in url:
        url = "http://" + url
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host or None


def _digits(phone: str | None) -> str | None:
    if not phone:
        return None
    d = re.sub(r"\D", "", phone)
    return d[-10:] if len(d) >= 10 else None


def pair_features(a: dict, b: dict) -> dict:
    na, nb = normalize_name(a["name"]), normalize_name(b["name"])
    dist = haversine_m(a["lat"], a["lon"], b["lat"], b["lon"])
    return {
        "name_sim": fuzz.token_set_ratio(na, nb) / 100.0 if na and nb else 0.0,
        "dist_m": dist,
        "same_wikidata": bool(a.get("wikidata_id") and a.get("wikidata_id") == b.get("wikidata_id")),
        "same_domain": bool(_domain(a.get("website")) and _domain(a.get("website")) == _domain(b.get("website"))),
        "same_phone": bool(_digits(a.get("phone")) and _digits(a.get("phone")) == _digits(b.get("phone"))),
        "same_category": a.get("category") == b.get("category"),
    }


def score(f: dict, radius_m: float = RADIUS_M) -> float:
    if f["same_wikidata"]:
        return 1.0
    dist_score = max(0.0, 1.0 - f["dist_m"] / radius_m)
    s = WEIGHTS["name"] * f["name_sim"] + WEIGHTS["dist"] * dist_score
    if f["same_domain"]:
        s += 0.10
    if f["same_phone"]:
        s += 0.10
    if not f["same_category"]:
        s -= 0.05
    return max(0.0, min(1.0, s))


# ---------------------------------------------------------------------------
# Blocking
# ---------------------------------------------------------------------------

def candidate_pairs(records: list[dict], radius_m: float = RADIUS_M):
    """Yield (i, j) index pairs from different sources within radius_m."""
    cell_deg = radius_m / 111_000.0  # ~ degrees latitude per cell
    grid: dict[tuple[int, int], list[int]] = defaultdict(list)
    for i, r in enumerate(records):
        grid[(int(r["lat"] // cell_deg), int(r["lon"] // cell_deg))].append(i)

    for (gx, gy), idxs in grid.items():
        neighbors = [
            j
            for dx in (-1, 0, 1)
            for dy in (-1, 0, 1)
            for j in grid.get((gx + dx, gy + dy), [])
        ]
        for i in idxs:
            ri = records[i]
            for j in neighbors:
                if j <= i:
                    continue
                rj = records[j]
                if ri["source"] == rj["source"]:
                    continue
                if haversine_m(ri["lat"], ri["lon"], rj["lat"], rj["lon"]) <= radius_m:
                    yield i, j


def scored_pairs(records: list[dict], radius_m: float = RADIUS_M) -> list[tuple[int, int, float, dict]]:
    out = []
    for i, j in candidate_pairs(records, radius_m):
        f = pair_features(records[i], records[j])
        out.append((i, j, score(f, radius_m), f))
    return out


# ---------------------------------------------------------------------------
# Clustering + merge
# ---------------------------------------------------------------------------

def cluster(records: list[dict], pairs, threshold: float = DEFAULT_THRESHOLD) -> list[list[int]]:
    """Greedy union-find: best pairs first, never two records from the same source in one cluster."""
    parent = list(range(len(records)))
    sources = [{records[i]["source"]} for i in range(len(records))]

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i, j, s, _ in sorted(pairs, key=lambda p: -p[2]):
        if s < threshold:
            break
        ri, rj = find(i), find(j)
        if ri == rj or sources[ri] & sources[rj]:
            continue
        parent[rj] = ri
        sources[ri] |= sources[rj]

    groups: dict[int, list[int]] = defaultdict(list)
    for i in range(len(records)):
        groups[find(i)].append(i)
    return list(groups.values())


def merge(members: list[dict]) -> dict:
    by_source = {m["source"]: m for m in members}
    canon: dict = {"field_sources": {}}
    for fld, order in FIELD_PRIORITY.items():
        for src in order + [s for s in by_source if s not in order]:
            val = by_source.get(src, {}).get(fld)
            if val:
                canon[fld] = val
                canon["field_sources"][fld] = src
                break
        else:
            canon[fld] = None
    # Coordinates: prefer OSM (usually the building centroid), else first available
    loc = by_source.get("osm") or members[0]
    canon["lat"], canon["lon"] = loc["lat"], loc["lon"]
    canon["field_sources"]["location"] = loc["source"]

    keys = sorted(f"{m['source']}:{m['source_id']}" for m in members)
    canon["destination_id"] = str(uuid.uuid5(_NAMESPACE, "|".join(keys)))
    canon["members"] = [
        {"source": m["source"], "source_id": m["source_id"], "raw": m.get("raw", {})} for m in members
    ]
    return canon


def resolve(records: list[dict], threshold: float = DEFAULT_THRESHOLD, radius_m: float = RADIUS_M):
    """Return (canonical_records, scored_pairs, filtered_input_records)."""
    records = [r for r in records if r.get("name") and r.get("lat") is not None]
    pairs = scored_pairs(records, radius_m)
    clusters = cluster(records, pairs, threshold)
    canon = [merge([records[i] for i in c]) for c in clusters]
    return canon, pairs, records
