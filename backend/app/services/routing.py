"""Road-network travel times between stops, by walking, transit or taxi.

Every number here comes from routes on the OpenStreetMap street network,
computed by OSRM (https://project-osrm.org): the ``foot`` profile for walking
and the ``car`` profile for taxis. Nothing is derived from straight-line
distance. If routing is unavailable the caller gets ``RoutingUnavailable``
rather than a silent guess.

How each mode is timed:

* **walk** -- OSRM foot route duration.
* **taxi** (``drive``) -- OSRM car route duration, inflated by
  ``TRAFFIC_FACTOR`` (OSRM's car profile assumes free-flowing traffic), plus
  ``TAXI_OVERHEAD_MIN`` for waiting for the pickup and getting out.
* **transit** -- the car route's *road distance* covered at an average transit
  speed, plus ``TRANSIT_OVERHEAD_MIN`` for walking to the stop and waiting.
  This follows real streets but not real bus/metro lines; that needs GTFS
  timetables and a transit planner (e.g. OpenTripPlanner), which is the one
  piece left to swap in here.

Each leg uses the mode with the lowest minutes + ``penalty_min``. The penalty
stands for cost and hassle (a cab fare, a transfer); it shapes the choice but is
never part of the reported time.

Routes that do not exist (an island with no bridge, a point OSRM cannot snap to
a street) make that mode unavailable for the leg. If no mode can make the trip,
the leg costs ``UNREACHABLE_MINUTES``, longer than any day, so the scheduler
never places that stop.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

Coordinate = tuple[float, float]
"""(latitude, longitude) in degrees, as in app.services.scheduler."""

TravelMode = Literal["walk", "transit", "drive"]
Profile = Literal["foot", "car"]

TRAFFIC_FACTOR = 1.25
"""OSRM car times assume empty roads; urban taxis are slower in practice."""

TAXI_OVERHEAD_MIN = 7.0
TRANSIT_OVERHEAD_MIN = 12.0
TRANSIT_SPEED_KMH = 20.0
"""Average bus/metro speed including stops, applied to the road distance."""

UNREACHABLE_MINUTES = 24 * 60

MAX_TABLE_POINTS = 100
"""Coordinates per OSRM table request (osrm-routed's default --max-table-size)."""

_REQUEST_TIMEOUT = httpx.Timeout(20.0, connect=5.0)
_USER_AGENT = "zoba-trip-planner/1.0"

_MAX_IN_FLIGHT = 2
"""Concurrent OSRM requests per call. Public servers answer bursts with 429."""

_RETRY_DELAYS_SECONDS = (1.0, 2.0, 4.0)
"""Backoff for 429 / 5xx answers; a Retry-After header, when sent, wins (capped)."""



class RoutingUnavailable(RuntimeError):
    """The routing service could not be reached or returned an error."""


_MIN_REQUEST_GAP_SECONDS = 0.5
"""Spacing between OSRM requests from this process. Free public servers rate-limit bursts."""

_next_request_at = 0.0


async def _pace() -> None:
    """Wait for this request's turn. Single-threaded asyncio, so no lock is needed."""
    global _next_request_at
    now = time.monotonic()
    slot = max(now, _next_request_at)
    _next_request_at = slot + _MIN_REQUEST_GAP_SECONDS
    if slot > now:
        await asyncio.sleep(slot - now)


_COOL_OFF_SECONDS = 30.0
"""After a failure, fail fast for this long instead of making every leg wait on a dead server."""

_unavailable_until = 0.0


def _trip_breaker(reason: str) -> RoutingUnavailable:
    global _unavailable_until
    _unavailable_until = time.monotonic() + _COOL_OFF_SECONDS
    return RoutingUnavailable(reason)


@dataclass(frozen=True)
class ModeRule:
    mode: TravelMode
    penalty_min: float
    min_meters: float = 0.0
    max_meters: float = float("inf")


MODE_RULES: tuple[ModeRule, ...] = (
    ModeRule("walk", penalty_min=0.0, max_meters=4000.0),
    ModeRule("transit", penalty_min=4.0, min_meters=1000.0),
    ModeRule("drive", penalty_min=15.0, min_meters=1200.0),
)


@dataclass(frozen=True)
class Route:
    seconds: float
    meters: float


@dataclass(frozen=True)
class Leg:
    minutes: int
    mode: TravelMode


@dataclass(frozen=True)
class RouteMatrix:
    """Routes between every ordered pair of ``points`` for one OSRM profile.

    ``routes[i][j]`` is None when OSRM found no route from point i to point j.
    """

    points: tuple[Coordinate, ...]
    routes: tuple[tuple[Route | None, ...], ...]


def choose_leg(walk: Route | None, car: Route | None, modes: Sequence[TravelMode]) -> Leg:
    """Pick the mode for one leg from its foot and car routes."""
    options: list[tuple[float, int, TravelMode]] = []
    for rule in MODE_RULES:
        if rule.mode not in modes:
            continue
        if rule.mode == "walk":
            if walk is None or not rule.min_meters <= walk.meters <= rule.max_meters:
                continue
            minutes = walk.seconds / 60
        elif car is None or not rule.min_meters <= car.meters <= rule.max_meters:
            continue
        elif rule.mode == "drive":
            minutes = TAXI_OVERHEAD_MIN + car.seconds / 60 * TRAFFIC_FACTOR
        else:
            minutes = TRANSIT_OVERHEAD_MIN + car.meters / 1000 / TRANSIT_SPEED_KMH * 60
        whole = max(1, round(minutes))
        options.append((whole + rule.penalty_min, whole, rule.mode))

    if not options and "walk" in modes and walk is not None:
        # Longer than anyone would choose to walk, but it is the only allowed way.
        whole = max(1, round(walk.seconds / 60))
        options.append((whole, whole, "walk"))

    if not options:
        return Leg(minutes=UNREACHABLE_MINUTES, mode=modes[0] if modes else "walk")
    _, minutes, mode = min(options)
    return Leg(minutes=minutes, mode=mode)


class RoutedEstimator:
    """Travel estimator over precomputed OSRM matrices.

    Callable like ``app.services.scheduler.TravelEstimator`` (returns minutes),
    and ``leg`` also reports the chosen mode. Only the points the matrices were
    built for can be asked about; anything else is a programming error, not a
    reason to guess.
    """

    def __init__(
        self,
        foot: RouteMatrix,
        car: RouteMatrix,
        modes: Sequence[TravelMode] = ("walk", "transit", "drive"),
    ) -> None:
        if foot.points != car.points:
            raise ValueError("foot and car matrices must cover the same points")
        if not modes:
            raise ValueError("at least one travel mode is required")
        self._index = {point: i for i, point in enumerate(foot.points)}
        self._foot = foot
        self._car = car
        self._modes = tuple(modes)
        self._legs: dict[tuple[int, int], Leg] = {}

    def leg(self, origin: Coordinate, destination: Coordinate) -> Leg:
        try:
            i, j = self._index[origin], self._index[destination]
        except KeyError as exc:
            raise KeyError(f"no route was fetched for {origin} -> {destination}") from exc
        if i == j:
            return Leg(minutes=0, mode="walk")
        cached = self._legs.get((i, j))
        if cached is None:
            cached = choose_leg(self._foot.routes[i][j], self._car.routes[i][j], self._modes)
            self._legs[(i, j)] = cached
        return cached

    def __call__(self, origin: Coordinate, destination: Coordinate) -> int:
        return self.leg(origin, destination).minutes


# ---------------------------------------------------------------------------
# OSRM client
# ---------------------------------------------------------------------------

# Routes between fixed places do not change between requests; keep them for the
# life of the process so regenerating an itinerary does not re-query OSRM.
_route_cache: dict[tuple[Profile, Coordinate, Coordinate], Route | None] = {}
_ROUTE_CACHE_LIMIT = 500_000


def _base_url(profile: Profile) -> str:
    settings = get_settings()
    return (settings.routing_foot_url if profile == "foot" else settings.routing_car_url).rstrip("/")


async def _get_json(client: httpx.AsyncClient, url: str, params: dict, what: str) -> dict:
    """GET with retries on rate limiting and server errors.

    A server that cannot be reached at all is not retried: the caller gets an
    answer in seconds, and later calls fail fast for ``_COOL_OFF_SECONDS``.
    """
    if time.monotonic() < _unavailable_until:
        raise RoutingUnavailable(f"{what} skipped: routing failed moments ago")
    for attempt in range(len(_RETRY_DELAYS_SECONDS) + 1):
        await _pace()
        try:
            response = await client.get(url, params=params)
        except httpx.HTTPError as exc:
            raise _trip_breaker(f"{what} failed: {type(exc).__name__} {exc}") from exc
        if response.status_code == 429 or response.status_code >= 500:
            if attempt == len(_RETRY_DELAYS_SECONDS):
                raise _trip_breaker(f"{what} failed: HTTP {response.status_code}")
            delay = _RETRY_DELAYS_SECONDS[attempt]
            try:
                delay = min(float(response.headers.get("Retry-After", delay)), 10.0)
            except ValueError:
                pass
            logger.info("%s got HTTP %s; retrying in %.1fs", what, response.status_code, delay)
            await asyncio.sleep(delay)
            continue
        try:
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise RoutingUnavailable(f"{what} failed: {exc}") from exc
    raise AssertionError("unreachable")


def _blocks(count: int, size: int) -> list[list[int]]:
    return [list(range(start, min(start + size, count))) for start in range(0, count, size)]


async def _fetch_block(
    client: httpx.AsyncClient,
    profile: Profile,
    points: Sequence[Coordinate],
    sources: list[int],
    destinations: list[int],
) -> dict[tuple[int, int], Route | None]:
    """One OSRM /table call for a block of sources x destinations."""
    ordered = sources + [d for d in destinations if d not in sources]
    position = {point_index: i for i, point_index in enumerate(ordered)}
    coordinates = ";".join(f"{points[i][1]:.6f},{points[i][0]:.6f}" for i in ordered)
    params = {
        "annotations": "duration,distance",
        "sources": ";".join(str(position[i]) for i in sources),
        "destinations": ";".join(str(position[i]) for i in destinations),
    }
    url = f"{_base_url(profile)}/table/v1/driving/{coordinates}"
    body = await _get_json(client, url, params, f"OSRM {profile} table request")
    if body.get("code") != "Ok":
        raise RoutingUnavailable(f"OSRM {profile} routing error: {body.get('code')} {body.get('message', '')}")

    durations, distances = body["durations"], body["distances"]
    result: dict[tuple[int, int], Route | None] = {}
    for row, source in enumerate(sources):
        for col, destination in enumerate(destinations):
            seconds, meters = durations[row][col], distances[row][col]
            result[(source, destination)] = (
                None if seconds is None or meters is None else Route(seconds=seconds, meters=meters)
            )
    return result


async def fetch_matrix(
    profile: Profile,
    points: Sequence[Coordinate],
    client: httpx.AsyncClient | None = None,
) -> RouteMatrix:
    """Routes between every ordered pair of ``points``, from cache or OSRM."""
    points = tuple(points)
    n = len(points)
    missing = any(
        (profile, points[i], points[j]) not in _route_cache for i in range(n) for j in range(n) if i != j
    )

    if missing and n > 1:
        owns_client = client is None
        client = client or httpx.AsyncClient(
            timeout=_REQUEST_TIMEOUT, headers={"User-Agent": _USER_AGENT}
        )
        try:
            # One request when everything fits; otherwise each request carries a
            # source block and a destination block of half the limit each.
            blocks = [list(range(n))] if n <= MAX_TABLE_POINTS else _blocks(n, MAX_TABLE_POINTS // 2)
            gate = asyncio.Semaphore(_MAX_IN_FLIGHT)

            async def block(src: list[int], dst: list[int]) -> dict[tuple[int, int], Route | None]:
                async with gate:
                    return await _fetch_block(client, profile, points, src, dst)

            results = await asyncio.gather(*(block(src, dst) for src in blocks for dst in blocks))
        finally:
            if owns_client:
                await client.aclose()
        if len(_route_cache) > _ROUTE_CACHE_LIMIT:
            _route_cache.clear()
        for block in results:
            for (i, j), route in block.items():
                if i != j:
                    _route_cache[(profile, points[i], points[j])] = route

    routes = tuple(
        tuple(
            Route(seconds=0.0, meters=0.0) if i == j else _route_cache[(profile, points[i], points[j])]
            for j in range(n)
        )
        for i in range(n)
    )
    return RouteMatrix(points=points, routes=routes)


async def build_estimator(
    points: Sequence[Coordinate],
    modes: Sequence[TravelMode] = ("walk", "transit", "drive"),
    client: httpx.AsyncClient | None = None,
) -> RoutedEstimator:
    """Fetch foot and car routes between ``points`` and wrap them as an estimator."""
    unique = tuple(dict.fromkeys(points))
    # One profile after the other: the two usually live on the same server.
    foot = await fetch_matrix("foot", unique, client)
    car = await fetch_matrix("car", unique, client)
    return RoutedEstimator(foot, car, modes)


# ---------------------------------------------------------------------------
# Route shapes (for drawing on the map)
# ---------------------------------------------------------------------------

LngLat = tuple[float, float]
"""(longitude, latitude): GeoJSON order, which is what map libraries draw."""

PROFILE_FOR_MODE: dict[TravelMode, Profile] = {"walk": "foot", "drive": "car", "transit": "car"}
"""Transit has no line data yet, so its shape follows the street route a bus would take."""

_shape_cache: dict[tuple[Profile, Coordinate, Coordinate], tuple[LngLat, ...]] = {}
_SHAPE_CACHE_LIMIT = 20_000


MAX_ROUTE_WAYPOINTS = 100
"""Waypoints per OSRM /route request (osrm-routed's default --max-viaroute-size is 500)."""


def _leg_shape(leg: dict) -> tuple[LngLat, ...]:
    """Concatenate a route leg's step geometries into one line."""
    points: list[LngLat] = []
    for step in leg.get("steps", []):
        for lng, lat in step["geometry"]["coordinates"]:
            point = (float(lng), float(lat))
            if not points or points[-1] != point:
                points.append(point)
    return tuple(points)


async def _fetch_chain(client: httpx.AsyncClient, profile: Profile, waypoints: Sequence[Coordinate]) -> None:
    """Route through ``waypoints`` in order in ONE request and cache every leg's shape.

    A day's whole tour is one request per profile instead of one per leg,
    which is what keeps a re-solve under public servers' rate limits.
    """
    coordinates = ";".join(f"{lng:.6f},{lat:.6f}" for lat, lng in waypoints)
    url = f"{_base_url(profile)}/route/v1/driving/{coordinates}"
    body = await _get_json(
        client,
        url,
        {"overview": "false", "steps": "true", "geometries": "geojson"},
        f"OSRM {profile} route request",
    )
    if len(_shape_cache) > _SHAPE_CACHE_LIMIT:
        _shape_cache.clear()
    pairs = list(zip(waypoints, waypoints[1:]))
    if body.get("code") == "Ok" and body.get("routes"):
        for (a, b), leg in zip(pairs, body["routes"][0]["legs"]):
            _shape_cache[(profile, a, b)] = _leg_shape(leg)
        return
    if len(pairs) == 1:
        # No route between the two points: draw nothing rather than a made-up line.
        _shape_cache[(profile, pairs[0][0], pairs[0][1])] = ()
        return
    # Some leg of the chain has no route; find which by routing the legs on their own.
    for a, b in pairs:
        if (profile, a, b) not in _shape_cache:
            await _fetch_chain(client, profile, (a, b))


def _chains(legs: Sequence[tuple[TravelMode, Coordinate, Coordinate]]) -> list[list[Coordinate]]:
    """Group consecutive legs that join end to start (a day's tour) into waypoint lists."""
    chains: list[list[Coordinate]] = []
    for _, origin, destination in legs:
        if chains and chains[-1][-1] == origin and len(chains[-1]) < MAX_ROUTE_WAYPOINTS:
            chains[-1].append(destination)
        else:
            chains.append([origin, destination])
    return chains


async def fetch_route_shapes(
    legs: Sequence[tuple[TravelMode, Coordinate, Coordinate]],
    client: httpx.AsyncClient | None = None,
) -> list[tuple[LngLat, ...]]:
    """Street shapes for many legs, in order, using as few OSRM requests as possible.

    Legs are grouped into chains (each day's tour). For each chain, each profile
    that has an uncached leg costs one request covering the whole chain, so a
    day with walking and riding legs is at most two requests -- and zero once
    cached, so a re-solve only fetches what actually changed.
    """
    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=_REQUEST_TIMEOUT, headers={"User-Agent": _USER_AGENT})
    try:
        for chain in _chains(legs):
            pairs = set(zip(chain, chain[1:]))
            needed = {
                PROFILE_FOR_MODE[mode]
                for mode, a, b in legs
                if (a, b) in pairs and (PROFILE_FOR_MODE[mode], a, b) not in _shape_cache
            }
            for profile in sorted(needed):
                await _fetch_chain(client, profile, chain)
    finally:
        if owns_client:
            await client.aclose()
    return [_shape_cache.get((PROFILE_FOR_MODE[mode], a, b), ()) for mode, a, b in legs]
