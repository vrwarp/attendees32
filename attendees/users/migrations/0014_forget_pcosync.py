"""Takes the Planning Center sync out of a database that ran it.

The pcosync app is gone from this fork. Its own migration seeded a menu row
per organization and two API rows, which would be dead links now, and its
tables hold nothing the rest of the system refers to. Both go here. A
database that never ran pcosync has none of them, and nothing happens.
"""
from django.db import migrations

URL_NAMES = ("pco_sync_view", "ApiPcoSyncRunsViewSet", "ApiPcoDivergencesViewSet")
TABLES = (
    "pcosync_divergenceshistory",
    "pcosync_household_linkshistory",
    "pcosync_person_linkshistory",
    "pcosync_divergences",
    "pcosync_household_links",
    "pcosync_person_links",
    "pcosync_runs",
)


def forget_menus(apps, schema_editor):
    Menu = apps.get_model("users", "Menu")
    MenuAuthGroup = apps.get_model("users", "MenuAuthGroup")
    menus = Menu.objects.filter(url_name__in=URL_NAMES)
    MenuAuthGroup.objects.filter(menu__in=menus).delete()
    menus.delete()


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0013_remove_emailaddressproxy_emailaddress_snapshot_update_and_more"),
    ]

    operations = [
        migrations.RunPython(forget_menus, migrations.RunPython.noop),
        migrations.RunSQL(
            [f"DROP TABLE IF EXISTS {table} CASCADE;" for table in TABLES],
            migrations.RunSQL.noop,
        ),
    ]
