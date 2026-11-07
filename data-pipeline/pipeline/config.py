"""City configuration and paths."""
from __future__ import annotations

import math
import os
from dataclasses import dataclass
from pathlib import Path

DATA_DIR = Path(os.environ.get("ZOBA_DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://zoba:zoba@localhost:5432/zoba")

# Foursquare OS Places parquet: local path/glob, or
# hf://datasets/foursquare/fsq-os-places/release/dt=YYYY-MM-DD/places/parquet/*.parquet (needs HF_TOKEN)
FSQ_PLACES_PATH = os.environ.get("FSQ_PLACES_PATH", "")

# Tried in order; the public Overpass servers are often busy (502/504/429).
OVERPASS_URLS = [u for u in [
    os.environ.get("OVERPASS_URL"),
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
] if u]


@dataclass(frozen=True)
class City:
    city_id: str
    name: str
    south: float
    west: float
    north: float
    east: float
    timezone: str

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        return (self.south, self.west, self.north, self.east)

    @classmethod
    def around(cls, city_id: str, name: str, lat: float, lon: float, timezone: str, half_km: float = 3.5) -> "City":
        """Square box `half_km` each way from a center point (the tourist core, not the whole metro)."""
        dlat = half_km / 111.0
        dlon = half_km / (111.0 * math.cos(math.radians(lat)))
        return cls(city_id, name, round(lat - dlat, 4), round(lon - dlon, 4),
                   round(lat + dlat, 4), round(lon + dlon, 4), timezone)


# Boxes cover each city's main tourist area. Bigger boxes = slower Overpass downloads,
# so keep them tight; widen half_km if important places are cut off.
_CITY_LIST = [
    # --- United States ---
    City("chicago", "Chicago", 41.860, -87.680, 41.920, -87.600, "America/Chicago"),
    City("dc", "Washington, DC", 38.870, -77.060, 38.920, -77.000, "America/New_York"),
    City.around("nyc", "New York City", 40.7400, -73.9900, "America/New_York", 6.0),  # Statue of Liberty to the Met
    City.around("boston", "Boston", 42.3554, -71.0640, "America/New_York", 3.0),
    City.around("philadelphia", "Philadelphia", 39.9550, -75.1650, "America/New_York", 3.0),
    City.around("miami", "Miami", 25.7750, -80.1650, "America/New_York", 5.0),  # downtown + South Beach
    City.around("new_orleans", "New Orleans", 29.9500, -90.0700, "America/Chicago", 3.5),
    City.around("las_vegas", "Las Vegas", 36.1300, -115.1600, "America/Los_Angeles", 5.0),  # Strip + Fremont St
    City.around("seattle", "Seattle", 47.6080, -122.3380, "America/Los_Angeles", 3.0),
    City.around("san_francisco", "San Francisco", 37.7920, -122.4100, "America/Los_Angeles", 3.5),
    City.around("los_angeles", "Los Angeles", 34.0720, -118.3200, "America/Los_Angeles", 7.0),  # Downtown to Hollywood
    City.around("san_diego", "San Diego", 32.7200, -117.1600, "America/Los_Angeles", 4.0),
    City.around("honolulu", "Honolulu", 21.2950, -157.8400, "Pacific/Honolulu", 4.0),  # Waikiki + Diamond Head
    City.around("cleveland", "Cleveland", 41.5030, -81.6500, "America/New_York", 5.0),
    City.around("irvine", "Irvine", 33.6600, -117.8000, "America/Los_Angeles", 6.0),
    # --- Canada & Mexico ---
    City.around("toronto", "Toronto", 43.6530, -79.3850, "America/Toronto", 3.5),
    City.around("vancouver", "Vancouver", 49.2830, -123.1200, "America/Vancouver", 3.5),
    City.around("montreal", "Montreal", 45.5040, -73.5650, "America/Toronto", 3.5),
    City.around("mexico_city", "Mexico City", 19.4300, -99.1600, "America/Mexico_City", 6.0),
    # --- Europe ---
    City.around("london", "London", 51.5080, -0.1281, "Europe/London", 4.0),
    City.around("paris", "Paris", 48.8580, 2.3400, "Europe/Paris", 4.0),
    City.around("rome", "Rome", 41.8960, 12.4830, "Europe/Rome", 4.0),
    City.around("barcelona", "Barcelona", 41.3900, 2.1700, "Europe/Madrid", 4.0),
    City.around("madrid", "Madrid", 40.4170, -3.7000, "Europe/Madrid", 3.5),
    City.around("lisbon", "Lisbon", 38.7050, -9.1700, "Europe/Lisbon", 5.0),  # Baixa/Alfama + Belem
    City.around("amsterdam", "Amsterdam", 52.3700, 4.8950, "Europe/Amsterdam", 3.0),
    City.around("berlin", "Berlin", 52.5150, 13.3900, "Europe/Berlin", 5.0),
    City.around("prague", "Prague", 50.0870, 14.4100, "Europe/Prague", 3.0),
    City.around("vienna", "Vienna", 48.2050, 16.3550, "Europe/Vienna", 4.5),  # incl. Schonbrunn
    City.around("istanbul", "Istanbul", 41.0150, 28.9750, "Europe/Istanbul", 4.0),
    # --- Asia & Pacific ---
    # Tokyo: Shinjuku/Meiji Shrine (west) to Asakusa/Skytree (east), Ueno (north) to Roppongi (south)
    City.around("tokyo", "Tokyo", 35.6800, 139.7550, "Asia/Tokyo", 6.0),
    City.around("osaka", "Osaka", 34.6850, 135.5100, "Asia/Tokyo", 4.5),
    # Kyoto: Kinkaku-ji (NW) to Fushimi Inari (SE); Arashiyama is further west and not included
    City.around("kyoto", "Kyoto", 35.0000, 135.7600, "Asia/Tokyo", 6.0),
    City.around("sapporo", "Sapporo (Hokkaido)", 43.0618, 141.3545, "Asia/Tokyo", 3.0),
    City.around("seoul", "Seoul", 37.5665, 126.9850, "Asia/Seoul", 4.0),
    City.around("taipei", "Taipei", 25.0400, 121.5350, "Asia/Taipei", 4.5),  # incl. Taipei 101
    City.around("hong_kong", "Hong Kong", 22.2900, 114.1700, "Asia/Hong_Kong", 3.0),
    City.around("singapore", "Singapore", 1.2900, 103.8500, "Asia/Singapore", 4.0),
    City.around("bangkok", "Bangkok", 13.7500, 100.5100, "Asia/Bangkok", 4.0),
    City.around("sydney", "Sydney", -33.8650, 151.2100, "Australia/Sydney", 3.0),
    City.around("dubai", "Dubai", 25.2300, 55.2850, "Asia/Dubai", 5.0),  # Downtown/Burj + Old Dubai
]
CITIES: dict[str, City] = {c.city_id: c for c in _CITY_LIST}


def raw_dir(city_id: str) -> Path:
    p = DATA_DIR / "raw" / city_id
    p.mkdir(parents=True, exist_ok=True)
    return p


def out_dir(city_id: str) -> Path:
    p = DATA_DIR / "processed" / city_id
    p.mkdir(parents=True, exist_ok=True)
    return p
