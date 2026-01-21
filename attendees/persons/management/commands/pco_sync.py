from django.core.management.base import BaseCommand
from attendees.persons.models import Attendee
from attendees.persons.services.pco_service import PCOService

class Command(BaseCommand):
    help = 'Sync attendees to Planning Center Online'

    def add_arguments(self, parser):
        parser.add_argument('--attendee', type=str, help='Specific Attendee ID to sync')
        parser.add_argument('--limit', type=int, help='Limit number of attendees to sync')

    def handle(self, *args, **options):
        self.stdout.write("Starting PCO Sync...")

        # Instantiate service. Credentials will be pulled from settings.
        service = PCOService()

        attendees = Attendee.objects.filter(is_removed=False)
        if options['attendee']:
            attendees = attendees.filter(id=options['attendee'])

        if options['limit']:
            attendees = attendees[:options['limit']]

        count = 0
        for attendee in attendees:
            try:
                self.stdout.write(f"Syncing {attendee} ({attendee.id})...")
                service.sync_attendee(attendee)
                count += 1
            except Exception as e:
                self.stderr.write(self.style.ERROR(f"Failed to sync {attendee}: {e}"))

        self.stdout.write(self.style.SUCCESS(f"Successfully synced {count} attendees."))
