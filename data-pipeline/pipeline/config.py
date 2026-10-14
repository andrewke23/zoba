"""City configuration. Placeholder seed cities until the team decides (SRS §8)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DATA_DIR = Path(os.environ.get("ZOBA_DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://zoba:zoba@localhost:5432/zoba")

# Foursquare OS Places parquet location (local path or s3:// glob).
# Check https://docs.foursquare.com/data-products/docs/access-fsq-os-places for the current release path.
FSQ_PLACES_PATH = os.environ.get("FSQ_PLACES_PATH", "")

OVERPASS_URL = os.environ.get("OVERPASS_URL", "https://overpass-api.de/api/interpreter")


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


CITIES: dict[str, City] = {
    # Downtown/core bounding boxes only — keep small while iterating.
    "chicago": City("chicago", "Chicago", 41.860, -87.680, 41.920, -87.600, "America/Chicago"),
    "dc": City("dc", "Washington, DC", 38.870, -77.060, 38.920, -77.000, "America/New_York"),
}


def raw_dir(city_id: str) -> Path:
    p = DATA_DIR / "raw" / city_id
    p.mkdir(parents=True, exist_ok=True)
    return p


def out_dir(city_id: str) -> Path:
    p = DATA_DIR / "processed" / city_id
    p.mkdir(parents=True, exist_ok=True)
    return p
