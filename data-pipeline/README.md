# zoba-data

Data pipeline and schema for Zoba (CSDS 395, Group 2). Turns OpenStreetMap and Foursquare
place data into a deduplicated destination catalog in PostGIS, with parsed opening hours,
for the solver (F09–F11), voting (F03–F08), map (F13), and cost estimates (F16).

## Layout

```
db/schema.sql          PostGIS schema: place catalog + app entities from SRS §4.3
pipeline/
  config.py            seed cities (placeholders: chicago, dc) and paths
  sources.py           Overpass + Foursquare ingestion, normalized to one record shape
  categories.py        source categories -> Zoba taxonomy + default visit durations (F14)
  resolve.py           entity resolution: blocking, scoring, clustering, merge w/ provenance
  hours.py             defensive opening_hours parser -> weekly windows (F10)
  eval.py              labeling sample + precision/recall threshold sweep
  load.py              idempotent upsert into PostGIS
  run.py               CLI
tests/                 unit tests for hours parsing and matching
```

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
docker compose up -d                       # PostGIS with schema applied on first start
python -m pytest -q                        # 18 tests

# OSM only (no Foursquare download needed) — good first run
python -m pipeline.run fetch   --city chicago --skip-fsq
python -m pipeline.run resolve --city chicago --skip-fsq
python -m pipeline.run hours   --city chicago
python -m pipeline.run load    --city chicago
```

To add Foursquare, set `FSQ_PLACES_PATH` to the OS Places parquet (local file or `s3://` glob —
check Foursquare's docs for the current release path), then rerun `fetch` and `resolve` without
`--skip-fsq`. The open dataset has no opening hours, so hours come from OSM.

## Evaluating the matcher (your DS deliverable)

```bash
python -m pipeline.run sample --city chicago   # writes data/processed/chicago/label_pairs.csv
# hand-label the `label` column: 1 = same place, 0 = different (~200 rows, ~1 hr)
python -m pipeline.run eval   --city chicago   # precision/recall/F1 across thresholds
```

The sample is stratified by score band so the hard cases near the threshold get labeled.
`eval` rescores from saved features, so you can change `WEIGHTS` in `resolve.py` and rerun
without relabeling. Natural next step: replace the hand-set weights with a logistic regression
trained on the labels and compare.

## Conventions

- Hours: `weekday` 0 = Monday. Minutes since local midnight. A window past midnight keeps
  `close_min > 1440` on the opening day (`18:00-02:00` → `1080..1560`); `ParsedHours.is_open`
  handles the spillover.
- `hours_status`: `ok` | `partial` (some rules skipped) | `unparseable` | `missing`. The solver
  should treat non-`ok` destinations as unknown, not as always open.
- `destination_id` is a UUIDv5 of the merged source IDs, so reruns are stable. If clustering
  changes, old IDs can be orphaned — clear the city's rows before reloading during development.
- Rows with `curated = true` are never overwritten by the loader.

## Open items

- Seed cities and bounding boxes (SRS §8) — `config.py` values are placeholders.
- Wikidata/Wikivoyage descriptions and admission costs (columns exist, not yet populated).
- Travel-time matrix (`travel_time` table) — confirm whether OSRM is owned here or by the solver.
