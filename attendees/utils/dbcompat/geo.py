"""SQLite implementations of the PostGIS functions the coordinates service uses.

``CoordinatesService.get_nearest_neighbors`` annotates places with raw SQL built on
``ST_MakePoint``, ``ST_DistanceSphere`` and ``ST_Azimuth``. Registering functions with the same
names lets that SQL run on SQLite unchanged, the same trick the history triggers use for
``_pgh_attach_context()``.

Semantics follow PostGIS for the cases the service exercises:

* ``ST_DistanceSphere`` measures along a sphere and returns meters (the service converts to
  miles itself).
* ``ST_Azimuth`` on *geometry* points is planar — ``atan2`` over raw coordinate deltas,
  north-based, in ``[0, 2π)`` — not great-circle bearing, and the neighbor compass only needs
  it to agree with what Postgres shows.

A point has to travel between the functions as a single SQLite value, so ``ST_MakePoint``
returns the pair as compact JSON text.
"""
import json
import math

# IUGG mean earth radius, in meters — the sphere PostGIS measures against.
_EARTH_RADIUS_M = 6371008.8


def st_make_point(longitude, latitude):
    if longitude is None or latitude is None:
        return None
    return json.dumps([float(longitude), float(latitude)])


def st_distance_sphere(point_a, point_b):
    """Great-circle distance in meters between two ``ST_MakePoint`` values."""
    if point_a is None or point_b is None:
        return None
    lon_a, lat_a = (math.radians(v) for v in json.loads(point_a))
    lon_b, lat_b = (math.radians(v) for v in json.loads(point_b))
    # Haversine formula.
    half_dlat = (lat_b - lat_a) / 2
    half_dlon = (lon_b - lon_a) / 2
    h = math.sin(half_dlat) ** 2 + math.cos(lat_a) * math.cos(lat_b) * math.sin(half_dlon) ** 2
    return 2 * _EARTH_RADIUS_M * math.asin(math.sqrt(h))


def st_azimuth(point_from, point_to):
    """North-based planar azimuth in radians, in ``[0, 2π)``, as PostGIS defines for geometry."""
    if point_from is None or point_to is None:
        return None
    lon_a, lat_a = json.loads(point_from)
    lon_b, lat_b = json.loads(point_to)
    azimuth = math.atan2(lon_b - lon_a, lat_b - lat_a)
    return azimuth % (2 * math.pi)


def register(conn):
    """Install the functions on a raw SQLite connection."""
    conn.create_function("ST_MakePoint", 2, st_make_point)
    conn.create_function("ST_DistanceSphere", 2, st_distance_sphere)
    conn.create_function("ST_Azimuth", 2, st_azimuth)
