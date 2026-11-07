"""Walkthrough of the data pipeline for demos and the report.

  python -m pipeline.demo                 # all sections
  python -m pipeline.demo --city chicago  # also summarize real pipeline output if it exists

Sections:
  1. Entity resolution  - two listings of the same place merged into one record
  2. Opening hours      - messy real-world strings parsed into scheduler windows
  3. Real data summary  - counts from data/processed/<city>/ (after fetch + resolve)
"""
from __future__ import annotations

import argparse
import json
from collections import Counter

from .config import CITIES, DATA_DIR
from .hours import DAYS, parse_opening_hours
from .resolve import DEFAULT_THRESHOLD, pair_features, resolve, score

LINE = "-" * 72


def _hm(m: int) -> str:
    return f"{(m // 60) % 24:02d}:{m % 60:02d}" + (" (+1 day)" if m > 1440 else "")


def section(title: str) -> None:
    print(f"\n{LINE}\n{title}\n{LINE}")


# ---------------------------------------------------------------------------
# 1. Entity resolution
# ---------------------------------------------------------------------------

def _rec(source, sid, name, lat, lon, **kw):
    base = {"source": source, "source_id": sid, "name": name, "lat": lat, "lon": lon,
            "category": "museum", "address": None, "website": None, "phone": None,
            "hours_raw": None, "wikidata_id": None, "raw": {}}
    base.update(kw)
    return base


EXAMPLE = [
    _rec("osm", "w1", "Art Institute of Chicago", 41.87960, -87.62370,
         hours_raw="Mo,Th-Su 11:00-17:00", website="https://www.artic.edu"),
    _rec("fsq", "f1", "The Art Institute of Chicago", 41.87950, -87.62390,
         website="artic.edu", phone="(312) 443-3600", address="111 S Michigan Ave Chicago"),
    _rec("fsq", "f2", "Starbucks", 41.87965, -87.62375, category="cafe"),
]


def demo_resolution() -> None:
    section("1. ENTITY RESOLUTION: same place, two sources -> one record")
    osm, fsq, cafe = EXAMPLE
    print("Input listings:")
    for r in EXAMPLE:
        print(f"  [{r['source']}] {r['name']:<30} ({r['lat']:.5f}, {r['lon']:.5f})")

    for a, b in [(osm, fsq), (osm, cafe)]:
        f = pair_features(a, b)
        s = score(f)
        verdict = "MATCH" if s >= DEFAULT_THRESHOLD else "different places"
        print(f"\n  '{a['name']}' vs '{b['name']}'")
        print(f"    name similarity {f['name_sim']:.2f} | distance {f['dist_m']:.0f} m | "
              f"same website {f['same_domain']}")
        print(f"    score {s:.2f}  ->  {verdict}")

    canon, _, _ = resolve(EXAMPLE)
    merged = next(c for c in canon if len(c["members"]) > 1)
    print(f"\n3 listings in -> {len(canon)} destinations out. Merged record:")
    for fld in ("name", "address", "phone", "website", "hours_raw"):
        print(f"  {fld:<10} {str(merged[fld]):<34} <- from {merged['field_sources'].get(fld, '-')}")


# ---------------------------------------------------------------------------
# 2. Opening hours
# ---------------------------------------------------------------------------

HOURS_EXAMPLES = [
    "Mo-Fr 09:00-17:00; Sa 10:00-14:00; Su off",
    "Fr-Sa 18:00-02:00",
    "Mo – Fr 9.00 - 17.30",
    "Mo-Fr 09:00-17:00; Apr-Oct Sa 10:00-16:00",
    "call ahead",
]


def demo_hours() -> None:
    section("2. OPENING HOURS: messy text -> structured windows for the scheduler")
    for raw in HOURS_EXAMPLES:
        p = parse_opening_hours(raw)
        print(f"\n  {raw!r}  ->  {p.status.upper()}")
        open_days = [(d, w) for d, w in p.windows.items() if w]
        for d, wins in open_days[:3]:
            print(f"     {DAYS[d]}: " + ", ".join(f"{_hm(o)}-{_hm(c)}" for o, c in wins))
        if len(open_days) > 3:
            print(f"     ... {len(open_days) - 3} more days")
        for note in p.notes:
            print(f"     note: {note}")
        if p.status == "unparseable":
            print("     flagged for review instead of guessing")


# ---------------------------------------------------------------------------
# 3. Real data
# ---------------------------------------------------------------------------

def demo_real(city_id: str) -> None:
    section(f"3. REAL DATA: {CITIES[city_id].name}")
    path = DATA_DIR / "processed" / city_id / "destinations.jsonl"
    if not path.exists():
        print(f"  No output yet. Run:\n    python -m pipeline.run fetch --city {city_id} --skip-fsq\n"
              f"    python -m pipeline.run resolve --city {city_id} --skip-fsq")
        return
    canon = [json.loads(line) for line in path.open() if line.strip()]
    merged = sum(1 for c in canon if len(c["members"]) > 1)
    statuses = Counter(parse_opening_hours(c.get("hours_raw")).status for c in canon)
    print(f"  destinations: {len(canon)}   merged from 2+ sources: {merged}")
    print("  by category:  " + ", ".join(f"{k} {v}" for k, v in Counter(c['category'] for c in canon).most_common()))
    print("  hours:        " + ", ".join(f"{k} {statuses[k]}" for k in ("ok", "partial", "unparseable", "missing")))
    famous = [c for c in canon if c.get("wikidata_id")][:8]
    if famous:
        print("  sample landmarks:")
        for c in famous:
            print(f"    - {c['name']} ({c['category']})")


def main() -> None:
    ap = argparse.ArgumentParser(description="Zoba data pipeline demo")
    ap.add_argument("--city", choices=sorted(CITIES))
    args = ap.parse_args()
    demo_resolution()
    demo_hours()
    if args.city:
        demo_real(args.city)
    print()


if __name__ == "__main__":
    main()
