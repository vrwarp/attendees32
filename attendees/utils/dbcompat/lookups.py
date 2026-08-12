"""Portable spellings for JSON queries that would otherwise be Postgres-only."""
from django.db import connection
from django.db.models import Q


def json_contains(field, mapping):
    """A ``Q`` matching rows whose JSON ``field`` contains every key/value in ``mapping``.

    ``JSONField.__contains`` is Postgres-only — Django raises ``NotSupportedError`` for it on
    SQLite. For the flat, single-level mappings this project uses, a key-path lookup is exactly
    equivalent and is supported everywhere::

        infos__schedulers__contains={"42": True}   ->   infos__schedulers__42=True

    Postgres keeps using the native containment operator so the GIN indexes on these columns
    still apply.
    """
    if connection.vendor == "postgresql":
        return Q(**{f"{field}__contains": mapping})

    query = Q()
    for key, value in mapping.items():
        query &= Q(**{f"{field}__{key}": value})
    return query
