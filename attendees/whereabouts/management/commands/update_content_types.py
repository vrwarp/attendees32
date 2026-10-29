from address.models import Address
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand, CommandError

from attendees.whereabouts.models import (
    Campus,
    ContentTypeExtra,
    Division,
    Organization,
    Property,
    Room,
    Suite,
)


class Command(BaseCommand):
    help = (
        "Fill the content type extras the site picker reads (genre, order, endpoint, hint). "
        "Run after migrations, once the content types exist; no arguments needed."
    )

    #: The kinds of place a gathering can be held at, in the order the picker lists them.
    LOCATIONS = (
        (Room, "organizational_rooms", 2, "single room/office", None),
        (Suite, "organizational_suites", 3, "entire floor/space", None),
        (Property, "organizational_properties", 4, "entire building/villa/lodge", None),
        (Campus, "organizational_campuses", 5, "entire campus/park", None),
        (Division, "user_divisions", 6, "entire division/department", None),
        (Organization, "user_organizations", 7, "entire organization", None),
        # Address lives in a third-party app, so its endpoint hangs off whereabouts.
        (Address, "all_addresses", 8, "street address", Organization._meta.app_label),
    )

    def handle(self, *args, **options):
        self.stdout.write("checking ContentType data ..")
        if ContentType.objects.count() < 1:
            raise CommandError(
                "ContentType data does not exist! Please try again after 30 sec."
            )

        self.stdout.write("update extra data for ContentType ...")
        for model, endpoint, display_order, hint, app_label in self.LOCATIONS:
            ContentTypeExtra.objects.update_or_create(
                content_type=ContentType.objects.get_for_model(model),
                defaults={
                    "genres": "location",
                    "display_order": display_order,
                    "endpoint": f"/{app_label or model._meta.app_label}/api/{endpoint}/",
                    "hint": hint,
                },
            )
        self.stdout.write("done!")
