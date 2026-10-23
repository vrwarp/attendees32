from address.models import Address
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from schedule.models.events import Event, Occurrence

from attendees.whereabouts.models import (
    Campus,
    Division,
    Organization,
    Property,
    Room,
    Suite,
)


class Command(BaseCommand):
    help = "Update extra content type columns after migrations and content type data seeded, no arguments needed"

    def handle(self, *args, **options):
        self.stdout.write("checking ContentType data ..")

        if ContentType._meta.db_table not in connection.introspection.table_names():
            raise CommandError(
                f"Fail! Cannot find the table {ContentType._meta.db_table}, did the migration run?"
            )

        if ContentType.objects.count() < 1:
            raise CommandError(
                "ContentType data does not exist! Please try again after 30 sec."
            )

        self.stdout.write("update extra data for ContentType ...")

        # One statement per execute: SQLite's driver rejects a multi-statement script outright.
        # The UPDATEs and the index DDL are portable as written; only COMMENT ON is not, and it
        # is documentation rather than behaviour, so it is simply skipped off Postgres.
        statements = [
            self._location_update(Room, "organizational_rooms", 2, "single room/office"),
            self._location_update(Suite, "organizational_suites", 3, "entire floor/space"),
            self._location_update(
                Property, "organizational_properties", 4, "entire building/villa/lodge"
            ),
            self._location_update(Campus, "organizational_campuses", 5, "entire campus/park"),
            self._location_update(
                Division, "user_divisions", 6, "entire division/department"
            ),
            self._location_update(
                Organization, "user_organizations", 7, "entire organization"
            ),
            # Address lives in a third-party app, so its endpoint hangs off whereabouts.
            self._location_update(
                Address, "all_addresses", 8, "street address",
                app_label=Organization._meta.app_label,
            ),
            f"CREATE INDEX IF NOT EXISTS {Occurrence._meta.db_table}_titles"
            f"  ON {Occurrence._meta.db_table} (title)",
            f"CREATE INDEX IF NOT EXISTS {Occurrence._meta.db_table}_description"
            f"  ON {Occurrence._meta.db_table} (description)",
            f"CREATE INDEX IF NOT EXISTS {Event._meta.db_table}__titles"
            f"  ON {Event._meta.db_table} (title)",
            f"CREATE INDEX IF NOT EXISTS {Event._meta.db_table}_description"
            f"  ON {Event._meta.db_table} (description)",
        ]

        if connection.vendor == "postgresql":
            statements += [
                f"COMMENT ON COLUMN {Event._meta.db_table}.description"
                f"  IS 'location: <model name>#<pk>'",
                f"COMMENT ON COLUMN {Occurrence._meta.db_table}.description"
                f"  IS 'location: <model name>#<pk>'",
                f"COMMENT ON COLUMN {Occurrence._meta.db_table}.title"
                f"  IS 'relation: gathering#<id>'",
            ]

        with connection.cursor() as cursor:
            for statement in statements:
                cursor.execute(statement)

        self.stdout.write("done!")

    @staticmethod
    def _location_update(model, endpoint, display_order, hint, app_label=None):
        return f"""
            UPDATE {ContentType._meta.db_table}
              SET genres='location',
                  display_order={display_order},
                  endpoint='/{app_label or model._meta.app_label}/api/{endpoint}/',
                  hint='{hint}'
              WHERE app_label='{model._meta.app_label}'
                AND model='{model._meta.model_name}'
        """
