"""Copy the trigger-written history into the event table, then remove the triggers and the old tables.

The 48 event tables that pghistory kept (one per tracked model, three for
memberships) and its ``pghistory_context`` table are read with plain SQL,
because their models are gone from the code. Their rows become events in
time order, each sealed onto the chain, and the first anchor is written.
The triggers and their functions exist only on PostgreSQL and are dropped
there; the old tables are dropped on every backend. A database that never
had them, such as a fresh one, has nothing to copy.
"""
import json

from django.conf import settings
from django.db import migrations
from django.utils import timezone

# pghistory table -> (the tracked model, the column holding the record's key)
TABLES = {
    "occasions_assemblieshistory": ("occasions.assembly", "pgh_obj_id"),
    "occasions_attendanceshistory": ("occasions.attendance", "pgh_obj_id"),
    "occasions_calendarhistory": ("schedule.calendar", "pgh_obj_id"),
    "occasions_calendarrelationhistory": ("schedule.calendarrelation", "pgh_obj_id"),
    "occasions_charactershistory": ("occasions.character", "pgh_obj_id"),
    "occasions_crontabschedulehistory": ("django_celery_beat.crontabschedule", "pgh_obj_id"),
    "occasions_eventhistory": ("schedule.event", "pgh_obj_id"),
    "occasions_eventrelationhistory": ("schedule.eventrelation", "pgh_obj_id"),
    "occasions_gatheringshistory": ("occasions.gathering", "pgh_obj_id"),
    "occasions_intervalschedulehistory": ("django_celery_beat.intervalschedule", "pgh_obj_id"),
    "occasions_meetshistory": ("occasions.meet", "pgh_obj_id"),
    "occasions_message_templateshistory": ("occasions.messagetemplate", "pgh_obj_id"),
    "occasions_occurrencehistory": ("schedule.occurrence", "pgh_obj_id"),
    "occasions_periodictaskhistory": ("django_celery_beat.periodictask", "pgh_obj_id"),
    "occasions_priceshistory": ("occasions.price", "pgh_obj_id"),
    "occasions_rulehistory": ("schedule.rule", "pgh_obj_id"),
    "occasions_teamshistory": ("occasions.team", "pgh_obj_id"),
    "persons_attendeeshistory": ("persons.attendee", "pgh_obj_id"),
    "persons_attending_meetshistory": ("persons.attendingmeet", "pgh_obj_id"),
    "persons_attendingshistory": ("persons.attending", "pgh_obj_id"),
    "persons_categorieshistory": ("persons.category", "pgh_obj_id"),
    "persons_folk_attendeeshistory": ("persons.folkattendee", "pgh_obj_id"),
    "persons_folkshistory": ("persons.folk", "pgh_obj_id"),
    "persons_noteshistory": ("persons.note", "pgh_obj_id"),
    "persons_pastshistory": ("persons.past", "pgh_obj_id"),
    "persons_registrationshistory": ("persons.registration", "pgh_obj_id"),
    "persons_relationshistory": ("persons.relation", "pgh_obj_id"),
    "users_emailaddresshistory": ("account.emailaddress", "pgh_obj_id"),
    "users_emailconfirmationhistory": ("account.emailconfirmation", "pgh_obj_id"),
    "users_grouppermissionshistory": ("auth.group_permissions", "id"),
    "users_groupshistory": ("auth.group", "pgh_obj_id"),
    "users_menu_auth_groupshistory": ("users.menuauthgroup", "pgh_obj_id"),
    "users_menushistory": ("users.menu", "pgh_obj_id"),
    "users_permissionshistory": ("auth.permission", "pgh_obj_id"),
    "users_usergroupshistory": ("users.user_groups", "id"),
    "users_userhistory": ("users.user", "pgh_obj_id"),
    "users_userpermissionshistory": ("users.user_user_permissions", "id"),
    "whereabouts_addresshistory": ("address.address", "pgh_obj_id"),
    "whereabouts_campuseshistory": ("whereabouts.campus", "pgh_obj_id"),
    "whereabouts_countryhistory": ("address.country", "pgh_obj_id"),
    "whereabouts_divisionshistory": ("whereabouts.division", "pgh_obj_id"),
    "whereabouts_localityhistory": ("address.locality", "pgh_obj_id"),
    "whereabouts_organizationshistory": ("whereabouts.organization", "pgh_obj_id"),
    "whereabouts_placeshistory": ("whereabouts.place", "pgh_obj_id"),
    "whereabouts_propertieshistory": ("whereabouts.property", "pgh_obj_id"),
    "whereabouts_roomshistory": ("whereabouts.room", "pgh_obj_id"),
    "whereabouts_statehistory": ("address.state", "pgh_obj_id"),
    "whereabouts_suiteshistory": ("whereabouts.suite", "pgh_obj_id"),
}
CONTEXT_TABLE = "pghistory_context"


