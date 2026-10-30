"""One event table for every tracked record, sealed into a ledger.

``HistoryEvent`` holds one row per change: which record, the whole record
as a snapshot, who did it (``HistoryContext``) and the seal (``prev_mac``,
``mac``). ``HistoryHead`` is the single row the writer locks to extend the
chain; ``HistoryAudit`` is what each run of the verifier found.
"""
from django.apps import apps
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from .canonical import GENESIS, diff


class HistoryContext(models.Model):
    """Who, from which request or job: one row per request that produced events."""

    created_at = models.DateTimeField(default=timezone.now)
    label = models.CharField(max_length=255, blank=True, help_text="The request (method and path), the task, or shell")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="history_contexts"
    )
    user_name = models.CharField(
        max_length=150, blank=True, help_text="The username at the time, or the operating-system user of a shell write"
    )

    class Meta:
        db_table = "history_context"

    def __str__(self):
        return f"{self.label} by {self.user_name or 'nobody'} at {self.created_at:%Y-%m-%d %H:%M}"

    @property
    def who(self):
        return self.user_name or (self.user.get_username() if self.user_id and self.user else "")


class HistoryEvent(models.Model):
    """One change to one tracked record."""

    SNAPSHOT = "snapshot"
    BEFORE_DELETE = "before_delete"
    LABELS = ((SNAPSHOT, "snapshot"), (BEFORE_DELETE, "before delete"))

    seq = models.BigIntegerField(primary_key=True, help_text="Contiguous across all events; the ledger order")
    model = models.CharField(max_length=100, help_text='The record\'s model, as "persons.attendee"')
    object_id = models.CharField(max_length=36, help_text="The record's key as text")
    label = models.CharField(max_length=20, choices=LABELS)
    created_at = models.DateTimeField()
    context = models.ForeignKey(HistoryContext, null=True, blank=True, on_delete=models.PROTECT, related_name="events")
    snapshot = models.JSONField(help_text="The whole record: column name to value, foreign keys as ids")
    prev_mac = models.CharField(max_length=64)
    mac = models.CharField(max_length=64)

    class Meta:
        db_table = "history_event"
        ordering = ("seq",)
        indexes = [
            models.Index(fields=["model", "object_id", "seq"], name="history_event_record"),
            models.Index(fields=["created_at"], name="history_event_created_at"),
        ]
        permissions = [("restore_historyevent", "Can restore a record to a version in its history")]

    def __str__(self):
        return f"#{self.seq} {self.label} {self.model} {self.object_id}"

    @property
    def model_class(self):
        return apps.get_model(self.model)

    @property
    def instance(self):
        """The snapshot as an unsaved instance of its model, foreign keys as ids."""
        return hydrate(self.model_class, self.snapshot)

    def previous(self):
        return HistoryEvent.objects.filter(model=self.model, object_id=self.object_id, seq__lt=self.seq).order_by("-seq").first()

    def changes(self):
        """What this event changed against the record's previous event."""
        before = self.previous()
        return diff(before.snapshot if before else {}, self.snapshot)

    def restore(self):
        """Put the record back as this snapshot has it, through the normal save path.

        The save is itself recorded, with who did it, like any other write.
        A hard-deleted record is created again under its old key.
        """
        model = self.model_class
        instance = self.instance
        instance._state.adding = not model._base_manager.filter(pk=instance.pk).exists()
        instance.save()
        return instance


class HistoryHead(models.Model):
    """The tail of the chain: the one row the writer locks before it extends the ledger."""

    seq = models.BigIntegerField(default=0)
    mac = models.CharField(max_length=64, default=GENESIS)

    class Meta:
        db_table = "history_head"

    def __str__(self):
        return f"head at {self.seq}"


class HistoryAudit(models.Model):
    """What one run of the verifier found."""

    created_at = models.DateTimeField(default=timezone.now)
    ok = models.BooleanField()
    full = models.BooleanField(help_text="Whole chain and replay, or only the events since the last clean run")
    events = models.BigIntegerField(help_text="Events checked")
    head_seq = models.BigIntegerField()
    head_mac = models.CharField(max_length=64)
    first_bad_seq = models.BigIntegerField(null=True, blank=True)
    report = models.TextField(blank=True)

    class Meta:
        db_table = "history_audit"
        ordering = ("-created_at",)

    def __str__(self):
        return f"{'clean' if self.ok else 'FAILED'} at {self.created_at:%Y-%m-%d %H:%M} up to {self.head_seq}"


def hydrate(model, snapshot):
    """An unsaved ``model`` instance holding ``snapshot``; keys the model no longer has are ignored."""
    instance = model()
    for field in model._meta.concrete_fields:
        if field.attname not in snapshot:
            continue
        value = snapshot[field.attname]
        if value is not None:
            try:
                value = field.to_python(value)
            except (ValidationError, TypeError, ValueError):
                pass  # keep the stored value rather than lose it
        setattr(instance, field.attname, value)
    return instance
