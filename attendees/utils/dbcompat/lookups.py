"""Portable spellings for JSON queries that would otherwise be Postgres-only."""
from django.db import connection
from django.db.models import Q


def json_contains(field, mapping):
    """A ``Q`` matching rows whose JSON ``field`` contains every key/value in ``mapping``.

    ``JSONField.__contains`` is Postgres-only — Django raises ``NotSupportedError`` for it on
    SQLite. For the flat, single-level mappings this project uses, a key-path lookup is exactly
    equivalent and is supported everywhere::

        infos__schedulers__contains={"<uuid>": True}   ->   infos__schedulers__<uuid>=True

    Postgres keeps using the native containment operator so the GIN indexes on these columns
    still apply.

    All-digit keys are refused on the fallback path rather than translated: Django compiles a
    digit path segment as an *array index* (``$[42]``, not ``$."42"``), which would silently
    match nothing. This project keys these mappings by attendee UUID, so the case cannot arise
    from real data — but silently-empty results are exactly the failure mode this layer exists
    to prevent, so it is an error, not a footnote.
    """
    if connection.vendor == "postgresql":
        return Q(**{f"{field}__contains": mapping})

    query = Q()
    for key, value in mapping.items():
        if key.isdigit():
            raise ValueError(
                f"json_contains cannot express the all-digit key {key!r} on "
                f"{connection.vendor}: Django would read it as an array index."
            )
        query &= Q(**{f"{field}__{key}": value})
    return query
