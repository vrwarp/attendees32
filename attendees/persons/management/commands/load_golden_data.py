"""Load (and optionally dump) the golden 350-member congregation.

    python manage.py load_golden_data --seed
    python manage.py load_golden_data --seed --dump fixtures/golden.json

The builder is deterministic: every UUID primary key comes from ``uuid5``, so
two runs against a freshly seeded database produce identical identifiers and
the dumped fixture diffs cleanly.  Dates are relative to *today* so ages and
"currently participating" windows stay true however long the fixture sits.
"""

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from attendees.persons.models import Attendee
from attendees.tests.golden import build_golden_dataset


class Command(BaseCommand):
    help = "Load the golden test congregation on top of fixtures/db_seed.json"

    def add_arguments(self, parser):
        parser.add_argument(
            "--seed",
            action="store_true",
            help="load fixtures/db_seed.json first",
        )
        parser.add_argument(
            "--dump",
            metavar="PATH",
            help="after building, dumpdata the whole thing to PATH",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="build even though golden attendees already exist",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        if not options["force"] and Attendee.objects.filter(
            infos__names__original__icontains="Zhongxin"
        ).exists():
            raise CommandError(
                "golden data looks already loaded; pass --force to build anyway"
            )

        dataset = build_golden_dataset(load_seed=options["seed"])

        width = max(len(name) for name in dataset.counts)
        for name, count in dataset.counts.items():
            self.stdout.write(f"  {name.ljust(width)}  {count}")
        self.stdout.write(
            self.style.SUCCESS(
                f"golden dataset built: {dataset.counts['attendees']} live attendees"
            )
        )

        if options["dump"]:
            call_command(
                "dumpdata",
                "--natural-foreign",
                "--natural-primary",
                "--indent",
                "1",
                "--exclude",
                "contenttypes",
                "--exclude",
                "auth.permission",
                "--output",
                options["dump"],
            )
            self.stdout.write(self.style.SUCCESS(f"dumped to {options['dump']}"))
