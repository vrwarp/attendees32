from django.core.exceptions import ValidationError
from django.db import models
from model_utils.models import SoftDeletableModel, TimeStampedModel

from . import Searchable, Utility
from attendees.history import track
from attendees.history.querysets import TrackedSoftDeletable


@track
class AttendingMeet(TrackedSoftDeletable, Searchable, TimeStampedModel, SoftDeletableModel, Utility):
    """
    Served as a partial template for attendance
    """

    id = models.BigAutoField(
        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
    )
    attending = models.ForeignKey(
        "Attending", on_delete=models.SET(0), null=False, blank=False
    )
    meet = models.ForeignKey(
        "occasions.Meet", on_delete=models.SET(0), null=False, blank=False
    )
    start = models.DateTimeField(
        null=False, blank=False, db_index=True, default=Utility.now_with_timezone
    )
    finish = models.DateTimeField(
        null=False,
        blank=False,
        db_index=True,
        help_text="Required for user to filter by time",
    )
    team = models.ForeignKey(
        "occasions.Team",
        default=None,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        help_text="empty for main meet",
    )
    character = models.ForeignKey(
        "occasions.Character", null=False, blank=False, on_delete=models.SET(0)
    )

    category = models.ForeignKey(
        "persons.Category",
        default=1,  # scheduled
        blank=False,
        null=False,
        on_delete=models.SET(1),
        help_text="primary, secondary, etc (primary will be displayed first)",
    )
    infos = models.JSONField(
        null=True,
        blank=True,
        default=dict,
        help_text='Example: {"kid_points": 5, "pdf_folks": ["uuid1"]}. Please keep {} here even no data',
    )

    def clean(self):
        if (
            not self.meet.assembly
            == self.character.assembly
        ):
            raise ValidationError(
                "The attending meet's assembly and character's assembly needed to be the same, "
                "please pick another character or meet "
            )

    class Meta:
        db_table = "persons_attending_meets"
        constraints = [
            models.UniqueConstraint(
                fields=["meet", "attending", "character", "team"],
                condition=models.Q(is_removed=False),
                name="attending_meet_uniq",
            )
        ]

    def __str__(self):
        return "%s %s" % (self.attending, self.meet)

    @staticmethod
    def check_participation_of(attendee, meet):
        return AttendingMeet.objects.filter(
                meet=meet,
                attending__attendee=attendee,
                finish__gte=Utility.now_with_timezone()
        ).exists()
