"""Copy each relation's reciprocal ids, kept in a Postgres array, into the reciprocals table."""
from django.db import migrations


def copy_reciprocals(apps, schema_editor):
    Relation = apps.get_model("persons", "Relation")
    through = Relation.reciprocals.through
    known = set(Relation._default_manager.values_list("pk", flat=True))
    rows = []
    for relation in Relation._default_manager.all():
        for other in relation.reciprocal_ids or []:
            if other in known:
                rows.append(through(from_relation_id=relation.pk, to_relation_id=other))
    through._default_manager.bulk_create(rows, ignore_conflicts=True)


class Migration(migrations.Migration):
    dependencies = [
        ("persons", "0021_schema_cleanups"),
    ]

    operations = [
        migrations.RunPython(copy_reciprocals, migrations.RunPython.noop, elidable=True),
    ]
