from django.db import migrations

from attendees.utils.search_text import search_text_of

BATCH = 500


def fill_search_text(apps, schema_editor):
    """Fill the new column for existing rows with the same function save() uses."""
    for label in ("Attendance", "Gathering"):
        model = apps.get_model("occasions", label)
        changed = []
        for instance in model._base_manager.all().iterator(chunk_size=BATCH):
            instance.search_text = search_text_of(instance.infos)
            changed.append(instance)
            if len(changed) >= BATCH:
                model._base_manager.bulk_update(changed, ["search_text"])
                changed = []
        if changed:
            model._base_manager.bulk_update(changed, ["search_text"])


class Migration(migrations.Migration):

    dependencies = [
        ("occasions", "0020_search_text"),
    ]

    operations = [
        # Nothing to fill in a new database, so a squash may drop this.
        migrations.RunPython(fill_search_text, migrations.RunPython.noop, elidable=True),
    ]
