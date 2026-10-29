from django.core.management.base import BaseCommand

from attendees.history import ledger


class Command(BaseCommand):
    help = (
        "Record the head of the history chain (seq, mac, time) where the database cannot reach it: "
        "appended to HISTORY_ANCHOR_FILE and mailed to HISTORY_ANCHOR_RECIPIENTS. Run it daily."
    )

    def add_arguments(self, parser):
        parser.add_argument("--no-email", action="store_true", help="Write the anchor file only")

    def handle(self, *args, **options):
        line = ledger.anchor(send=not options["no_email"])
        self.stdout.write(line)
