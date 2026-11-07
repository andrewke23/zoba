"""Multi-city support: non-Latin names, high-latitude blocking, city config, Overpass fallback."""
from zoneinfo import ZoneInfo

import pytest

from pipeline import sources
from pipeline.config import CITIES
from pipeline.curate import notability, read_curation_csv, shortlist, write_curation_csv
from pipeline.resolve import candidate_pairs, normalize_name, pair_features, resolve, score


def rec(source, sid, name, lat, lon, alt=(), name_en=None, category="landmark"):
    return {"source": source, "source_id": sid, "name": name, "name_en": name_en, "alt_names": list(alt),
            "lat": lat, "lon": lon, "category": category, "address": None, "website": None, "phone": None,
            "hours_raw": None, "wikidata_id": None, "raw": {}}


# --- names in any script ---------------------------------------------------

def test_normalize_keeps_non_latin_and_strips_accents():
    assert normalize_name("東京タワー") == "東京タワー"
    assert normalize_name("경복궁") == "경복궁"
    assert normalize_name("Café de Flore") == "cafe de flore"
    assert normalize_name("ＴＯＫＹＯ") == "tokyo"  # full-width letters, common in Japanese data


def test_english_name_matches_japanese_listing_via_name_en():
    osm = rec("osm", "w1", "東京タワー", 35.65858, 139.74543, alt=["Tokyo Tower"], name_en="Tokyo Tower")
    fsq = rec("fsq", "f1", "Tokyo Tower", 35.65860, 139.74550)
    assert score(pair_features(osm, fsq)) >= 0.9
    canon, _, _ = resolve([osm, fsq])
    assert len(canon) == 1
    assert canon[0]["name"] == "Tokyo Tower" and canon[0]["name_local"] == "東京タワー"


def test_korean_names_match_and_different_places_do_not():
    palace = rec("osm", "w2", "경복궁", 37.57961, 126.97704, alt=["Gyeongbokgung Palace"], name_en="Gyeongbokgung Palace")
    same = rec("fsq", "f2", "경복궁", 37.57970, 126.97710)
    cafe = rec("fsq", "f3", "스타벅스", 37.57965, 126.97700, category="cafe")
    assert score(pair_features(palace, same)) >= 0.9
    assert score(pair_features(palace, cafe)) < 0.6


# --- blocking far from the equator ----------------------------------------

def test_pairs_140m_apart_east_west_are_compared_in_london():
    # 140 m of longitude at 51.5 N is 0.00203 degrees. With equal-size cells these two
    # landed 2 cells apart and were never compared.
    a = rec("osm", "n1", "A", 51.5080, -0.127167)
    b = rec("fsq", "f1", "A", 51.5080, -0.127167 + 0.002026)
    assert list(candidate_pairs([a, b], radius_m=150)) == [(0, 1)]


# --- city config -----------------------------------------------------------

@pytest.mark.parametrize("city", list(CITIES.values()), ids=list(CITIES))
def test_city_boxes_are_valid(city):
    s, w, n, e = city.bbox
    assert s < n and w < e
    assert n - s < 0.2 and e - w < 0.2  # small enough for one Overpass query
    ZoneInfo(city.timezone)  # raises if the timezone name is wrong


def test_osm_names_collects_alternates():
    tags = {"name": "東京タワー", "name:en": "Tokyo Tower", "alt_name": "Nippon Denpato;東京タワー"}
    assert sources.osm_names(tags) == ["東京タワー", "Tokyo Tower", "Nippon Denpato"]


# --- Overpass fallback -----------------------------------------------------

def test_fetch_osm_falls_back_to_next_server(tmp_path, monkeypatch):
    import requests

    calls = []

    class Resp:
        def __init__(self, ok): self.ok, self.text = ok, '{"elements": []}'
        def raise_for_status(self):
            if not self.ok:
                raise requests.HTTPError("502 Bad Gateway")

    def fake_post(url, **kw):
        calls.append(url)
        return Resp(ok=len(calls) > 1)  # first server fails, second works

    monkeypatch.setattr(requests, "post", fake_post)
    monkeypatch.setattr(sources, "raw_dir", lambda cid: tmp_path)
    path = sources.fetch_osm(CITIES["chicago"])
    assert path.read_text() == '{"elements": []}' and len(calls) == 2


