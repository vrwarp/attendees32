"""Make pghistory's request/task context tracking work on SQLite.

On Postgres, ``pghistory.context`` prepends ``SET LOCAL pghistory.context_id=...`` to every
statement, and the ``_pgh_attach_context()`` stored procedure reads those session variables and
upserts a row into ``pghistory_context``. SQLite has neither session variables nor stored
procedures, and the prepended statement would break every query.

The replacement keeps the same observable behaviour:

* ``_pgh_attach_context()`` is a per-connection Python function (registered by our SQLite
  backend) that reads pghistory's own thread-local. Trigger bodies therefore stay
  byte-identical to the Postgres ones.
* The ``pghistory_context`` row is written from Python, and — matching Postgres — only when a
  trigger actually fired. The UDF flags that it ran; the flag is flushed when the context exits.

Nothing here changes the public API, so the ``pghistory.context(...)`` call sites in
``occasions/tasks.py``, ``pcosync/tasks.py``, ``pcosync/management/commands/pcosync.py`` and the
``HistoryMiddleware`` entry in settings are untouched.
"""
import json

from django.db import connections

_patched = False


def context_was_attached(tracker):
    """True when a history trigger called ``_pgh_attach_context()`` during this context."""
    return getattr(tracker, "pgh_context_attached", False)


def _flush_context_row(value, using):
    """Write the ``pghistory_context`` row for a context that a trigger referenced."""
    from pghistory.models import Context

    connection = connections[using]
    if connection.vendor == "postgresql":  # pragma: no cover - Postgres upserts in-procedure
        return

    with connection.cursor() as cursor:
        cursor.execute(
            f"INSERT OR REPLACE INTO {Context._meta.db_table} "
            "(id, metadata, created_at, updated_at) "
            "VALUES (%s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
            [str(value.id), json.dumps(value.metadata, cls=_encoder())],
        )


def _encoder():
    from pghistory.tracking import _json_encoder

    return _json_encoder()


def patch_pghistory_for_sqlite():
    """Install the SQLite-aware context hooks. Idempotent; a no-op on a Postgres-only install.

    ``context.__enter__`` looks ``_inject_history_context`` up in module globals at call time,
    so rebinding the module attribute is enough — the class itself needs no subclassing.
    """
    global _patched
    if _patched:
        return

    from pghistory import tracking

    original_inject = tracking._inject_history_context
    original_exit = tracking.context.__exit__

    def _vendor_aware_inject(execute, sql, params, many, context):
        connection = context["connection"]
        if connection.vendor == "postgresql":
            return original_inject(execute, sql, params, many, context)
        # SQLite: the UDF reads the thread-local directly, so nothing needs prepending.
        return execute(sql, params, many, context)

    def _vendor_aware_exit(self, *exc):
        value = getattr(tracking._tracker, "value", None)
        if (
            self._pre_execute_hook
            and value is not None
            and context_was_attached(tracking._tracker)
        ):
            try:
                _flush_context_row(value, "default")
            finally:
                tracking._tracker.pgh_context_attached = False
        return original_exit(self, *exc)

    tracking._inject_history_context = _vendor_aware_inject
    tracking.context.__exit__ = _vendor_aware_exit
    _patched = True
