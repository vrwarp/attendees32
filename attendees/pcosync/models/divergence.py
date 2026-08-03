from uuid import uuid4

import django.utils.timezone
import model_utils.fields
import pghistory
from django.conf import settings
from django.db import models
from model_utils.models import SoftDeletableModel, TimeStampedModel


class PcoDivergence(TimeStampedModel, SoftDeletableModel):
    """Something the two systems disagree about, for a person to settle.

    The vocabulary is borrowed from pcomirror's own divergence module, which
    names a difference by *where* it is rather than by what it is -- a pointer,
    the two values, and a sentence of plain language. An operator reading a
    pcomirror shadow report and this table is then reading the same kind of
    thing.

    Its posture is borrowed too: a diagnostic, and only a diagnostic. Nothing
    here repairs what it finds. Resolution is a separate act, performed by a
    human, and it works by moving a baseline rather than by queueing a write.
    """

    FIELD_CONFLICT = "field_conflict"
    WOULD_WRITE = "would_write"
    UNLINKED_PERSON = "unlinked_person"
    UNLINKED_ATTENDEE = "unlinked_attendee"
    AMBIGUOUS_PERSON = "ambiguous_person"
    MERGE_FOLLOWED = "merge_followed"
    MERGE_COLLISION = "merge_collision"
    PERSON_GONE = "person_gone"
    WRITE_INDETERMINATE = "write_indeterminate"
    WRITE_REFUSED = "write_refused"
    NOT_REPRESENTABLE = "not_representable"
    UNMAPPED_CONGREGATION = "unmapped_congregation"
    LOCAL_CONTRADICTION = "local_contradiction"
    VALUE_TOO_LONG = "value_too_long"
    CONFIG_MISSING_FIELD = "config_missing_field"
    HOUSEHOLD_CONFLICT = "household_conflict"
    HOUSEHOLD_MEMBERSHIP_REMOVED = "household_membership_removed"
    UNHYDRATED = "unhydrated"
    BUDGET_EXHAUSTED = "budget_exhausted"
    MIRROR_STALE = "mirror_stale"

    INFO, WARNING, ERROR = "info", "warning", "error"
    SEVERITIES = ((INFO, "info"), (WARNING, "warning"), (ERROR, "error"))

    OPEN = "open"
    KEEP_LOCAL = "keep_local"
    KEEP_PCO = "keep_pco"
    IGNORED = "ignored"
    RESOLVED_ELSEWHERE = "resolved_elsewhere"
    RESOLUTIONS = (
        (OPEN, "open"),
        (KEEP_LOCAL, "keep the attendees32 value"),
        (KEEP_PCO, "keep the Planning Center value"),
        (IGNORED, "stop reporting this field for this person"),
        (RESOLVED_ELSEWHERE, "went away on its own"),
    )

    id = models.UUIDField(
        default=uuid4, primary_key=True, editable=False, serialize=False
    )
    organization = models.ForeignKey(
        "whereabouts.Organization", default=0, null=False, blank=False,
        on_delete=models.SET(0),
    )
    run = models.ForeignKey(
        "pcosync.PcoSyncRun", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="divergences",
        help_text="the run that last saw it, not the one that opened it",
    )
    link = models.ForeignKey(
        "pcosync.PcoPersonLink", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="divergences",
    )
    attendee = models.ForeignKey(
        "persons.Attendee", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="pco_divergences",
    )
    pco_person_id = models.CharField(max_length=32, blank=True, db_index=True)

    kind = models.CharField(max_length=32, db_index=True)
    pointer = models.CharField(
        max_length=120,
        help_text='where the disagreement is, e.g. "$.person.first_name"',
    )
    #: Identity for the partial unique constraint below. Built by the service
    #: rather than the database because the parts differ by kind: a field
    #: conflict is identified by its person and pointer, an unmatched attendee
    #: has no PCO person at all, and Postgres treats NULLs as distinct, which
    #: would quietly let duplicates through.
    dedupe_key = models.CharField(max_length=160, db_index=True)
    label = models.CharField(max_length=120, blank=True)
    local_value = models.JSONField(null=True, blank=True)
    pco_value = models.JSONField(null=True, blank=True)
    baseline_value = models.JSONField(null=True, blank=True)
    suggestion = models.JSONField(
        default=dict, blank=True,
        help_text="ranked match candidates, for an unmatched Planning Center person",
    )
    note = models.TextField(blank=True)
    severity = models.CharField(max_length=8, default=WARNING, choices=SEVERITIES)

    resolution = models.CharField(
        max_length=20, default=OPEN, choices=RESOLUTIONS, db_index=True
    )
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    first_seen_at = models.DateTimeField(null=True, blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    infos = models.JSONField(default=dict, blank=True)

    def __str__(self):
        return f"{self.kind} {self.pointer} ({self.resolution})"

    @staticmethod
    def build_dedupe_key(pointer, pco_person_id=None, attendee_id=None):
        return f"{pco_person_id or ''}|{attendee_id or ''}|{pointer}"[:160]

    class Meta:
        db_table = "pcosync_divergences"
        ordering = ("-severity", "kind", "pointer")
        constraints = [
            # An unresolved disagreement is one row, refreshed each run. Without
            # this a weekly sync would grow a new row per week for the same
            # unanswered question, and the report would become unreadable
            # exactly when somebody finally sat down to work through it.
            models.UniqueConstraint(
                fields=["organization", "dedupe_key"],
                condition=models.Q(resolution="open", is_removed=False),
                name="pcosync_one_open_divergence",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "resolution", "kind"],
                name="pcosync_div_triage",
            ),
        ]


