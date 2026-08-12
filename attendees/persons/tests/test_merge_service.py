"""Merging one attendee into another.

The three things worth pinning are the ones a merge gets wrong quietly: that
the loser's attendance actually moves rather than being stranded on a
tombstone, that a duplicate row is retired instead of raising against the
partial unique constraints, and that following a chain terminates -- including
when somebody has edited it into a circle.
"""

import pytest
from datetime import datetime, timedelta, timezone
from django.contrib.auth.models import Group
from django.contrib.contenttypes.models import ContentType

from attendees.occasions.models import Assembly, Character, Meet
from attendees.persons.models import (
    Attendee,
    Attending,
    Category,
    Folk,
    FolkAttendee,
    Registration,
    Relation,
)
from attendees.persons.models.enum import GenderEnum
from attendees.persons.services.merge_service import (
    AttendeeMergeService,
    MergeRefused,
)
from attendees.users.models import User
from attendees.whereabouts.models import Division, Organization


@pytest.mark.django_db
class TestAttendeeMergeService:
    def setup_method(self):
        self.organization = Organization.objects.create(
            display_name="Test Organization", slug="test-org"
        )
        self.group = Group.objects.create(name="Test Group")
        self.division = Division.objects.create(
            organization=self.organization,
            display_name="Test Division",
            slug="test-division",
            audience_auth_group=self.group,
        )
        self.category = Category.objects.create(id=25, display_name="Test Category")
        self.family_category = Category.objects.create(id=0, display_name="Family")
        self.relation = Relation.objects.create(
            id=0, title="test relation", gender=GenderEnum.UNSPECIFIED.value
        )
        self.assembly = Assembly.objects.create(
            display_name="Test Assembly",
            slug="test-assembly",
            division=self.division,
            category=self.category,
        )

        self.keeper = Attendee.objects.create(
            first_name="Ava", last_name="Chen", division=self.division, gender="unspecified"
        )
        self.duplicate = Attendee.objects.create(
            first_name="Ava", last_name="Chen", division=self.division, gender="unspecified"
        )

    def test_moves_attendance_to_the_survivor(self):
        attending = Attending.objects.create(attendee=self.duplicate)

        AttendeeMergeService.merge(self.duplicate, self.keeper)

        attending.refresh_from_db()
        assert attending.attendee_id == self.keeper.id
        assert not attending.is_removed

    def test_retires_a_row_the_survivor_already_has(self):
        """The pair *is* the duplication, and the constraint says so.

        `(attendee, registration)` is unique where `is_removed=False`, so
        moving this row would raise. Leaving it alone would be worse: a live
        attendance pointing at a tombstone.
        """
        registration = Registration.objects.create(
            registrant=self.keeper, assembly=self.assembly
        )
        theirs = Attending.objects.create(attendee=self.keeper, registration=registration)
        ours = Attending.objects.create(attendee=self.duplicate, registration=registration)

        AttendeeMergeService.merge(self.duplicate, self.keeper)

        ours.refresh_from_db()
        theirs.refresh_from_db()
        assert ours.is_removed
        assert not theirs.is_removed
        assert theirs.attendee_id == self.keeper.id

    def test_moves_family_membership(self):
        folk = Folk.objects.create(
            category=self.family_category, division=self.division, display_name="Chen family"
        )
        membership = FolkAttendee.objects.create(
            folk=folk, attendee=self.duplicate, role=self.relation
        )

        AttendeeMergeService.merge(self.duplicate, self.keeper)

        membership.refresh_from_db()
        assert membership.attendee_id == self.keeper.id

    def test_keeps_the_loser_as_a_tombstone(self):
        AttendeeMergeService.merge(self.duplicate, self.keeper)

        # Not deleted: an id that has been handed out has to stay followable,
        # and a merge performed by mistake has to be answerable.
        buried = Attendee.all_objects.get(pk=self.duplicate.pk)
        assert buried.is_removed
        assert buried.merged_into_id == self.keeper.id
        assert not Attendee.objects.filter(pk=self.duplicate.pk).exists()

    def test_follows_a_chain_to_its_end(self):
        third = Attendee.objects.create(
            first_name="Ava", last_name="Chen", division=self.division, gender="unspecified"
        )
        # Sunday: this one into that one. Wednesday: that one into a third.
        AttendeeMergeService.merge(self.duplicate, self.keeper)
        AttendeeMergeService.merge(self.keeper, third)

        survivor, was_merged = AttendeeMergeService.resolve(self.duplicate.pk)
        assert was_merged
        assert survivor.id == third.id

    def test_says_gone_when_the_trail_ends_nowhere(self):
        AttendeeMergeService.merge(self.duplicate, self.keeper)
        self.keeper.is_removed = True
        self.keeper.save(update_fields=["is_removed"])

        survivor, was_merged = AttendeeMergeService.resolve(self.duplicate.pk)
        assert was_merged
        assert survivor is None

    def test_a_circle_is_gone_rather_than_a_hang(self):
        AttendeeMergeService.merge(self.duplicate, self.keeper)
        # Only reachable by editing data by hand, which is exactly when it
        # happens. The bound is what makes it an answer instead of a hang.
        self.keeper.merged_into = self.duplicate
        self.keeper.save(update_fields=["merged_into"])

        assert AttendeeMergeService.survivor_of(self.duplicate) is None

    def test_refuses_a_merge_into_itself(self):
        with pytest.raises(MergeRefused):
            AttendeeMergeService.merge(self.duplicate, self.duplicate)

    def test_refuses_a_merge_across_organizations(self):
        other_org = Organization.objects.create(display_name="Other", slug="other-org")
        other_division = Division.objects.create(
            organization=other_org,
            display_name="Other Division",
            slug="other-division",
            audience_auth_group=Group.objects.create(name="Other Group"),
        )
        stranger = Attendee.objects.create(
            first_name="Ava", last_name="Chen", division=other_division, gender="unspecified"
        )

        with pytest.raises(MergeRefused):
            AttendeeMergeService.merge(self.duplicate, stranger)

    def test_refuses_a_merge_into_a_record_already_merged_away(self):
        third = Attendee.objects.create(
            first_name="Ava", last_name="Chen", division=self.division, gender="unspecified"
        )
        AttendeeMergeService.merge(self.keeper, third)

        # The caller means the person, so they are told to name the person
        # rather than have a second hop invented for them.
        with pytest.raises(MergeRefused):
            AttendeeMergeService.merge(self.duplicate, self.keeper)

    def test_a_live_attendee_resolves_to_themselves(self):
        survivor, was_merged = AttendeeMergeService.resolve(self.keeper.pk)
        assert survivor.id == self.keeper.id
        assert not was_merged
