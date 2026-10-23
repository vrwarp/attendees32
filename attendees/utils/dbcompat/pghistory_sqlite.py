"""Make pghistory's request/task context tracking work on SQLite.

On Postgres, ``pghistory.context`` prepends ``SET LOCAL pghistory.context_id=...`` to every
statement, and the ``_pgh_attach_context()`` stored procedure reads those session variables and
upserts a row into ``pghistory_context``. SQLite has neither session variables nor stored
procedures, and the prepended statement would break every query.

The replacement keeps the same observable behaviour:

* ``_pgh_attach_context()`` becomes a per-connection Python function. Our SQLite backend
  registers it under the same name, so trigger bodies stay byte-identical to the Postgres ones.
  It answers from :func:`current_context_id` below, which reads pghistory's own thread-local.
* The ``pghistory_context`` row is written from Python, and — matching Postgres — only when a
  trigger actually fired. SQLite documents writing to the database from inside a function a
  trigger invoked as undefined behaviour, so the function only *marks* that it ran, and the row
  is flushed when the context exits. The deferred write cannot break integrity:
  ``pgh_context_id`` is ``db_constraint=False`` on every event model.

Nothing here changes the public API: ``pghistory.context(...)`` call sites and the
``HistoryMiddleware`` entry in settings are untouched, and on Postgres every hook defers to the
original behaviour.
"""
import json

from django.db import connections

_patched = False


def current_context_id():
    """The active pghistory context id, or None when tracking is not enabled.

    Called (via the backend's ``_pgh_attach_context`` function) from inside history triggers.
    Reads a thread-local, so it is inherently per-thread and per-connection — a shared table
    here would leak one worker's context id into another worker's history rows.

    As a side effect it marks the context as used, which is what tells the ``__exit__`` hook
    below to materialise the context row. Postgres creates that row only when a trigger fires;
    marking on read gives SQLite the same economy, so read-only requests leave nothing behind.
    """
    from pghistory import tracking

    value = getattr(tracking._tracker, "value", None)
    if value is None:
        return None
    tracking._tracker.pgh_context_attached = True
    return str(value.id)


def _flush_context_row(value):
    """Write the ``pghistory_context`` row for a context some trigger referenced.

    Only ever reached on SQLite: the flag it is guarded by is set by the function above, which
    only the SQLite backend registers.
    """
    from pghistory.models import Context
    from pghistory.tracking import _json_encoder

    with connections["default"].cursor() as cursor:
        cursor.execute(
            f"INSERT OR REPLACE INTO {Context._meta.db_table} "
            "(id, metadata, created_at, updated_at) "
            "VALUES (%s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
            [str(value.id), json.dumps(value.metadata, cls=_json_encoder())],
        )


def patch_pghistory_for_sqlite():
    """Install the SQLite-aware context hooks. Idempotent; inert on a Postgres-only install.

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
        # SQLite: the registered function reads the thread-local directly, nothing to prepend.
        return execute(sql, params, many, context)

    def _vendor_aware_exit(self, *exc):
        value = getattr(tracking._tracker, "value", None)
        if (
            self._pre_execute_hook  # only the outermost context flushes, as upstream exits
            and value is not None
            and getattr(tracking._tracker, "pgh_context_attached", False)
        ):
            try:
                _flush_context_row(value)
            finally:
                tracking._tracker.pgh_context_attached = False
        return original_exit(self, *exc)

    tracking._inject_history_context = _vendor_aware_inject
    tracking.context.__exit__ = _vendor_aware_exit
    _patched = True
