from uuid import uuid4
from django.db import models
from model_utils.models import SoftDeletableModel, TimeStampedModel

from attendees.persons.models import Utility
from attendees.history import track
from attendees.history.querysets import TrackedSoftDeletable


@track
class Folk(TrackedSoftDeletable, TimeStampedModel, SoftDeletableModel):
    """
    Model function as Family (category # 0) or other relationship (category # 25).

    For other relationship, primary attendee needs to be "hidden" role
    """
    id = models.UUIDField(default=uuid4, primary_key=True, editable=False, serialize=False)
    division = models.ForeignKey(
        "whereabouts.Division",
        default=0,
        null=False,
        blank=False,
        on_delete=models.SET(0),
    )
    category = models.ForeignKey(
        "persons.Category",
        null=False,
        blank=False,
        default=0,
        on_delete=models.SET(0),
        help_text="subtype: for folk, 0 is family and 25 is other",
    )
    attendees = models.ManyToManyField(
        "persons.Attendee", through="FolkAttendee", related_name="attendees"
    )
    display_name = models.CharField(max_length=50, blank=True, null=True)
    display_order = models.SmallIntegerField(
        default=0, blank=False, null=False, db_index=True
    )
    infos = models.JSONField(
        null=True,
        blank=True,
        default=Utility.folk_infos,
        help_text='Example: {"print_directory": False}. Please keep {} here even no data',
    )

    def __str__(self):
        return "%s %s %s" % (self.division, self.category, self.display_name)

    class Meta:
        db_table = "persons_folks"
        ordering = ("division", "category", "display_order", "display_name", "-modified")
