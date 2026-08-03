"""Make the Sync page reachable.

``RouteGuard`` authorizes by looking the request's ``url_name`` up in the
``Menu`` table and checking the caller's groups against ``MenuAuthGroup``. A
view with no row is a bare 403 for everybody, superusers included, and the nav
is rendered from the same table -- so without this migration the page exists but
nobody can see it or reach it.

Granted to each organization's configured data-admin groups, which is where the
project already keeps the answer to "who may change data" (``Organization.infos``
``["data_admins"]``). An organization with none configured is skipped with a
note rather than failing the migration: a deployment that has not set that up
yet should still be able to migrate.
"""

from django.db import migrations

PAGE = {
    "category": "main",
    "html_type": "a",
    "urn": "/pcosync/sync/",
    "url_name": "pco_sync_view",
    "display_name": "Planning Center 同步",
    "display_order": 4000,
    "infos": {"class": "nav-link", "title": "Planning Center sync"},
}

# The API rows are keyed by the viewset class name, matching the existing
# category="API" rows in fixtures/db_seed.json.
APIS = [
    {
        "urn": "/pcosync/api/sync_runs/",
        "url_name": "ApiPcoSyncRunsViewSet",
        "display_name": "api_pco_sync_runs",
    },
    {
        "urn": "/pcosync/api/divergences/",
        "url_name": "ApiPcoDivergencesViewSet",
        "display_name": "api_pco_divergences",
    },
]


def seed(apps, schema_editor):
    Organization = apps.get_model("whereabouts", "Organization")
    Menu = apps.get_model("users", "Menu")
    MenuAuthGroup = apps.get_model("users", "MenuAuthGroup")
    Group = apps.get_model("auth", "Group")

    for organization in Organization.objects.all():
        infos = organization.infos or {}
        group_names = infos.get("data_admins") or []
        groups = list(Group.objects.filter(name__in=group_names))
        if not groups:
            print(
                f"\n  pcosync: {organization.slug or organization.pk} has no "
                f"data_admins groups, so the sync page is not granted to "
                f"anyone yet. Add a Menu/MenuAuthGroup row when you configure "
                f"the sync."
            )

        rows = [dict(PAGE)] + [
            {**api, "category": "API", "html_type": "", "display_order": 4000,
             "infos": {}}
            for api in APIS
        ]
        for row in rows:
            menu, created = Menu.objects.get_or_create(
                organization=organization,
                url_name=row["url_name"],
                category=row["category"],
                defaults={
                    "urn": row["urn"],
                    "html_type": row["html_type"],
                    "display_name": row["display_name"],
                    "display_order": row["display_order"],
                    "infos": row["infos"],
                    "parent": None,
                    # mptt would normally maintain these, but a historical model
                    # has no MPTT manager, so a new root is written by hand.
                    "lft": 1, "rght": 2, "tree_id": _next_tree_id(Menu),
                    "level": 0,
                },
            )
            for group in groups:
                MenuAuthGroup.objects.get_or_create(
                    menu=menu, auth_group=group,
                    defaults={"read": True, "write": True},
                )


def unseed(apps, schema_editor):
    Menu = apps.get_model("users", "Menu")
    MenuAuthGroup = apps.get_model("users", "MenuAuthGroup")
    url_names = [PAGE["url_name"]] + [api["url_name"] for api in APIS]
    menus = Menu.objects.filter(url_name__in=url_names)
    MenuAuthGroup.objects.filter(menu__in=menus).delete()
    menus.delete()


def _next_tree_id(Menu):
    highest = Menu.objects.order_by("-tree_id").values_list(
        "tree_id", flat=True).first()
    return (highest or 0) + 1


class Migration(migrations.Migration):

    dependencies = [
        ("pcosync", "0001_initial"),
        ("users", "0004_menu_auth_group"),
        ("whereabouts", "0003_organization"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
