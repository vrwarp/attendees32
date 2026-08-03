"""Households: the exact-set join, and the rule that nobody is ever removed."""

import pytest
from django.contrib.auth.models import Group

from attendees.pcosync.models import (
    PcoDivergence,
    PcoHouseholdLink,
    PcoPersonLink,
    PcoSyncRun,
)
from attendees.pcosync.services.config import write_config
from attendees.pcosync.services.households import HouseholdSync, fetch_memberships
from attendees.pcosync.services.runner import Runner
from attendees.pcosync.tests.fake_mirror import FakeMirror, FakeResponse
from attendees.pcosync.tests.test_runner import BASE, KEY, _client, definitions_body
from attendees.persons.models import (
    Attendee,
    Category,
    Folk,
    FolkAttendee,
    GenderEnum,
    Relation,
)
from attendees.whereabouts.models import Division, Organization


def household(household_id, name="The Lees"):
    return {"type": "Household", "id": str(household_id),
            "attributes": {"name": name}}


def membership(membership_id, person_id, role="child"):
    return {
        "type": "HouseholdMembership", "id": str(membership_id),
        "attributes": {"person_id": str(person_id), "household_role": role,
                       "pending": False},
        "relationships": {"person": {"data": {"type": "Person",
                                              "id": str(person_id)}}},
    }