# --- shortlist tie-breaker and hand-entered hours --------------------------

def _dest(i, tags):
    return {"destination_id": f"id-{i}", "name": tags["name"], "category": "museum", "wikidata_id": "Q",
            "website": "x", "phone": None, "hours_raw": "Mo-Su 10:00-17:00",
            "members": [{"source": "osm", "source_id": f"w{i}", "raw": tags}, {"source": "fsq", "source_id": f"f{i}", "raw": {}}]}


def test_richer_osm_entry_breaks_ties():
    famous = {"name": "Art Institute of Chicago", "tourism": "museum", "wikipedia": "en:Art Institute of Chicago",
              **{f"name:{l}": "x" for l in ["fr", "de", "ja", "ko", "zh", "es", "it", "ru", "pl", "pt"]},
              **{f"extra{i}": "x" for i in range(25)}}
    obscure = {"name": "Money Museum", "tourism": "museum"}
    assert notability(_dest(1, famous)) > notability(_dest(2, obscure)) + 1


def test_hand_entered_hours_override(tmp_path):
    path = tmp_path / "curation.csv"
    kept = shortlist([_dest(1, {"name": "Field Museum", "tourism": "museum"})], size=5)
    write_curation_csv(kept, path)
    assert "Mo-Su 10:00-17:00" in path.read_text()  # pre-filled from the data
    path.write_text(path.read_text().replace("Mo-Su 10:00-17:00", "Mo-Su 09:00-17:00"))
    assert read_curation_csv(path)["id-1"]["hours_raw"] == "Mo-Su 09:00-17:00"


# --- messy websites and phones from Asian data -----------------------------

def test_malformed_and_full_width_urls_never_crash():
    from pipeline.resolve import _digits, _domain

    assert _domain("http：//www.tokyotower.co.jp/") == "tokyotower.co.jp"  # full-width colon
    assert _domain("https://example.com:8080/x") == "example.com"
    assert _domain("www.artic.edu; https://other.org") == "artic.edu"
    for bad in ["http://[broken", "http：", "not a url", "://", "　"]:
        assert _domain(bad) is None or isinstance(_domain(bad), str)
    assert _digits("０３－３４３３－５１１１") == "0334335111"  # full-width digits


# --- must-see places fall inside each city's box ----------------------------

