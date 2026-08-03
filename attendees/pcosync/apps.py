from django.apps import AppConfig


class PcosyncConfig(AppConfig):
    name = "attendees.pcosync"
    verbose_name = "Planning Center sync"

    def ready(self):
        # Celery's autodiscover_tasks() looks for a tasks module in every
        # installed app, so registering this app is what makes the sync task
        # visible to the worker.
        try:
            import attendees.pcosync.tasks  # noqa: F401
        except ImportError:  # pragma: no cover - tasks arrive with the orchestration step
            pass
