from django.apps import AppConfig
from django.db.models.signals import post_migrate


def record_permissions(sender, using="default", **kwargs):
    """Django creates permissions after every migrate, behind the writer's back; give them a first event."""
    from django.contrib.auth.models import Permission

    from .context import context
    from .tracking import baseline_rows, tracked_for

    if tracked_for(Permission) is None:
        return
    with context("migrate: first snapshot of new permissions"):
        baseline_rows(models=[Permission], using=using)


class HistoryConfig(AppConfig):
    name = "attendees.history"
    verbose_name = "History"

    def ready(self):
        from .tracking import track_frameworks

        track_frameworks()
        post_migrate.connect(record_permissions, dispatch_uid="attendees.history.record_permissions")
