"""Application-level audit history: one event table, sealed into a tamper-evident chain.

``from attendees.history import track, context, events_for``; the managers
a tracked model needs are in ``attendees.history.querysets``.
"""
from .context import context
from .tracking import events_for, track

__all__ = ["context", "events_for", "track"]
