from uuid import uuid4
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from partial_date import PartialDateField
from django.db import models
from model_utils.models import SoftDeletableModel, TimeStampedModel

from . import Confidential, Utility  # , Note
from attendees.history import track
from attendees.history.querysets import TrackedSoftDeletable


@track
class Past(TrackedSoftDeletable, Confidential, TimeStampedModel, SoftDeletableModel, Utility):
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
        ]

    def __str__(self):
        return "%s %s %s" % (self.subject, self.category, self.display_name)
