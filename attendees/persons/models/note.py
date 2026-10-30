from uuid import uuid4
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from model_utils.models import SoftDeletableModel, TimeStampedModel

from attendees.persons.models import Confidential, Utility
from attendees.history import track
from attendees.history.querysets import TrackedSoftDeletable


@track
class Note(TrackedSoftDeletable, Confidential, TimeStampedModel, SoftDeletableModel):
    COUNSELING = "counseling"  # for private data, and only assigned counselors

    id = models.UUIDField(default=uuid4, editable=False, primary_key=True, serialize=False)
    content_type = models.ForeignKey(ContentType, on_delete=models.SET(0))
    object_id = models.CharField(max_length=36)
    content_object = GenericForeignKey("content_type", "object_id")
    category = models.ForeignKey(
        "persons.Category",
        null=False,
        blank=False,
        on_delete=models.SET(0),
        help_text="subtype: for note it's public/counseling sub-types etc",
    )
    organization = models.ForeignKey(
        "whereabouts.Organization", null=False, blank=False, on_delete=models.SET(0)
    )
    display_order = models.SmallIntegerField(default=0, blank=False, null=False)
    body = models.TextField()
    infos = models.JSONField(
        null=True,
        blank=True,
        default=Utility.relationship_infos,
        help_text='Example: {"owner": "John"}. Please keep {} here even no data',
    )

    def __str__(self):
        return "%s %s %s" % (self.content_type, self.content_object, self.category)

    class Meta:
        db_table = "persons_notes"
        ordering = (
            "organization",
            "category",
            "content_type",
            "object_id",
            "display_order",
            "-modified",
        )
        indexes = [
            models.Index(
                fields=["content_type", "object_id"],
                condition=models.Q(is_removed=False),
                name="note_content_objects",
            ),
        ]

    # @property
    # def iso_updated_at(self):
    #     return self.modified.isoformat()
