from django.contrib.contenttypes.models import ContentType
from django.db import models
from attendees.history import track
from attendees.history.querysets import Tracked


@track
class ContentTypeExtra(Tracked, models.Model):
    """What the site picker knows about a content type beyond Django's own row: the genre of
    model it is (``location`` for the kinds of place a gathering can be held at), the order to
    list them in, the endpoint that lists the rows of that model and a hint for the picker.

    These used to be four columns added to ``django_content_type`` itself by raw SQL, filled and
    read back by raw SQL. ``manage.py update_content_types`` fills the rows once the content types
    exist.
    """

    content_type = models.OneToOneField(
        ContentType, on_delete=models.CASCADE, primary_key=True, related_name="extra"
    )
    display_order = models.SmallIntegerField(default=0)
    genres = models.CharField(max_length=100, blank=True, null=True, db_index=True)
    endpoint = models.CharField(max_length=100, blank=True, null=True)
    hint = models.CharField(max_length=100, blank=True, null=True)

    class Meta:
        db_table = "whereabouts_content_type_extras"
        ordering = ("display_order",)

    def __str__(self):
        return f"{self.content_type} ({self.genres or 'no genre'})"
