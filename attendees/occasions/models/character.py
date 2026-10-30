from django.contrib.contenttypes.fields import GenericRelation
from django.db import models
from django.urls import reverse
from model_utils.models import SoftDeletableModel, TimeStampedModel

from attendees.persons.models import Note, Utility
from attendees.history import track
from attendees.history.querysets import TrackedSoftDeletable


@track
class Character(TrackedSoftDeletable, TimeStampedModel, SoftDeletableModel, Utility):
    notes = GenericRelation(Note)
    id = models.BigAutoField(
        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
    )
    assembly = models.ForeignKey(
        "Assembly", on_delete=models.SET(0), null=False, blank=False
    )
    display_name = models.CharField(
        max_length=50, blank=True, null=False, db_index=True
    )
    display_order = models.SmallIntegerField(default=0, blank=False, null=False)
    slug = models.SlugField(
        max_length=50,
        blank=False,
        null=False,
        unique=True,
        help_text="format: Assembly_name-Character_name",
    )
    infos = models.JSONField(blank=True, default=dict, help_text='example: {"info": "for distrubuting food"}, please keep {} here even there\'s no data', null=True)
    type = models.CharField(max_length=50, null=False, default="normal", db_index=True)

    def get_absolute_url(self):  # Todo: probably not needed, please remove it when upgrade
        return reverse("character_detail", args=[str(self.id)])

    class Meta:
        db_table = "occasions_characters"
        ordering = ["assembly", "display_order"]

    def __str__(self):
        return "%s %s %s" % (self.assembly, self.display_name, self.type)
