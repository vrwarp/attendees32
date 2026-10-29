"""Distances and bearings on the sphere, in Python, so no database has to know geography.

A congregation has hundreds of geocoded places; computing the distance to
each is well under a millisecond, and a bounding box on the indexed
latitude and longitude columns keeps even that bounded.
"""
import math
from collections import namedtuple

EARTH_RADIUS_MILES = 3958.7613  # mean radius, 6371.0088 km
MILES_PER_DEGREE = 2 * math.pi * EARTH_RADIUS_MILES / 360

BoundingBox = namedtuple("BoundingBox", "south north west east")


def haversine_miles(latitude_1, longitude_1, latitude_2, longitude_2):
    """The great-circle distance between two points, in miles."""
    phi_1, phi_2 = math.radians(latitude_1), math.radians(latitude_2)
    half_dphi = math.radians(latitude_2 - latitude_1) / 2
    half_dlambda = math.radians(longitude_2 - longitude_1) / 2
    a = math.sin(half_dphi) ** 2 + math.cos(phi_1) * math.cos(phi_2) * math.sin(half_dlambda) ** 2
    return 2 * EARTH_RADIUS_MILES * math.asin(min(1.0, math.sqrt(a)))


def bearing_radians(latitude_1, longitude_1, latitude_2, longitude_2):
    """The initial bearing from the first point to the second: radians clockwise from north, in [0, 2π)."""
    phi_1, phi_2 = math.radians(latitude_1), math.radians(latitude_2)
    dlambda = math.radians(longitude_2 - longitude_1)
    y = math.sin(dlambda) * math.cos(phi_2)
    x = math.cos(phi_1) * math.sin(phi_2) - math.sin(phi_1) * math.cos(phi_2) * math.cos(dlambda)
    return math.atan2(y, x) % (2 * math.pi)


def bounding_box(latitude, longitude, miles):
    """The latitude and longitude ranges that hold every point within ``miles`` of a point.

    Conservative: a point inside the box may be farther than ``miles``, but
    no point within ``miles`` is outside it. ``None`` when the box would reach
    a pole or cross the antimeridian, where a simple range no longer works
    and the caller should take every row instead.
    """
    dlat = miles / MILES_PER_DEGREE
    south, north = latitude - dlat, latitude + dlat
    if south <= -90 or north >= 90:
        return None
    widest = max(abs(south), abs(north))  # the parallel where a degree of longitude is shortest
    dlon = miles / (MILES_PER_DEGREE * math.cos(math.radians(widest)))
    west, east = longitude - dlon, longitude + dlon
    if dlon >= 180 or west < -180 or east > 180:
        return None
    return BoundingBox(south, north, west, east)
