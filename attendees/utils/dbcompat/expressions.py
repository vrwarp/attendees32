"""Portable spellings for Postgres-only SQL expressions."""
import json

from django.db.models import Func
from django.db.models.fields import BooleanField, CharField


class JsonArrayHasKeyValue(Func):
    """True when a JSON array annotation contains an object with ``key`` set to ``value``.

    Used to sort the attendee datagrid by whether a row participates in a given meet. The
    aggregated column is a JSON array of objects such as::

        [{"attendingmeet_id": 1, "meet_slug": "choir", ...}, ...]

    Postgres uses the native containment operator so the expression stays indexable. SQLite has
    no containment operator; ``json_each`` would be the principled equivalent but cannot be
    correlated against an aggregate alias in ORDER BY, so this matches the serialized form
    instead. That is safe here because both ``json_object`` and ``jsonb_build_object`` emit
    compact, separator-free JSON, and meet slugs are URL-safe (no quotes, colons or backslashes
    to escape).
    """

    output_field = BooleanField()

    def __init__(self, expression, key, value, **extra):
        self.key = key
        self.value = value
        super().__init__(expression, **extra)

    def as_sql(self, compiler, connection, **extra_context):
        probe = json.dumps([{self.key: self.value}], separators=(",", ":"))
        sql, params = compiler.compile(self.get_source_expressions()[0])
        # Bind the probe rather than inlining it, so a slug can never break out of the literal.
        return f"%s::jsonb <@ ({sql})", [probe, *params]

    def as_sqlite(self, compiler, connection, **extra_context):
        sql, params = compiler.compile(self.get_source_expressions()[0])
        needle = f'%"{self.key}":"{self.value}"%'
        return f"({sql}) LIKE %s", [*params, needle]


class UuidAsText(Func):
    """Render a UUID primary key as canonical hyphenated text on every backend.

    Generic relations here store the parent key in a ``CharField`` (``Place.object_id``), so
    joining against a ``UUIDField`` pk needs the UUID as text. The two backends disagree about
    what that text is: Postgres stores a native ``uuid`` and casts it to the hyphenated form,
    while Django's SQLite backend stores UUIDs as 32 hex characters with no hyphens. A plain
    CAST therefore matches on Postgres and silently matches nothing on SQLite.

    ``uuid_text()`` is registered per connection by our SQLite backend and normalises both
    spellings to the hyphenated one.
    """

    output_field = CharField()

    def as_sql(self, compiler, connection, **extra_context):
        return super().as_sql(
            compiler, connection, template="CAST(%(expressions)s AS varchar)", **extra_context
        )

    def as_sqlite(self, compiler, connection, **extra_context):
        return super().as_sql(
            compiler, connection, template="uuid_text(%(expressions)s)", **extra_context
        )


def json_array_has_key_value(expression, key, value):
    """Convenience wrapper mirroring the old inline ``Func`` construction."""
    return JsonArrayHasKeyValue(expression, key, value)


__all__ = ["JsonArrayHasKeyValue", "json_array_has_key_value", "Value"]