def copy_contexts(apps, connection, present):
    """``pghistory_context`` rows as ``history_context`` rows; returns old id -> new id."""
    HistoryContext = apps.get_model("history", "HistoryContext")
    User = apps.get_model(settings.AUTH_USER_MODEL)
    if CONTEXT_TABLE not in present:
        return {}
    usernames = dict(User.objects.values_list("pk", "username"))
    rows, old_ids = [], []
    with connection.cursor() as cursor:
        cursor.execute(f'SELECT id, created_at, metadata FROM "{CONTEXT_TABLE}" ORDER BY created_at')
        for old_id, created_at, metadata in cursor.fetchall():
            if isinstance(metadata, str):
                metadata = json.loads(metadata) if metadata else {}
            metadata = metadata or {}
            user = metadata.get("user")
            user_id = int(user) if user is not None and str(user).isdigit() and int(user) in usernames else None
            user_name = usernames[user_id] if user_id else (f"user {user}" if user else "")
            label = str(metadata.get("url") or metadata.get("modifier") or "")[:255]
            rows.append(HistoryContext(created_at=created_at, label=label, user_id=user_id, user_name=user_name))
            old_ids.append(str(old_id))
    created = HistoryContext.objects.bulk_create(rows, batch_size=1000)
    return {old: row.pk for old, row in zip(old_ids, created)}


def copy_history(apps, schema_editor):
    from attendees.history.canonical import GENESIS, chain_key, mac_for, plain

    connection = schema_editor.connection
    HistoryEvent = apps.get_model("history", "HistoryEvent")
    HistoryHead = apps.get_model("history", "HistoryHead")
    if not HistoryHead.objects.filter(pk=1).exists():
        HistoryHead.objects.create(pk=1, seq=0, mac=GENESIS)
    present = set(connection.introspection.table_names())
    tables = [table for table in TABLES if table in present]
    if not tables:
        return
    contexts = copy_contexts(apps, connection, present)

    rows = []
    for table in tables:
        model_label, id_column = TABLES[table]
        try:
            model = apps.get_model(model_label)
        except LookupError:
            model = None
        converters = {}
        if model is not None:
            for field in model._meta.concrete_fields:
                if hasattr(field, "from_db_value"):
                    converters[field.column] = field
        with connection.cursor() as cursor:
            cursor.execute(f'SELECT * FROM "{table}"')
            columns = [column[0] for column in cursor.description]
            while True:
                chunk = cursor.fetchmany(5000)
                if not chunk:
                    break
                for values in chunk:
                    record = dict(zip(columns, values))
                    snapshot = {}
                    for column, value in record.items():
                        if column.startswith("pgh_"):
                            continue
                        field = converters.get(column)
                        if field is not None and value is not None:
                            value = field.from_db_value(value, None, connection)
                        snapshot[column] = plain(value)
                    label = "before_delete" if str(record["pgh_label"]).endswith((".before_delete", ".remove")) else "snapshot"
                    context_id = contexts.get(str(record["pgh_context_id"])) if record.get("pgh_context_id") else None
                    rows.append((record["pgh_created_at"], table, record["pgh_id"], model_label, str(record[id_column]), label, context_id, snapshot))
    rows.sort(key=lambda row: (row[0], row[1], row[2]))

    key = chain_key()
    head = HistoryHead.objects.get(pk=1)
    prev, seq, batch = head.mac, head.seq, []
    for created_at, _table, _pgh_id, model_label, object_id, label, context_id, snapshot in rows:
        seq += 1
        mac = mac_for(prev, model_label, object_id, label, created_at, snapshot, key=key)
        batch.append(
            HistoryEvent(
                seq=seq,
                model=model_label,
                object_id=object_id,
                label=label,
                created_at=created_at,
                context_id=context_id,
                snapshot=snapshot,
                prev_mac=prev,
                mac=mac,
            )
        )
        prev = mac
        if len(batch) >= 1000:
            HistoryEvent.objects.bulk_create(batch)
            batch = []
    if batch:
        HistoryEvent.objects.bulk_create(batch)
    HistoryHead.objects.filter(pk=1).update(seq=seq, mac=prev)

    anchor_file = getattr(settings, "HISTORY_ANCHOR_FILE", "")
    if anchor_file:
        with open(anchor_file, "a", encoding="utf-8") as anchors:
            anchors.write(f"{seq} {prev} {timezone.now().isoformat()}\n")


