from django.contrib.contenttypes.fields import GenericRelation
from django.core.exceptions import ValidationError
from django.db import models
from django.urls import reverse
from django.utils.functional import cached_property
from model_utils.models import SoftDeletableModel, TimeStampedModel
from private_storage.fields import PrivateFileField

from attendees.persons.models import Note, Searchable, Utility
from attendees.history import track
from attendees.history.querysets import TrackedSoftDeletable


@track
class Attendance(TrackedSoftDeletable, Searchable, TimeStampedModel, SoftDeletableModel, Utility):
    notes = GenericRelation(Note)
    id = models.BigAutoField(
        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
    )
    start = models.DateTimeField(null=True, blank=True, help_text="optional", db_index=True)
    finish = models.DateTimeField(null=True, blank=True, help_text="optional", db_index=True)
    gathering = models.ForeignKey(
        "Gathering", null=False, blank=False, on_delete=models.SET(0)
    )
    team = models.ForeignKey(
        "Team",
        default=None,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        help_text="empty for main meet",
    )
    attending = models.ForeignKey(
        "persons.Attending", null=False, blank=False, on_delete=models.SET(0)
    )
    character = models.ForeignKey(
        "Character", null=False, blank=False, on_delete=models.SET(0)
    )
    # free = models.SmallIntegerField(
    #     default=0,
    #     blank=True,
    #     null=True,
    #     help_text="multitasking: the person cannot join other gatherings if negative",
    # )
    category = models.ForeignKey(
        "persons.Category",
        default=1,  # scheduled
        blank=False,
        null=False,
        on_delete=models.SET(1),
        help_text="RSVPed, leave, remote, etc",
    )
    display_order = models.SmallIntegerField(default=0, blank=False, null=False)
    infos = models.JSONField(
        null=True,
        blank=True,
        default=dict,
        help_text='Example: {"kid_points": 5}. Please keep {} here even no data',
    )
    file = PrivateFileField(
        "file", blank=True, null=True, upload_to="attendance_file"
    )  # https://github.com/edoburu/django-private-storage

    def clean(self):
        if (
            self.character.assembly != self.gathering.meet.assembly
            or self.gathering.meet not in self.attending.meets.all()
        ):
            raise ValidationError(
                "The character assembly, gathering's meet/assembly, and attendings meets needed to be matched,"
                "please pick another gathering, character or attending"
            )

    @cached_property
    def attendance_info(self):
        gathering = self.gathering
        return gathering.meet.display_name + gathering.start.strftime(" @ %b.%d'%y")

    def get_absolute_url(self):
        return reverse("attendance_detail", args=[str(self.id)])

    # @property
    # def gathering_label(self):
    #     return f'{self.gathering.meet.display_name} {self.gathering.display_name}'

    @property
    def attendance_label(self):
        return f"{self.attending.attendee.display_label}-{self.attending.main_contact.display_label}"

    # @property
    # def team_label(self):
    #     return self.team.display_name

    # @property
    # def character_label(self):
    #     return self.character.display_name

    class Meta:
        db_table = "occasions_attendances"
        constraints = [
            models.UniqueConstraint(
                fields=["gathering", "attending", "character", "team", "start"],
                condition=models.Q(is_removed=False),
                name="gathering_attending_character_team_start",
            )
        ]

    def __str__(self):
        return "%s %s %s %s" % (
            self.gathering,
            self.character,
            self.attending,
            self.team or "",
        )
