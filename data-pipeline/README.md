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
  curate.py            notability shortlist + curation.csv for hand-entered prices
  demo.py              walkthrough for demos
  run.py               CLI
tests/                 unit tests for hours parsing, matching and the shortlist
```

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
docker compose up -d                       # PostGIS with schema applied on first start
python -m pytest -q                        # 121 tests

# OSM only (no Foursquare download needed) — good first run
python -m pipeline.run fetch   --city chicago --skip-fsq
python -m pipeline.run resolve --city chicago --skip-fsq
python -m pipeline.run hours   --city chicago
python -m pipeline.run load    --city chicago
```

To add Foursquare, set `FSQ_PLACES_PATH` to the OS Places parquet (local file or `s3://` glob —
check Foursquare's docs for the current release path), then rerun `fetch` and `resolve` without
`--skip-fsq`. The open dataset has no opening hours, so hours come from OSM.

## Cities

`config.py` has 41 cities across the US, Canada, Mexico, Europe, Asia and Australia
(`python -c "from pipeline.config import CITIES; print(*CITIES)"` lists them). Each box covers the tourist
core only (a few km across). To add one, add a `City.around(...)` line with its center and timezone.

Names in any script work: OSM's English/romanized names (`name:en`, `int_name`, ...) are matched too,
so Foursquare's "Tokyo Tower" merges with OSM's 東京タワー, and the app shows the English name.

Typical run for a new city (Foursquare env vars set, see below):

```bash
python -m pipeline.run fetch     --city tokyo            # tries several Overpass servers
python -m pipeline.run resolve   --city tokyo
python -m pipeline.run shortlist --city tokyo --size 40
python -m pipeline.demo --city tokyo
```

If Overpass is down but you already have `osm.json`, use `fetch --skip-osm` to get Foursquare only.

## Running every city

`bash run_all_cities.sh` runs fetch -> resolve -> shortlist for all 41 cities (or
`bash run_all_cities.sh london paris` for some). Finished cities are skipped, so it is safe
to stop and rerun; `FORCE=1` redoes a city. Expect a few hours for all of them.
Each city has a must-see list in `pins/<city>.txt`.

## Foursquare data

The dataset is free but gated on Hugging Face. Create an account, open
huggingface.co/datasets/foursquare/fsq-os-places, accept the terms, and make a read token
(Settings -> Access Tokens). Check the dataset's Files tab for the newest `release/dt=...` folder.

```bash
export HF_TOKEN="hf_..."
export FSQ_PLACES_PATH="hf://datasets/foursquare/fsq-os-places/release/dt=2026-10-15/places/parquet/*.parquet"
python -m pipeline.run fetch   --city chicago      # OSM + Foursquare (Foursquare scan can take 5-20 min)
python -m pipeline.run resolve --city chicago
```

## Shortlist and hand curation

```bash
python -m pipeline.run shortlist --city chicago --size 40   # ranked, category-balanced shortlist
# fill in hours (OSM format, e.g. Mo-Su 10:00-17:00) / admission_cost_usd / description in curation/chicago.csv
python -m pipeline.run load --city chicago --shortlist      # loads only the shortlist + your edits
```

Notability = Wikidata entry (+3), listed by both sources (+2), tourism tag (+1), parseable hours (+1),
website/phone (+0.75), plus tie-breakers: Wikipedia link (+0.5), translated names (up to +1), and how
detailed the OSM entry is (up to +1), so famous places outrank merely well-documented ones. Each category gets a fixed share of the list so restaurants can't crowd out museums.
`curation/<city>.csv` and `pins/<city>.txt` are committed to the repo so hand edits are shared.
`load --shortlist` also removes this city's other pipeline rows unless a trip already uses them.

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
