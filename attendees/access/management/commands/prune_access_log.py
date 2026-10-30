from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from attendees.access.models import AccessLog


class Command(BaseCommand):
    help = "Delete access log rows older than the retention period (12 months by default). Run it nightly."

    def add_arguments(self, parser):
        parser.add_argument("--months", type=int, default=12, help="Keep this many months (default 12)")

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(days=30 * options["months"])
        deleted, _ = AccessLog.objects.filter(when__lt=cutoff).delete()
        self.stdout.write(f"pruned {deleted} access log rows older than {cutoff:%Y-%m-%d}")
