"""For every tracked model, the writer records what the triggers used to.

On the golden congregation, each model's first row is saved unchanged,
changed, changed again through the queryset, and deleted; the events each
step produces are the ones the database triggers produced before Phase 5:
a snapshot per real change (a timestamped model's ``modified`` moves on
every save, so every save of one is a change), a ``before_delete`` on the
way out, and nothing for a save that changed nothing.
"""
import pytest
from django.contrib.contenttypes.fields import GenericRelation
from django.db import models
from django.db.models.deletion import ProtectedError

from attendees.history.models import HistoryEvent
from attendees.history.querysets import TrackedQuerySet
from attendees.history.tracking import tracked_models

pytestmark = pytest.mark.django_db

LABELS = sorted(tracked.label for tracked in tracked_models())


def events_of(label, key):
    return HistoryEvent.objects.filter(model=label, object_id=str(key)).order_by("seq")


def changeable_field(tracked):
    """A plain text field of the snapshot a test can write anything short into."""
    for field in tracked.fields:
        if (
            type(field) in (models.CharField, models.TextField)
            and field.editable
            and not field.unique
            and not field.choices
            and field.name not in ("search_text", "slug")
            and (field.max_length or 10) >= 2
        ):
            return field
    return None


def is_referenced(record):
    """Whether any row points at ``record``; deleting such a row would take others with it or leave them dangling."""
    for relation in record._meta.related_objects:
        if relation.many_to_many:
            continue
        if relation.related_model._base_manager.filter(**{relation.field.name: record}).exists():
            return True
    for field in record._meta.private_fields:  # a GenericRelation cascades too
        if isinstance(field, GenericRelation) and getattr(record, field.name).exists():
            return True
    return False


@pytest.mark.parametrize("label", LABELS)
def test_each_tracked_model_records_its_writes(golden, label):
    tracked = next(tracked for tracked in tracked_models() if tracked.label == label)
    model = tracked.model
    record = model._base_manager.order_by("pk").first()
    if record is None:
        pytest.skip(f"{label} has no rows in the golden data")
    key = record.pk
    stamped = any(
        getattr(field, "auto_now", False) or type(field).__name__ == "AutoLastModifiedField" for field in model._meta.concrete_fields
    )

    before = events_of(label, key).count()
    record.save()
    assert events_of(label, key).count() == before + (1 if stamped else 0), "a save that changes nothing"

    field = changeable_field(tracked)
    if field is not None:
        setattr(record, field.attname, "zz")
        record.save()
        latest = events_of(label, key).last()
        assert latest.label == "snapshot" and latest.snapshot[field.attname] == "zz", "a change"
        manager = getattr(model, "all_objects", model._default_manager)
        if isinstance(manager.all(), TrackedQuerySet):
            assert manager.filter(pk=key).update(**{field.attname: "yy"}) == 1
            assert events_of(label, key).last().snapshot[field.attname] == "yy", "a queryset update"

    if model._meta.auto_created:
        return  # a membership row deleted directly sends no signal; removals and cascades are covered in the history tests
    if is_referenced(record):
        return  # the delete path is covered on rows nothing points at
    try:
        model._base_manager.filter(pk=key).delete()
    except ProtectedError:
        return
    assert events_of(label, key).last().label == "before_delete"
    assert events_of(label, key).last().snapshot[model._meta.pk.attname] == (str(key) if not isinstance(key, int) else key)
