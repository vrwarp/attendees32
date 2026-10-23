"""
Write down the Tally integration: its connection, and a ledger of what it wrote.

    python manage.py backup_tally_integration --out tally-backup.json

The file is small and readable. It holds the names the setup was run with and
which of them it created, plus every record Tally made or changed, by id, with
whether anyone else has touched it since. It does not hold record contents:
the history tables already do, and the church's own database backup is the
backup of the data.

``--with-token`` adds the DRF token, so ``setup_tally_integration --from`` can
restore the same key and Tally keeps working without re-pairing. The file then
holds a secret; keep it like one.
"""
import json

from django.core.management.base import BaseCommand, CommandError

from attendees.persons.services.tally_integration_service import (
    USERNAME,
    NoIntegration,
    TallyIntegrationService,
)


class Command(BaseCommand):
    help = "Write the Tally integration's connection and ledger to a JSON file."

    def add_arguments(self, parser):
        parser.add_argument("--out", default=None, help="Where to write. Default: standard output.")
        parser.add_argument("--with-token", action="store_true", help="Include the DRF token (a secret).")
        parser.add_argument("--username", default=USERNAME, help="The integration user.")

    def handle(self, *args, **options):
        try:
            backup = TallyIntegrationService.backup(options["username"], with_token=options["with_token"])
        except NoIntegration as error:
            raise CommandError(str(error))
        text = json.dumps(backup, indent=2)
        if options["out"]:
            with open(options["out"], "w") as handle:
                handle.write(text + "\n")
            made = sum(len(table["made"]) for table in backup["ledger"].values())
            changed = sum(len(table["changed"]) for table in backup["ledger"].values())
            self.stdout.write(
                f"Wrote {options['out']}: {made} records Tally made, {changed} it changed"
                + (", token included" if options["with_token"] else "")
            )
        else:
            self.stdout.write(text)
