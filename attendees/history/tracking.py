"""What is tracked, and the one writer every path lands on.

``@track`` on a model (or ``track(Model)`` for one that is not ours) puts
it in the registry. The registry's signal handlers record a ``snapshot``
after every save that changed something and a ``before_delete`` before
every delete; ``record_rows`` is what the tracked querysets call after a
bulk write; ``append_events`` is the writer itself, which seals each event
onto the chain under the head row's lock.
"""
import logging
from dataclasses import dataclass

from django.apps import apps
from django.db import models, router, transaction
from django.db.models.signals import m2m_changed, post_save, pre_delete
from django.utils import timezone

from .canonical import chain_key, mac_for, snapshot_of, snapshot_of_row
from .context import context_row_id

log = logging.getLogger(__name__)

SNAPSHOT = "snapshot"
BEFORE_DELETE = "before_delete"

# Models from the frameworks the application builds on, tracked through signals alone: their
# managers are their own, so a bulk write of theirs is a known gap the nightly replay reports.
FRAMEWORK_MODELS = (
    "auth.Group",
    "auth.Permission",
    "account.EmailAddress",
    "account.EmailConfirmation",
    "address.Country",
    "address.State",
    "address.Locality",
    "address.Address",
    "django_celery_beat.PeriodicTask",
    "django_celery_beat.CrontabSchedule",
    "django_celery_beat.IntervalSchedule",
    "schedule.Rule",
    "schedule.Calendar",
    "schedule.CalendarRelation",
    "schedule.Event",
    "schedule.EventRelation",
    "schedule.Occurrence",
)


@dataclass(frozen=True)
class TrackedModel:
    model: type
    exclude: frozenset

    @property
    def label(self):
        return self.model._meta.label_lower

    @property
    def fields(self):
        """The concrete fields a snapshot holds; the key is never excluded."""
        return [
            field
            for field in self.model._meta.concrete_fields
            if field.primary_key or (field.name not in self.exclude and field.attname not in self.exclude)
        ]

    @property
    def attnames(self):
        return [field.attname for field in self.fields]


_registry = {}


def track(model=None, *, exclude=()):
    """Register ``model``; ``exclude`` names fields kept out of its snapshots (``User.password``)."""

    def register(cls):
        concrete = cls._meta.concrete_model
        key = concrete._meta.label_lower
        if key not in _registry:
            _registry[key] = TrackedModel(concrete, frozenset(exclude))
            if concrete.__module__.startswith("attendees.") and not hasattr(concrete, "history"):
                concrete.history = property(events_for)
        return cls

    return register(model) if model is not None else register


def tracked_for(model):
    """The registry entry for ``model`` (a proxy counts as its concrete model), or ``None``.

    A migration's historical model carries the same label but is another
    class; it is not tracked, so data migrations write no events.
    """
    concrete = model._meta.concrete_model
    tracked = _registry.get(concrete._meta.label_lower)
    return tracked if tracked is not None and tracked.model is concrete else None


def is_tracked(model):
    return tracked_for(model) is not None


def tracked_models():
    return list(_registry.values())


def track_frameworks():
    """Track the framework models and every auto-made membership table of a tracked model.

    Called once the apps are ready, so the models exist; the membership tables
    (``users.user_groups``, ``persons.note_viewers``) are found from the
    many-to-many fields of what is tracked by then.
    """
    for label in FRAMEWORK_MODELS:
        try:
            track(apps.get_model(label))
        except LookupError:
            log.warning("history: %s is not installed, so it is not tracked", label)
    for tracked in list(_registry.values()):
        for field in tracked.model._meta.local_many_to_many:
            through = field.remote_field.through
            if through._meta.auto_created:
                track(through)


def baseline_rows(models=None, using=None):
    """A first snapshot for every live row of the tracked ``models`` (all when None) that has no event.

    Run by the migration that switches the history on and after every
    ``migrate``, because the permissions Django creates then are written
    behind the writer's back. Returns how many rows were recorded.
    """
    from .models import HistoryEvent

    db = using or router.db_for_write(HistoryEvent)
    chosen = [tracked for tracked in tracked_models() if models is None or tracked.model in models]
    recorded_rows = 0
    for tracked in chosen:
        recorded = set(HistoryEvent.objects.using(db).filter(model=tracked.label).values_list("object_id", flat=True).distinct())
        pk = tracked.model._meta.pk.attname
        events = []
        for row in tracked.model._base_manager.using(db).values(*tracked.attnames).iterator(chunk_size=2000):
            if str(row[pk]) not in recorded:
                events.append((tracked.label, str(row[pk]), SNAPSHOT, snapshot_of_row(row, tracked.fields)))
        recorded_rows += len(append_events(events, using=db))
    return recorded_rows


