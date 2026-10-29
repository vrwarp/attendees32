from uuid import uuid4
import pghistory
import partial_date.fields
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from partial_date import PartialDateField
from django.contrib.postgres.indexes import GinIndex
from django.db import models
import django.utils.timezone
import model_utils.fields
from model_utils.models import SoftDeletableModel, TimeStampedModel

from . import Confidential, Utility  # , Note


class Past(Confidential, TimeStampedModel, SoftDeletableModel, Utility):
    """A note, status or education entry about a subject, usually an attendee.

    Who may read one is decided twice: by its category (a counseling note is for counselors, a
    coworker note for coworkers and counselors, the rest for anyone who may open the subject) and,
    within that, by ``Confidential``: a past with viewers is seen by those viewers only.
    """

    COUNSELING = "counseling"  # for private data, and only assigned counselors
    COWORKER = "coworker"  # for data of limited access for coworker & counselors
    # notes = GenericRelation(Note)
    id = models.UUIDField(default=uuid4, editable=False, primary_key=True, serialize=False)
    content_type = models.ForeignKey(
        ContentType, on_delete=models.CASCADE, null=False, blank=False
    )
    object_id = models.CharField(max_length=36, null=False, blank=False)
    subject = GenericForeignKey("content_type", "object_id")
    when = PartialDateField(blank=True, null=True, help_text='1998, 1998-12 or 1992-12-31, please enter 1800 if year not known')
    finish = models.DateTimeField(null=True, blank=True)
    category = models.ForeignKey(
        "persons.Category",
        null=False,
        blank=False,
        on_delete=models.SET(0),
        help_text="subtype: for education it's primary/high/college sub-types etc",
    )
    display_order = models.SmallIntegerField(
        default=30000, blank=False, null=False, db_index=True
    )
    display_name = models.CharField(max_length=50, blank=True, null=True)
    organization = models.ForeignKey(
        "whereabouts.Organization", null=False, blank=False, on_delete=models.SET(0)
    )
    infos = models.JSONField(
        null=True,
        blank=True,
        default=Utility.relationship_infos,
        help_text='Example: {"comment": "..."}. Please keep {} here even no data',
    )

    class Meta:
        db_table = "persons_pasts"
        ordering = (
            "organization",
            "category__type",
            "display_order",
            "category__display_order",
            "when",
        )
        indexes = [
            models.Index(
                fields=["content_type", "object_id"],
                condition=models.Q(is_removed=False),
                name="past_subjects",
            ),
            GinIndex(
                fields=["infos"],
                name="past_infos_gin",
            ),
        ]

    def __str__(self):
        return "%s %s %s" % (self.subject, self.category, self.display_name)


class PastsHistory(pghistory.get_event_model(
    Past,
    pghistory.Snapshot('past.snapshot'),
    pghistory.BeforeDelete('past.before_delete'),
    name='PastsHistory',
    related_name='history',
)):
    pgh_id = models.BigAutoField(primary_key=True, serialize=False)
    pgh_created_at = models.DateTimeField(auto_now_add=True)
    pgh_label = models.TextField(help_text='The event label.')
    created = model_utils.fields.AutoCreatedField(default=django.utils.timezone.now, editable=False, verbose_name='created')
    modified = model_utils.fields.AutoLastModifiedField(default=django.utils.timezone.now, editable=False, verbose_name='modified')
    is_removed = models.BooleanField(default=False)
    pgh_obj = models.ForeignKey(db_constraint=False, on_delete=models.deletion.DO_NOTHING, related_name='history', to='persons.past')
    id = models.UUIDField(db_index=True, default=uuid4, editable=False, serialize=False)
    object_id = models.CharField(max_length=36)
    display_order = models.SmallIntegerField(default=30000)
    infos = models.JSONField(blank=True, default=Utility.relationship_infos, help_text='Example: {"comment": "..."}. Please keep {} here even no data', null=True)
    category = models.ForeignKey(db_constraint=False, help_text="subtype: for education it's primary/high/college sub-types etc", on_delete=models.deletion.DO_NOTHING, related_name='+', related_query_name='+', to='persons.category')
    content_type = models.ForeignKey(db_constraint=False, on_delete=models.deletion.DO_NOTHING, related_name='+', related_query_name='+', to='contenttypes.contenttype')
    organization = models.ForeignKey(db_constraint=False, on_delete=models.deletion.DO_NOTHING, related_name='+', related_query_name='+', to='whereabouts.organization')
    when = partial_date.fields.PartialDateField(blank=True, help_text='1998, 1998-12 or 1992-12-31, please enter 1800 if year not known', null=True)
    finish = models.DateTimeField(blank=True, null=True)
    display_name = models.CharField(blank=True, max_length=50, null=True)
    pgh_context = models.ForeignKey(db_constraint=False, null=True, on_delete=models.deletion.DO_NOTHING, related_name='+', to='pghistory.context')

    class Meta:
        db_table = 'persons_pastshistory'
