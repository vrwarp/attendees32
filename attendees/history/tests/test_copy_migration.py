"""The one-time copy of pghistory's tables into the event table, run against tables built here."""
import importlib
import json
import uuid

import pytest
from django.apps import apps
from django.db import connection
from partial_date import PartialDate

from attendees.history import ledger
from attendees.history.models import HistoryEvent, HistoryHead
from attendees.persons.models import Past

migration = importlib.import_module("attendees.history.migrations.0002_copy_from_pghistory")

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.skipif(connection.vendor != "postgresql", reason="pghistory's tables only ever existed on PostgreSQL"),
]


class Editor:
    def __init__(self, connection):
        self.connection = connection


@pytest.fixture
def old_tables(user):
    """Three of pghistory's tables with a few rows: a group, its membership, and a past."""
    context_id = uuid.uuid4()
    past_id = uuid.uuid4()
    when = Past._meta.get_field("when").get_prep_value(PartialDate("2024-05"))
    with connection.cursor() as cursor:
        cursor.execute(
            "CREATE TABLE pghistory_context (id uuid PRIMARY KEY, created_at timestamptz NOT NULL, "
            "updated_at timestamptz NOT NULL, metadata jsonb NOT NULL)"
        )
        cursor.execute(
            "INSERT INTO pghistory_context VALUES (%s, '2024-05-01 10:00:00+00', '2024-05-01 10:00:00+00', %s)",
            [context_id, json.dumps({"url": "/persons/api/attendees/", "user": user.pk})],
        )
        cursor.execute(
            "CREATE TABLE users_groupshistory (pgh_id bigserial PRIMARY KEY, pgh_created_at timestamptz NOT NULL, "
            "pgh_label text NOT NULL, pgh_obj_id integer, pgh_context_id uuid, id integer NOT NULL, name varchar(150) NOT NULL)"
        )
        cursor.execute(
            "INSERT INTO users_groupshistory (pgh_created_at, pgh_label, pgh_obj_id, pgh_context_id, id, name) VALUES "
            "('2024-05-01 10:00:01+00', 'group.snapshot', 77, %s, 77, 'Ushers'), "
            "('2024-05-01 10:00:02+00', 'group.snapshot', 77, %s, 77, 'Head ushers'), "
            "('2024-05-02 09:00:00+00', 'group.before_delete', 77, NULL, 77, 'Head ushers')",
            [context_id, context_id],
        )
        cursor.execute(
            "CREATE TABLE users_usergroupshistory (pgh_id bigserial PRIMARY KEY, pgh_created_at timestamptz NOT NULL, "
            "pgh_label text NOT NULL, pgh_context_id uuid, id integer NOT NULL, user_id integer NOT NULL, group_id integer NOT NULL)"
        )
        cursor.execute(
            "INSERT INTO users_usergroupshistory (pgh_created_at, pgh_label, pgh_context_id, id, user_id, group_id) VALUES "
            "('2024-05-01 10:00:01.5+00', 'group.add', %s, 5, %s, 77), ('2024-05-02 08:00:00+00', 'group.remove', NULL, 5, %s, 77)",
            [context_id, user.pk, user.pk],
        )
        cursor.execute(
            "CREATE TABLE persons_pastshistory (pgh_id bigserial PRIMARY KEY, pgh_created_at timestamptz NOT NULL, "
            'pgh_label text NOT NULL, pgh_obj_id uuid, pgh_context_id uuid, id uuid NOT NULL, "when" timestamptz, infos jsonb, '
            "display_name varchar(50))"
        )
        cursor.execute(
            'INSERT INTO persons_pastshistory (pgh_created_at, pgh_label, pgh_obj_id, pgh_context_id, id, "when", infos, display_name) '
            "VALUES ('2024-05-01 11:00:00+00', 'past.snapshot', %s, %s, %s, %s, %s, 'Baptized')",
            [past_id, context_id, past_id, when, json.dumps({"comment": "記錄"})],
        )
    return {"past_id": past_id}


def test_the_copy_turns_the_rows_into_sealed_events_in_time_order(old_tables, user):
    head_before = HistoryHead.objects.get(pk=1).seq
    migration.copy_history(apps, Editor(connection))

    events = list(HistoryEvent.objects.filter(seq__gt=head_before).order_by("seq"))
    assert [(event.model, event.label) for event in events] == [
        ("auth.group", "snapshot"),
        ("users.user_groups", "snapshot"),
        ("auth.group", "snapshot"),
        ("persons.past", "snapshot"),
        ("users.user_groups", "before_delete"),
        ("auth.group", "before_delete"),
    ]
    first = events[0]
    assert first.snapshot == {"id": 77, "name": "Ushers"}
    assert first.object_id == "77"
    assert first.created_at.isoformat().startswith("2024-05-01T10:00:01")
    assert first.context.label == "/persons/api/attendees/"
    assert first.context.user == user and first.context.user_name == user.username
    assert events[-1].context is None
    membership = events[1]
    assert membership.snapshot == {"id": 5, "user_id": user.pk, "group_id": 77}
    past = events[3]
    assert past.object_id == str(old_tables["past_id"])
    assert past.snapshot["when"] == "2024-05"  # through the field's own conversion, as a live snapshot would be
    assert past.snapshot["infos"] == {"comment": "記錄"}
    assert past.instance.when == PartialDate("2024-05")

    audit = ledger.verify(full=False)
    assert audit.ok, audit.report

    migration.drop_old_history(apps, Editor(connection))
    tables = set(connection.introspection.table_names())
    assert not tables & {"users_groupshistory", "users_usergroupshistory", "persons_pastshistory", "pghistory_context"}


def test_a_database_without_the_old_tables_has_nothing_to_copy():
    head_before = HistoryHead.objects.get(pk=1).seq
    migration.copy_history(apps, Editor(connection))
    assert HistoryHead.objects.get(pk=1).seq == head_before
