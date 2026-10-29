from django.core.management.base import BaseCommand

from attendees.occasions.models import Attendance, Gathering
from attendees.persons.models import Attendee, AttendingMeet
from attendees.utils.search_text import search_text_of


class Command(BaseCommand):
    help = (
        "Recompute search_text for every searchable record. save() keeps the column current; "
        "this covers writes that bypassed it, such as queryset.update()."
    )

    BATCH = 500

    def handle(self, *args, **options):
        # Attendees derive their names on save as well, so they go through save() itself.
        attendees = Attendee.all_objects.select_related("division__organization")
        count = 0
        for attendee in attendees.iterator(chunk_size=self.BATCH):
            attendee.save(update_fields=["infos", "full_name", "search_text"])
            count += 1
        self.stdout.write(f"attendees: {count}")

        for model in (AttendingMeet, Attendance, Gathering):
            changed = []
            total = 0
            for instance in model.all_objects.only("pk", "infos", "search_text").iterator(
                chunk_size=self.BATCH
            ):
                total += 1
                text = search_text_of(*instance.search_text_parts())
                if text != instance.search_text:
                    instance.search_text = text
                    changed.append(instance)
                if len(changed) >= self.BATCH:
                    model.all_objects.bulk_update(changed, ["search_text"])
                    changed = []
            if changed:
                model.all_objects.bulk_update(changed, ["search_text"])
            self.stdout.write(f"{model._meta.label_lower}: {total} checked")
