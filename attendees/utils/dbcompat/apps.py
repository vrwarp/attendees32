from django.apps import AppConfig
from django.core.checks import register
from django.db import connections
from django.db.models.signals import post_migrate


def _resync_sqlite_triggers(sender, using, **kwargs):
    """Reinstall history triggers after every migrate on SQLite.

    SQLite has no ALTER for most column changes, so Django emulates them by building a new
    table, copying rows, dropping the original and renaming. Dropping the table drops its
    triggers, and Django has no concept of triggers so it never puts them back. Without this
    receiver an ordinary AlterField would silently stop the audit trail, which is the worst
    failure mode an audit system has: history keeps "working" and simply records nothing.

    This mirrors what pgtrigger's install-on-migrate does for Postgres.
    """
    if connections[using].vendor == "postgresql":
        return

    from attendees.utils.dbcompat.triggers import sync_sqlite_triggers

    sync_sqlite_triggers(using=using)


class DbCompatConfig(AppConfig):
    name = "attendees.utils.dbcompat"
    label = "dbcompat"
    verbose_name = "Database compatibility"

    def ready(self):
        from attendees.utils.dbcompat.checks import check_sqlite_history_triggers
        from attendees.utils.dbcompat.pghistory_sqlite import patch_pghistory_for_sqlite

        patch_pghistory_for_sqlite()
        post_migrate.connect(_resync_sqlite_triggers, dispatch_uid="dbcompat.resync_triggers")
        register(check_sqlite_history_triggers, "database", deploy=False)