def events_for(record, using=None):
    """The record's events, oldest first; ``object_id`` is compared as text on every backend."""
    from .models import HistoryEvent

    tracked = tracked_for(type(record))
    label = tracked.label if tracked else type(record)._meta.concrete_model._meta.label_lower
    return HistoryEvent.objects.using(using).filter(model=label, object_id=str(record.pk)).order_by("seq")


# --- the writer -------------------------------------------------------------------------------


def record(instance, *, label=SNAPSHOT, created=False, using=None, tracked=None):
    """Record one event for ``instance``; a snapshot that changed nothing is skipped.

    A snapshot of a record that already existed is read back from the
    database, so it holds the row as it stands rather than as the instance
    in memory has it (deferred fields, values the database filled in).
    """
    tracked = tracked or tracked_for(type(instance))
    if tracked is None:
        raise ValueError(f"{type(instance)._meta.label} is not tracked")
    db = using or router.db_for_write(tracked.model, instance=instance)
    object_id = str(instance.pk)
    if label == BEFORE_DELETE or created:
        snapshot = snapshot_of(instance, tracked.fields)
    else:
        row = tracked.model._base_manager.using(db).filter(pk=instance.pk).values(*tracked.attnames).first()
        if row is None:
            return None
        snapshot = snapshot_of_row(row, tracked.fields)
        if _last_snapshots(tracked.label, [object_id], db).get(object_id) == (SNAPSHOT, snapshot):
            return None
    return append_events([(tracked.label, object_id, label, snapshot)], using=db)[0]


def record_rows(model, pks, *, using=None, created=False, label=SNAPSHOT):
    """Record an event for each of ``pks`` as the rows now stand; an unchanged snapshot is skipped."""
    tracked = tracked_for(model)
    if tracked is None or not pks:
        return []
    db = using or router.db_for_write(tracked.model)
    pk_attname = tracked.model._meta.pk.attname
    snapshots = {}
    for chunk in _chunks(list(pks)):
        for row in tracked.model._base_manager.using(db).filter(pk__in=chunk).values(*tracked.attnames):
            snapshots[str(row[pk_attname])] = snapshot_of_row(row, tracked.fields)
    if label == SNAPSHOT and not created:
        last = _last_snapshots(tracked.label, list(snapshots), db)
        snapshots = {key: snapshot for key, snapshot in snapshots.items() if last.get(key) != (SNAPSHOT, snapshot)}
    return append_events([(tracked.label, key, label, snapshot) for key, snapshot in snapshots.items()], using=db)


def append_events(events, *, using=None, created_at=None):
    """Seal ``events`` (model, object_id, label, snapshot) onto the chain and insert them.

    One lock on the head row covers the batch; every event gets the next
    ``seq`` and a ``mac`` over the previous one, so the chain stays linear
    however many writers there are.
    """
    from .models import HistoryEvent, HistoryHead

    if not events:
        return []
    db = using or router.db_for_write(HistoryEvent)
    key = chain_key()
    with transaction.atomic(using=db, savepoint=False):
        head = HistoryHead.objects.using(db).select_for_update().filter(pk=1).first()
        if head is None:
            head = HistoryHead.objects.using(db).create(pk=1)
        context_id = context_row_id(using=db)
        now = created_at or timezone.now()
        prev, seq = head.mac, head.seq
        rows = []
        for model, object_id, label, snapshot in events:
            seq += 1
            mac = mac_for(prev, model, object_id, label, now, snapshot, key=key)
            rows.append(
                HistoryEvent(
                    seq=seq,
                    model=model,
                    object_id=object_id,
                    label=label,
                    created_at=now,
                    context_id=context_id,
                    snapshot=snapshot,
                    prev_mac=prev,
                    mac=mac,
                )
            )
            prev = mac
        HistoryEvent.objects.using(db).bulk_create(rows, batch_size=500)
        HistoryHead.objects.using(db).filter(pk=1).update(seq=seq, mac=prev)
    return rows


