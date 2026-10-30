import time
import logging
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Min, Q
from address.models import Address
from attendees.whereabouts.models import Place
from attendees.whereabouts.services.coordinates_service import CoordinatesService

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = "Populate missing latitude and longitude for Address records using Google Maps API."

    def add_arguments(self, parser):
        parser.add_argument(
            '--sleep',
            type=float,
            default=0.2,
            help='Time to sleep between API calls in seconds (default: 0.2 to respect rate limits)'
        )

    def handle(self, *args, **options):
        if not getattr(settings, 'GOOGLE_MAPS_API_KEY', '') or not str(settings.GOOGLE_MAPS_API_KEY).strip():
            self.stdout.write(self.style.ERROR("GOOGLE_MAPS_API_KEY is not configured or empty. Aborting."))
            return

        sleep_time = options['sleep']

        # Clean up unused Address records first
        used_address_ids = Place.all_objects.values_list('address_id', flat=True).distinct()
        unused_addresses = Address.objects.exclude(id__in=used_address_ids)

        # Django's delete() returns a tuple (total_deleted, dict_of_deleted_models)
        deleted_count, deleted_details = unused_addresses.delete()
        if deleted_count > 0:
            self.stdout.write(self.style.WARNING(f"Cleaned up {deleted_count} unused Address records."))

        # Find all addresses missing coordinates and having both street_number and route
        # Because CoordinatesService updates siblings, we only need to query distinct address combinations.
        # The service itself protects against redundant API calls if siblings were already updated in a previous iteration.
        missing_coords_addresses = (
            Address.objects.filter(Q(latitude__isnull=True) | Q(longitude__isnull=True))
            .exclude(Q(street_number__isnull=True) | Q(street_number=''))
            .exclude(Q(route__isnull=True) | Q(route=''))
        )

        # Optimize by getting only one representative address per distinct combination of
        # street_number, route and locality, minimizing the loop size. Postgres could say this
        # as DISTINCT ON, but that is Postgres-only syntax; grouping and taking the lowest id
        # per combination is the same choice — the service updates every sibling anyway, so any
        # representative does — and runs on both backends. order_by() first, or the model's
        # default ordering would leak into the GROUP BY.
        representative_ids = (
            missing_coords_addresses.order_by()
            .values('street_number', 'route', 'locality_id')
            .annotate(representative_id=Min('id'))
            .values_list('representative_id', flat=True)
        )
        distinct_addresses = Address.objects.filter(id__in=representative_ids).order_by(
            'street_number', 'route', 'locality_id'
        )

        total_to_process = distinct_addresses.count()
        self.stdout.write(self.style.WARNING(f"Found {total_to_process} distinct addresses missing coordinates."))

        if total_to_process == 0:
            self.stdout.write(self.style.SUCCESS("All addresses have coordinates. Exiting."))
            return

        success_count = 0
        failure_count = 0

        for index, address in enumerate(distinct_addresses, start=1):
            self.stdout.write(f"Processing {index}/{total_to_process}: Id {address.id} {address.name}...")

            success, reason = CoordinatesService.geocode_address(address.id, return_details=True)

            if success:
                success_count += 1
                self.stdout.write(self.style.SUCCESS(f"  -> Success: {reason}"))
            else:
                failure_count += 1
                self.stdout.write(self.style.ERROR(f"  -> Failed or Skipped: {reason}"))

            # Sleep to respect rate limits
            time.sleep(sleep_time)

        self.stdout.write(self.style.SUCCESS(
            f"Finished. Successfully geocoded {success_count} address groups. Failed/Skipped: {failure_count}."
        ))
