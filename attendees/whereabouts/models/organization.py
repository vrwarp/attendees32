from django.contrib.contenttypes.fields import GenericRelation

from django.db import models
from model_utils.models import SoftDeletableModel, TimeStampedModel
from schedule.models import CalendarRelation

from attendees.occasions.models import Gathering
from attendees.persons.models import Note, Utility
from attendees.history import track
from attendees.history.querysets import TrackedSoftDeletable


@track
class Organization(TrackedSoftDeletable, TimeStampedModel, SoftDeletableModel, Utility):
    notes = GenericRelation(Note)
    calendar_relations = GenericRelation(CalendarRelation)
    gathering = GenericRelation(
        Gathering,
        object_id_field="site_id",
        content_type_field="site_type",
        related_query_name="organization",
    )
    id = models.BigAutoField(
        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
    )
    slug = models.SlugField(
        max_length=50,
        blank=False,
        null=False,
        unique=True,
        help_text="alphanumeric only",
    )
    display_name = models.CharField(max_length=50, blank=False, null=False)
    infos = models.JSONField(
        null=True,
        blank=True,
        default=Utility.organization_infos,
        help_text='Example: {"hostname": "where the app deployed"}. Please keep {} here even no data',
    )

    class Meta:
        db_table = "whereabouts_organizations"

    def __str__(self):
        return "%s" % self.display_name
