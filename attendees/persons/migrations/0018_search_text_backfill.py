from django.db import migrations

from attendees.utils.search_text import attendee_full_name, attendee_search_text, search_text_of

BATCH = 500


def fill_search_text(apps, schema_editor):
    """Fill the new columns for existing rows with the same functions save() uses."""
    Attendee = apps.get_model("persons", "Attendee")
    AttendingMeet = apps.get_model("persons", "AttendingMeet")

    changed = []
    for attendee in Attendee._base_manager.all().iterator(chunk_size=BATCH):
        attendee.full_name = attendee_full_name(
            attendee.first_name, attendee.last_name, attendee.last_name2, attendee.first_name2
        )
        attendee.search_text = attendee_search_text(
            attendee.first_name,
            attendee.last_name,
            attendee.last_name2,
            attendee.first_name2,
            attendee.infos,
        )
        changed.append(attendee)
        if len(changed) >= BATCH:
            Attendee._base_manager.bulk_update(changed, ["full_name", "search_text"])
            changed = []
    if changed:
        Attendee._base_manager.bulk_update(changed, ["full_name", "search_text"])

    changed = []
    for attending_meet in AttendingMeet._base_manager.all().iterator(chunk_size=BATCH):
        attending_meet.search_text = search_text_of(attending_meet.infos)
        changed.append(attending_meet)
        if len(changed) >= BATCH:
            AttendingMeet._base_manager.bulk_update(changed, ["search_text"])
            changed = []
    if changed:
        AttendingMeet._base_manager.bulk_update(changed, ["search_text"])


class Migration(migrations.Migration):

    dependencies = [
        ("persons", "0017_search_text"),
    ]

    operations = [
        # Nothing to fill in a new database, so a squash may drop this.
        migrations.RunPython(fill_search_text, migrations.RunPython.noop, elidable=True),
    ]
