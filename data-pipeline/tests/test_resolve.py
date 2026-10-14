from pipeline.eval import threshold_report
from pipeline.resolve import normalize_name, pair_features, resolve, score


def rec(source, sid, name, lat, lon, **kw):
    base = {"source": source, "source_id": sid, "name": name, "lat": lat, "lon": lon,
            "category": kw.pop("category", "museum"), "address": None, "website": None,
            "phone": None, "hours_raw": None, "wikidata_id": None, "raw": {}}
    base.update(kw)
    return base


AIC_OSM = rec("osm", "w1", "Art Institute of Chicago", 41.87960, -87.62370,
              hours_raw="Mo-Su 11:00-17:00", wikidata_id="Q239303", website="https://www.artic.edu")
AIC_FSQ = rec("fsq", "f1", "The Art Institute of Chicago", 41.87950, -87.62390,
              website="artic.edu", phone="(312) 443-3600")
CAFE_FSQ = rec("fsq", "f2", "Starbucks", 41.87965, -87.62375, category="cafe")
BEAN_OSM = rec("osm", "n2", "Cloud Gate", 41.88270, -87.62330, category="landmark")
BEAN_FSQ = rec("fsq", "f3", "Cloud Gate (The Bean)", 41.88265, -87.62340, category="landmark")


def test_normalize_name():
    assert normalize_name("The Art Institute of Chicago") == "art institute chicago"
    # "&" and "and" normalize the same way ("and" is a stopword)
    assert normalize_name("Café & Bar") == normalize_name("Cafe and Bar") == "cafe bar"


def test_true_match_scores_high():
    assert score(pair_features(AIC_OSM, AIC_FSQ)) >= 0.9


def test_nearby_different_place_scores_low():
    assert score(pair_features(AIC_OSM, CAFE_FSQ)) < 0.6


def test_resolve_merges_and_keeps_provenance():
    canon, pairs, _ = resolve([AIC_OSM, AIC_FSQ, CAFE_FSQ, BEAN_OSM, BEAN_FSQ])
    assert len(canon) == 3
    aic = next(c for c in canon if c["wikidata_id"] == "Q239303")
    assert {m["source"] for m in aic["members"]} == {"osm", "fsq"}
    assert aic["hours_raw"] == "Mo-Su 11:00-17:00" and aic["field_sources"]["hours_raw"] == "osm"
    assert aic["phone"] == "(312) 443-3600" and aic["field_sources"]["phone"] == "fsq"
    assert aic["name"] == "Art Institute of Chicago"  # OSM name preferred


def test_one_record_per_source_per_cluster():
    dup = rec("fsq", "f9", "Art Institute of Chicago", 41.87955, -87.62380)
    canon, _, _ = resolve([AIC_OSM, AIC_FSQ, dup])
    assert all(len({m["source"] for m in c["members"]}) == len(c["members"]) for c in canon)


def test_ids_are_stable():
    a, _, _ = resolve([AIC_OSM, AIC_FSQ])
    b, _, _ = resolve([AIC_FSQ, AIC_OSM])
    assert a[0]["destination_id"] == b[0]["destination_id"]


def test_threshold_report():
    labeled = [(pair_features(AIC_OSM, AIC_FSQ), 1), (pair_features(AIC_OSM, CAFE_FSQ), 0),
               (pair_features(BEAN_OSM, BEAN_FSQ), 1)]
    rep = threshold_report(labeled, thresholds=[0.75])
    assert rep[0]["precision"] == 1.0 and rep[0]["recall"] == 1.0