MUST_SEE = {  # (lat, lon) of landmarks each city's box has to cover
    "chicago": {"Art Institute": (41.8796, -87.6237), "Shedd Aquarium": (41.8676, -87.6140), "Navy Pier": (41.8917, -87.6086)},
    "dc": {"Lincoln Memorial": (38.8893, -77.0502), "US Capitol": (38.8899, -77.0091), "White House": (38.8977, -77.0365)},
    "nyc": {"Statue of Liberty": (40.6892, -74.0445), "Met Museum": (40.7794, -73.9632), "Times Square": (40.7580, -73.9855),
            "Brooklyn Bridge": (40.7061, -73.9969)},
    "boston": {"Fenway Park": (42.3467, -71.0972), "Faneuil Hall": (42.3600, -71.0568), "MFA Boston": (42.3394, -71.0940)},
    "philadelphia": {"Liberty Bell": (39.9496, -75.1503), "Philadelphia Museum of Art": (39.9656, -75.1810)},
    "miami": {"Bayside": (25.7781, -80.1867), "South Beach": (25.7810, -80.1300), "Vizcaya": (25.7443, -80.2105)},
    "new_orleans": {"Jackson Square": (29.9574, -90.0629), "WWII Museum": (29.9430, -90.0705), "Garden District": (29.9290, -90.0850)},
    "las_vegas": {"Bellagio": (36.1126, -115.1767), "Fremont Street": (36.1707, -115.1430), "Mandalay Bay": (36.0909, -115.1750)},
    "seattle": {"Space Needle": (47.6205, -122.3493), "Pike Place Market": (47.6097, -122.3422)},
    "san_francisco": {"Fisherman's Wharf": (37.8080, -122.4177), "Union Square": (37.7880, -122.4075), "Ferry Building": (37.7955, -122.3937)},
    "los_angeles": {"Griffith Observatory": (34.1184, -118.3004), "Disney Concert Hall": (34.0553, -118.2498), "LACMA": (34.0639, -118.3592)},
    "san_diego": {"Balboa Park": (32.7341, -117.1446), "Gaslamp": (32.7110, -117.1600), "USS Midway": (32.7137, -117.1751)},
    "honolulu": {"Waikiki Beach": (21.2766, -157.8270), "Iolani Palace": (21.3069, -157.8590), "Diamond Head": (21.2620, -157.8060)},
    "cleveland": {"Rock Hall": (41.5085, -81.6954), "Cleveland Museum of Art": (41.5079, -81.6119), "West Side Market": (41.4848, -81.7030)},
    "irvine": {"UC Irvine": (33.6405, -117.8443), "Irvine Spectrum": (33.6500, -117.7430)},
    "toronto": {"CN Tower": (43.6426, -79.3871), "Royal Ontario Museum": (43.6677, -79.3948), "St Lawrence Market": (43.6487, -79.3715)},
    "vancouver": {"Stanley Park": (49.3043, -123.1443), "Granville Island": (49.2712, -123.1340), "Gastown": (49.2844, -123.1089)},
    "montreal": {"Old Port": (45.5075, -73.5537), "Notre-Dame Basilica": (45.5045, -73.5561), "Mount Royal": (45.5048, -73.5878)},
    "mexico_city": {"Zocalo": (19.4326, -99.1332), "Anthropology Museum": (19.4260, -99.1863), "Bellas Artes": (19.4352, -99.1412)},
    "london": {"British Museum": (51.5194, -0.1270), "Tower of London": (51.5081, -0.0759), "Big Ben": (51.5007, -0.1246),
               "Buckingham Palace": (51.5014, -0.1419)},
    "paris": {"Eiffel Tower": (48.8584, 2.2945), "Louvre": (48.8606, 2.3376), "Notre-Dame": (48.8530, 2.3499),
              "Sacre-Coeur": (48.8867, 2.3431), "Arc de Triomphe": (48.8738, 2.2950)},
    "rome": {"Colosseum": (41.8902, 12.4922), "St Peter's": (41.9022, 12.4539), "Trevi Fountain": (41.9009, 12.4833)},
    "barcelona": {"Sagrada Familia": (41.4036, 2.1744), "Park Guell": (41.4145, 2.1527), "La Boqueria": (41.3817, 2.1716)},
    "madrid": {"Prado": (40.4138, -3.6921), "Royal Palace": (40.4180, -3.7143), "Retiro Park": (40.4153, -3.6845)},
    "lisbon": {"Belem Tower": (38.6916, -9.2160), "Jeronimos": (38.6979, -9.2068), "Sao Jorge Castle": (38.7139, -9.1335)},
    "amsterdam": {"Rijksmuseum": (52.3600, 4.8852), "Anne Frank House": (52.3752, 4.8840), "Van Gogh Museum": (52.3584, 4.8811)},
    "berlin": {"Brandenburg Gate": (52.5163, 13.3777), "East Side Gallery": (52.5050, 13.4397), "Museum Island": (52.5169, 13.4019)},
    "prague": {"Prague Castle": (50.0909, 14.4005), "Charles Bridge": (50.0865, 14.4114), "Old Town Square": (50.0875, 14.4213)},
    "vienna": {"Schonbrunn": (48.1845, 16.3122), "St Stephen's": (48.2085, 16.3731), "Belvedere": (48.1915, 16.3809)},
    "istanbul": {"Hagia Sophia": (41.0086, 28.9802), "Topkapi": (41.0115, 28.9834), "Galata Tower": (41.0256, 28.9741)},
    "tokyo": {"Senso-ji": (35.7148, 139.7967), "Tokyo Skytree": (35.7101, 139.8107), "Meiji Shrine": (35.6764, 139.6993),
              "Shibuya Crossing": (35.6595, 139.7005), "Tokyo National Museum": (35.7188, 139.7765), "Tokyo Tower": (35.6586, 139.7454)},
    "osaka": {"Osaka Castle": (34.6873, 135.5262), "Dotonbori": (34.6687, 135.5013), "Umeda Sky Building": (34.7053, 135.4906)},
    "kyoto": {"Kinkaku-ji": (35.0394, 135.7292), "Fushimi Inari": (34.9671, 135.7727), "Kiyomizu-dera": (34.9949, 135.7850)},
    "sapporo": {"Odori Park": (43.0597, 141.3480), "Clock Tower": (43.0625, 141.3536), "Susukino": (43.0556, 141.3536)},
    "seoul": {"Gyeongbokgung": (37.5796, 126.9770), "N Seoul Tower": (37.5512, 126.9882), "Myeongdong": (37.5636, 126.9827)},
    "taipei": {"Taipei 101": (25.0340, 121.5645), "CKS Memorial Hall": (25.0346, 121.5218), "Longshan Temple": (25.0372, 121.4999)},
    "hong_kong": {"Victoria Peak": (22.2759, 114.1455), "Star Ferry TST": (22.2940, 114.1689), "Temple Street": (22.3060, 114.1700)},
    "singapore": {"Marina Bay Sands": (1.2834, 103.8607), "Gardens by the Bay": (1.2816, 103.8636), "Chinatown": (1.2836, 103.8443)},
    "bangkok": {"Grand Palace": (13.7500, 100.4913), "Wat Arun": (13.7437, 100.4888), "Jim Thompson House": (13.7493, 100.5283)},
    "sydney": {"Opera House": (-33.8568, 151.2153), "Harbour Bridge": (-33.8523, 151.2108), "Darling Harbour": (-33.8748, 151.2010)},
    "dubai": {"Burj Khalifa": (25.1972, 55.2744), "Al Fahidi": (25.2633, 55.2972), "Gold Souk": (25.2697, 55.2963)},
}


