"""Which meets a user's groups may see, and which pages list a meet."""
import importlib
from datetime import timedelta

import pytest
from django.apps import apps
from django.contrib.auth.models import Group
from django.contrib.contenttypes.models import ContentType

from attendees.occasions.models import Assembly, Meet, MeetAllowedModel
from attendees.persons.models import Category, Utility
from attendees.whereabouts.models import Division, Organization


@pytest.mark.django_db
class TestMeetAllowed:
    def setup_method(self):
        self.organization = Organization.objects.create(display_name="Test Organization", slug="test-org")
        self.groups = {name: Group.objects.create(name=name) for name in ("participant", "organizer", "counselor")}
        division = Division.objects.create(
            organization=self.organization, display_name="Main", slug="main", audience_auth_group=self.groups["participant"]
        )
        category = Category.objects.create(type="assembly", display_name="public", display_order=0, infos={})
        self.assembly = Assembly.objects.create(division=division, slug="youth", display_name="Youth", category=category, infos={})

    def meet(self, slug, groups=(), pages=None):
        now = Utility.now_with_timezone()
        meet = Meet.objects.create(
            assembly=self.assembly,
            slug=slug,
            display_name=slug,
            start=now,
            finish=now + timedelta(days=365),
            infos=Utility.meet_infos(),
            site_type=ContentType.objects.get_for_model(Organization),
            site_id=str(self.organization.id),
        )
        meet.allowed_groups.set([self.groups[name] for name in groups])
        if pages is not None:
            meet.list_on(*pages)
        return meet

    def test_a_meet_open_to_several_of_the_users_groups_is_listed_once(self):
        friday = self.meet("friday", groups=("participant", "organizer", "counselor"))
        staff = self.meet("staff", groups=("organizer",))
        self.meet("closed")
        mine = Meet.objects.filter(Meet.allowed_to_any_of(["participant", "organizer"]))
        assert set(mine) == {friday, staff}
        assert mine.count() == 2
        assert list(Meet.objects.filter(Meet.allowed_to_any_of([]))) == []

    def test_a_meet_is_listed_on_the_pages_it_allows(self):
        status_only = self.meet("believed", pages=(MeetAllowedModel.ATTENDINGMEET,))
        full = self.meet("friday", pages=())  # the default: every page
        unlisted = self.meet("draft")
        assert set(Meet.objects.filter(Meet.listed_on("attendingmeet"))) == {status_only, full}
        assert set(Meet.objects.filter(Meet.listed_on("attendance"))) == {full}
        assert unlisted.allowed_models.count() == 0
        full.list_on()  # again: no duplicates
        assert full.allowed_models.count() == len(MeetAllowedModel.DEFAULT)

    def test_the_backfill_copies_the_json_lists_and_drops_them(self):
        meet = self.meet("friday")
        Meet.objects.filter(pk=meet.pk).update(
            infos={
                **meet.infos,
                "allowed_groups": ["participant", "no_such_group"],
                "allowed_models": ["gathering", "attendance", "no_such_page"],
            }
        )

        importlib.import_module("attendees.occasions.migrations.0023_meet_allowed_backfill").copy_allowed(apps, None)

        meet.refresh_from_db()
        assert list(meet.allowed_groups.values_list("name", flat=True)) == ["participant"]
        assert sorted(meet.allowed_models.values_list("model", flat=True)) == ["attendance", "gathering"]
        assert "allowed_groups" not in meet.infos and "allowed_models" not in meet.infos
