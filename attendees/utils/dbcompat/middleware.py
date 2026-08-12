"""Request-scoped SQLite transaction mode."""
from attendees.db.backends.sqlite3.base import (
    DEFERRED,
    IMMEDIATE,
    set_transaction_mode,
)

# Methods that must not write. Anything else is assumed to, and takes the write lock up front.
SAFE_METHODS = frozenset(["GET", "HEAD", "OPTIONS", "TRACE"])


class SqliteTransactionModeMiddleware:
    """Open read-only requests as DEFERRED so they do not queue behind the write lock.

    ``ATOMIC_REQUESTS`` wraps every request in a transaction, and on SQLite a write transaction
    has to start as ``BEGIN IMMEDIATE`` — a deferred one cannot reliably upgrade to a write lock
    under WAL. Opening *reads* that way too makes every request contend for a single lock, which
    is pure cost: a read-only transaction never upgrades, so it was never at risk.

    Installed only when the database is SQLite (see config/settings/base.py). This middleware
    must run outside ``ATOMIC_REQUESTS``, which it does: Django opens that transaction around the
    view, after the whole middleware chain has been entered.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        set_transaction_mode(DEFERRED if request.method in SAFE_METHODS else IMMEDIATE)
        try:
            return self.get_response(request)
        finally:
            # Anything later on this thread — a session write during the response phase, say —
            # gets the safe default back.
            set_transaction_mode(IMMEDIATE)
