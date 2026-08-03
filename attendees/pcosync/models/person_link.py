from uuid import uuid4

import django.utils.timezone
import model_utils.fields
import pghistory
from django.contrib.postgres.indexes import GinIndex
from django.db import models
from model_utils.models import SoftDeletableModel, TimeStampedModel


class PcoPersonLink(TimeStampedModel, SoftDeletableModel):
    """What attendees32 knows about one Planning Center person.

    Deliberately not a column on ``Attendee`` and not a corner of
    ``Attendee.infos``, for three reasons that get worse in that order:

    1. ``Attendee`` is pghistory-tracked with a snapshot on every save. Sync
       bookkeeping kept on the attendee would write a full history row per
       person per run, and an attendee's audit trail should read as a record of
       name changes, not of sync heartbeats.
    2. The baseline cannot live in ``infos`` at all. The merge reads
       ``infos["contacts"]`` as a *value*; a baseline stored beside it would end
       up being diffed against itself.
    3. A single column cannot express the states that actually occur -- a PCO
       person seen but matched to nobody, a merged-away id kept for provenance,
       a link to an attendee somebody soft-deleted.

    ``baseline`` is the load-bearing field: the compare-normalised value of each
    mapped field as of the last time the two systems agreed. Without it you can
    only see *that* two values differ, never *who moved*, and every automatic
    write becomes a guess.
    """

    #: Linked to a live Planning Center person.
    LIVE = "live"
    #: The PCO person was merged away; ``merged_into_pco_id`` names the survivor.
    MERGED = "merged"
    #: The PCO person is gone with no forwarding address.
    GONE = "gone"
    #: Seen in Planning Center but not yet matched to an attendee by a human.
    UNCONFIRMED = "unconfirmed"

    STATES = (
        (LIVE, "live"),
        (MERGED, "merged"),
        (GONE, "gone"),
        (UNCONFIRMED, "unconfirmed"),
    )

    #: Matched by the attendees_uuid custom field: the only exact join.
    BY_UUID = "uuid"
    #: Matched by a human choosing from the divergence report.
    BY_MATCH = "match"
    CREATED_HERE = "created_here"
    CREATED_THERE = "created_there"

    LINK_SOURCES = (
        (BY_UUID, "attendees_uuid custom field"),
        (BY_MATCH, "chosen by a person"),
        (CREATED_HERE, "created in attendees32"),
        (CREATED_THERE, "created in Planning Center"),
    )

    id = models.UUIDField(
        default=uuid4, primary_key=True, editable=False, serialize=False
    )
    organization = models.ForeignKey(
        "whereabouts.Organization",
        default=0,
        null=False,
        blank=False,
        on_delete=models.SET(0),
    )
    attendee = models.ForeignKey(
        "persons.Attendee",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="pco_links",
        help_text="null while a Planning Center person waits to be matched",
    )
    pco_person_id = models.CharField(max_length=32, db_index=True)
    state = models.CharField(
        max_length=16, default=LIVE, choices=STATES, db_index=True
    )
    link_source = models.CharField(
        max_length=16, default=BY_UUID, choices=LINK_SOURCES
    )
    merged_into_pco_id = models.CharField(max_length=32, null=True, blank=True)
    baseline = models.JSONField(
        default=dict,
        blank=True,
        help_text="{field_key: value} as of the last time both sides agreed. "
                  "Written only on agreement or a write that succeeded.",
    )
    baseline_synced_at = models.DateTimeField(null=True, blank=True)
    field_datum_ids = models.JSONField(
        default=dict,
        blank=True,
        help_text='{slug: field_datum_id}, so a PATCH knows which datum row to hit',
    )
    pco_updated_at = models.DateTimeField(null=True, blank=True)
    infos = models.JSONField(
        default=dict,
        blank=True,
        help_text='Example: {"ignored_fields": ["gender"]}. Please keep {} here '
                  "even no data",
    )

    def __str__(self):
        return f"{self.attendee or 'unmatched'} <-> PCO {self.pco_person_id}"

    @property
    def ignored_fields(self):
        return set(self.infos.get("ignored_fields") or [])

    class Meta:
        db_table = "pcosync_person_links"
        ordering = ("organization", "pco_person_id")
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "pco_person_id"],
                condition=models.Q(is_removed=False),
                name="pcosync_org_pco_person",
            ),
            # Only live links are exclusive. A merged or gone link keeps its
            # attendee for provenance, and must not block the replacement.
            models.UniqueConstraint(
                fields=["organization", "attendee"],
                condition=models.Q(is_removed=False, state="live"),
                name="pcosync_org_attendee_live",
            ),
        ]
        indexes = [
            GinIndex(fields=["baseline"], name="pcosync_link_baseline_gin"),
        ]


class PcoPersonLinksHistory(pghistory.get_event_model(
    PcoPersonLink,
    pghistory.Snapshot("pcopersonlink.snapshot"),
    pghistory.BeforeDelete("pcopersonlink.before_delete"),
    name="PcoPersonLinksHistory",
    related_name="history",
)):
    pgh_id = models.BigAutoField(primary_key=True, serialize=False)
    pgh_created_at = models.DateTimeField(auto_now_add=True)
    pgh_label = models.TextField(help_text="The event label.")
    pgh_obj = models.ForeignKey(db_constraint=False, on_delete=models.deletion.DO_NOTHING, related_name="history", to="pcosync.pcopersonlink")
    pgh_context = models.ForeignKey(db_constraint=False, null=True, on_delete=models.deletion.DO_NOTHING, related_name="+", to="pghistory.context")
    id = models.UUIDField(db_index=True, default=uuid4, editable=False, serialize=False)
    created = model_utils.fields.AutoCreatedField(default=django.utils.timezone.now, editable=False, verbose_name="created")
    modified = model_utils.fields.AutoLastModifiedField(default=django.utils.timezone.now, editable=False, verbose_name="modified")
    is_removed = models.BooleanField(default=False)
    organization = models.ForeignKey(db_constraint=False, default=0, on_delete=models.deletion.DO_NOTHING, related_name="+", related_query_name="+", to="whereabouts.organization")
    attendee = models.ForeignKey(blank=True, db_constraint=False, null=True, on_delete=models.deletion.DO_NOTHING, related_name="+", related_query_name="+", to="persons.attendee")
    pco_person_id = models.CharField(max_length=32)
    state = models.CharField(default=PcoPersonLink.LIVE, max_length=16)
    link_source = models.CharField(default=PcoPersonLink.BY_UUID, max_length=16)
    merged_into_pco_id = models.CharField(blank=True, max_length=32, null=True)
    baseline = models.JSONField(blank=True, default=dict)
    baseline_synced_at = models.DateTimeField(blank=True, null=True)
    field_datum_ids = models.JSONField(blank=True, default=dict)
    pco_updated_at = models.DateTimeField(blank=True, null=True)
    infos = models.JSONField(blank=True, default=dict)

    class Meta:
        db_table = "pcosync_person_linkshistory"
