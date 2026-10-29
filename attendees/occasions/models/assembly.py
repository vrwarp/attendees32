from django.contrib.contenttypes.fields import GenericRelation
from django.db import models
from django.urls import reverse
from model_utils.models import SoftDeletableModel, TimeStampedModel

from attendees.persons.models import Note, Utility
from attendees.history import track
from attendees.history.querysets import TrackedSoftDeletable


@track
class Assembly(TrackedSoftDeletable, TimeStampedModel, SoftDeletableModel, Utility):
    notes = GenericRelation(Note)
    id = models.BigAutoField(
        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
    )
    start = models.DateTimeField(null=True, blank=True, help_text="optional")
    finish = models.DateTimeField(null=True, blank=True, help_text="optional")
    category = models.ForeignKey(
        "persons.Category",
        null=False,
        blank=False,
        default=33,  # public
        on_delete=models.deletion.DO_NOTHING,
        help_text="normal, no-display, etc",
    )
    display_name = models.CharField(
        max_length=50,
        blank=False,
        null=False,
        help_text="Uniq within Organization, adding year helps",
    )
    display_order = models.SmallIntegerField(default=0, blank=False, null=False)
    slug = models.SlugField(
        max_length=50,
        blank=False,
        null=False,
        unique=True,
        help_text="format: Organization_name-Assembly_name",
    )
    division = models.ForeignKey(
        "whereabouts.Division", null=False, blank=False, on_delete=models.SET(0)
    )
    infos = models.JSONField(
        default=dict,
        null=True,
        blank=True,
        help_text='example: {"need_age": 18}, please keep {} here even there\'s no data',
    )

    def get_absolute_url(self):  # Todo: probably not needed, please remove it when upgrade
        return reverse("assembly_detail", args=[str(self.id)])

    class Meta:
        db_table = "occasions_assemblies"
        verbose_name_plural = "Assemblies"
        ordering = (
            "division",
            "display_order",
        )

    def __str__(self):
        return "%s" % self.display_name

    def get_addresses(self):
        return "\n".join([a.street for a in self.places.all() if a is not None])


# Todo 20210718 add uniq at save:  within organization, the display_name should be uniq for grouped dropdown
