from datetime import datetime
from django.contrib.contenttypes.fields import GenericForeignKey, GenericRelation
from django.contrib.contenttypes.models import ContentType
import pytz
from django.db import models
from django.db.models import Q
from django.urls import reverse
from django.conf import settings
from model_utils.models import SoftDeletableModel, TimeStampedModel
from schedule.models import EventRelation

from attendees.persons.models import Note, Utility

from .meet_allowed_model import MeetAllowedModel
from attendees.history import track
from attendees.history.querysets import TrackedSoftDeletable


@track
class Meet(TrackedSoftDeletable, TimeStampedModel, SoftDeletableModel, Utility):
    """
    Event is related by EventRelation with distinction 'source'.  The site_id/type here is just
    default, should copy to Event description as 'room#42', so one meet can have multiple Events
    happening at different sites.  WARNING: if multiple source events associated with a single
    meet, attendances will be generated for all source events!
    code usage: ContentType.objects.get(model='room').model_class().objects.get(pk=1)

    """

    notes = GenericRelation(Note)
    event_relations = GenericRelation(EventRelation)
    id = models.BigAutoField(
        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
    )
    assembly = models.ForeignKey(
        "occasions.Assembly", null=True, blank=True, on_delete=models.SET_NULL
    )
    attendings = models.ManyToManyField(
        "persons.Attending", through="persons.AttendingMeet", related_name="attendings"
    )
    major_character = models.ForeignKey(
        "occasions.Character", null=True, blank=True, on_delete=models.SET_NULL
    )
    shown_audience = models.BooleanField(
        "show AttendingMeet to participant?",
        null=False,
        blank=False,
        db_index=True,
        default=True,
        help_text="[some meets are only for internal records] show the AttendingMeet to attendee?",
    )
    audience_editable = models.BooleanField(
        "participant can edit AttendingMeet?",
        null=False,
        blank=False,
        default=True,
        help_text="[some meets are editable only by coworkers] participant can edit AttendingMeet?",
    )
    start = models.DateTimeField(
        null=False, blank=False, default=Utility.now_with_timezone, db_index=True
    )
    finish = models.DateTimeField(
        null=False, blank=False, help_text="Required for user to filter by time", db_index=True
    )
    display_name = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        db_index=True,
        help_text="The Rock, Little Foot, singspiration, A/V control, etc.",
    )
    slug = models.SlugField(max_length=50, blank=False, null=False, unique=True)
    infos = models.JSONField(
        null=True,
        blank=True,
        default=Utility.meet_infos,
        help_text='Example: {"info": "...", "url": "https://..."}. Please keep {} here even no data',
    )
    allowed_groups = models.ManyToManyField(
        "auth.Group",
        blank=True,
        related_name="meets",
        help_text="the auth groups whose members may see this meet and work on it; "
        "organization_participant lets its own participants see it",
    )
    site_type = models.ForeignKey(
        ContentType,
        on_delete=models.SET(0),
        help_text="site: django_content_type id for table name",
    )
    site_id = models.CharField(max_length=36, null=False, blank=False, default="0")
    site = GenericForeignKey("site_type", "site_id")  # This is default, will copy over to Event.description by signal

    def all_sites(self):
        return ", ".join([Utility.get_object_name(er.event) for er in self.event_relations.all() if er.event.description])

    # def save(self, *args, **kwargs):  # https://stackoverflow.com/a/27241824
    #     super(Meet, self).save(*args, **kwargs)  # One meet may have multiple Events

    def get_absolute_url(self):  # Todo: probably not needed, please remove it when upgrade
        return reverse("meet_detail", args=[str(self.id)])

    def info(self):
        return self.infos.get("info", "")

    def url(self):
        return self.infos.get("url", "")

    @property
    def schedule_rules(self):
        ers = (
            [er for er in self.event_relations.all() if er.distinction == 'source']
            if hasattr(self, '_prefetched_objects_cache') and 'event_relations' in self._prefetched_objects_cache
            else self.event_relations.filter(distinction='source')
        )
        return [
            {
                "rule": er.event.rule.name if er.event.rule else None,
                "start": er.event.start,
                "end": er.event.end,
                "location": Utility.get_object_name(er.event),
            }
            for er in ers
        ]

    def schedule_text(self, timezone_name=settings.TIME_ZONE, format='%H:%M%p %a'):
        schedules = [
            f"{datetime.strftime(er.event.start.astimezone(pytz.timezone(timezone_name)), format)}~{datetime.strftime(er.event.end.astimezone(pytz.timezone(timezone_name)), format)} {timezone_name},{er.event.rule.name}@{Utility.get_object_name(er.event)}"
            for er in self.event_relations.all()
        ]
        return ", ".join(schedules)

    @staticmethod
    def allowed_to_any_of(group_names):
        """A ``Q`` for the meets whose allowed groups include any of these auth group names. A
        subquery rather than a join, so a meet allowed to several of a user's groups comes out once."""
        allowed = Meet.allowed_groups.through.objects.filter(group__name__in=list(group_names))
        return Q(pk__in=allowed.values("meet_id"))

    @staticmethod
    def listed_on(model):
        """A ``Q`` for the meets listed on the page of ``model``, one of ``MeetAllowedModel.MODELS``."""
        return Q(pk__in=MeetAllowedModel.objects.filter(model=model).values("meet_id"))

    def list_on(self, *models):
        """Have the meet listed on these pages, the default ones when none are given."""
        for model in models or MeetAllowedModel.DEFAULT:
            MeetAllowedModel.objects.get_or_create(meet=self, model=model)

    class Meta:
        db_table = "occasions_meets"
        indexes = [
            models.Index(
                fields=["site_type", "site_id"],
                condition=models.Q(is_removed=False),
                name="meet_sites",
            ),
        ]

    def __str__(self):
        return "%s %s %s" % (
            self.display_name or "",
            self.infos.get("info", ""),
            self.infos.get("url", ""),
        )
