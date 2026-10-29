import pghistory
from uuid import uuid4
from address.models import AddressField
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.db.models import Q
import django.utils.timezone
import model_utils.fields
from model_utils.models import SoftDeletableModel, TimeStampedModel

from attendees.persons.models import Utility

#: The subject keys of a place, one of which every place sets.
SUBJECT_FIELDS = ("attendee", "folk", "assembly", "campus", "estate")


class Place(TimeStampedModel, SoftDeletableModel, Utility):
    """An address in use by one subject: an attendee, a folk, an assembly, a campus or a property.

    Exactly one of the subject keys is set; the database checks it. They replaced a generic
    content-type link whose 36-character text ``object_id`` had to be cast to join on, differently
    on every database and failing on Postgres for the rows holding integer ids. ``content_type``
    and ``object_id`` remain as properties, and the API still speaks them, so the pages and
    clients that name a place's subject that way need not change.
    """

    SUBJECT_FIELDS = SUBJECT_FIELDS

    id = models.UUIDField(default=uuid4, primary_key=True, editable=False, serialize=False)
    attendee = models.ForeignKey(
        "persons.Attendee", null=True, blank=True, on_delete=models.CASCADE, related_name="places"
    )
    folk = models.ForeignKey(
        "persons.Folk", null=True, blank=True, on_delete=models.CASCADE, related_name="places"
    )
    assembly = models.ForeignKey(
        "occasions.Assembly", null=True, blank=True, on_delete=models.CASCADE, related_name="places"
    )
    campus = models.ForeignKey(
        "whereabouts.Campus", null=True, blank=True, on_delete=models.CASCADE, related_name="places"
    )
    estate = models.ForeignKey(
        "whereabouts.Property",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="places",
        help_text="the property (a building, villa or lodge) this is the address of",
    )
    organization = models.ForeignKey(
        "whereabouts.Organization",
        default=0,
        null=False,
        blank=False,
        on_delete=models.SET(0),
    )
    address = AddressField(related_name="place", blank=True, null=True)
    # address_extra = models.CharField(max_length=50, blank=True, null=True, help_text='i.e. Apartment number')
    # address_type = models.CharField(max_length=20, default='street', blank=True, null=True, help_text='mailing, remote or street address')
    display_name = models.CharField(
        db_index=True,
        max_length=50,
        default="main",
        blank=False,
        null=False,
        help_text="main, resident, etc (main will be displayed first)",
    )
    display_order = models.SmallIntegerField(default=0, blank=False, null=False)
    start = models.DateField(null=True, blank=True, help_text="optional, moved in date")
    finish = models.DateField(
        null=True, blank=True, help_text="optional, moved out date"
    )
    infos = models.JSONField(
        default=Utility.default_infos,
        null=True,
        blank=True,
        help_text="please keep {} here even there's no data",
    )
    # need to validate there only one 'main' for display_name

    class Meta:
        db_table = "whereabouts_places"
        ordering = ("organization", "display_order")
        constraints = [
            models.CheckConstraint(
                name="place_one_subject",
                condition=Q(
                    *(
                        Q(**{f"{field}__isnull": False}, **{f"{other}__isnull": True for other in SUBJECT_FIELDS if other != field})
                        for field in SUBJECT_FIELDS
                    ),
                    _connector=Q.OR,
                ),
            ),
            # One live place per subject and address; a partial unique index per subject key,
            # because a key that is null never collides on any database.
            *(
                models.UniqueConstraint(
                    fields=["organization", field, "address"],
                    condition=Q(is_removed=False, **{f"{field}__isnull": False}),
                    name=f"address_of_{field}",
                )
                for field in SUBJECT_FIELDS
            ),
        ]

    @property
    def subject_field(self):
        """The name of the subject key that is set."""
        return next((field for field in self.SUBJECT_FIELDS if getattr(self, f"{field}_id") is not None), None)

    @property
    def subject(self):
        field = self.subject_field
        return getattr(self, field) if field else None

    @property
    def content_type(self):
        """The subject's content type, as the API and the pages still name it."""
        field = self.subject_field
        return ContentType.objects.get_for_model(self._meta.get_field(field).related_model) if field else None

    @property
    def object_id(self):
        field = self.subject_field
        return str(getattr(self, f"{field}_id")) if field else None

    @classmethod
    def subject_field_for(cls, model):
        """The subject key for a model class or a content type; ValueError for a model no place
        can be the address of."""
        model_class = model.model_class() if isinstance(model, ContentType) else model
        for field in cls.SUBJECT_FIELDS:
            if cls._meta.get_field(field).related_model is model_class:
                return field
        raise ValueError(f"a place cannot be the address of a {getattr(model_class, '__name__', model_class)}")

    @classmethod
    def subject_values(cls, model, object_id):
        """Every subject key as a field value: the one the model names set to the id, the others
        None, for a save that names the subject the API's way."""
        field = cls.subject_field_for(model)
        return {f"{other}_id": (object_id if other == field else None) for other in cls.SUBJECT_FIELDS}

    @property
    def street(self):
        return str(self.address)
        # if self.address:
        #     if Utility.blank_check(self.address_extra) and Utility.present_check(self.address.formatted):
        #         txt = '%s' % self.address.formatted
        #     elif self.address.locality:
        #         txt = ''
        #         if self.address.street_number:
        #             txt = '%s' % self.address.street_number
        #         if self.address.route:
        #             if txt:
        #                 txt += ' %s' % self.address.route
        #         if self.address_extra:
        #             txt = txt + ' %s' % self.address_extra if txt else ' %s' % self.address_extra
        #         locality = '%s' % self.address.locality
        #         if txt and locality:
        #             txt += ', '
        #         txt += locality
        #     else:
        #         txt = '%s' % self.address.raw
        #     return txt
        # else:
        #     return self.address_extra

    def __str__(self):
        return "%s %s" % (self.address, self.subject)


