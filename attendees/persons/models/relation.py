from django.db import models
from model_utils.models import SoftDeletableModel, TimeStampedModel

from . import GenderEnum
from attendees.history import track
from attendees.history.querysets import TrackedSoftDeletable


@track
class Relation(TrackedSoftDeletable, TimeStampedModel, SoftDeletableModel):
    id = models.BigAutoField(
        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
    )
    gender = models.CharField(
        max_length=11,
        blank=False,
        null=False,
        default=GenderEnum.UNSPECIFIED,
        choices=GenderEnum.choices(),
    )
    reciprocals = models.ManyToManyField(
        "self",
        symmetrical=False,
        blank=True,
        related_name="reciprocal_of",
        verbose_name="corresponding relations",
        help_text="the same tie seen from the other side: father to son and daughter",
    )
    title = models.CharField(
        "To be called", max_length=50, blank=False, null=False, unique=True
    )
    display_order = models.SmallIntegerField(
        default=0, blank=False, null=False, db_index=True
    )
    emergency_contact = models.BooleanField(
        "to be the emergency contact?",
        null=False,
        blank=False,
        default=False,
        help_text="default value, can be changed in relationships further",
    )
    scheduler = models.BooleanField(
        "to be the scheduler?",
        null=False,
        blank=False,
        default=False,
        help_text="default value, can view/change the schedules of the caller?",
    )
    relative = models.BooleanField(
        "relative?",
        null=False,
        blank=False,
        default=False,
        help_text="is it a relative?",
    )
    consanguinity = models.BooleanField(
        "blood relatives?",
        null=False,
        blank=False,
        default=False,
        help_text="is it blood relatives?",
    )

    def __str__(self):
        return "%s" % self.title

    class Meta:
        db_table = "persons_relations"
        ordering = (
            "display_order",
            "title",
        )