class PcoDivergencesHistory(pghistory.get_event_model(
    PcoDivergence,
    pghistory.Snapshot("pcodivergence.snapshot"),
    pghistory.BeforeDelete("pcodivergence.before_delete"),
    name="PcoDivergencesHistory",
    related_name="history",
)):
    pgh_id = models.BigAutoField(primary_key=True, serialize=False)
    pgh_created_at = models.DateTimeField(auto_now_add=True)
    pgh_label = models.TextField(help_text="The event label.")
    pgh_obj = models.ForeignKey(db_constraint=False, on_delete=models.deletion.DO_NOTHING, related_name="history", to="pcosync.pcodivergence")
    pgh_context = models.ForeignKey(db_constraint=False, null=True, on_delete=models.deletion.DO_NOTHING, related_name="+", to="pghistory.context")
    id = models.UUIDField(db_index=True, default=uuid4, editable=False, serialize=False)
    created = model_utils.fields.AutoCreatedField(default=django.utils.timezone.now, editable=False, verbose_name="created")
    modified = model_utils.fields.AutoLastModifiedField(default=django.utils.timezone.now, editable=False, verbose_name="modified")
    is_removed = models.BooleanField(default=False)
    organization = models.ForeignKey(db_constraint=False, default=0, on_delete=models.deletion.DO_NOTHING, related_name="+", related_query_name="+", to="whereabouts.organization")
    run = models.ForeignKey(blank=True, db_constraint=False, null=True, on_delete=models.deletion.DO_NOTHING, related_name="+", related_query_name="+", to="pcosync.pcosyncrun")
    link = models.ForeignKey(blank=True, db_constraint=False, null=True, on_delete=models.deletion.DO_NOTHING, related_name="+", related_query_name="+", to="pcosync.pcopersonlink")
    attendee = models.ForeignKey(blank=True, db_constraint=False, null=True, on_delete=models.deletion.DO_NOTHING, related_name="+", related_query_name="+", to="persons.attendee")
    resolved_by = models.ForeignKey(blank=True, db_constraint=False, null=True, on_delete=models.deletion.DO_NOTHING, related_name="+", related_query_name="+", to=settings.AUTH_USER_MODEL)
    pco_person_id = models.CharField(blank=True, max_length=32)
    kind = models.CharField(max_length=32)
    pointer = models.CharField(max_length=120)
    dedupe_key = models.CharField(max_length=160)
    label = models.CharField(blank=True, max_length=120)
    local_value = models.JSONField(blank=True, null=True)
    pco_value = models.JSONField(blank=True, null=True)
    baseline_value = models.JSONField(blank=True, null=True)
    suggestion = models.JSONField(blank=True, default=dict)
    note = models.TextField(blank=True)
    severity = models.CharField(default=PcoDivergence.WARNING, max_length=8)
    resolution = models.CharField(default=PcoDivergence.OPEN, max_length=20)
    resolved_at = models.DateTimeField(blank=True, null=True)
    first_seen_at = models.DateTimeField(blank=True, null=True)
    last_seen_at = models.DateTimeField(blank=True, null=True)
    infos = models.JSONField(blank=True, default=dict)

    class Meta:
        db_table = "pcosync_divergenceshistory"
