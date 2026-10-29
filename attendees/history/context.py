"""Who is writing: the request, job or shell behind a run of events.

A context variable holds the current state; the middleware sets one per
request, ``history.context(...)`` sets one for a task or a command, and a
write with neither records ``shell`` and the operating-system user. The
``history_context`` row is created lazily, by the first event the state
produces, so a request that writes nothing leaves nothing behind.
"""
import contextvars
import functools
import getpass


class State:
    __slots__ = ("label", "user_getter", "user_id", "user_name", "row_id")

    def __init__(self, label, user_getter=None, user_id=None, user_name=""):
        self.label = label[:255]
        self.user_getter = user_getter
        self.user_id = user_id
        self.user_name = user_name
        self.row_id = None


def _os_user():
    try:
        return getpass.getuser()
    except Exception:  # no login name in this environment
        return ""


_state = contextvars.ContextVar("attendees_history_context", default=None)
_shell = State("shell", user_name=_os_user())


def begin(label, user_getter=None):
    """Enter a state; returns the token ``end`` takes."""
    return _state.set(State(label, user_getter=user_getter))


def end(token):
    _state.reset(token)


def current():
    return _state.get() or _shell


class context:
    """A labelled state for a task or a command.

    ``with history.context("batch create gatherings"):`` or as a decorator on
    the task function. ``user`` or ``user_id`` names who the work is done for.
    """

    def __init__(self, label, *, user=None, user_id=None, user_name=""):
        self.label = label
        self.user_id = user.pk if user is not None else user_id
        self.user_name = user.get_username() if user is not None else user_name

    def __enter__(self):
        self._token = _state.set(State(self.label, user_id=self.user_id, user_name=self.user_name))
        return self

    def __exit__(self, *exc):
        _state.reset(self._token)
        return False

    def __call__(self, func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            with self:
                return func(*args, **kwargs)

        return wrapper


def context_row_id(using=None):
    """The ``history_context`` row for the current state, created on first use."""
    from .models import HistoryContext

    state = current()
    if state.user_getter is not None:
        user = state.user_getter()
        if user is not None and getattr(user, "is_authenticated", False):
            state.user_id, state.user_name = user.pk, user.get_username()
        state.user_getter = None
    # The row is checked by content, not by id alone: a row created in a transaction that rolled
    # back leaves a stale id, and SQLite hands the same id to the next row.
    if state.row_id is not None and HistoryContext.objects.using(using).filter(
        pk=state.row_id, label=state.label, user_id=state.user_id, user_name=state.user_name
    ).exists():
        return state.row_id
    row = HistoryContext.objects.using(using).create(label=state.label, user_id=state.user_id, user_name=state.user_name)
    state.row_id = row.pk
    return row.pk
