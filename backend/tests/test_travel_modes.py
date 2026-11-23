"""Road-network travel: mode choice, the OSRM client, and scheduler integration.

OSRM is replaced by an in-process fake (httpx.MockTransport), so these tests
never touch the network.
"""

import asyncio
from datetime import date
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import httpx
import pytest

from app.services import routing
from app.services.routing import (
    UNREACHABLE_MINUTES,
    Route,
    RoutingUnavailable,
    build_estimator,
    choose_leg,
)
from app.services.scheduler import Candidate, schedule_trip

ALL = ("walk", "transit", "drive")
HOME = (41.8800, -87.6300)
NEAR = (41.8830, -87.6300)
FAR = (41.8800, -87.4000)


@pytest.fixture(autouse=True)
def fresh_cache(monkeypatch):
    routing._route_cache.clear()
    monkeypatch.setattr(routing, "_base_url", lambda profile: f"http://osrm.test/{profile}")
    monkeypatch.setattr(routing, "_RETRY_DELAYS_SECONDS", (0.0, 0.0, 0.0))
    monkeypatch.setattr(routing, "_unavailable_until", 0.0)
    monkeypatch.setattr(routing, "_MIN_REQUEST_GAP_SECONDS", 0.0)
    monkeypatch.setattr(routing, "_next_request_at", 0.0)
    routing._shape_cache.clear()
    yield
    routing._route_cache.clear()


# ---------------------------------------------------------------------------
# Mode choice
# ---------------------------------------------------------------------------


def test_short_hops_are_walked():
    assert choose_leg(Route(600, 800), Route(120, 900), ALL).mode == "walk"


def test_medium_trips_take_transit():
    leg = choose_leg(Route(1800, 2400), Route(300, 2600), ALL)

    assert leg.mode == "transit"
    assert leg.minutes == 20  # 12 min overhead + 2.6 road km at 20 km/h


def test_long_trips_take_a_taxi():
    leg = choose_leg(Route(7200, 9000), Route(900, 12000), ALL)

    assert leg.mode == "drive"
    assert leg.minutes == 26  # 7 min pickup + 15 min drive x 1.25 traffic


def test_restricted_modes_are_respected():
    assert choose_leg(Route(7200, 9000), Route(900, 12000), ("walk", "transit")).mode == "transit"
    # Too far to walk comfortably, but walking is the only allowed way: still walk.
    assert choose_leg(Route(7200, 9000), Route(900, 12000), ("walk",)) == routing.Leg(120, "walk")


def test_no_route_at_all_is_unreachable():
    assert choose_leg(None, None, ALL).minutes == UNREACHABLE_MINUTES


# ---------------------------------------------------------------------------
# OSRM client
# ---------------------------------------------------------------------------


def fake_osrm(calls: list[str], fail: bool = False):
    """A fake /table endpoint. Routes are asymmetric so source/destination mixups show."""

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if fail:
            return httpx.Response(502)
        url = urlsplit(str(request.url))
        profile = url.path.split("/")[1]
        coords = [tuple(map(float, pair.split(","))) for pair in url.path.split("/")[-1].split(";")]
        query = parse_qs(url.query)
        sources = [int(i) for i in query["sources"][0].split(";")]
        destinations = [int(i) for i in query["destinations"][0].split(";")]

        def meters(a, b):
            (lon1, lat1), (lon2, lat2) = coords[a], coords[b]
            base = (abs(lon1 - lon2) * 83_000 + abs(lat1 - lat2) * 111_000) * 1.3
            return base + (100 if a < b else 0)  # one-way streets: not symmetric

        speed = 1.3 if profile == "foot" else 10.0  # m/s
        distances = [[0 if s == d else meters(s, d) for d in destinations] for s in sources]
        durations = [[m / speed for m in row] for row in distances]
        return httpx.Response(200, json={"code": "Ok", "durations": durations, "distances": distances})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def run(coro):
    return asyncio.run(coro)


def test_estimator_uses_routed_times_both_ways():
    calls: list[str] = []
    estimate = run(build_estimator([HOME, NEAR, FAR], client=fake_osrm(calls)))

    assert {url.split("/")[3] for url in calls} == {"foot", "car"}
    assert estimate.leg(HOME, NEAR).mode == "walk"
    assert estimate.leg(HOME, FAR).mode == "drive"
    # Asymmetric routes are kept per direction.
    assert routing._route_cache[("car", HOME, NEAR)] != routing._route_cache[("car", NEAR, HOME)]


def test_routes_are_cached_between_requests():
    calls: list[str] = []
    run(build_estimator([HOME, NEAR, FAR], client=fake_osrm(calls)))
    first = len(calls)
    run(build_estimator([HOME, NEAR, FAR], client=fake_osrm(calls)))

    assert len(calls) == first