class PlacesHistory(pghistory.get_event_model(
    Place,
    pghistory.Snapshot('place.snapshot'),
    pghistory.BeforeDelete('place.before_delete'),
    name='PlacesHistory',
    related_name='history',
)):
    pgh_id = models.BigAutoField(primary_key=True, serialize=False)
    pgh_created_at = models.DateTimeField(auto_now_add=True)
    pgh_label = models.TextField(help_text='The event label.')
    pgh_obj = models.ForeignKey(db_constraint=False, on_delete=models.deletion.DO_NOTHING, related_name='history', to='whereabouts.place')
    created = model_utils.fields.AutoCreatedField(default=django.utils.timezone.now, editable=False, verbose_name='created')
    id = models.UUIDField(db_index=True, default=uuid4, editable=False, serialize=False)
    modified = model_utils.fields.AutoLastModifiedField(default=django.utils.timezone.now, editable=False, verbose_name='modified')
    is_removed = models.BooleanField(default=False)
    organization = models.ForeignKey(db_constraint=False, default=0, on_delete=models.deletion.DO_NOTHING, related_name='+', related_query_name='+', to='whereabouts.organization')
    infos = models.JSONField(blank=True, default=Utility.default_infos, help_text="please keep {} here even there's no data", null=True)
    display_order = models.SmallIntegerField(default=0)
    display_name = models.CharField(default='main', help_text='main, resident, etc (main will be displayed first)', max_length=50)
    address = AddressField(blank=True, db_constraint=False, null=True, on_delete=models.deletion.DO_NOTHING, related_name='+', related_query_name='+', to='address.address')
    start = models.DateField(blank=True, help_text='optional, moved in date', null=True)
    finish = models.DateField(blank=True, help_text='optional, moved out date', null=True)
    pgh_context = models.ForeignKey(db_constraint=False, null=True, on_delete=models.deletion.DO_NOTHING, related_name='+', to='pghistory.context')

    class Meta:
        db_table = 'whereabouts_placeshistory'
