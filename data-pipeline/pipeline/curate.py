"""Shortlist: rank resolved destinations by notability and keep a votable set.

A raw city pull has thousands of places (every restaurant and bar), but members
can only vote on a few dozen. This step scores each destination on signals that
mark well-known, plannable places, then keeps the best per category so the
shortlist stays balanced (not 40 restaurants).

Outputs in data/processed/<city>/:
  shortlist.jsonl   the kept destinations, ranked
  curation.csv      one row per kept place for hand entry of admission price,
                    description and visit length. Existing edits are preserved
                    when the shortlist is rebuilt. `load --shortlist` applies them.
"""
from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

from .hours import parse_opening_hours

# Share of the shortlist each category may take (rounded, at least 1 if any exist).
CATEGORY_SHARE = {
    "museum": 0.18, "landmark": 0.18, "entertainment": 0.12, "park": 0.12,
    "viewpoint": 0.08, "food": 0.16, "cafe": 0.06, "nightlife": 0.06, "shopping": 0.04,
}
CURATION_FIELDS = ["destination_id", "name", "category", "notability",
                   "hours", "admission_cost_usd", "description", "est_duration_min"]
# `hours` uses OSM format, e.g. "Mo-Su 10:00-17:00" or "Tu-Su 09:30-17:00; Mo off".
# It is pre-filled with what the data already has; fix or fill it in by hand.


def notability(d: dict) -> float:
    """Higher = better known and easier to plan around."""
    s = 0.0
    if d.get("wikidata_id"):
        s += 3.0  # has a Wikipedia/Wikidata entry
    if len(d.get("members", [])) > 1:
        s += 2.0  # listed independently by both sources
    if d.get("website"):
        s += 0.5
    if d.get("phone"):
        s += 0.25
    status = parse_opening_hours(d.get("hours_raw")).status
    s += {"ok": 1.0, "partial": 0.5}.get(status, 0.0)  # schedulable
    tags = {}
    for m in d.get("members", []):
        if m["source"] == "osm":
            tags = m.get("raw") or {}
    if tags.get("tourism") in ("museum", "attraction", "zoo", "aquarium", "theme_park", "viewpoint", "gallery"):
        s += 1.0
    if tags.get("heritage") or tags.get("historic") in ("monument", "castle", "building"):
        s += 0.5
    # Tie-breakers. The signals above max out for every well-documented museum, so the
    # Money Museum tied the Art Institute. Famous places have far richer OSM entries:
    # a Wikipedia link, names in many languages, and dozens of tags.
    if tags.get("wikipedia"):
        s += 0.5
    s += min(sum(1 for k in tags if k.startswith("name:")), 20) / 20  # up to +1: translated names
    s += min(len(tags), 60) / 60                                       # up to +1: entry detail
    return round(s, 2)


PINS_DIR = Path(__file__).resolve().parent.parent / "pins"
# Hand-entered hours/prices/descriptions live in the repo (not in the git-ignored data/
# folder) so they are shared with the team and survive a re-download.
CURATION_DIR = Path(__file__).resolve().parent.parent / "curation"


def curation_path(city_id: str, curation_dir: Path = CURATION_DIR, old_dir: Path | None = None) -> Path:
    """curation/<city>.csv. On first use, moves over an older data/processed/<city>/curation.csv
    so edits made before this change are kept."""
    curation_dir.mkdir(parents=True, exist_ok=True)
    path = curation_dir / f"{city_id}.csv"
    if old_dir is not None:
        old = old_dir / "curation.csv"
        if old.exists() and not path.exists():
            path.write_bytes(old.read_bytes())
            print(f"moved your existing edits: {old} -> {path}")
    return path


def read_pins(city_id: str, pins_dir: Path = PINS_DIR) -> tuple[list[str], list[str]]:
    """pins/<city>.txt: one place name per line = always include; '-Name' = always exclude.
    Blank lines and '#' comments are ignored. Names can be English or local ("浅草寺")."""
    path = pins_dir / f"{city_id}.txt"
    include, exclude = [], []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.split("#", 1)[0].strip()
            if line.startswith("-"):
                exclude.append(line[1:].strip())
            elif line:
                include.append(line)
    return include, exclude


def _name_index(canon: list[dict]) -> dict[str, list[dict]]:
    """normalized name -> destinations with that English, local or alternate name."""
    from .resolve import normalize_name

    index: dict[str, list[dict]] = defaultdict(list)
    for d in canon:
        names = {d.get("name"), d.get("name_local")}
        for m in d.get("members", []):
            raw = m.get("raw") or {}
            names |= {raw.get(k) for k in ("name", "name:en", "int_name", "official_name")}
        for n in {normalize_name(x) for x in names if isinstance(x, str)}:
            if n:
                index[n].append(d)
    return index


