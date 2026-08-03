from uuid import uuid4

import django.utils.timezone
import model_utils.fields
import pghistory
from django.db import models
from model_utils.models import SoftDeletableModel, TimeStampedModel


class PcoHouseholdLink(TimeStampedModel, SoftDeletableModel):
    """Which ``Folk`` corresponds to which Planning Center household.

    People have ``attendees_uuid`` to join on. Households have nothing -- PCO
    has no custom-field tab for them -- so this table *is* the join key, and the
    only way to establish a row is co-membership: the set of linkable people in
    the PCO household must match a family's members exactly.

    That bar is deliberately high. A household is the widest thing this sync
    writes, and a join that is wrong by one person merges two families' directory
    entries. Anything short of exact agreement is reported instead of guessed.
    """

    LIVE = "live"
    GONE = "gone"
    STATES = ((LIVE, "live"), (GONE, "gone"))

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
    folk = models.ForeignKey(
        "persons.Folk",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="pco_links",
    )
    pco_household_id = models.CharField(max_length=32, db_index=True)
    state = models.CharField(
        max_length=16, default=LIVE, choices=STATES, db_index=True
    )
    baseline = models.JSONField(
        default=dict,
        blank=True,
        help_text='{"name": str, "members": {pco_person_id: household_role}} '
                  "as of the last agreement",
    )
    baseline_synced_at = models.DateTimeField(null=True, blank=True)
    infos = models.JSONField(default=dict, blank=True)

    def __str__(self):
        return f"{self.folk or 'unmatched'} <-> PCO household {self.pco_household_id}"

    class Meta:
        db_table = "pcosync_household_links"
        ordering = ("organization", "pco_household_id")
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "pco_household_id"],
                condition=models.Q(is_removed=False),
                name="pcosync_org_pco_household",
            ),
        ]


class PcoHouseholdLinksHistory(pghistory.get_event_model(
    PcoHouseholdLink,
    pghistory.Snapshot("pcohouseholdlink.snapshot"),
    pghistory.BeforeDelete("pcohouseholdlink.before_delete"),
    name="PcoHouseholdLinksHistory",
    related_name="history",
)):
    pgh_id = models.BigAutoField(primary_key=True, serialize=False)
    pgh_created_at = models.DateTimeField(auto_now_add=True)
    pgh_label = models.TextField(help_text="The event label.")
    pgh_obj = models.ForeignKey(db_constraint=False, on_delete=models.deletion.DO_NOTHING, related_name="history", to="pcosync.pcohouseholdlink")
    pgh_context = models.ForeignKey(db_constraint=False, null=True, on_delete=models.deletion.DO_NOTHING, related_name="+", to="pghistory.context")
    id = models.UUIDField(db_index=True, default=uuid4, editable=False, serialize=False)
    created = model_utils.fields.AutoCreatedField(default=django.utils.timezone.now, editable=False, verbose_name="created")
    modified = model_utils.fields.AutoLastModifiedField(default=django.utils.timezone.now, editable=False, verbose_name="modified")
    is_removed = models.BooleanField(default=False)
    organization = models.ForeignKey(db_constraint=False, default=0, on_delete=models.deletion.DO_NOTHING, related_name="+", related_query_name="+", to="whereabouts.organization")
    folk = models.ForeignKey(blank=True, db_constraint=False, null=True, on_delete=models.deletion.DO_NOTHING, related_name="+", related_query_name="+", to="persons.folk")
    pco_household_id = models.CharField(max_length=32)
    state = models.CharField(default=PcoHouseholdLink.LIVE, max_length=16)
    baseline = models.JSONField(blank=True, default=dict)
    baseline_synced_at = models.DateTimeField(blank=True, null=True)
    infos = models.JSONField(blank=True, default=dict)

    class Meta:
        db_table = "pcosync_household_linkshistory"
