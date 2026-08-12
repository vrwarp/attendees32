"""Postgres aggregates with SQLite equivalents.

Each class subclasses the ``django.contrib.postgres`` original and adds an ``as_sqlite``
method. Django's compiler dispatches to ``as_<vendor>`` when it exists, so the Postgres path is
completely untouched — same class, same SQL — and only SQLite takes the alternative branch.

SQLite equivalents (verified on 3.45):

======================  =============================================================
Postgres                SQLite
======================  =============================================================
``JSONB_AGG(x)``        ``json_group_array(x)``   — nests JSON values correctly
``ARRAY_AGG(x)``        ``json_group_array(x)``   — read back as a list via JSONField
``STRING_AGG(x, d)``    ``group_concat(x, d)``
``jsonb_build_object``  ``json_object``
======================  =============================================================
"""
import json

from django.contrib.postgres.aggregates import ArrayAgg as PGArrayAgg
from django.contrib.postgres.aggregates import JSONBAgg as PGJSONBAgg
from django.contrib.postgres.aggregates import StringAgg as PGStringAgg
from django.db.models import Func, JSONField


def _as_sqlite_function(aggregate, compiler, connection, function, source_expressions=None):
    """Recompile an aggregate under a different function name.

    These aggregates mix in ``OrderableAggMixin``, whose ``as_sql`` takes no ``function``
    override, so the name is set on a clone instead of passed through. Calling ``as_sql`` on
    the clone is safe: vendor dispatch happens on the original node, not here.
    """
    clone = aggregate.copy()
    clone.function = function
    if source_expressions is not None:
        clone.set_source_expressions(source_expressions)
    return clone.as_sql(compiler, connection)


class JSONBAgg(PGJSONBAgg):
    """``JSONB_AGG`` on Postgres, ``json_group_array`` on SQLite.

    ``output_field`` is a ``JSONField`` on both, which matters: psycopg2 hands back parsed
    Python objects, whereas ``json_group_array`` returns a JSON *string*. Without the
    ``JSONField`` the SQLite result would reach the caller double-encoded.
    """

    def as_sqlite(self, compiler, connection, **extra_context):
        return _as_sqlite_function(self, compiler, connection, "json_group_array")


class ArrayAgg(PGArrayAgg):
    """``ARRAY_AGG`` on Postgres; a JSON array on SQLite, which reads back as a Python list."""

    def as_sqlite(self, compiler, connection, **extra_context):
        return _as_sqlite_function(self, compiler, connection, "json_group_array")

    def convert_value(self, value, expression, connection):
        # ArrayAgg's output_field is an ArrayField, so unlike JSONBAgg nothing decodes the
        # json_group_array result for us — without this the caller iterates the characters of
        # the string "[4]" instead of the list [4].
        if connection.vendor != "postgresql" and isinstance(value, str):
            return json.loads(value)
        return super().convert_value(value, expression, connection)


class StringAgg(PGStringAgg):
    """``STRING_AGG`` on Postgres, ``group_concat`` on SQLite.

    SQLite rejects ``group_concat(DISTINCT x, ', ')`` outright — "DISTINCT aggregates must have
    exactly one argument" — with no spelling that accepts both. When ``distinct=True`` the
    delimiter is therefore dropped and SQLite's default comma is used, so a distinct
    aggregation renders ``"a,b"`` where Postgres renders ``"a, b"``. This is cosmetic and
    confined to display columns; a REPLACE-based workaround was rejected because it would
    corrupt any value that itself contains a comma.
    """

    def as_sqlite(self, compiler, connection, **extra_context):
        sources = self.get_source_expressions()
        if self.distinct:
            # Keep only the aggregated expression; the delimiter cannot come along.
            sources = sources[:1]
        return _as_sqlite_function(self, compiler, connection, "group_concat", sources)


class JsonBuildObject(Func):
    """``jsonb_build_object`` on Postgres, ``json_object`` on SQLite.

    Both take alternating key/value arguments and both nest correctly inside the JSON array
    aggregates above.
    """

    function = "jsonb_build_object"
    output_field = JSONField()

    def as_sqlite(self, compiler, connection, **extra_context):
        return self.as_sql(compiler, connection, function="json_object", **extra_context)