def _find(index: dict[str, list[dict]], name: str, fuzzy: list | None = None) -> dict | None:
    """Best-scoring destination with this name (case, accents, punctuation ignored).

    Exact match first. Otherwise falls back to names containing every word of the pin
    ("Louvre" -> "Musee du Louvre"), picking the most notable; those are recorded in
    `fuzzy` so the user can check them."""
    from .resolve import normalize_name

    target = normalize_name(name)
    if not target:
        return None
    hits = index.get(target, [])
    if hits:
        return max(hits, key=notability)
    words = set(target.split())
    cands = [d for key, ds in index.items()
             if (target in key if len(words) == 1 else words <= set(key.split()))
             for d in ds]
    if not cands:
        return None
    # Prefer an attraction over a business that just mentions it ("PJ's Coffee at the National
    # WWII Museum", "Loewe Marina Bay Sands"), then notability, then the shortest name.
    businesses = {"food", "cafe", "nightlife", "shopping", "other"}
    best = max(cands, key=lambda d: (d.get("category") not in businesses, notability(d), -len(d["name"])))
    if fuzzy is not None:
        fuzzy.append((name, best["name"]))
    return best


def shortlist(canon: list[dict], size: int = 40, include: list[str] = (), exclude: list[str] = (),
              report: dict | None = None) -> list[dict]:
    """Top `size` places, balanced by category. `include`/`exclude` are hand-picked names
    (see pins/<city>.txt); unmatched names are listed in report["unmatched"]."""
    report = report if report is not None else {}
    report["unmatched"], report["fuzzy"] = [], []
    index = _name_index(canon) if (include or exclude) else {}
    banned = set()
    for name in exclude:
        d = _find(index, name, report["fuzzy"])
        if d:
            banned.add(d["destination_id"])
        else:
            report["unmatched"].append("-" + name)
    pinned = []
    for name in include:
        d = _find(index, name, report["fuzzy"])
        if d and d["destination_id"] not in {p["destination_id"] for p in pinned}:
            pinned.append({**d, "notability": notability(d), "pinned": True})
        elif not d:
            report["unmatched"].append(name)
    canon = [d for d in canon if d["destination_id"] not in banned]
    auto = _auto_shortlist(canon, size)
    taken = {d["destination_id"] for d in pinned}
    # Pinned places go first; the rest of the slots keep the automatic ranking.
    kept = pinned + [d for d in auto if d["destination_id"] not in taken][: max(0, size - len(pinned))]
    kept.sort(key=lambda d: (not d.get("pinned"), -d["notability"], d["name"]))
    return kept


def _auto_shortlist(canon: list[dict], size: int) -> list[dict]:
    by_cat: dict[str, list[dict]] = defaultdict(list)
    for d in canon:
        if d.get("category") in CATEGORY_SHARE:
            by_cat[d["category"]].append({**d, "notability": notability(d)})
    for items in by_cat.values():
        items.sort(key=lambda d: (-d["notability"], d["name"]))

    kept: list[dict] = []
    for cat, share in CATEGORY_SHARE.items():
        kept += by_cat.get(cat, [])[: max(1, round(size * share))]
    # Fill any leftover slots with the best remaining places of any category.
    taken = {d["destination_id"] for d in kept}
    rest = sorted((d for items in by_cat.values() for d in items if d["destination_id"] not in taken),
                  key=lambda d: -d["notability"])
    kept += rest[: max(0, size - len(kept))]
    kept.sort(key=lambda d: (-d["notability"], d["name"]))
    return kept[:size]


def write_curation_csv(kept: list[dict], path: Path) -> None:
    """Write the hand-entry sheet, keeping any values already typed in."""
    old: dict[str, dict] = {}
    if path.exists():
        with path.open(newline="") as f:
            old = {r["destination_id"]: r for r in csv.DictReader(f)}
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CURATION_FIELDS)
        w.writeheader()
        for d in kept:
            prev = old.get(d["destination_id"], {})
            w.writerow({
                "destination_id": d["destination_id"], "name": d["name"], "category": d["category"],
                "notability": d["notability"],
                "hours": prev.get("hours") or d.get("hours_raw") or "",
                "admission_cost_usd": prev.get("admission_cost_usd", ""),
                "description": prev.get("description", ""),
                "est_duration_min": prev.get("est_duration_min", ""),
            })


def read_curation_csv(path: Path) -> dict[str, dict]:
    """destination_id -> {field: value} for the cells that were filled in."""
    if not path.exists():
        return {}
    out = {}
    with path.open(newline="") as f:
        for r in csv.DictReader(f):
            vals = {}
            if (r.get("hours") or "").strip():
                vals["hours_raw"] = r["hours"].strip()
            if r.get("admission_cost_usd", "").strip():
                vals["admission_cost_usd"] = float(r["admission_cost_usd"])
            if r.get("description", "").strip():
                vals["description"] = r["description"].strip()
            if r.get("est_duration_min", "").strip():
                vals["est_duration_min"] = int(float(r["est_duration_min"]))
            if vals:
                out[r["destination_id"]] = vals
    return out
