"""SQLite backend carrying the settings a primary-database SQLite install needs.

This is a backend rather than a ``connection_created`` receiver because only a backend can
promise the PRAGMAs and the pghistory functions exist before *any* statement runs, including
during ``migrate`` and management commands.
"""
import datetime
import json
import threading

from django.db.backends.sqlite3 import base as sqlite3_base
from django.db.backends.sqlite3 import operations as sqlite3_operations

# Django stores datetimes on SQLite as naive UTC strings; match that exactly so history rows
# compare equal to rows written by the ORM.
_DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S.%f"

# How the next transaction on this thread should open. IMMEDIATE is the safe default: it takes
# the write lock up front, which is what a transaction that will write needs. Read-only work
# sets DEFERRED so it does not queue behind every other request. See set_transaction_mode.
_state = threading.local()

DEFERRED = "DEFERRED"
IMMEDIATE = "IMMEDIATE"


def set_transaction_mode(mode):
    _state.mode = mode


def get_transaction_mode():
    return getattr(_state, "mode", IMMEDIATE)


def _uuid_text(value):
    """Normalise a stored UUID to its canonical hyphenated form.

    Django's SQLite backend writes UUIDs as 32 hex characters with no hyphens, while Postgres
    renders its native uuid type hyphenated. Generic relations join a UUID pk against a
    CharField, so without this the same row compares equal on one backend and not the other.
    """
    if value is None:
        return None
    text = str(value)
    if len(text) == 32:
        return f"{text[0:8]}-{text[8:12]}-{text[12:16]}-{text[16:20]}-{text[20:32]}"
    return text.lower()


class DatabaseOperations(sqlite3_operations.DatabaseOperations):
    def adapt_json_value(self, value, encoder):
        """Store JSON as real UTF-8 rather than \\uXXXX escapes.

        Django's default serialization is ``json.dumps(..., ensure_ascii=True)``, so a name
        like 陳 is written to SQLite as the seven literal characters ``\\u9673``. Postgres does
        not have this problem: ``jsonb`` holds the decoded text, so casting it for a
        ``infos__icontains`` search matches what the user typed.

        Left alone, every search of a Han name silently returns nothing on SQLite — the query
        succeeds and the grid is simply empty. This congregation's records are largely Chinese,
        so that is a functional gap rather than a cosmetic one.
        """
        return json.dumps(value, cls=encoder, ensure_ascii=False)


class DatabaseWrapper(sqlite3_base.DatabaseWrapper):
    """SQLite with WAL, per-request transaction modes, and this project's SQL functions."""

    ops_class = DatabaseOperations

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Postgres NOW() is transaction-start time. SQLite's STRFTIME('now') is statement time,
        # so two writes in one request would disagree across backends. Cache the first reading
        # taken inside a transaction and reuse it until the transaction ends.
        self._pgh_transaction_now = None

    def get_new_connection(self, conn_params):
        conn = super().get_new_connection(conn_params)
        # WAL lets readers and the single writer proceed concurrently. It is a persistent
        # property of the database file, so setting it per connection is merely idempotent.
        # In-memory databases silently refuse it, which is fine.
        conn.execute("PRAGMA journal_mode = WAL")
        # NORMAL is the standard durability trade for WAL: safe against process crashes,
        # exposed only to a power loss reordering the last commits.
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.execute("PRAGMA foreign_keys = ON")
        # recursive_triggers is deliberately left at its default OFF: it is the closer match to
        # Postgres. Turning it on makes INSERT OR REPLACE emit a delete event that Postgres
        # would never produce.
        self._register_pgh_functions(conn)
        return conn

    def _register_pgh_functions(self, conn):
        """Install the functions the compiled history triggers call.

        ``_pgh_attach_context`` and ``_pgh_now`` keep the names of their Postgres counterparts,
        which is what lets the trigger compiler emit byte-identical trigger bodies on both
        backends. The context logic itself lives with the rest of the pghistory glue in
        ``attendees.utils.dbcompat.pghistory_sqlite``.
        """
        from attendees.utils.dbcompat import geo
        from attendees.utils.dbcompat.pghistory_sqlite import current_context_id

        conn.create_function("_pgh_attach_context", 0, current_context_id)
        conn.create_function("_pgh_now", 0, self._pgh_now)
        conn.create_function("uuid_text", 1, _uuid_text)
        # The coordinates service's raw SQL calls PostGIS functions by name; same trick.
        geo.register(conn)

    def _pgh_now(self):
        if self._pgh_transaction_now is None:
            now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
            formatted = now.strftime(_DATETIME_FORMAT)
            if not self.in_atomic_block:
                # Outside a transaction every statement is its own transaction, so there is
                # nothing to hold the reading for.
                return formatted
            self._pgh_transaction_now = formatted
        return self._pgh_transaction_now

    def _start_transaction_under_autocommit(self):
        """Open the transaction in the mode this piece of work actually needs.

        ``ATOMIC_REQUESTS = True`` wraps every request in a transaction. Django's default bare
        ``BEGIN`` is deferred: it takes a read lock and tries to upgrade on the first write. In
        WAL mode that upgrade fails immediately with SQLITE_BUSY_SNAPSHOT if anyone committed
        in the meantime, and ``busy_timeout`` does not retry it because retrying can never
        succeed. So anything that writes must use ``BEGIN IMMEDIATE``, which takes the write
        lock at the start where the timeout does apply.

        Applying that to *every* request, though, serialises reads behind the single write lock.
        Measured against this project's attendee page, which fires eight API calls at once, it
        cost about 70% added latency on reads — mean 747ms against 445ms on Postgres for the
        same endpoint — with no benefit, since a read-only transaction never upgrades and so can
        never hit SQLITE_BUSY_SNAPSHOT. Read-only requests therefore open DEFERRED and run
        concurrently under WAL, which brought the same endpoint back to 412ms.

        The mode is chosen per request by SqliteTransactionModeMiddleware; everything else —
        management commands, Celery tasks, tests — keeps the IMMEDIATE default.
        """
        self._pgh_transaction_now = None
        self.cursor().execute(f"BEGIN {get_transaction_mode()}")

    def _commit(self):
        self._pgh_transaction_now = None
        return super()._commit()

    def _rollback(self):
        self._pgh_transaction_now = None
        return super()._rollback()
