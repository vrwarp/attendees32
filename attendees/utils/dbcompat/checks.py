"""System checks guarding the SQLite compatibility layer's invariants."""
import sys

from django.core.checks import Error, Warning
from django.db import connections

# `migrate` runs system checks before applying anything, and our post_migrate receiver is what
# reinstalls missing triggers. Reporting them as errors there would block the one command that
# fixes them, and make the hint below impossible to follow.
_REPAIRING_COMMANDS = {"migrate", "makemigrations", "sqlmigrate", "showmigrations"}

# Array lookups compile to Postgres array operators. PortableArrayField stores JSON text on
# SQLite, where these would silently match the wrong rows rather than fail loudly.
UNSUPPORTED_ARRAY_LOOKUPS = {"contains", "contained_by", "overlap", "len"}


def check_sqlite_history_triggers(app_configs, **kwargs):
    """Fail loudly when the SQLite database is missing history triggers it should have.

    The audit trail is enforced in the database, so a missing trigger is invisible at the
    application layer: writes keep succeeding and simply go unrecorded. This turns that into a
    startup error. It mainly catches a table rebuilt outside ``migrate`` — by a hand-run ALTER,
    or a restored dump.
    """
    connection = connections["default"]
    if connection.vendor == "postgresql":
        return []

    if len(sys.argv) > 1 and sys.argv[1] in _REPAIRING_COMMANDS:
        return []

    from attendees.utils.dbcompat.triggers import (
        expected_trigger_names,
        installed_trigger_names,
    )

    try:
        installed = installed_trigger_names()
    except Exception:
        # No database yet (a fresh checkout running `migrate` for the first time). The
        # post_migrate receiver installs the triggers; nothing to report.
        return []

    if not installed:
        # An unmigrated database is a normal state, not a broken one.
        return []

    missing = expected_trigger_names() - installed
    if not missing:
        return []

    sample = ", ".join(sorted(missing)[:5])
    more = f" (and {len(missing) - 5} more)" if len(missing) > 5 else ""
    return [
        Error(
            f"{len(missing)} history trigger(s) are missing from the SQLite database: "
            f"{sample}{more}.",
            hint=(
                "Changes to these tables are not being recorded in the history tables. "
                "Run `manage.py migrate` to reinstall them, or call "
                "`attendees.utils.dbcompat.triggers.sync_sqlite_triggers()`."
            ),
            id="dbcompat.E001",
        )
    ]


def check_no_array_lookups(app_configs, **kwargs):
    """Warn when a query filters a PortableArrayField with a Postgres-only array lookup."""
    from attendees.utils.dbcompat.fields import PortableArrayField

    problems = []
    from django.apps import apps

    for model in apps.get_models():
        for field in model._meta.get_fields():
            if isinstance(field, PortableArrayField):
                for lookup in UNSUPPORTED_ARRAY_LOOKUPS:
                    if lookup in field.class_lookups:
                        problems.append(
                            Warning(
                                f"{model._meta.label}.{field.name} registers the array lookup "
                                f"'{lookup}', which has no SQLite equivalent.",
                                hint=(
                                    "PortableArrayField stores JSON text outside Postgres; "
                                    "array lookups would match incorrectly there."
                                ),
                                id="dbcompat.W001",
                            )
                        )
    return problems
