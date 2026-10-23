"""
Take the Tally integration down.

    python manage.py delete_tally_integration            # says what it would do
    python manage.py delete_tally_integration --force    # does it
    python manage.py delete_tally_integration --force --purge
    python manage.py delete_tally_integration --undo tally-receipt-….json

Without ``--force`` nothing changes: the command prints the plan. With it, the
token is revoked, the user deactivated and taken out of the group, the group
taken off the organization's privilege lists and the readable meets, the
integration's own attendee removed, and the division the setup created removed
if nothing lives in it any more. The records Tally wrote stay: a youth Tally
checked in is still a youth who was there.

``--purge`` also removes the records Tally made that nobody else has touched
since, in order: memberships, families, people. A record a person edited
afterwards is listed and left. A record Tally merged away is left too, unless
``--unmerge`` undoes that merge first.

Every real run writes a receipt, and ``--undo RECEIPT`` puts it all back,
the token included. Everything removed is a soft delete, so that is exact.
"""
import json
from datetime import datetime, timezone

from django.core.management.base import BaseCommand, CommandError

from attendees.persons.services.tally_integration_service import (
    LEDGER,
    USERNAME,
    NoIntegration,
    TallyIntegrationService,
)


class Command(BaseCommand):
    help = "Take the Tally integration down, with a receipt that --undo reads."

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true", help="Do it. Without this, only say what would happen.")
        parser.add_argument("--purge", action="store_true", help="Also remove the records Tally made that nobody else touched.")
        parser.add_argument("--unmerge", action="store_true", help="Undo Tally's merges first, so those records can go too.")
        parser.add_argument("--receipt", default=None, help="Where to write the receipt. Default: tally-receipt-<time>.json")
        parser.add_argument("--undo", default=None, metavar="RECEIPT", help="Put back what a previous run took.")
        parser.add_argument("--username", default=USERNAME, help="The integration user.")

    def handle(self, *args, **options):
        if options["undo"]:
            return self.undo(options["undo"])
        try:
            if not options["force"]:
                return self.dry_run(options)
            receipt = TallyIntegrationService.delete(
                options["username"], purge=options["purge"], unmerge=options["unmerge"]
            )
        except NoIntegration as error:
            raise CommandError(str(error))

        path = options["receipt"] or f"tally-receipt-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json"
        with open(path, "w") as handle:
            handle.write(json.dumps(receipt, indent=2) + "\n")

        connection = receipt["connection"]
        self.stdout.write("removed token" if connection.get("token") else "no token to remove")
        self.stdout.write(f"deactivated user: {options['username']}")
        for key in connection.get("privileges", []):
            self.stdout.write(f"removed from organization {key}")
        for slug in connection.get("meets", []):
            self.stdout.write(f"no longer readable: {slug}")
        if connection.get("attendee"):
            self.stdout.write(f"removed attendee: {connection['attendee']}")
        if connection.get("division_removed"):
            self.stdout.write(f"removed division: {receipt['backup']['division']}")
        for name, *_ in LEDGER:
            if receipt["removed"][name]:
                self.stdout.write(f"removed {len(receipt['removed'][name])} {name.replace('_', ' ')}")
        if receipt["unmerged"]:
            self.stdout.write(f"unmerged {len(receipt['unmerged'])} records first")
        self.report_kept(receipt["kept"])
        self.stdout.write(self.style.SUCCESS(f"Receipt: {path} (holds the token; keep it like one). Undo with --undo {path}"))

    def dry_run(self, options):
        plan = TallyIntegrationService.plan(options["username"], purge=options["purge"], unmerge=options["unmerge"])
        backup = plan["backup"]
        self.stdout.write(self.style.WARNING("Dry run. Nothing changes without --force."))
        self.stdout.write(f"would revoke the token and deactivate {options['username']}")
        self.stdout.write(f"would take {backup['group']} off the organization's privilege lists")
        for slug in backup["readable_meets"]:
            self.stdout.write(f"would make unreadable: {slug}")
        if backup["attendee"]:
            self.stdout.write(f"would remove attendee: {backup['attendee']}")
        if backup["division_created"]:
            self.stdout.write(f"would remove division {backup['division']} if nothing lives in it")
        if options["purge"]:
            for name, *_ in LEDGER:
                self.stdout.write(f"would remove {len(plan['removed'][name])} {name.replace('_', ' ')}")
            self.report_kept(plan["kept"])
        else:
            made = sum(len(table["made"]) for table in backup["ledger"].values())
            self.stdout.write(f"would leave the {made} records Tally made (add --purge to remove the untouched ones)")

    def report_kept(self, kept):
        for name, *_ in LEDGER:
            for row in kept.get(name, []):
                if row.get("in_use"):
                    why = "someone still lives there"
                elif row.get("merged") and not row.get("others_since"):
                    why = "merged"
                else:
                    why = "someone else changed it"
                self.stdout.write(f"    kept {name.replace('_', ' ')[:-1]} {row['id']}: {why}")

    def undo(self, path):
        try:
            with open(path) as handle:
                receipt = json.load(handle)
            TallyIntegrationService.undo(receipt)
        except (OSError, ValueError, KeyError) as error:
            raise CommandError(f"Could not undo from {path}: {error}")
        self.stdout.write(self.style.SUCCESS(f"Put back what {path} took."))
