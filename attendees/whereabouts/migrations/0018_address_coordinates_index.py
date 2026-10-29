"""Index the address coordinates together, for the nearest-neighbour bounding box.

``Address`` belongs to django-address, so the index is created through the
schema editor rather than declared on the model; the schema editor writes
the right statement for whichever database is in use.
"""
from django.db import migrations, models

INDEX = models.Index(fields=["latitude", "longitude"], name="address_coordinates_idx")


def add_index(apps, schema_editor):
    schema_editor.add_index(apps.get_model("address", "Address"), INDEX)


def remove_index(apps, schema_editor):
    schema_editor.remove_index(apps.get_model("address", "Address"), INDEX)


class Migration(migrations.Migration):
    dependencies = [
        ("whereabouts", "0017_place_subject_constraints"),
        ("address", "__latest__"),
    ]

    operations = [
        migrations.RunPython(add_index, remove_index),
    ]
