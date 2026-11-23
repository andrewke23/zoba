import csv

from pipeline.curate import notability, read_curation_csv, shortlist, write_curation_csv
from pipeline.resolve import pair_features


def dest(i, name, category, wikidata=None, sources=("osm",), hours=None, tags=None):
    return {
        "destination_id": f"id-{i}", "name": name, "category": category, "wikidata_id": wikidata,
        "website": None, "phone": None, "hours_raw": hours,
        "members": [{"source": s, "source_id": f"{s}{i}", "raw": tags or {}} for s in sources],
    }


def test_notability_rewards_known_places():
    famous = dest(1, "Art Institute", "museum", "Q1", ("osm", "fsq"), "Mo-Su 10:00-17:00", {"tourism": "museum"})
    obscure = dest(2, "Tiny Gallery", "museum")
    assert notability(famous) > notability(obscure)


def test_shortlist_is_balanced_and_sized():
    canon = [dest(i, f"Restaurant {i}", "food", "Q", ("osm", "fsq")) for i in range(30)]
    canon += [dest(100 + i, f"Museum {i}", "museum") for i in range(5)]
    kept = shortlist(canon, size=10)
    assert len(kept) == 10
    assert any(d["category"] == "museum" for d in kept)  # famous restaurants can't crowd museums out
    assert all("notability" in d for d in kept)


def test_shortlist_skips_other_category():
    kept = shortlist([dest(1, "Chase Bank", "other"), dest(2, "Park", "park")], size=5)
    assert [d["name"] for d in kept] == ["Park"]


def test_curation_csv_keeps_edits(tmp_path):
    path = tmp_path / "curation.csv"
    kept = shortlist([dest(1, "Field Museum", "museum", "Q1")], size=5)
    write_curation_csv(kept, path)
    rows = list(csv.DictReader(path.open()))
    rows[0]["admission_cost_usd"] = "30"
    rows[0]["description"] = "Home of SUE the T. rex"
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)
    write_curation_csv(kept, path)  # rebuilding must not wipe hand edits
    edits = read_curation_csv(path)
    assert edits["id-1"] == {"admission_cost_usd": 30.0, "description": "Home of SUE the T. rex"}


def test_missing_values_from_parquet_do_not_crash_matching():
    a = {"name": "Navy Pier", "lat": 41.8917, "lon": -87.6086, "website": float("nan"), "phone": float("nan"),
         "category": "landmark", "wikidata_id": None}
    b = {"name": "Navy Pier", "lat": 41.8918, "lon": -87.6090, "website": "navypier.org", "phone": None,
         "category": "landmark", "wikidata_id": None}
    f = pair_features(a, b)
    assert f["same_domain"] is False and f["same_phone"] is False


# --- pins: hand-picked must-include / exclude ------------------------------

def _city(n_low=50):
    famous = dest(1, "Sensō-ji", "landmark", "Q1", ("osm",), None, {"name": "浅草寺", "name:en": "Sensō-ji"})
    famous["name_local"] = "浅草寺"
    filler = [dest(100 + i, f"Well Documented {i}", "landmark", "Q", ("osm", "fsq"), "Mo-Su 09:00-17:00",
                   {"tourism": "attraction"}) for i in range(n_low)]
    return [famous] + filler


def test_pinned_place_gets_in_even_when_it_ranks_low():
    canon = _city()
    assert "Sensō-ji" not in [d["name"] for d in shortlist(canon, size=10)]
    kept = shortlist(canon, size=10, include=["浅草寺"])  # matched by Japanese name
    assert kept[0]["name"] == "Sensō-ji" and kept[0]["pinned"] and len(kept) == 10
    assert shortlist(canon, size=10, include=["senso-ji"])[0]["name"] == "Sensō-ji"  # accents/case ignored


def test_excluded_place_is_dropped_and_typos_are_reported():
    canon = _city()
    report = {}
    kept = shortlist(canon, size=10, exclude=["Well Documented 0"], include=["Sensoji Templ"], report=report)
    assert "Well Documented 0" not in [d["name"] for d in kept]
    assert report["unmatched"] == ["Sensoji Templ"]


def test_pins_file_parsing(tmp_path):
    from pipeline.curate import read_pins

    (tmp_path / "tokyo.txt").write_text("# comment\n浅草寺   # Senso-ji\n\n-Money Museum\nTokyo Tower\n", encoding="utf-8")
    assert read_pins("tokyo", tmp_path) == (["浅草寺", "Tokyo Tower"], ["Money Museum"])
    assert read_pins("nowhere", tmp_path) == ([], [])


def test_curation_file_lives_in_repo_and_old_edits_move_over(tmp_path):
    from pipeline.curate import curation_path

    old_dir = tmp_path / "data" / "processed" / "chicago"
    old_dir.mkdir(parents=True)
    (old_dir / "curation.csv").write_text("destination_id,name\nid-1,Field Museum\n")
    path = curation_path("chicago", curation_dir=tmp_path / "curation", old_dir=old_dir)
    assert path == tmp_path / "curation" / "chicago.csv"
    assert "Field Museum" in path.read_text()                  # old edits carried over
    path.write_text("destination_id,name\nid-1,EDITED\n")
    curation_path("chicago", curation_dir=tmp_path / "curation", old_dir=old_dir)
    assert "EDITED" in path.read_text()                        # never overwritten afterwards


def test_pin_without_exact_name_falls_back_to_best_containing_match():
    louvre = dest(1, "Musée du Louvre", "museum", "Q19675", ("osm", "fsq"), "Mo,We-Su 09:00-18:00",
                  {"name": "Musée du Louvre", "tourism": "museum", "wikipedia": "fr:Louvre"})
    shop = dest(2, "Louvre Gift Shop", "shopping", None, ("fsq",), None, {})
    filler = [dest(100 + i, f"Gallery {i}", "museum", "Q", ("osm", "fsq"), "Mo-Su 09:00-17:00",
                   {"tourism": "museum", "wikipedia": "x", **{f"name:{k}": "x" for k in range(20)}}) for i in range(20)]
    report = {}
    kept = shortlist([louvre, shop] + filler, size=5, include=["Louvre"], report=report)
    assert kept[0]["name"] == "Musée du Louvre"           # the museum, not the gift shop
    assert report["fuzzy"] == [("Louvre", "Musée du Louvre")] and report["unmatched"] == []


def test_fuzzy_pin_prefers_the_attraction_over_a_business_inside_it():
    museum = dest(1, "National World War II Museum", "museum", None, ("osm",), None, {"tourism": "museum"})
    cafe = dest(2, "PJ's Coffee at the National WWII Museum", "cafe", "Q", ("osm", "fsq"), "Mo-Su 07:00-17:00",
                {"amenity": "cafe", "wikipedia": "x"})
    museum2 = dest(3, "The National WWII Museum", "museum", None, ("fsq",), None, {})
    report = {}
    kept = shortlist([museum, cafe, museum2], size=3, include=["National WWII Museum"], report=report)
    assert kept[0]["name"] == "The National WWII Museum"  # the museum, even though the cafe scores higher
