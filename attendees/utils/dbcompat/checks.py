"""System checks guarding the SQLite compatibility layer's invariants."""
import sys

from django.core.checks import Error
from django.db import connections

# `migrate` runs system checks before applying anything, and our post_migrate receiver is what
# reinstalls missing triggers. Reporting them as errors there would block the one command that
# fixes them, and make the hint below impossible to follow.
_REPAIRING_COMMANDS = {"migrate", "makemigrations", "sqlmigrate", "showmigrations"}


def check_sqlite_history_triggers(app_configs, **kwargs):
    """Fail loudly when the SQLite database is missing history triggers it should have.

    The audit trail is enforced in the database, so a missing trigger is invisible at the
    application layer: writes keep succeeding and simply go unrecorded. This turns that into an
    error on any management command that runs system checks — `runserver`, `check`, and most
    others. It mainly catches a table rebuilt outside `migrate`, by a hand-run ALTER or a
    restored dump.
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
