#!/bin/bash
# Run fetch -> resolve -> shortlist for every city (or the ones you list).
#
#   bash run_all_cities.sh                 # all cities in pipeline/config.py
#   bash run_all_cities.sh london paris    # just these
#   FORCE=1 bash run_all_cities.sh tokyo   # redo a city that's already done
#
# Safe to stop and rerun: finished cities are skipped, and already-downloaded
# files are reused. Output is also saved to all_cities_log.txt.

if [ -z "$HF_TOKEN" ] || [ -z "$FSQ_PLACES_PATH" ]; then
  echo "Set HF_TOKEN and FSQ_PLACES_PATH first (see README, 'Foursquare data')."
  exit 1
fi

cities="$*"
if [ -z "$cities" ]; then
  cities=$(python -c "from pipeline.config import CITIES; print(' '.join(CITIES))")
fi

{
for c in $cities; do
  echo "========== $c =========="
  if [ -f "data/processed/$c/shortlist.jsonl" ] && [ -z "$FORCE" ]; then
    echo "already done, skipping (FORCE=1 to redo)"
    continue
  fi
  if [ -f "data/raw/$c/osm.json" ] && [ -f "data/raw/$c/fsq.parquet" ] && [ -z "$FORCE" ]; then
    echo "using files already downloaded"
  else
    python -m pipeline.run fetch --city "$c" || { echo "!!! $c FAILED at fetch, rerun later"; sleep 20; continue; }
    sleep 20   # be polite to the free OpenStreetMap servers
  fi
  python -m pipeline.run resolve   --city "$c" || { echo "!!! $c FAILED at resolve"; continue; }
  python -m pipeline.run shortlist --city "$c" --size 40 || { echo "!!! $c FAILED at shortlist"; continue; }
done

echo
echo "================ SUMMARY ================"
for c in $cities; do
  if [ -f "data/processed/$c/shortlist.jsonl" ]; then echo "done    $c"; else echo "MISSING $c"; fi
done
} 2>&1 | tee -a all_cities_log.txt
