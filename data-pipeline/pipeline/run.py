"""CLI entry point.

  python -m pipeline.run fetch   --city chicago            # Overpass + Foursquare -> data/raw/
  python -m pipeline.run resolve --city chicago            # normalize + dedupe -> data/processed/
  python -m pipeline.run sample  --city chicago            # pairs CSV for hand labeling
  python -m pipeline.run eval    --city chicago            # precision/recall from labeled CSV
  python -m pipeline.run hours   --city chicago            # opening-hours parse coverage
  python -m pipeline.run load    --city chicago            # upsert into PostGIS
  python -m pipeline.run all     --city chicago            # fetch -> resolve -> load
"""
from __future__ import annotations

import argparse
import json
from collections import Counter

from . import sources
from .config import CITIES, out_dir, raw_dir
from .hours import parse_opening_hours


def cmd_fetch(city, args):
    print("OSM ->", sources.fetch_osm(city))
    if args.skip_fsq:
        print("Foursquare skipped")
    else:
        print("FSQ ->", sources.fetch_fsq(city))


def _load_raw(city, skip_fsq: bool):
    recs = sources.normalize_osm(raw_dir(city.city_id) / "osm.json")
    fsq_path = raw_dir(city.city_id) / "fsq.parquet"
    if not skip_fsq and fsq_path.exists():
        recs += sources.normalize_fsq(fsq_path)
    return recs


def cmd_resolve(city, args):
    from .resolve import resolve

    recs = _load_raw(city, args.skip_fsq)
    canon, pairs, kept = resolve(recs, threshold=args.threshold)
    sources.write_jsonl(canon, out_dir(city.city_id) / "destinations.jsonl")
    by_src = Counter(r["source"] for r in kept)
    multi = sum(1 for c in canon if len(c["members"]) > 1)
    print(f"input records: {dict(by_src)}")
    print(f"candidate pairs: {len(pairs)}   canonical destinations: {len(canon)}   merged (2+ sources): {multi}")
    print("categories:", dict(Counter(c["category"] for c in canon).most_common()))


def cmd_sample(city, args):
    from .eval import write_label_sample
    from .resolve import scored_pairs

    recs = [r for r in _load_raw(city, args.skip_fsq) if r.get("name")]
    pairs = scored_pairs(recs)
    path = out_dir(city.city_id) / "label_pairs.csv"
    n = write_label_sample(recs, pairs, path)
    print(f"wrote {n} pairs to {path} — fill in the `label` column (1/0), then run `eval`")


def cmd_eval(city, args):
    from .eval import load_labels, print_report, threshold_report

    labeled = load_labels(out_dir(city.city_id) / "label_pairs.csv")
    print(f"{len(labeled)} labeled pairs")
    print_report(threshold_report(labeled))


def cmd_hours(city, args):
    canon = sources.read_jsonl(out_dir(city.city_id) / "destinations.jsonl")
    counts, bad = Counter(), []
    for d in canon:
        p = parse_opening_hours(d.get("hours_raw"))
        counts[p.status] += 1
        if p.status in ("partial", "unparseable"):
            bad.append((d["name"], d["hours_raw"], p.notes[:2]))
    total = sum(counts.values()) or 1
    for k in ("ok", "partial", "unparseable", "missing"):
        print(f"{k:>12}: {counts[k]:5d}  ({counts[k] / total:.0%})")
    print("\nexamples to fix in the parser:")
    for row in bad[: args.show]:
        print("  ", json.dumps(row))


def cmd_load(city, args):
    from .load import load_city

    canon = sources.read_jsonl(out_dir(city.city_id) / "destinations.jsonl")
    print(load_city(city, canon))


def main():
    ap = argparse.ArgumentParser(description="Zoba data pipeline")
    ap.add_argument("command", choices=["fetch", "resolve", "sample", "eval", "hours", "load", "all"])
    ap.add_argument("--city", required=True, choices=sorted(CITIES))
    ap.add_argument("--threshold", type=float, default=0.75)
    ap.add_argument("--skip-fsq", action="store_true", help="OSM only (no Foursquare parquet needed)")
    ap.add_argument("--show", type=int, default=15)
    args = ap.parse_args()
    city = CITIES[args.city]

    if args.command == "all":
        for fn in (cmd_fetch, cmd_resolve, cmd_hours, cmd_load):
            fn(city, args)
    else:
        globals()[f"cmd_{args.command}"](city, args)


if __name__ == "__main__":
    main()
