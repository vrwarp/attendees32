"""Schedulers and emergency contacts as link rows, and the backfill that made them."""
import pytest
from django.contrib.auth.models import Group

from attendees.persons.models import (
    Attendee,
    AttendeeEmergencyContact,
    AttendeeScheduler,
    Category,
    Relation,
)
from attendees.persons.models.enum import GenderEnum
from attendees.persons.services import AttendeeService
from attendees.whereabouts.models import Division, Organization


@pytest.mark.django_db
class TestAttendeeLinks:
    def setup_method(self):
        organization = Organization.objects.create(display_name="Test Organization", slug="test-org")
        group = Group.objects.create(name="Test Group")
        self.division = Division.objects.create(
            organization=organization, display_name="Test Division", slug="test-division", audience_auth_group=group
        )
        Relation.objects.create(id=0, title="self", gender=GenderEnum.UNSPECIFIED.value)
        Category.objects.create(id=0, display_name="Family")
        Category.objects.create(id=25, display_name="Non-family")

    def person(self, first):
        return Attendee.objects.create(first_name=first, last_name="Chen", division=self.division, gender="unspecified")

    def test_a_parent_schedules_the_children_and_themselves_each_once(self):
        mother, grandmother = self.person("Mei"), self.person("Lan")
        grace, joshua = self.person("Grace"), self.person("Joshua")
        grace.schedulers.set([mother, grandmother])
        joshua.schedulers.set([mother])
        # the parent has schedulers of their own, which a join would count her once per
        mother.schedulers.set([grandmother, grace])

        scheduled = list(mother.scheduling_attendees().order_by("first_name"))
        assert scheduled == [grace, joshua, mother]
        assert list(mother.scheduling_attendees(include_self=False)) == [grace, joshua]
        assert grace.can_be_scheduled_by(str(mother.id))
        assert mother.can_schedule_attendee(str(grace.id))
        assert grace.can_be_scheduled_by(str(grace.id)), "everyone schedules themselves"
        assert not joshua.can_be_scheduled_by(str(grandmother.id))
        assert not grandmother.can_schedule_attendee(str(joshua.id))

    def test_a_removed_contact_is_no_longer_a_contact(self):
        child, mother, father = self.person("Grace"), self.person("Mei"), self.person("Wei")
        child.emergency_contacts.set([mother, father])
        father.is_removed = True
        father.save()
        assert list(child.get_relative_emergency_contacts()) == [mother]
        assert child.parents_notifiers_names == "Mei Chen"

    def test_the_dead_schedule_and_answer_for_nobody(self):
        grandfather, mother, child = self.person("Guo"), self.person("Mei"), self.person("Grace")
        child.schedulers.set([mother, grandfather])
        child.emergency_contacts.set([mother, grandfather])
        grandfather.schedulers.set([mother])  # his own links stay, as a record
        grandfather.emergency_contacts.set([mother])

        AttendeeService.end_all_activities(grandfather, str(mother.id))

        assert list(child.schedulers.all()) == [mother]
        assert list(child.emergency_contacts.all()) == [mother]
        assert list(grandfather.schedulers.all()) == [mother]
        child.refresh_from_db()
        assert str(mother.id) in child.infos["updating_attendees"]

    def test_the_api_lists_and_takes_the_links_as_ids(self):
        from attendees.persons.serializers import AttendeeSerializer

        child, mother, father = self.person("Grace"), self.person("Mei"), self.person("Wei")
        child.schedulers.set([mother])
        data = AttendeeSerializer(child).data
        assert data["schedulers"] == [mother.id] and data["emergency_contacts"] == []

        serializer = AttendeeSerializer(
            child, data={"schedulers": [str(mother.id), str(father.id)], "emergency_contacts": [str(father.id)]}, partial=True
        )
        assert serializer.is_valid(), serializer.errors
        serializer.save()
        assert set(child.schedulers.all()) == {mother, father}
        assert list(child.emergency_contacts.all()) == [father]


@pytest.mark.django_db
class TestBackfill:
    """The data migration's functions, run on the live models against rows written the old way."""

    def setup_method(self):
        organization = Organization.objects.create(display_name="Test Organization", slug="test-org")
        group = Group.objects.create(name="Test Group")
        self.division = Division.objects.create(
            organization=organization, display_name="Test Division", slug="test-division", audience_auth_group=group
        )
        Relation.objects.create(id=0, title="self", gender=GenderEnum.UNSPECIFIED.value)
        Category.objects.create(id=0, display_name="Family")
        Category.objects.create(id=25, display_name="Non-family")

    @staticmethod
    def migration(name):
        import importlib

        return importlib.import_module(f"attendees.persons.migrations.{name}")

    def test_true_entries_naming_living_attendees_become_rows_and_the_keys_go(self):
        from django.apps import apps

        make = lambda first: Attendee.objects.create(first_name=first, last_name="Chen", division=self.division, gender="unspecified")
        child, mother, father, nobody = make("Grace"), make("Mei"), make("Wei"), "00000000-0000-0000-0000-000000000000"
        legacy = {
            **child.infos,
            "schedulers": {str(mother.id): True, str(father.id): False, nobody: True},
            "emergency_contacts": {str(mother.id): True, str(father.id): True},
        }
        Attendee.objects.filter(pk=child.pk).update(infos=legacy)

        self.migration("0020_links_and_viewers_backfill").copy_links(apps, None)

        assert list(child.schedulers.all()) == [mother]
        assert set(child.emergency_contacts.all()) == {mother, father}
        child.refresh_from_db()
        assert "schedulers" not in child.infos and "emergency_contacts" not in child.infos
        assert child.infos["names"]["original"] == "Grace Chen"
