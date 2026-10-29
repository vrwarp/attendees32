"""Rebuilding the tables from the history: as of a moment, and against the live tables."""
import time

import pytest
from django.contrib.auth.models import Group
from django.db import connection, connections
from django.utils import timezone

from attendees.history import replay
from attendees.persons.models import Attendee

pytestmark = pytest.mark.django_db


def test_reconstruct_gives_the_record_as_it_was_at_a_moment():
    group = Group.objects.create(name="Before")
    moment = timezone.now()
    time.sleep(0.01)
    group.name = "After"
    group.save()
    assert replay.reconstruct(as_of=moment)["auth.group"][str(group.pk)]["name"] == "Before"
    assert replay.reconstruct()["auth.group"][str(group.pk)]["name"] == "After"
    group.delete()
    assert str(group.pk) not in replay.reconstruct().get("auth.group", {})


def test_compare_is_clean_when_every_write_went_through_the_writer(make_attendee):
    attendee = make_attendee()
    attendee.first_name = "Amazing"
    attendee.save()
    Attendee.objects.filter(pk=attendee.pk).update(last_name="Lin")
    assert replay.compare() == {}


def test_compare_finds_writes_that_bypassed_the_writer():
    group = Group.objects.create(name="Ushers")
    with connection.cursor() as cursor:
        cursor.execute("UPDATE auth_group SET name = %s WHERE id = %s", ["Sneaky", group.pk])
        cursor.execute("INSERT INTO auth_group (name) VALUES (%s)", ["Ghost"])
    found = replay.compare()["auth.group"]
    assert found["changed"] == {str(group.pk): {"name": ("Ushers", "Sneaky")}}
    assert found["extra"] == [str(Group.objects.get(name="Ghost").pk)]
    assert found["missing"] == []
    with connection.cursor() as cursor:
        cursor.execute("DELETE FROM auth_group WHERE id = %s", [group.pk])
    assert replay.compare()["auth.group"]["missing"] == [str(group.pk)]


def test_write_sqlite_rebuilds_the_tables_as_of_a_moment_into_a_file(tmp_path, make_attendee):
    attendee = make_attendee()
    attendee.first_name = "Amazing"
    attendee.save()
    moment = timezone.now()
    time.sleep(0.01)
    attendee.last_name = "Later"
    attendee.save()

    path = tmp_path / "replay.sqlite3"
    counts = replay.write_sqlite(path, as_of=moment)
    alias = replay.REPLAY_ALIAS
    try:
        rebuilt = Attendee.objects.using(alias).get(pk=attendee.pk)
        assert (rebuilt.first_name, rebuilt.last_name) == ("Amazing", "Chen")
        assert rebuilt.modified == attendee.history.filter(created_at__lte=moment).last().instance.modified
        assert rebuilt.division.display_name == "Test Division"
        assert counts["persons.attendee"] == 1
    finally:
        connections[alias].close()
    with pytest.raises(FileExistsError):
        replay.write_sqlite(path)
