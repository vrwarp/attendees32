"""Distances and bearings against known pairs of coordinates."""
import math
import random

import pytest

from attendees.whereabouts.services import geo

SAN_FRANCISCO = (37.7749, -122.4194)
OAKLAND = (37.8044, -122.2712)
SAN_JOSE = (37.3382, -121.8863)
LONDON = (51.5074, -0.1278)
PARIS = (48.8566, 2.3522)


@pytest.mark.parametrize(
    "start, end, miles",
    [
        (SAN_FRANCISCO, OAKLAND, 8.4),  # across the bay
        (SAN_FRANCISCO, SAN_JOSE, 42.0),  # down the peninsula
        (LONDON, PARIS, 213.5),  # the classic pair: 343.5 km
        ((0.0, 0.0), (0.0, 1.0), 69.09),  # one degree along the equator
        ((0.0, 0.0), (1.0, 0.0), 69.09),  # one degree along a meridian
        ((10.0, 20.0), (10.0, 20.0), 0.0),
    ],
)
def test_haversine_matches_known_distances(start, end, miles):
    assert geo.haversine_miles(*start, *end) == pytest.approx(miles, abs=0.3)


@pytest.mark.parametrize(
    "start, end, degrees",
    [
        ((0.0, 0.0), (1.0, 0.0), 0.0),  # due north
        ((0.0, 0.0), (0.0, 1.0), 90.0),  # due east
        ((0.0, 0.0), (-1.0, 0.0), 180.0),  # due south
        ((0.0, 0.0), (0.0, -1.0), 270.0),  # due west
        (LONDON, PARIS, 148.1),  # south-east
        (SAN_FRANCISCO, OAKLAND, 75.8),  # east-north-east
    ],
)
def test_bearing_matches_known_directions(start, end, degrees):
    assert math.degrees(geo.bearing_radians(*start, *end)) == pytest.approx(degrees, abs=0.5)


def test_the_box_holds_every_point_within_its_radius():
    """The box is conservative: nothing within the radius is outside it."""
    rng = random.Random(7)
    for _ in range(500):
        latitude, longitude = rng.uniform(-60, 60), rng.uniform(-170, 170)
        miles = rng.uniform(1, 500)
        box = geo.bounding_box(latitude, longitude, miles)
        assert box is not None
        bearing = rng.uniform(0, 2 * math.pi)
        # a point ``miles`` away along ``bearing``, by the direct geodesic formula
        delta = miles / geo.EARTH_RADIUS_MILES
        phi_1, lambda_1 = math.radians(latitude), math.radians(longitude)
        phi_2 = math.asin(math.sin(phi_1) * math.cos(delta) + math.cos(phi_1) * math.sin(delta) * math.cos(bearing))
        lambda_2 = lambda_1 + math.atan2(
            math.sin(bearing) * math.sin(delta) * math.cos(phi_1), math.cos(delta) - math.sin(phi_1) * math.sin(phi_2)
        )
        point = (math.degrees(phi_2), math.degrees(lambda_2))
        assert box.south <= point[0] <= box.north
        assert box.west <= point[1] <= box.east
        assert geo.haversine_miles(latitude, longitude, *point) == pytest.approx(miles, rel=1e-6)


def test_the_box_gives_up_at_the_poles_and_the_antimeridian():
    assert geo.bounding_box(89.0, 0.0, 200.0) is None
    assert geo.bounding_box(0.0, 179.5, 100.0) is None
    assert geo.bounding_box(0.0, 0.0, 20000.0) is None
    assert geo.bounding_box(37.0, -122.0, 50.0) is not None
