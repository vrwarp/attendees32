from django.apps import AppConfig


class OccasionsConfig(AppConfig):
    name = "attendees.occasions"

    def ready(self):
        import attendees.occasions.signals  # noqa F401  https://docs.djangoproject.com/en/dev/topics/signals/#preventing-duplicate-signals
