# from django.core.exceptions import ValidationError
from django.contrib.contenttypes.fields import GenericForeignKey, GenericRelation
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.urls import reverse
from model_utils.models import SoftDeletableModel, TimeStampedModel
from schedule.models import Occurrence

from attendees.persons.models import Note, Searchable, Utility
from attendees.history import track
from attendees.history.querysets import TrackedSoftDeletable


@track
class Gathering(TrackedSoftDeletable, Searchable, TimeStampedModel, SoftDeletableModel, Utility):
    """
    The gathering pk/id is also stored in the corresponding 3rd party model
    schedule.Occurrence.title such as gathering#42, so when calendar shows
    Occurrences of Events, the corresponding gathering can be fetched. The
    location is also stored in schedule.Occurrence.description like room#53.
    code usage: ContentType.objects.get(model='room').model_class().objects.get(pk=1)

    Note: Multiple occurrences from different calendars, such as location calendars
          and users calendars, can point to the very same Gathering instance.
    """

    notes = GenericRelation(Note)
    id = models.BigAutoField(
        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
    )  # will copy over to occurrence title by signal
    meet = models.ForeignKey("Meet", on_delete=models.SET(0), null=False, blank=False)
    start = models.DateTimeField(null=False, blank=False, db_index=True)
    finish = models.DateTimeField(
        null=False, blank=False, help_text="Required for user to filter by time", db_index=True
    )
    attendings = models.ManyToManyField("persons.Attending", through="Attendance")
    display_name = models.CharField(
        max_length=255, blank=True, null=True, help_text="02/09/2020, etc"
    )
    infos = models.JSONField(
        null=True,
        blank=True,
        default=dict,
        help_text='Example: {"LG_location": "F207", "link": "https://..."}. Please keep {} here even no data',
    )
    site_type = models.ForeignKey(
        ContentType,
        on_delete=models.SET(0),
        help_text="site: django_content_type id for table name",
    )
    site_id = models.CharField(max_length=36, null=False, blank=False, default="0")
    site = GenericForeignKey("site_type", "site_id")  # will copy over to occurrence description by signal

    # from itertools import groupby
    # from operator import attrgetter
    #
    # ordered_program_sessions = ProgramSession.objects.order_by('program_group', 'start_at')
    # program_sessions_grouped_by_program_groups = {
    #     k: list(v)
    #     for k, v in groupby(ordered_program_sessions, attrgetter('program_group'))
    # } #=> {<ProgramGroup: The Rock  >: [<ProgramSession: The Rock #1...>, <ProgramSession: The Rock #2...>]}

    def get_absolute_url(self):
        return reverse("gathering_detail", args=[str(self.id)])

    @property
    def gathering_label(self):
        return (self.display_name or "") + (f" in {self.meet.display_name}" if self.meet.display_name else "")

    @property
    def meet_display_name(self):
        return self.meet.display_name

    class Meta:
        db_table = "occasions_gatherings"
        ordering = ["meet", "start"]
        constraints = [
            models.UniqueConstraint(
                fields=["meet_id", "site_type", "site_id", "start"],
                condition=models.Q(is_removed=False),
                name="gathering_uniq_meet_location_time",
            )
        ]
        indexes = [
            models.Index(
                fields=["site_type", "site_id"],
                condition=models.Q(is_removed=False),
                name="gathering_sites",
            ),
        ]

    def __str__(self):
        return "%s %s %s %s" % (
            self.meet,
            self.start,
            self.display_name or "",
            self.site or "",
        )

    def occurrences(self):
        if self.pk:
            return Occurrence.objects.filter(title=f'{self.__class__.__name__.lower()}#{self.pk}')
        else:
            return []

    # def save(self, *args, **kwargs):  # https://stackoverflow.com/a/27241824
    #     super(Gathering, self).save(*args, **kwargs)

    # def time_and_location_dict(self, timezone='UTC', timeformat='%Y/%m/%d,%H:%M %p %Z'):
    #     return {
    #         "time": self.start.astimezone(pytz.timezone(timezone)).strftime(timeformat),
    #         "location": str(self.site),
    #     }