def baseline_rows(apps, schema_editor):
    """A first snapshot of every live row of a tracked model that has no event.

    The tables Phases 2 and 4 added were never tracked by pghistory, and a
    few framework rows predate the triggers; without a first snapshot the
    nightly replay would report them for ever. This runs through the
    application's own writer, on the real models, at the end of the chain.
    """
    from attendees.history import context
    from attendees.history.tracking import baseline_rows as record_rows_without_history

    with context("migrate history.0002: first snapshot of rows that had no history"):
        record_rows_without_history(using=schema_editor.connection.alias)


def drop_old_history(apps, schema_editor):
    """The triggers, their functions and the old tables; nothing writes them any more."""
    connection = schema_editor.connection
    with connection.cursor() as cursor:
        if connection.vendor == "postgresql":
            cursor.execute(
                "SELECT trigger_name, event_object_table FROM information_schema.triggers "
                "WHERE trigger_name LIKE 'pgtrigger_%' GROUP BY trigger_name, event_object_table"
            )
            for name, table in cursor.fetchall():
                cursor.execute(f'DROP TRIGGER IF EXISTS "{name}" ON "{table}"')
            cursor.execute(
                "SELECT p.proname, pg_get_function_identity_arguments(p.oid) FROM pg_proc p "
                "JOIN pg_namespace n ON n.oid = p.pronamespace WHERE n.nspname = current_schema() "
                "AND (p.proname LIKE '%pgtrigger%' OR p.proname LIKE '%pgh_%')"
            )
            for name, arguments in cursor.fetchall():
                cursor.execute(f'DROP FUNCTION IF EXISTS "{name}"({arguments}) CASCADE')
        cascade = " CASCADE" if connection.vendor == "postgresql" else ""
        for table in list(TABLES) + [CONTEXT_TABLE]:
            cursor.execute(f'DROP TABLE IF EXISTS "{table}"{cascade}')


class Migration(migrations.Migration):
    dependencies = [
        ("history", "0001_initial"),
        ("occasions", "0024_schema_cleanups"),
        ("persons", "0023_remove_reciprocal_ids"),
        ("users", "0016_user_tracked_manager"),
        ("whereabouts", "0017_place_subject_constraints"),
        # The baseline reads every tracked table through the current models, so every app they
        # belong to must be fully migrated first.
        ("account", "__latest__"),
        ("address", "__latest__"),
        ("auth", "__latest__"),
        ("contenttypes", "__latest__"),
        ("django_celery_beat", "__latest__"),
        ("schedule", "__latest__"),
    ]

    operations = [
        migrations.RunPython(copy_history, migrations.RunPython.noop),
        migrations.RunPython(drop_old_history, migrations.RunPython.noop),
        migrations.RunPython(baseline_rows, migrations.RunPython.noop),
    ]
