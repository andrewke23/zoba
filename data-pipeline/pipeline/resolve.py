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
DEFAULT_THRESHOLD = 0.80  # best F1 on 200 hand-labeled Chicago pairs (eval.py): P 0.77, R 0.88
WEIGHTS = {"name": 0.65, "dist": 0.35}

_STOP = {"the", "a", "an", "of", "and", "at"}
_NAMESPACE = uuid.UUID("6f1c2a8e-6b0e-4c55-9a8b-2b7d3c0e5a11")

# Which source to trust first for each canonical field
FIELD_PRIORITY = {
    "name": ["osm", "fsq"],
    # OSM first: its tourism/amenity tags are reliable for attractions, while Foursquare
    # labels can be odd (it called the Suntory Museum of Art a cafe). OSM "other" is skipped below.
    "category": ["osm", "fsq"],
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
    """Lowercase, strip accents and punctuation, drop filler words.

    Works for any script: "Café" -> "cafe", but "東京タワー" and "경복궁" are kept
    (an older version dropped every non-English character, so Asian names matched nothing).
    """
    if not isinstance(name, str) or not name:
        return ""
    s = unicodedata.normalize("NFKD", name)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))  # é -> e; CJK untouched
    s = unicodedata.normalize("NFKC", s).casefold().replace("&", " and ")
    s = re.sub(r"[^\w ]+|_", " ", s)
    return " ".join(t for t in s.split() if t not in _STOP)


def _names(r: dict) -> list[str]:
    """The record's main name plus any alternates (English, romanized, local)."""
    out = []
    for n in [r.get("name"), *(r.get("alt_names") or [])]:
        n = normalize_name(n)
        if n and n not in out:
            out.append(n)
    return out


def name_similarity(a: dict, b: dict) -> float:
    """Best fuzzy match over every name pair, so 'Tokyo Tower' matches 東京タワー via its name:en."""
    best = 0.0
    for na in _names(a):
        for nb in _names(b):
            best = max(best, fuzz.token_set_ratio(na, nb) / 100.0)
            if best == 1.0:
                return best
    return best


def _domain(url: str | None) -> str | None:
    """Website domain, or None if missing or malformed (never raises: one bad URL
    must not stop a city's whole run)."""
    if not isinstance(url, str) or not url.strip():
        return None
    # NFKC turns full-width characters (common in Japanese data, e.g. "http：//") into normal ones.
    url = unicodedata.normalize("NFKC", url).strip().split()[0].split(";")[0]
    if "://" not in url:
        url = "http://" + url
    try:
        host = urlparse(url).netloc.lower().split("@")[-1].split(":")[0]
    except ValueError:
        return None
    host = host[4:] if host.startswith("www.") else host
    return host if "." in host else None


def _digits(phone: str | None) -> str | None:
    if not isinstance(phone, str):
        return None
    phone = unicodedata.normalize("NFKC", phone)  # full-width digits -> 0-9
    d = re.sub(r"[^0-9]", "", phone)
    return d[-10:] if len(d) >= 10 else None


def pair_features(a: dict, b: dict) -> dict:
    dist = haversine_m(a["lat"], a["lon"], b["lat"], b["lon"])
    return {
        "name_sim": name_similarity(a, b),
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
    if not records:
        return
    # Cells must be at least radius_m wide in BOTH directions. A degree of longitude
    # shrinks away from the equator (~70 km in London vs 111 km), so widen lon cells,
    # otherwise pairs ~100-150 m apart east-west were never compared.
    max_lat = max(abs(r["lat"]) for r in records)
    cell_lat = radius_m / 111_000.0
    cell_lon = radius_m / (111_000.0 * math.cos(math.radians(min(max_lat, 85.0))))
    grid: dict[tuple[int, int], list[int]] = defaultdict(list)
    for i, r in enumerate(records):
        grid[(int(r["lat"] // cell_lat), int(r["lon"] // cell_lon))].append(i)

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
            if fld == "category" and val == "other":
                continue  # an uncategorized source shouldn't override a real category
            if val:
                canon[fld] = val
                canon["field_sources"][fld] = src
                break
        else:
            canon[fld] = None
    # Show English names in the app when OSM has one (東京タワー -> "Tokyo Tower"); keep the local name.
    osm = by_source.get("osm")
    if osm and osm.get("name_en") and osm.get("name_en") != canon.get("name"):
        canon["name_local"] = canon["name"]
        canon["name"] = osm["name_en"]
        canon["field_sources"]["name"] = "osm:name:en"
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
