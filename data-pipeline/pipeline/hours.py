"""Defensive parser for OSM-style opening_hours strings.

Handles the common subset seen in real data:
  "24/7"
  "Mo-Fr 09:00-17:00; Sa 10:00-14:00"
  "Mo,We,Fr 10:00-12:00,13:00-18:00"
  "Fr-Mo 18:00-02:00"        (day wrap + past-midnight close)
  "Su off" / "Su closed"
  "09:00-17:00"              (no day selector = every day)
  "PH off"                   (public-holiday rules are ignored, noted)

Anything else (month ranges, sunrise/sunset, free text) is skipped and
the result is marked 'partial' or 'unparseable' instead of guessing.

Output windows use minutes since local midnight. A window that runs past
midnight keeps close_min > 1440 on the day it opened (18:00-02:00 -> 1080..1560).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

DAYS = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
_DAY_TOKEN = r"(?:Mo|Tu|We|Th|Fr|Sa|Su|PH|SH)"
DAYSPEC_RE = re.compile(rf"^{_DAY_TOKEN}(?:[-,]{_DAY_TOKEN})*$")
TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})-(\d{1,2}):(\d{2})\+?$")

# Common free-text variants people put in OSM / FSQ
_ALIASES = {
    "mon": "Mo", "tue": "Tu", "tues": "Tu", "wed": "We", "thu": "Th", "thur": "Th",
    "thurs": "Th", "fri": "Fr", "sat": "Sa", "sun": "Su",
}


@dataclass
class ParsedHours:
    status: str  # ok | partial | unparseable | missing
    windows: dict[int, list[tuple[int, int]]] = field(
        default_factory=lambda: {d: [] for d in range(7)}
    )
    notes: list[str] = field(default_factory=list)

    def rows(self) -> list[tuple[int, int, int]]:
        """(weekday, open_min, close_min) rows for destination_hours."""
        return [(d, o, c) for d in range(7) for (o, c) in sorted(self.windows[d])]

    def is_open(self, weekday: int, start_min: int, end_min: int) -> bool:
        """True if [start,end) fits inside one window (checks spillover from previous day)."""
        for o, c in self.windows[weekday]:
            if o <= start_min and end_min <= c:
                return True
        prev = (weekday - 1) % 7
        for o, c in self.windows[prev]:
            if c > 1440 and end_min <= c - 1440 and start_min >= 0:
                return True
        return False


def _normalize(raw: str) -> str:
    s = raw.strip()
    s = s.replace("–", "-").replace("—", "-")
    s = re.sub(r"\s*([-,])\s*", r"\1", s)          # "Mo - Fr" -> "Mo-Fr"
    s = re.sub(r"\b(\d{1,2})\.(\d{2})\b", r"\1:\2", s)  # 9.00 -> 9:00

    def alias(m: re.Match) -> str:
        return _ALIASES.get(m.group(0).lower(), m.group(0))

    s = re.sub(r"\b[A-Za-z]{3,5}\b", alias, s)
    return s


def _expand_days(spec: str) -> tuple[list[int], bool]:
    """Return (weekday indices, had_holiday_token)."""
    days: list[int] = []
    holiday = False
    for part in spec.split(","):
        if part in ("PH", "SH"):
            holiday = True
            continue
        if "-" in part:
            a, b = part.split("-")
            if a not in DAYS or b not in DAYS:
                holiday = holiday or "PH" in (a, b)
                continue
            i, j = DAYS.index(a), DAYS.index(b)
            k = i
            while True:
                days.append(k)
                if k == j:
                    break
                k = (k + 1) % 7
        elif part in DAYS:
            days.append(DAYS.index(part))
    return sorted(set(days)), holiday


def _parse_times(text: str) -> list[tuple[int, int]] | None:
    out = []
    for chunk in text.split(","):
        m = TIME_RE.match(chunk)
        if not m:
            return None
        h1, m1, h2, m2 = map(int, m.groups())
        if h1 > 24 or h2 > 48 or m1 > 59 or m2 > 59:
            return None
        o, c = h1 * 60 + m1, h2 * 60 + m2
        if c <= o:  # past midnight
            c += 1440
        if o >= 1440:
            return None
        out.append((o, c))
    return out


def parse_opening_hours(raw: str | None) -> ParsedHours:
    if raw is None or not str(raw).strip():
        return ParsedHours(status="missing")

    s = _normalize(str(raw))
    if s.lower() in ("24/7", "mo-su 00:00-24:00"):
        return ParsedHours(status="ok", windows={d: [(0, 1440)] for d in range(7)})

    result = ParsedHours(status="ok")
    parsed_any = False
    skipped = False

    for rule in (r.strip() for r in s.split(";")):
        if not rule:
            continue
        tokens = rule.split()
        if DAYSPEC_RE.match(tokens[0]):
            days, holiday = _expand_days(tokens[0])
            rest = " ".join(tokens[1:])
            if holiday:
                result.notes.append(f"holiday selector ignored: {rule!r}")
            if not days:
                continue  # rule was only PH/SH
        else:
            days, rest = list(range(7)), rule

        if rest.lower() in ("off", "closed"):
            for d in days:
                result.windows[d] = []
            parsed_any = True
            continue

        times = _parse_times(rest.replace(" ", ""))
        if times is None:
            skipped = True
            result.notes.append(f"unrecognized rule skipped: {rule!r}")
            continue

        for d in days:  # later rules override earlier ones for the same days (OSM semantics)
            result.windows[d] = list(times)
        parsed_any = True

    if not parsed_any:
        result.status = "unparseable"
        result.windows = {d: [] for d in range(7)}
    elif skipped:
        result.status = "partial"
    return result