def _last_snapshots(label, object_ids, db):
    """``{object_id: (label, snapshot)}`` of the latest event of each of ``object_ids``."""
    from .models import HistoryEvent

    found = {}
    for chunk in _chunks(object_ids):
        latest = (
            HistoryEvent.objects.using(db)
            .filter(model=label, object_id__in=chunk)
            .values("object_id")
            .annotate(last=models.Max("seq"))
        )
        seqs = [row["last"] for row in latest]
        if seqs:
            for object_id, event_label, snapshot in HistoryEvent.objects.using(db).filter(seq__in=seqs).values_list(
                "object_id", "label", "snapshot"
            ):
                found[object_id] = (event_label, snapshot)
    return found


def _chunks(items, size=500):
    for start in range(0, len(items), size):
        yield items[start : start + size]


# --- signals ----------------------------------------------------------------------------------


def _on_post_save(sender, instance, created, using, **kwargs):
    tracked = tracked_for(sender)
    if tracked is not None:
        record(instance, created=created, using=using, tracked=tracked)


def _on_pre_delete(sender, instance, using, **kwargs):
    tracked = tracked_for(sender)
    if tracked is None:
        return
    record(instance, label=BEFORE_DELETE, using=using, tracked=tracked)
    # The collector deletes the record's memberships in auto-made tables without any signal.
    for through, column in _membership_tables(tracked.model):
        pks = list(through._base_manager.using(using).filter(**{column: instance.pk}).values_list("pk", flat=True))
        record_rows(through, pks, using=using, label=BEFORE_DELETE)


def _membership_tables(model):
    """``(through model, column naming this model)`` for every auto-made membership table of ``model``."""
    tables = []
    for field in model._meta.local_many_to_many:
        through = field.remote_field.through
        if through._meta.auto_created and tracked_for(through) is not None:
            tables.append((through, field.m2m_field_name()))
    for relation in model._meta.related_objects:
        if relation.many_to_many:
            through = relation.through
            if through._meta.auto_created and tracked_for(through) is not None:
                tables.append((through, relation.field.m2m_reverse_field_name()))
    return tables


def _on_m2m_changed(sender, instance, action, reverse, model, pk_set, using, **kwargs):
    """Memberships are written with ``bulk_create`` and deleted by the collector, and for an
    auto-made membership table neither sends a signal, so they are recorded from here.

    An explicit membership model (``AttendeeScheduler``) has tracked managers
    and sends ``pre_delete``, so only its adds are read back, and those are
    compared with what its own ``bulk_create`` recorded.
    """
    tracked = tracked_for(sender)
    if tracked is None:
        return
    owner = (model if reverse else type(instance))._meta.concrete_model
    m2m = next(
        (field for field in owner._meta.many_to_many if field.remote_field.through._meta.concrete_model is sender._meta.concrete_model),
        None,
    )
    if m2m is None:
        return
    source, target = m2m.m2m_field_name(), m2m.m2m_reverse_field_name()
    if reverse:
        source, target = target, source
    if action == "post_add" and pk_set:
        rows = models.Q(**{source: instance.pk, f"{target}__in": pk_set})
        if m2m.remote_field.symmetrical:
            rows |= models.Q(**{target: instance.pk, f"{source}__in": pk_set})
        pks = list(sender._base_manager.using(using).filter(rows).values_list("pk", flat=True))
        record_rows(sender, pks, using=using)
    elif action in ("pre_remove", "pre_clear") and sender._meta.auto_created:
        rows = models.Q(**{source: instance.pk})
        if action == "pre_remove":
            if not pk_set:
                return
            rows &= models.Q(**{f"{target}__in": pk_set})
        pks = list(sender._base_manager.using(using).filter(rows).values_list("pk", flat=True))
        record_rows(sender, pks, using=using, label=BEFORE_DELETE)


post_save.connect(_on_post_save, dispatch_uid="attendees.history.post_save", weak=False)
pre_delete.connect(_on_pre_delete, dispatch_uid="attendees.history.pre_delete", weak=False)
m2m_changed.connect(_on_m2m_changed, dispatch_uid="attendees.history.m2m_changed", weak=False)
