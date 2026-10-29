from datetime import datetime, timedelta, timezone

import pytest
from django.contrib.auth.models import Group
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.db.models import Q

from attendees.occasions.models import Assembly, Character, Meet
from attendees.persons.models import Attendee, Attending, AttendingMeet, Category, Relation
from attendees.persons.models.enum import GenderEnum
from attendees.persons.services.search_service import SearchService
from attendees.utils.search_text import attendee_full_name, normalise, search_text_of
from attendees.whereabouts.models import Division, Organization


class TestSearchTextFunctions:
    def test_leaves_are_lowercased_flattened_and_deduplicated(self):
        text = search_text_of(
            "Grace",
            {"names": {"original": "Grace Chen", "traditional": "陳恩典"}, "contacts": {"phone": "+1 510 555 0100"}},
            ["Grace", None, True, 5],
        )
        assert text == "grace grace chen 陳恩典 +1 510 555 0100 5"

    def test_normalise_collapses_case_and_whitespace(self):
        assert normalise("  Grace   CHEN ") == "grace chen"
        assert normalise(None) == ""

    def test_full_name_puts_the_western_name_before_the_eastern_one(self):
        assert attendee_full_name("Grace", "Chen", "陳", "恩典") == "Grace Chen 陳恩典"
        assert attendee_full_name(None, "Chen", None, None) == "Chen"


@pytest.mark.django_db
class TestSearchableAttendee:
    def setup_method(self):
        self.organization = Organization.objects.create(display_name="Test Organization", slug="test-org")
        group = Group.objects.create(name="Test Group")
        self.division = Division.objects.create(
            organization=self.organization, display_name="Test Division", slug="test-division", audience_auth_group=group
        )
        # Creating an attendee links it to itself, which needs the self relation and the categories.
        Relation.objects.create(id=0, title="self", gender=GenderEnum.UNSPECIFIED.value)
        Category.objects.create(id=0, display_name="Family")
        Category.objects.create(id=25, display_name="Non-family")

    def person(self, first, last, last2="", first2="", **infos):
        return Attendee.objects.create(
            first_name=first,
            last_name=last,
            last_name2=last2,
            first_name2=first2,
            division=self.division,
            gender="unspecified",
            infos={**Attendee.infos.field.default(), **infos},
        )

    def test_save_fills_full_name_and_search_text_from_names_and_contacts(self):
        grace = self.person("Grace", "Chen", "陳", "恩典", contacts={"phone": "+15105550100"})
        grace.refresh_from_db()
        assert grace.full_name == "Grace Chen 陳恩典"
        for expected in ("grace chen 陳恩典", "chen en dian", "+15105550100"):
            assert expected in grace.search_text
        # ids and timestamps are not something a person is looked up by
        assert "schedulers" not in grace.search_text

    def test_a_limited_update_fields_save_still_refreshes_the_derived_columns(self):
        grace = self.person("Grace", "Chen")
        grace.first_name = "Gracie"
        grace.save(update_fields=["first_name"])
        grace.refresh_from_db()
        assert grace.full_name == "Gracie Chen"
        assert "gracie" in grace.search_text

    def test_contains_builds_a_portable_lookup_on_the_joined_column(self):
        assert SearchService.contains("attending__attendee__search_text", " Grace ") == Q(
            attending__attendee__search_text__contains="grace"
        )
        assert SearchService.contains("search_text", "   ") == Q()

    def test_substring_search_matches_any_name_form(self):
        grace = self.person("Grace", "Chen", "陳", "恩典")
        self.person("Joshua", "Lin")
        people = Attendee.objects.filter(division=self.division)
        assert list(SearchService.search(people, "CHEN")) == [grace]
        assert list(SearchService.search(people, "恩典")) == [grace]
        assert list(SearchService.search(people, "en dian")) == [grace]

    def test_fuzzy_ranking_finds_a_typo_when_the_substring_match_comes_up_empty(self):
        grace = self.person("Grace", "Chen")
        self.person("Joshua", "Lin")
        people = Attendee.objects.filter(division=self.division)
        assert list(SearchService.search(people, "Grce Chen")) == [grace]
        assert list(SearchService.search(people, "Chen Grace")) == [grace]

    def test_fuzzy_ranking_holds_up_against_the_long_text_of_a_real_record(self):
        """A record's text is many times longer than a typed name: every name form, the contacts
        and the fixed facts. A name typed in full, with its Han form, in the other order or with a
        letter wrong must still find that record and not the people who share one of its words."""
        fixed = {"grade": 9, "food_pref": "no nuts", "medical": "asthma inhaler"}

        def contacts(who):
            return {"phone1": "+15105550302", "phone2": "+16505550302", "email1": f"{who}@example.org"}

        hannah = self.person("Hannah", "Liu", "劉", "恩晴", contacts=contacts("hannah"), fixed=fixed)
        self.person("Hannah", "Huang", "黃", "以琳", contacts=contacts("hannah.h"), fixed=fixed)
        self.person("Marcus", "Liu", "劉", "寶山", contacts=contacts("marcus"), fixed=fixed)
        self.person("Serena", "Liu", contacts=contacts("serena"))
        people = Attendee.objects.filter(division=self.division)
        for term in ("Hannah Liu 劉恩晴", "Hannah Liu", "Liu Hannah", "Hanah Liu", "Hannnah Liu 劉恩晴"):
            assert list(SearchService.search(people, term)) == [hannah], term
        # a three-letter word has to appear as typed: Lau is not Liu
        assert list(SearchService.search(people, "Hannah Lau")) == []
        # so has an email address or a phone number: nearly the same one is someone else's
        assert list(SearchService.search(people, "hannah@example.org")) == [hannah]
        assert list(SearchService.search(people, "hanna@example.org")) == []
        assert list(SearchService.search(people, "+15105550303")) == []

    def test_short_terms_are_substring_only(self):
        self.person("Grace", "Chen")
        people = Attendee.objects.filter(division=self.division)
        assert list(SearchService.search(people, "xq")) == []

    def test_refresh_command_repairs_a_column_a_bulk_write_skipped(self):
        grace = self.person("Grace", "Chen")
        Attendee.objects.filter(pk=grace.pk).update(search_text="", full_name="")
        call_command("refresh_search_text", verbosity=0)
        grace.refresh_from_db()
        assert grace.full_name == "Grace Chen"
        assert "grace chen" in grace.search_text


