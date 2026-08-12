"""Fields that present one identity to migration state and two representations to the database.

Same reasoning as ``indexes.py``: ``Field.deconstruct()`` embeds the class path, so swapping
field classes on a vendor check would fork the migration state. Instead the class is constant
and only ``db_type``/value preparation branch.
"""
import json

from django.contrib.postgres.fields import ArrayField


class PortableArrayField(ArrayField):
    """A Postgres array; a JSON-encoded text column elsewhere.

    The Python value is a plain list on both backends, so forms, serializers, admin and the
    history triggers (which copy the column verbatim) all behave identically.

    Array *lookups* — ``__contains``, ``__overlap``, ``__len`` — are deliberately not
    supported outside Postgres: they would compile against JSON text and match the wrong rows
    instead of failing. ``checks.check_no_array_lookups`` guards against one being introduced.
    """

    def deconstruct(self):
        name, _path, args, kwargs = super().deconstruct()
        return name, "attendees.utils.dbcompat.fields.PortableArrayField", args, kwargs

    def db_type(self, connection):
        if connection.vendor == "postgresql":
            return super().db_type(connection)
        return "text"

    def cast_db_type(self, connection):
        if connection.vendor == "postgresql":
            return super().cast_db_type(connection)
        return "text"

    def get_placeholder(self, value, compiler, connection):
        if connection.vendor == "postgresql":
            return super().get_placeholder(value, compiler, connection)
        # ArrayField placeholders carry an explicit `%s::bigint[]` cast, which SQLite cannot
        # parse. A bare placeholder is right for the JSON text we bind instead.
        return "%s"

    def get_db_prep_value(self, value, connection, prepared=False):
        if connection.vendor == "postgresql":
            return super().get_db_prep_value(value, connection, prepared)
        if value is None:
            return None
        return json.dumps(list(value))

    def from_db_value(self, value, expression, connection):
        if connection.vendor == "postgresql" or value is None:
            return value
        if isinstance(value, (list, tuple)):
            return list(value)
        return json.loads(value)
