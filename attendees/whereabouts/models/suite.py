from django.contrib.contenttypes.fields import GenericRelation
from django.db import models
from django.urls import reverse
from model_utils.models import SoftDeletableModel, TimeStampedModel
from schedule.models import CalendarRelation

from attendees.occasions.models import Gathering
from attendees.persons.models import Note, Utility
from attendees.history import track
from attendees.history.querysets import TrackedSoftDeletable


@track
class Suite(TrackedSoftDeletable, TimeStampedModel, SoftDeletableModel, Utility):
    notes = GenericRelation(Note)
    calendar_relations = GenericRelation(CalendarRelation)
    gathering = GenericRelation(
        Gathering,
        object_id_field="site_id",
        content_type_field="site_type",
        related_query_name="suite",
    )
    id = models.BigAutoField(
        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
    )
    display_name = models.CharField(
        max_length=50, blank=False, null=False, db_index=True
    )
    slug = models.SlugField(max_length=50, blank=False, null=False, unique=True)
    property = models.ForeignKey("Property", null=True, on_delete=models.SET_NULL)
    site = models.CharField(max_length=50, blank=True, null=True, help_text="2F floor, etc")

    class Meta:
        db_table = "whereabouts_suites"

    def get_absolute_url(self):
        return reverse("suite_detail", args=[str(self.id)])

    def __str__(self):
        return "%s %s %s" % (
            self.property.display_name,
            self.display_name,
            self.site or "",
        )