@pytest.mark.django_db
class TestHouseholds:
    def setup_method(self):
        self.organization = Organization.objects.create(
            display_name="Test Organization", slug="testorg")
        self.group = Group.objects.create(name="Test Group")
        self.division = Division.objects.create(
            organization=self.organization, display_name="Chinese Ministry",
            slug="chinese-ministry", audience_auth_group=self.group)
        # Category 0 is the family category and the SET(0) sentinel.
        Category.objects.create(id=0, display_name="family", type="folk")
        Category.objects.create(id=25, display_name="other", type="folk")
        Category.objects.create(id=5, display_name="baptized", type="status")
        Category.objects.create(id=4, display_name="receive", type="status")
        Category.objects.create(id=22, display_name="disbeliever", type="status")
        Relation.objects.create(id=0, title="hidden",
                                gender=GenderEnum.UNSPECIFIED.value)
        Relation.objects.create(id=25, title="unspecified",
                                gender=GenderEnum.UNSPECIFIED.value)
        Relation.objects.create(id=27, title="child",
                                gender=GenderEnum.UNSPECIFIED.value)
        Relation.objects.create(id=30, title="parent",
                                gender=GenderEnum.UNSPECIFIED.value)

        write_config(self.organization, {
            "enabled": True, "dry_run": False, "push_enabled": False,
            "base_url": BASE, "api_key": KEY,
            "field_definition_tab_id": "183466",
            "household_role_to_relation_id": {"parent_guardian": 30,
                                              "child": 27, "adult": 25,
                                              "other_adult": 25},
        })

    # -- helpers ---------------------------------------------------------

    def attendee(self, first_name, pco_person_id=None):
        person = Attendee(first_name=first_name, last_name="Lee",
                          division=self.division,
                          gender=GenderEnum.UNSPECIFIED.value)
        person.save()
        if pco_person_id:
            PcoPersonLink.objects.create(
                organization=self.organization,
                pco_person_id=str(pco_person_id), attendee=person,
                state=PcoPersonLink.LIVE)
        return person

    def family(self, *attendees, role_id=27):
        folk = Folk.objects.create(division=self.division, category_id=0,
                                   display_name="Lee family")
        for person in attendees:
            FolkAttendee.objects.create(folk=folk, attendee=person,
                                        role_id=role_id)
        return folk

    def runner(self, mirror, mode=PcoSyncRun.PULL_ONLY):
        run = PcoSyncRun.objects.create(organization=self.organization,
                                        mode=mode)
        runner = Runner(run, client=_client(mirror))
        runner.definitions = None
        return runner

    def mirror(self, households, memberships_by_household):
        mirror = FakeMirror()
        mirror.add_any_query("GET", "/field_definitions",
                             FakeResponse(200, definitions_body()))
        mirror.add_any_query("GET", "/households", FakeResponse(200, {
            "data": households, "meta": {"total_count": len(households)},
            "links": {}}))
        for household_id, memberships in memberships_by_household.items():
            mirror.add_any_query(
                "GET", f"/households/{household_id}/household_memberships",
                FakeResponse(200, {"data": memberships,
                                   "meta": {"total_count": len(memberships)},
                                   "links": {}}))
        return mirror

    def divergences(self, kind):
        return PcoDivergence.objects.filter(
            organization=self.organization, kind=kind,
            resolution=PcoDivergence.OPEN, is_removed=False)

    # -- fetching --------------------------------------------------------

    def test_memberships_are_stamped_with_the_household_they_came_from(self):
        """The records carry no household reference of their own."""
        mirror = self.mirror([household(10)], {10: [membership(1, 900)]})
        memberships = fetch_memberships(_client(mirror), "10")
        assert memberships == [{"id": "1", "household_id": "10",
                                "person_id": "900", "role": "child",
                                "pending": False}]

    # -- joining ---------------------------------------------------------

    def test_a_household_links_to_the_family_with_exactly_those_members(self):
        parent = self.attendee("Parent", 900)
        child = self.attendee("Child", 901)
        folk = self.family(parent, child)

        mirror = self.mirror([household(10)], {10: [
            membership(1, 900, "parent_guardian"), membership(2, 901, "child")]})
        HouseholdSync(self.runner(mirror)).sync_all()

        link = PcoHouseholdLink.objects.get(pco_household_id="10")
        assert link.folk_id == folk.id

    def test_a_partial_overlap_is_reported_and_never_linked(self):
        """One member out is how two families get merged into one entry."""
        parent = self.attendee("Parent", 900)
        child = self.attendee("Child", 901)
        other = self.attendee("Cousin", 902)
        self.family(parent, child, other)

        mirror = self.mirror([household(10)], {10: [
            membership(1, 900, "parent_guardian"), membership(2, 901, "child")]})
        HouseholdSync(self.runner(mirror)).sync_all()

        assert not PcoHouseholdLink.objects.filter(folk__isnull=False).exists()
        assert self.divergences(PcoDivergence.HOUSEHOLD_CONFLICT).exists()

    def test_two_families_with_the_same_members_are_reported_not_guessed(self):
        parent = self.attendee("Parent", 900)
        self.family(parent)
        self.family(parent)

        mirror = self.mirror([household(10)],
                             {10: [membership(1, 900, "parent_guardian")]})
        HouseholdSync(self.runner(mirror)).sync_all()

        divergence = self.divergences(PcoDivergence.HOUSEHOLD_CONFLICT).get()
        assert "more than one family" in divergence.note

    def test_a_household_of_people_nobody_here_knows_is_skipped_quietly(self):
        mirror = self.mirror([household(10)],
                             {10: [membership(1, 999, "parent_guardian")]})
        HouseholdSync(self.runner(mirror)).sync_all()

        assert not PcoHouseholdLink.objects.filter(folk__isnull=False).exists()
        divergence = self.divergences(PcoDivergence.HOUSEHOLD_CONFLICT).get()
        assert divergence.severity == PcoDivergence.INFO

    def test_unlinked_members_do_not_prevent_a_match(self):
        """A household with a stranger in it is still the family it obviously is."""
        parent = self.attendee("Parent", 900)
        child = self.attendee("Child", 901)
        folk = self.family(parent, child)

        mirror = self.mirror([household(10)], {10: [
            membership(1, 900, "parent_guardian"), membership(2, 901, "child"),
            membership(3, 999, "other_adult")]})
        HouseholdSync(self.runner(mirror)).sync_all()

        assert PcoHouseholdLink.objects.get(pco_household_id="10").folk_id \
            == folk.id

    # -- membership merge ------------------------------------------------

    def test_somebody_new_upstream_is_added_to_the_family(self):
        parent = self.attendee("Parent", 900)
        child = self.attendee("Child", 901)
        folk = self.family(parent, child)
        newcomer = self.attendee("Baby", 902)

        # First run establishes the link and the baseline.
        first = self.mirror([household(10)], {10: [
            membership(1, 900, "parent_guardian"), membership(2, 901, "child")]})
        HouseholdSync(self.runner(first)).sync_all()

        # Now Planning Center has one more member.
        second = self.mirror([household(10)], {10: [
            membership(1, 900, "parent_guardian"), membership(2, 901, "child"),
            membership(3, 902, "child")]})
        HouseholdSync(self.runner(second)).sync_all()

        assert FolkAttendee.objects.filter(folk=folk, attendee=newcomer,
                                           is_removed=False).exists()

    def test_the_household_role_becomes_the_relation(self):
        parent = self.attendee("Parent", 900)
        folk = self.family(parent, role_id=30)
        child = self.attendee("Child", 901)

        first = self.mirror([household(10)],
                            {10: [membership(1, 900, "parent_guardian")]})
        HouseholdSync(self.runner(first)).sync_all()

        second = self.mirror([household(10)], {10: [
            membership(1, 900, "parent_guardian"), membership(2, 901, "child")]})
        HouseholdSync(self.runner(second)).sync_all()

        assert FolkAttendee.objects.get(folk=folk, attendee=child).role_id == 27

    def test_a_membership_removed_upstream_is_reported_never_applied(self):
        parent = self.attendee("Parent", 900)
        child = self.attendee("Child", 901)
        folk = self.family(parent, child)

        first = self.mirror([household(10)], {10: [
            membership(1, 900, "parent_guardian"), membership(2, 901, "child")]})
        HouseholdSync(self.runner(first)).sync_all()

        # The child is gone from the Planning Center household.
        second = self.mirror([household(10)],
                             {10: [membership(1, 900, "parent_guardian")]})
        HouseholdSync(self.runner(second)).sync_all()

        assert FolkAttendee.objects.filter(folk=folk, attendee=child,
                                           is_removed=False).exists(), \
            "a sync must not remove somebody from a family"
        assert self.divergences(
            PcoDivergence.HOUSEHOLD_MEMBERSHIP_REMOVED).exists()

    def test_a_soft_deleted_membership_is_revived_rather_than_duplicated(self):
        """The unique index is conditional on is_removed, so create() would pass.

        Reached through an already-linked household: with the row soft-deleted
        the member sets no longer match, so a fresh join would not be made -- it
        is an established family gaining somebody back that exercises this.
        """
        parent = self.attendee("Parent", 900)
        child = self.attendee("Child", 901)
        folk = self.family(parent, child)
        FolkAttendee.objects.get(folk=folk, attendee=child).delete()  # soft
        PcoHouseholdLink.objects.create(
            organization=self.organization, pco_household_id="10", folk=folk)

        mirror = self.mirror([household(10)], {10: [
            membership(1, 900, "parent_guardian"), membership(2, 901, "child")]})
        HouseholdSync(self.runner(mirror)).sync_all()
        HouseholdSync(self.runner(mirror)).sync_all()

        rows = FolkAttendee.all_objects.filter(folk=folk, attendee=child)
        assert rows.count() == 1, "the conditional unique index allows a second"
        assert rows.first().is_removed is False

    def test_a_dry_run_adds_nobody(self):
        parent = self.attendee("Parent", 900)
        folk = self.family(parent)
        newcomer = self.attendee("Baby", 902)

        first = self.mirror([household(10)],
                            {10: [membership(1, 900, "parent_guardian")]})
        HouseholdSync(self.runner(first)).sync_all()

        second = self.mirror([household(10)], {10: [
            membership(1, 900, "parent_guardian"), membership(2, 902, "child")]})
        HouseholdSync(self.runner(second, mode=PcoSyncRun.DRY_RUN)).sync_all()

        assert not FolkAttendee.objects.filter(folk=folk,
                                               attendee=newcomer).exists()
        assert self.divergences(PcoDivergence.WOULD_WRITE).exists()

    def test_one_broken_household_does_not_abandon_the_rest(self):
        parent = self.attendee("Parent", 900)
        folk = self.family(parent)

        mirror = self.mirror([household(10), household(11)],
                             {11: [membership(1, 900, "parent_guardian")]})
        # Household 10's memberships were never registered, so fetching them
        # raises inside the loop.
        HouseholdSync(self.runner(mirror)).sync_all()

        assert PcoHouseholdLink.objects.filter(pco_household_id="11",
                                               folk=folk).exists()
        assert self.divergences(PcoDivergence.HOUSEHOLD_CONFLICT).filter(
            severity=PcoDivergence.ERROR).exists()

    def test_internal_relations_are_never_written_from_planning_center(self):
        from attendees.pcosync.services.households import relation_for, role_for

        class Config:
            household_role_to_relation_id = {"hidden": 0, "child": 27}
            relation_id_to_household_role = {0: "hidden", 27: "child"}

        assert relation_for("hidden", Config()) is None
        assert role_for(0, Config()) is None
        assert role_for(27, Config()) == "child"
