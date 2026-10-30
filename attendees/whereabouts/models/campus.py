from django.contrib.contenttypes.fields import GenericRelation
from django.db import models
from django.urls import reverse
from model_utils.models import SoftDeletableModel, TimeStampedModel
from schedule.models import CalendarRelation

from attendees.occasions.models import Gathering
from attendees.persons.models import Note, Utility
from attendees.whereabouts.models import Organization
from attendees.history import track
from attendees.history.querysets import TrackedSoftDeletable


@track
class Campus(TrackedSoftDeletable, TimeStampedModel, SoftDeletableModel, Utility):
    notes = GenericRelation(Note)
    calendar_relations = GenericRelation(CalendarRelation)
    gathering = GenericRelation(
        Gathering,
        object_id_field="site_id",
        content_type_field="site_type",
        related_query_name="campus",
    )
    id = models.BigAutoField(
        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
    )
    organization = models.ForeignKey(
        Organization,
        verbose_name="used by",
        null=False,
        blank=False,
        on_delete=models.SET(0),
        help_text="which organization use this?",
    )
    display_name = models.CharField(
        max_length=50, blank=False, null=False, db_index=True
    )
    slug = models.SlugField(max_length=50, blank=False, null=False, unique=True)
    infos = models.JSONField(
        null=True,
        blank=True,
        default=dict,
        help_text='Example: {"hostname": "where the app deployed"}. Please keep {} here even no data',
    )

    class Meta:
        db_table = "whereabouts_campuses"
        verbose_name_plural = "Campuses"

    def get_absolute_url(self):
        return reverse("campus_detail", args=[str(self.id)])

    def __str__(self):
        return "%s" % self.display_name
