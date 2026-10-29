import pytest
from datetime import date
from django.core.exceptions import ValidationError
from attendees.history.models import HistoryEvent
from attendees.persons.models.enum import GenderEnum
from attendees.persons.models import Attendee, Category, Relation
from attendees.whereabouts.models import Division, Organization
from django.contrib.auth.models import Group


@pytest.mark.django_db
class TestAttendee:
    def setup_method(self):
        self.organization = Organization.objects.create(display_name="Test Organization")
        self.group = Group.objects.create(name="Test Group")
        self.division = Division.objects.create(
            organization=self.organization,
            display_name="Test Division",
            slug="test-division",
            audience_auth_group=self.group
        )
        self.category = Category.objects.create(id=25, display_name="Test Category")
        self.relation = Relation.objects.create(id=0, title="test", gender=GenderEnum.UNSPECIFIED.value)

    def test_create_attendee(self):
        attendee = Attendee(
            first_name="John",
            last_name="Doe",
            gender=GenderEnum.UNSPECIFIED.value,
            division=self.division
        )
        attendee.save()
        assert attendee.id is not None

    def test_create_attendee_without_name(self):
        attendee = Attendee(
            gender=GenderEnum.UNSPECIFIED.value,
            division=self.division
        )
        with pytest.raises(ValidationError):
            attendee.clean()

    def test_attendee_age(self):
        actual_birthday = date(2000, 1, 1)
        attendee = Attendee(
            first_name="Jane",
            last_name="Smith",
            actual_birthday=actual_birthday,
            gender=GenderEnum.UNSPECIFIED.value,
            division=self.division
        )
        attendee.save()
        expected_age = (date.today() - actual_birthday).days // 365
        assert attendee.age() == expected_age

    def test_attendee_str(self):
        attendee = Attendee(
            first_name="Alice",
            last_name="Johnson",
            gender=GenderEnum.UNSPECIFIED.value,
            division=self.division
        )
        attendee.save()
        assert str(attendee) == "Alice Johnson"

    def test_attendee_division_label(self):
        attendee = Attendee(
            first_name="Division",
            last_name="Tester",
            gender=GenderEnum.UNSPECIFIED.value,
            division=self.division
        )
        attendee.save()
        assert attendee.division_label == "Test Division"

    def test_a_partial_infos_is_completed_on_save(self):
        attendee = Attendee.objects.create(
            first_name="Jane",
            last_name="Doe",
            gender=GenderEnum.UNSPECIFIED.value,
            division=self.division,
            infos={"fixed": {"grade": 9}},
        )
        attendee.refresh_from_db()
        assert attendee.infos["fixed"] == {"grade": 9}
        assert attendee.infos["names"]["original"] == "Jane Doe"
        assert attendee.infos["contacts"] == {}
        assert attendee.infos["updating_attendees"] == {}

    def test_a_null_infos_becomes_the_default(self):
        attendee = Attendee.objects.create(
            first_name="Jane",
            last_name="Doe",
            gender=GenderEnum.UNSPECIFIED.value,
            division=self.division,
            infos=None,
        )
        attendee.refresh_from_db()
        assert attendee.infos["names"]["original"] == "Jane Doe"
        assert attendee.infos["fixed"] == {"mobility": 2}

    def test_renaming_through_update_or_create_updates_searchable_names(self):
        """The datagrid serializer saves edits with update_or_create(defaults=...),
        which since Django 4.2 passes update_fields=set(defaults). The names in
        infos are derived in save() and must still be written."""
        attendee = Attendee.objects.create(
            first_name="John",
            last_name="Doe",
            gender=GenderEnum.UNSPECIFIED.value,
            division=self.division
        )

        Attendee.objects.update_or_create(id=attendee.id, defaults={"first_name": "Jonathan"})

        attendee.refresh_from_db()
        assert attendee.infos["names"]["original"] == "Jonathan Doe"

    def test_attendee_history(self):
        attendee = Attendee.objects.create(
            first_name="HistoryTracking",
            last_name="Attendee",
            gender=GenderEnum.UNSPECIFIED.value,
            division=self.division,
        )

        # 1. A snapshot is recorded when the attendee is created
        assert attendee.history.count() == 1
        assert attendee.history.first().label == "snapshot"
        assert attendee.history.first().snapshot["first_name"] == "HistoryTracking"

        # 2. and when it is updated
        attendee.first_name = "Renamed"
        attendee.save()
        assert attendee.history.count() == 2
        assert attendee.history.last().instance.first_name == "Renamed"

        # 3. merged_into is in the snapshot like any other field
        target_attendee = Attendee.objects.create(
            first_name="Target",
            last_name="Attendee",
            gender=GenderEnum.UNSPECIFIED.value,
            division=self.division,
        )
        attendee.merged_into = target_attendee
        attendee.save()
        assert attendee.history.last().instance.merged_into == target_attendee

        # 4. A soft delete is a save with is_removed set, so it is a snapshot
        attendee.delete()
        assert attendee.history.last().label == "snapshot"
        assert attendee.history.last().instance.is_removed is True

        # 5. A hard delete records the record before it goes
        key = attendee.pk
        attendee.delete(soft=False)
        gone = HistoryEvent.objects.filter(model="persons.attendee", object_id=str(key)).order_by("seq").last()
        assert gone.label == "before_delete"
        assert gone.snapshot["first_name"] == "Renamed"