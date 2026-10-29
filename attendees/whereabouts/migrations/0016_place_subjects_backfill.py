"""Name every place's subject by its typed key, and move the content type extras into their table.

A place's subject used to be a content type and a 36-character text ``object_id``. Each row's pair
becomes the one typed key it names; a row naming a subject no place can have, or one that no
longer exists, stops the migration with a list of them, to be re-pointed or deleted first.

The site picker's four columns added to ``django_content_type`` by raw SQL move to
``ContentTypeExtra``; on Postgres the columns are then dropped.
"""
from django.db import migrations

SUBJECT_FIELDS = {
    ("persons", "attendee"): "attendee",
    ("persons", "folk"): "folk",
    ("occasions", "assembly"): "assembly",
    ("whereabouts", "campus"): "campus",
    ("whereabouts", "property"): "estate",
}
EXTRA_COLUMNS = ("display_order", "genres", "endpoint", "hint")


def copy_place_subjects(apps, schema_editor):
    ContentType = apps.get_model("contenttypes", "ContentType")
    types = {ct.pk: (ct.app_label, ct.model) for ct in ContentType.objects.all()}
    unsupported, missing = [], []

    def subject_of(place, check=True):
        key = types.get(place.content_type_id)
        field = SUBJECT_FIELDS.get(key)
        if field is None:
            unsupported.append((str(place.pk), key, place.object_id))
            return None, None
        model = apps.get_model(*key)
        try:
            value = model._meta.pk.to_python(place.object_id)
        except Exception:
            value = None
        if check and (value is None or not model._default_manager.filter(pk=value).exists()):
            missing.append((str(place.pk), key, place.object_id))
            return None, None
        return field, value

    Place = apps.get_model("whereabouts", "Place")
    for place in Place._default_manager.all().iterator(chunk_size=500):
        field, value = subject_of(place)
        if field:
            setattr(place, f"{field}_id", value)
            place.save(update_fields=[field])
    if unsupported or missing:
        raise RuntimeError(
            "These places cannot be given a subject key; re-point or delete them, then migrate again. "
            f"Subjects no place can have: {unsupported[:20]}. Subjects that no longer exist: {missing[:20]}."
        )

    unsupported.clear()


def copy_content_type_extras(apps, schema_editor):
    ContentTypeExtra = apps.get_model("whereabouts", "ContentTypeExtra")
    connection = schema_editor.connection
    table = "django_content_type"
    with connection.cursor() as cursor:
        columns = {column.name for column in connection.introspection.get_table_description(cursor, table)}
        if not set(EXTRA_COLUMNS) <= columns:
            return  # a database that never had the raw columns: nothing to copy
        cursor.execute(
            f"SELECT id, {', '.join(EXTRA_COLUMNS)} FROM {table} "
            "WHERE genres IS NOT NULL OR endpoint IS NOT NULL OR hint IS NOT NULL OR display_order <> 0"
        )
        rows = cursor.fetchall()
    ContentTypeExtra._default_manager.bulk_create(
        [
            ContentTypeExtra(content_type_id=row[0], **dict(zip(EXTRA_COLUMNS, row[1:])))
            for row in rows
        ],
        ignore_conflicts=True,
    )
    if connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute("DROP INDEX IF EXISTS django_content_genres")
            for column in EXTRA_COLUMNS:
                cursor.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS {column}")


class Migration(migrations.Migration):
    dependencies = [
        ("whereabouts", "0015_content_type_extra_and_place_subjects"),
        ("contenttypes", "0002_remove_content_type_name"),
        ("persons", "0021_schema_cleanups"),
        ("occasions", "0024_schema_cleanups"),
    ]

    operations = [
        migrations.RunPython(copy_place_subjects, migrations.RunPython.noop, elidable=True),
        migrations.RunPython(copy_content_type_extras, migrations.RunPython.noop, elidable=True),
    ]