@pytest.mark.django_db
class TestSearchableInfos:
    def test_an_attending_meet_is_found_by_the_note_in_its_infos(self):
        organization = Organization.objects.create(display_name="Test Organization", slug="test-org")
        group = Group.objects.create(name="Test Group")
        division = Division.objects.create(
            organization=organization, display_name="Test Division", slug="test-division", audience_auth_group=group
        )
        Relation.objects.create(id=0, title="self", gender=GenderEnum.UNSPECIFIED.value)
        Category.objects.create(id=0, display_name="Family")
        category = Category.objects.create(id=25, display_name="Test Category")
        assembly = Assembly.objects.create(display_name="Assembly", slug="assembly", division=division, category=category)
        character = Character.objects.create(assembly=assembly, display_name="Member", slug="member", type="normal")
        now = datetime.now(timezone.utc)
        meet = Meet.objects.create(
            assembly=assembly,
            major_character=character,
            shown_audience=True,
            audience_editable=True,
            start=now,
            finish=now + timedelta(days=1),
            display_name="Sunday service",
            slug="sunday-service",
            site_type=ContentType.objects.get_for_model(Assembly),
            site_id=str(assembly.id),
        )
        attendee = Attendee.objects.create(first_name="Grace", last_name="Chen", division=division, gender="unspecified")
        attending = Attending.objects.filter(attendee=attendee).first() or Attending.objects.create(attendee=attendee)
        attending_meet = AttendingMeet.objects.create(
            attending=attending,
            meet=meet,
            character=character,
            category=category,
            start=now,
            finish=now + timedelta(days=1),
            infos={"note": "Needs a Ride", "kid_points": 3},
        )
        attending_meet.refresh_from_db()
        assert attending_meet.search_text == "needs a ride 3"
        found = AttendingMeet.objects.filter(SearchService.contains("search_text", "ride"))
        assert list(found) == [attending_meet]
        by_person = AttendingMeet.objects.filter(SearchService.contains("attending__attendee__search_text", "grace"))
        assert list(by_person) == [attending_meet]