@pytest.mark.parametrize("city_id", list(MUST_SEE))
def test_city_box_covers_must_see_places(city_id):
    s, w, n, e = CITIES[city_id].bbox
    outside = [name for name, (lat, lon) in MUST_SEE[city_id].items() if not (s <= lat <= n and w <= lon <= e)]
    assert not outside, f"{city_id} box misses {outside}"


def test_shrines_and_temples_are_downloaded_and_categorized():
    from pipeline.categories import from_osm_tags

    assert 'place_of_worship"]["name"]["wikidata"]' in sources.OVERPASS_QUERY
    assert from_osm_tags({"amenity": "place_of_worship", "religion": "shinto"}) == "landmark"


def test_osm_category_wins_over_odd_foursquare_label():
    osm = rec("osm", "w9", "Suntory Museum of Art", 35.6662, 139.7311, category="museum")
    fsq = rec("fsq", "f9", "Suntory Museum of Art", 35.6663, 139.7312, category="cafe")
    canon, _, _ = resolve([osm, fsq])
    assert len(canon) == 1 and canon[0]["category"] == "museum"
    # but an uncategorized OSM record doesn't override a real Foursquare category
    osm2 = rec("osm", "n9", "Blue Bottle", 35.67, 139.71, category="other")
    fsq2 = rec("fsq", "f8", "Blue Bottle", 35.67, 139.71, category="cafe")
    assert resolve([osm2, fsq2])[0][0]["category"] == "cafe"
