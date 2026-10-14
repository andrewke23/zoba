"""Map source categories to one shared Zoba taxonomy.

The taxonomy drives F14 (default visit durations) and F16 (category-average costs),
so every destination must land in exactly one bucket.
"""
from __future__ import annotations

import re

ZOBA_CATEGORIES = {
    # category: default visit duration (minutes) — F14 priors, refine with user corrections
    "museum": 120,
    "landmark": 45,
    "park": 60,
    "viewpoint": 30,
    "entertainment": 150,   # theatre, zoo, aquarium, theme park
    "food": 75,
    "cafe": 40,
    "nightlife": 90,
    "shopping": 60,
    "other": 45,
}

_OSM_RULES: list[tuple[str, str, str]] = [
    # (tag key, tag value or "*", zoba category) — first match wins
    ("tourism", "museum", "museum"),
    ("tourism", "gallery", "museum"),
    ("tourism", "zoo", "entertainment"),
    ("tourism", "aquarium", "entertainment"),
    ("tourism", "theme_park", "entertainment"),
    ("tourism", "viewpoint", "viewpoint"),
    ("tourism", "attraction", "landmark"),
    ("amenity", "theatre", "entertainment"),
    ("amenity", "arts_centre", "museum"),
    ("amenity", "restaurant", "food"),
    ("amenity", "cafe", "cafe"),
    ("amenity", "bar", "nightlife"),
    ("amenity", "pub", "nightlife"),
    ("leisure", "park", "park"),
    ("leisure", "garden", "park"),
    ("historic", "*", "landmark"),
    ("shop", "*", "shopping"),
]

# Substring match against FSQ labels like "Arts and Entertainment > Museum > Art Museum"
_FSQ_RULES: list[tuple[str, str]] = [
    ("museum", "museum"),
    ("art gallery", "museum"),
    ("zoo", "entertainment"),
    ("aquarium", "entertainment"),
    ("theme park", "entertainment"),
    ("theater", "entertainment"),
    ("scenic lookout", "viewpoint"),
    ("park", "park"),
    ("garden", "park"),
    ("monument", "landmark"),
    ("landmarks and outdoors", "landmark"),
    ("historic", "landmark"),
    ("café", "cafe"),
    ("cafe", "cafe"),
    ("coffee", "cafe"),
    ("restaurant", "food"),
    ("dining and drinking", "food"),
    ("bar", "nightlife"),
    ("nightlife", "nightlife"),
    ("retail", "shopping"),
]


def from_osm_tags(tags: dict) -> str:
    for key, val, cat in _OSM_RULES:
        if key in tags and (val == "*" or tags[key] == val):
            return cat
    return "other"


def from_fsq_labels(labels: list[str] | None) -> str:
    if not labels:
        return "other"
    # Most specific level first
    for label in labels:
        for part in reversed([p.strip().lower() for p in label.split(">")]):
            for needle, cat in _FSQ_RULES:
                # word boundaries so "bar" != "barbershop", "park" != "parking"
                if re.search(rf"\b{re.escape(needle)}s?\b", part):
                    return cat
    return "other"
