"""Copy the links and grants kept in JSON into their tables, then drop the keys.

``Attendee.infos["schedulers"]`` and ``["emergency_contacts"]`` were maps of attendee id to true
or false; a true entry naming an attendee that still exists becomes a row. The ``show_secret`` map
on pasts, notes and folk memberships named the attendees allowed to see the record, and the key
``all_counselors_`` opened it to every counselor; those become ``viewers`` and
``counselors_may_view``. The keys are removed afterwards so nothing is kept in two places. The
history tables keep their snapshots as they were written.
"""
from django.db import migrations

BATCH = 500
ALL_COUNSELORS = "all_counselors_"


def _named(mapping):
    """The attendee ids a map names with a true value."""
    if not isinstance(mapping, dict):
        return []
    return [key for key, value in mapping.items() if value and key != ALL_COUNSELORS]


def _flush(model, rows, fields):
    if rows:
        model._default_manager.bulk_update(rows, fields, batch_size=BATCH)
    rows.clear()


def copy_links(apps, schema_editor):
    Attendee = apps.get_model("persons", "Attendee")
    AttendeeScheduler = apps.get_model("persons", "AttendeeScheduler")
    AttendeeEmergencyContact = apps.get_model("persons", "AttendeeEmergencyContact")
    known = {str(pk) for pk in Attendee._default_manager.values_list("pk", flat=True)}

    schedulers, contacts, stripped = [], [], []
    for attendee in Attendee._default_manager.iterator(chunk_size=BATCH):
        infos = attendee.infos
        if not isinstance(infos, dict):
            continue
        for other in _named(infos.get("schedulers")):
            if other in known:
                schedulers.append(AttendeeScheduler(attendee_id=attendee.pk, scheduler_id=other))
        for other in _named(infos.get("emergency_contacts")):
            if other in known:
                contacts.append(AttendeeEmergencyContact(attendee_id=attendee.pk, contact_id=other))
        if "schedulers" in infos or "emergency_contacts" in infos:
            infos.pop("schedulers", None)
            infos.pop("emergency_contacts", None)
            stripped.append(attendee)
            if len(stripped) >= BATCH:
                _flush(Attendee, stripped, ["infos"])
    _flush(Attendee, stripped, ["infos"])
    AttendeeScheduler._default_manager.bulk_create(schedulers, batch_size=BATCH, ignore_conflicts=True)
    AttendeeEmergencyContact._default_manager.bulk_create(contacts, batch_size=BATCH, ignore_conflicts=True)


def copy_viewers(apps, schema_editor):
    Attendee = apps.get_model("persons", "Attendee")
    known = {str(pk) for pk in Attendee._default_manager.values_list("pk", flat=True)}

    for name in ("Past", "Note", "FolkAttendee"):
        Model = apps.get_model("persons", name)
        through = Model.viewers.through
        record_field = f"{Model._meta.model_name}_id"
        viewers, stripped = [], []
        for record in Model._default_manager.iterator(chunk_size=BATCH):
            infos = record.infos
            if not isinstance(infos, dict) or "show_secret" not in infos:
                continue
            secret = infos.pop("show_secret")
            if isinstance(secret, dict) and secret.get(ALL_COUNSELORS):
                record.counselors_may_view = True
            for other in _named(secret):
                if other in known:
                    viewers.append(through(**{record_field: record.pk, "attendee_id": other}))
            stripped.append(record)
            if len(stripped) >= BATCH:
                _flush(Model, stripped, ["infos", "counselors_may_view"])
        _flush(Model, stripped, ["infos", "counselors_may_view"])
        through._default_manager.bulk_create(viewers, batch_size=BATCH, ignore_conflicts=True)


class Migration(migrations.Migration):
    dependencies = [
        ("persons", "0019_links_and_viewers"),
    ]

    operations = [
        migrations.RunPython(copy_links, migrations.RunPython.noop, elidable=True),
        migrations.RunPython(copy_viewers, migrations.RunPython.noop, elidable=True),
    ]
