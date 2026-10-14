"""Matching evaluation — the measurable part of the data-science component.

1. `sample`  writes a stratified sample of candidate pairs to CSV for hand labeling
             (fill the `label` column with 1 = same place, 0 = different).
2. `report`  reads the labeled CSV and prints precision / recall / F1 across thresholds.

Stratifying by score band matters: a random sample is mostly obvious non-matches,
which tells you nothing about where the threshold should sit.
"""
from __future__ import annotations

import csv
import random
from pathlib import Path

from .resolve import score

BANDS = [(0.0, 0.4), (0.4, 0.6), (0.6, 0.75), (0.75, 0.9), (0.9, 1.01)]
FEATURE_COLS = ["name_sim", "dist_m", "same_wikidata", "same_domain", "same_phone", "same_category"]


def write_label_sample(records, pairs, path: Path, per_band: int = 40, seed: int = 395) -> int:
    rng = random.Random(seed)
    rows = []
    for lo, hi in BANDS:
        band = [p for p in pairs if lo <= p[2] < hi]
        rows += rng.sample(band, min(per_band, len(band)))
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["a_source", "a_id", "a_name", "b_source", "b_id", "b_name", "score", *FEATURE_COLS, "label"])
        for i, j, s, feat in rows:
            a, b = records[i], records[j]
            w.writerow([
                a["source"], a["source_id"], a["name"], b["source"], b["source_id"], b["name"],
                f"{s:.3f}", *[feat[c] if c != "dist_m" else round(feat[c], 1) for c in FEATURE_COLS], "",
            ])
    return len(rows)


def _to_bool(v: str) -> bool:
    return str(v).strip().lower() in ("true", "1")


def load_labels(path: Path) -> list[tuple[dict, int]]:
    out = []
    with path.open() as f:
        for row in csv.DictReader(f):
            if row["label"].strip() == "":
                continue
            feat = {
                "name_sim": float(row["name_sim"]),
                "dist_m": float(row["dist_m"]),
                **{c: _to_bool(row[c]) for c in FEATURE_COLS if c.startswith("same_")},
            }
            out.append((feat, int(row["label"])))
    return out


def threshold_report(labeled: list[tuple[dict, int]], thresholds=None) -> list[dict]:
    """Rescore from features (so weight changes in resolve.py are picked up) and sweep thresholds."""
    thresholds = thresholds or [round(0.5 + 0.05 * k, 2) for k in range(9)]
    scored = [(score(f), y) for f, y in labeled]
    report = []
    for t in thresholds:
        tp = sum(1 for s, y in scored if s >= t and y == 1)
        fp = sum(1 for s, y in scored if s >= t and y == 0)
        fn = sum(1 for s, y in scored if s < t and y == 1)
        p = tp / (tp + fp) if tp + fp else 0.0
        r = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * p * r / (p + r) if p + r else 0.0
        report.append({"threshold": t, "precision": p, "recall": r, "f1": f1, "tp": tp, "fp": fp, "fn": fn})
    return report


def print_report(report: list[dict]) -> None:
    print(f"{'thresh':>7} {'prec':>6} {'recall':>6} {'f1':>6} {'tp':>4} {'fp':>4} {'fn':>4}")
    best = max(report, key=lambda r: r["f1"])
    for r in report:
        mark = "  <- best F1" if r is best else ""
        print(f"{r['threshold']:>7.2f} {r['precision']:>6.3f} {r['recall']:>6.3f} {r['f1']:>6.3f} "
              f"{r['tp']:>4} {r['fp']:>4} {r['fn']:>4}{mark}")
