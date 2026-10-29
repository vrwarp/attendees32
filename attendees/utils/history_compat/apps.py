from django.apps import AppConfig


class HistoryCompatConfig(AppConfig):
    """Holds the pghistory shim in ``models.py``; see that module for why it is an app."""

    name = "attendees.utils.history_compat"
    label = "history_compat"
