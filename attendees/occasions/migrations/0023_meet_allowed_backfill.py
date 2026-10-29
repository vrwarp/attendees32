"""Copy a meet's allowed groups and pages out of its JSON into the tables, then drop the keys.

``Meet.infos["allowed_groups"]`` named auth groups; a name that is a group becomes a row.
``["allowed_models"]`` listed the pages the meet is shown on; a meet without the key was shown on
none, and stays that way.
"""
from django.db import migrations

BATCH = 500
PAGES = ("gathering", "attendingmeet", "attendance", "eventrelation")


def copy_allowed(apps, schema_editor):
    Meet = apps.get_model("occasions", "Meet")
    Group = apps.get_model("auth", "Group")
    MeetAllowedModel = apps.get_model("occasions", "MeetAllowedModel")
    through = Meet.allowed_groups.through
    groups = {group.name: group.pk for group in Group._default_manager.all()}

    group_rows, page_rows, stripped = [], [], []
    for meet in Meet._default_manager.iterator(chunk_size=BATCH):
        infos = meet.infos
        if not isinstance(infos, dict):
            continue
        for name in infos.get("allowed_groups") or []:
            if name in groups:
                group_rows.append(through(meet_id=meet.pk, group_id=groups[name]))
        for page in infos.get("allowed_models") or []:
            if page in PAGES:
                page_rows.append(MeetAllowedModel(meet_id=meet.pk, model=page))
        if "allowed_groups" in infos or "allowed_models" in infos:
            infos.pop("allowed_groups", None)
            infos.pop("allowed_models", None)
            stripped.append(meet)
    through._default_manager.bulk_create(group_rows, batch_size=BATCH, ignore_conflicts=True)
    MeetAllowedModel._default_manager.bulk_create(page_rows, batch_size=BATCH, ignore_conflicts=True)
    if stripped:
        Meet._default_manager.bulk_update(stripped, ["infos"], batch_size=BATCH)


class Migration(migrations.Migration):
    dependencies = [
        ("occasions", "0022_meet_allowed_groups_and_pages"),
    ]

    operations = [
        migrations.RunPython(copy_allowed, migrations.RunPython.noop, elidable=True),
    ]
