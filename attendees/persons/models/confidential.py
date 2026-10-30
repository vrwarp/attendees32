"""A record a few people keep between themselves."""
from django.db import models
from django.db.models import Q


class Confidential(models.Model):
    """Mixed into a record that can be kept from everyone but a few named people.

    ``viewers`` are the attendees who may see the record. Nobody listed means everyone who may see
    records of its category may see it. Ticking "Secret?" on the attendee page puts the reader on
    the list, so from then on only they, and whoever else is listed, see it. A counseling record
    can also be opened to every counselor with ``counselors_may_view``.

    This used to be ``infos["show_secret"]``, a map of attendee id to true, read by building a
    JSON key from the reader's id, which only Postgres could do.
    """

    viewers = models.ManyToManyField(
        "persons.Attendee",
        blank=True,
        related_name="+",
        help_text="who may see this record; nobody listed means everyone who may see its category",
    )
    counselors_may_view = models.BooleanField(
        default=False,
        help_text="a counseling record every counselor may see, not only the viewers listed",
    )

    class Meta:
        abstract = True

    @classmethod
    def visible_to(cls, attendee_id):
        """A ``Q`` for the records a reader may see: those listing the reader as a viewer, and
        those with no viewers at all. Written with subqueries rather than a join so that it can
        be combined with any other condition without duplicating rows."""
        through = cls.viewers.through
        record = f"{cls._meta.model_name}_id"
        granted = through.objects.filter(attendee_id=attendee_id).values(record)
        restricted = through.objects.values(record)
        return Q(pk__in=granted) | ~Q(pk__in=restricted)

    def is_visible_to(self, attendee_id):
        return not self.viewers.exists() or self.viewers.filter(pk=attendee_id).exists()
