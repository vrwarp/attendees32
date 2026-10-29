from django.core.management.base import BaseCommand, CommandError

from attendees.history import ledger


class Command(BaseCommand):
    help = (
        "Verify the history: seq has no gaps, every mac recomputes and chains to the previous one, "
        "every anchor matches, and (in full) the replay of the history equals the live tables. "
        "The result is stored as a HistoryAudit; a failure is mailed to HISTORY_AUDIT_RECIPIENTS."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--incremental",
            action="store_true",
            help="Check only the events since the last clean run, without the replay (run after each anchor)",
        )

    def handle(self, *args, **options):
        audit = ledger.verify(full=not options["incremental"])
        self.stdout.write(f"{'clean' if audit.ok else 'FAILED'}: {audit.events} events checked, head at {audit.head_seq}")
        if audit.report:
            self.stdout.write(audit.report)
        if not audit.ok:
            raise CommandError(f"history verification failed; first bad event: {audit.first_bad_seq}")