def test_large_point_sets_are_split_into_table_sized_blocks(monkeypatch):
    monkeypatch.setattr(routing, "MAX_TABLE_POINTS", 4)
    points = [(41.88 + i * 0.01, -87.63) for i in range(5)]
    calls: list[str] = []

    matrix = run(routing.fetch_matrix("car", points, client=fake_osrm(calls)))

    assert len(calls) == 9  # 3 blocks of 2 sources x 3 blocks of 2 destinations
    assert all(matrix.routes[i][j] is not None for i in range(5) for j in range(5))
    assert all(len(urlsplit(url).path.split("/")[-1].split(";")) <= 4 for url in calls)


def test_routing_failure_is_reported_not_guessed():
    with pytest.raises(RoutingUnavailable):
        run(build_estimator([HOME, FAR], client=fake_osrm([], fail=True)))


def test_unknown_points_are_an_error():
    estimate = run(build_estimator([HOME, NEAR], client=fake_osrm([])))

    with pytest.raises(KeyError):
        estimate(HOME, FAR)


def test_scheduler_reaches_far_stops_by_taxi():
    far = Candidate(destination_id=UUID(int=1), name="Far museum", score=10.0, location=FAR, duration_min=60)
    estimate = run(build_estimator([HOME, FAR], client=fake_osrm([])))

    itinerary = schedule_trip(
        [far],
        days=[date(2026, 10, 19)],
        day_start_minute=9 * 60,
        day_end_minute=12 * 60,
        home_base=HOME,
        travel=estimate,
    )

    assert [stop.name for stop in itinerary.stops] == ["Far museum"]
    assert estimate.leg(HOME, FAR).mode == "drive"


# ---------------------------------------------------------------------------
# Route shapes
# ---------------------------------------------------------------------------


def fake_route_server(calls: list[str], no_route: bool = False):
    """Fake /route: one leg per consecutive waypoint pair, each an L-shaped "street" path."""

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if no_route:
            return httpx.Response(200, json={"code": "NoRoute", "routes": []})
        points = [tuple(map(float, p.split(","))) for p in urlsplit(str(request.url)).path.split("/")[-1].split(";")]
        legs = []
        for (a_lng, a_lat), (b_lng, b_lat) in zip(points, points[1:]):
            legs.append(
                {
                    "steps": [
                        {"geometry": {"coordinates": [[a_lng, a_lat], [a_lng, b_lat]]}},
                        {"geometry": {"coordinates": [[a_lng, b_lat], [b_lng, b_lat]]}},
                    ]
                }
            )
        return httpx.Response(200, json={"code": "Ok", "routes": [{"legs": legs}]})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


DAY_TOUR = [("walk", HOME, NEAR), ("drive", NEAR, FAR), ("transit", FAR, HOME)]


def test_route_shapes_follow_the_routed_path_with_the_right_profile():
    calls: list[str] = []
    shapes = run(routing.fetch_route_shapes(DAY_TOUR, client=fake_route_server(calls)))

    assert shapes[0][0] == (HOME[1], HOME[0])  # GeoJSON (lng, lat) order
    # Follows the routed "street" (with its corner), steps joined without duplicates.
    assert shapes[1] == ((NEAR[1], NEAR[0]), (NEAR[1], FAR[0]), (FAR[1], FAR[0]))
    # The whole day is one request per profile, not one per leg.
    assert sorted(url.split("/")[3] for url in calls) == ["car", "foot"]


def test_cached_tours_need_no_requests():
    calls: list[str] = []
    run(routing.fetch_route_shapes(DAY_TOUR, client=fake_route_server(calls)))
    first = len(calls)
    run(routing.fetch_route_shapes(DAY_TOUR, client=fake_route_server(calls)))

    assert len(calls) == first


def test_missing_routes_draw_nothing():
    shapes = run(routing.fetch_route_shapes([("walk", HOME, FAR)], client=fake_route_server([], no_route=True)))

    assert shapes == [()]


def test_routes_endpoint_is_registered():
    from app.main import app

    assert "get" in app.openapi()["paths"]["/api/v1/trips/{trip_id}/itinerary/routes"]


def test_rate_limited_requests_are_retried():
    attempts = {"n": 0}
    inner = fake_osrm([])

    async def flaky(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] <= 2:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return await inner._transport.handle_async_request(request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(flaky))
    estimate = run(build_estimator([HOME, NEAR], client=client))

    assert estimate.leg(HOME, NEAR).mode == "walk"
    assert attempts["n"] == 4  # two 429s, then one foot and one car table


def test_small_point_sets_use_one_table_request_per_profile():
    calls: list[str] = []
    points = [(41.88 + i * 0.002, -87.63) for i in range(60)]
    run(build_estimator(points, client=fake_osrm(calls)))

    assert len(calls) == 2


def test_unreachable_server_fails_fast_and_cools_off():
    calls: list[str] = []

    def refuse(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        raise httpx.ConnectError("connection refused", request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(refuse))
    with pytest.raises(RoutingUnavailable):
        run(build_estimator([HOME, FAR], client=client))
    assert len(calls) == 1  # no retries against a dead server

    with pytest.raises(RoutingUnavailable, match="moments ago"):
        run(build_estimator([HOME, NEAR], client=fake_osrm(calls)))
    assert len(calls) == 1  # cooling off: nothing sent
