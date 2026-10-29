"""Rebuilding the tracked tables from their history.

Every snapshot is the whole record, so the tables as of any moment are the
latest event of each record at or before it, leaving out those whose latest
event is a ``before_delete``. ``compare`` replays to now and diffs against
the live tables, which is how a change made with no event is found;
``write_sqlite`` replays as of a moment into a SQLite file the normal
queries can run against through ``.using(alias)``.
"""
import os
from collections import defaultdict

from django.contrib.contenttypes.models import ContentType
from django.db import connections

from .canonical import diff, snapshot_of_row
from .models import HistoryEvent, hydrate
from .tracking import BEFORE_DELETE, tracked_models

REPLAY_ALIAS = "history_replay"


def reconstruct(as_of=None, using=None, models=None):
    """``{model label: {object_id: snapshot}}`` as the tracked tables stood at ``as_of`` (now when None)."""
    events = HistoryEvent.objects.using(using).order_by("seq").values_list("model", "object_id", "label", "snapshot")
    if as_of is not None:
        events = events.filter(created_at__lte=as_of)
    if models:
        events = events.filter(model__in=models)
    tables = defaultdict(dict)
    for model, object_id, label, snapshot in events.iterator(chunk_size=2000):
        if label == BEFORE_DELETE:
            tables[model].pop(object_id, None)
        else:
            tables[model][object_id] = snapshot
    return tables


def live_snapshots(tracked, using=None):
    """The live table of a tracked model in snapshot form, keyed like the history."""
    pk = tracked.model._meta.pk.attname
    rows = tracked.model._base_manager.using(using).values(*tracked.attnames).iterator(chunk_size=2000)
    return {str(row[pk]): snapshot_of_row(row, tracked.fields) for row in rows}


def compare(using=None):
    """Replay to now against the live tables.

    Returns ``{model label: {"missing": [...], "extra": [...], "changed": {object_id: {field: (history, live)}}}}``
    for every model that differs: ``missing`` rows the history has and the
    table does not (deleted with no event), ``extra`` rows the table has and
    the history does not (created with no event), ``changed`` rows whose
    recorded fields differ. Fields one side does not hold, such as a column
    added after a record's last event, are not compared.
    """
    rebuilt = reconstruct(using=using)
    report = {}
    for tracked in tracked_models():
        history = rebuilt.get(tracked.label, {})
        live = live_snapshots(tracked, using=using)
        missing = sorted(set(history) - set(live))
        extra = sorted(set(live) - set(history))
        changed = {}
        for key in set(history) & set(live):
            differences = {
                field: values
                for field, values in diff(history[key], live[key]).items()
                if field in history[key] and field in live[key]
            }
            if differences:
                changed[key] = differences
        if missing or extra or changed:
            report[tracked.label] = {"missing": missing, "extra": extra, "changed": changed}
    return report


def open_sqlite(path, alias=REPLAY_ALIAS):
    """Open the SQLite file at ``path`` as database ``alias`` for this thread, for ``.using(alias)``.

    The connection is registered directly, outside ``settings.DATABASES``,
    so it is this thread's alone and never part of a test's or a migration's
    set of databases.
    """
    from django.db.utils import ConnectionDoesNotExist, load_backend

    try:
        connections[alias].close()
    except ConnectionDoesNotExist:
        pass
    settings_dict = {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": str(path),
        "ATOMIC_REQUESTS": False,
        "AUTOCOMMIT": True,
        "CONN_MAX_AGE": 0,
        "CONN_HEALTH_CHECKS": False,
        "OPTIONS": {},
        "TIME_ZONE": None,
        "USER": "",
        "PASSWORD": "",
        "HOST": "",
        "PORT": "",
        "TEST": {"CHARSET": None, "COLLATION": None, "MIGRATE": True, "MIRROR": None, "NAME": None},
    }
    connections[alias] = load_backend(settings_dict["ENGINE"]).DatabaseWrapper(settings_dict, alias)
    return alias


def write_sqlite(path, as_of=None, using=None, alias=REPLAY_ALIAS):
    """Replay the tracked tables as of ``as_of`` into a new SQLite file; returns ``{model label: rows}``.

    The file gets the tracked tables and the content types they refer to,
    created from the models rather than the migrations, with foreign key
    checks off because untracked tables (sessions, uploaded files) are not
    there. Query it with ``Model.objects.using(alias)``.
    """
    if os.path.exists(path):
        raise FileExistsError(f"{path} exists; the replay writes a new file")
    open_sqlite(path, alias)
    connection = connections[alias]
    tables = reconstruct(as_of=as_of, using=using)
    owners = [tracked.model for tracked in tracked_models() if not tracked.model._meta.auto_created]
    with connection.schema_editor() as editor:
        editor.create_model(ContentType)
        for model in owners:
            editor.create_model(model)
    connection.ensure_connection()
    connection.connection.execute("PRAGMA foreign_keys = OFF")  # the driver's own connection: the file holds no untracked tables to point at
    ContentType.objects.using(alias).bulk_create(list(ContentType.objects.using(using).all()))
    counts = {}
    for tracked in tracked_models():
        instances = [hydrate(tracked.model, snapshot) for snapshot in tables.get(tracked.label, {}).values()]
        manager = tracked.model._base_manager.using(alias)
        manager.bulk_create(instances, batch_size=500)
        # Fields that stamp "now" on every save would have overwritten the recorded value.
        stamped = [field.attname for field in tracked.fields if getattr(field, "auto_now", False) or type(field).__name__ == "AutoLastModifiedField"]
        if stamped and instances:
            manager.bulk_update(instances, stamped, batch_size=500)
        counts[tracked.label] = len(instances)
    return counts
