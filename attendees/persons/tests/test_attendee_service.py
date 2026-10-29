import pytest
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from django.contrib.contenttypes.models import ContentType
from django.contrib.auth.models import Group
from attendees.users.models import User
from attendees.whereabouts.models import Organization, Division
from attendees.persons.models import Attendee, Attending, AttendingMeet, Category, Registration, Relation, Folk, FolkAttendee, Past
from attendees.persons.models.enum import GenderEnum
from attendees.occasions.models import Meet, Character, Assembly
from attendees.persons.services.attendee_service import AttendeeService

@pytest.mark.django_db
class TestAttendeeService:
    def setup_method(self):
        self.organization = Organization.objects.create(display_name="Test Organization", slug="test-org")
        self.group = Group.objects.create(name="Test Group")
        self.division = Division.objects.create(
            organization=self.organization,
            display_name="Test Division",
            slug="test-division",
            audience_auth_group=self.group
        )
        self.category = Category.objects.create(id=25, display_name="Test Category")
        self.category_1 = Category.objects.create(id=1, display_name="Scheduled")
        self.family_category = Category.objects.create(id=0, display_name="Family")
        self.past_category = Category.objects.create(id=26, display_name="Past Category")
        self.relation = Relation.objects.create(id=0, title="test relation", gender=GenderEnum.UNSPECIFIED.value)
        
        self.assembly = Assembly.objects.create(
            display_name="Test Assembly",
            slug="test-assembly",
            division=self.division,
            category=self.category,
        )
        self.character = Character.objects.create(
            assembly=self.assembly,
            display_name="Test Character",
            slug="test-character",
            type="normal",
        )
        self.site_type = ContentType.objects.get_for_model(Assembly)
        
        self.now = datetime.now(timezone.utc)
        self.meet = Meet.objects.create(
            assembly=self.assembly,
            major_character=self.character,
            shown_audience=True,
            audience_editable=True,
            start=self.now,
            finish=self.now + timedelta(days=1),
            display_name="Test Meet",
            slug="test-meet",
            site_type=self.site_type,
            site_id=str(self.assembly.id),
        )

        self.user = User.objects.create(
            username="testuser",
            email="testuser@example.com",
            organization=self.organization
        )

        self.attendee = Attendee.objects.create(
            first_name="John",
            last_name="Doe",
            division=self.division,
            user=self.user,
            gender="unspecified"
        )
        self.user.attendee = self.attendee
        self.user.save()

        self.attending = Attending.objects.filter(attendee=self.attendee).first()
        if not self.attending:
            self.attending = Attending.objects.create(attendee=self.attendee)

        self.attendingmeet = AttendingMeet.objects.create(
            attending=self.attending,
            meet=self.meet,
            character=self.character,
            finish=self.now + timedelta(days=10)
        )

    def test_by_assembly_meets(self):
        qs = AttendeeService.by_assembly_meets(
            assembly_slug=self.assembly.slug,
            meet_slugs=[self.meet.slug]
        )
        assert qs.count() == 1
        assert qs.first().id == self.attendee.id

    def test_orderby_parser(self):
        orderby_string = '[{"selector":"first_name","desc":true}]'
        # Pass empty list for meets for simplicity
        parsed, sorters = AttendeeService.orderby_parser(orderby_string, [], self.user)
        assert parsed == ["-first_name"]
        assert sorters == {}

    def test_grid_sorters_are_portable_subqueries_and_aggregates(self):
        orderby_string = f'[{{"selector":"{self.meet.slug}","desc":true}},{{"selector":"visitor_since","desc":false}},{{"selector":"folkcities","desc":false}}]'
        parsed, sorters = AttendeeService.orderby_parser(orderby_string, [self.meet.id], self.user, visitor_meet_id=self.meet.id)
        assert parsed == ["-in_meet_0", "visitor_since_at", "folkcity"]
        assert set(sorters) == {"in_meet_0", "visitor_since_at", "folkcity"}

    def test_the_grid_puts_the_enrolled_first_when_sorted_by_a_meet(self):
        stranger = Attendee.objects.create(first_name="Aaron", last_name="Abel", division=self.division, gender="unspecified")
        for who in (self.attendee, stranger):
            AttendeeService.create_or_update_first_folk(attendee=who, folk_name=f"{who.first_name} family", category_id=self.family_category.id, role_id=self.relation.id)
        self.user.organization.infos = {"groups_see_all_meets_attendees": [self.group.name]}
        self.user.organization.save()
        self.user.groups.add(self.group)
        orderby = f'[{{"selector":"{self.meet.slug}","desc":true}},{{"selector":"first_name","desc":false}}]'
        rows = list(AttendeeService.by_datagrid_params(self.user, [self.meet.id], orderby, [], include_dead=None))
        assert [row.first_name for row in rows] == ["John", "Aaron"]
        rows = list(AttendeeService.by_datagrid_params(self.user, [self.meet.id], orderby.replace("true", "false"), [], include_dead=None))
        assert [row.first_name for row in rows] == ["Aaron", "John"]

    def test_the_grid_columns_are_built_from_the_enrollments_and_folks(self):
        from attendees.whereabouts.models import Place
        from address.models import Address, Locality, State, Country

        ended = AttendingMeet.objects.create(attending=self.attending, meet=self.meet, character=self.character,
                                             start=self.now - timedelta(days=400), finish=self.now - timedelta(days=1), infos={"note": "old"})
        self.attendingmeet.infos = {"note": "car pool"}
        self.attendingmeet.save()
        folk = AttendeeService.create_or_update_first_folk(attendee=self.attendee, folk_name="Doe family", category_id=self.family_category.id, role_id=self.relation.id)
        country = Country.objects.create(name="USA", code="US")
        state = State.objects.create(name="California", code="CA", country=country)
        locality = Locality.objects.create(name="Fremont", postal_code="94536", state=state)
        address = Address.objects.create(raw="1 Main St, Fremont, CA 94536", locality=locality)
        place = Place.objects.create(folk=folk, address=address, organization=self.organization)
        former = Address.objects.create(raw="9 Old Rd, Hayward, CA 94541", locality=Locality.objects.create(name="Hayward", postal_code="94541", state=state))
        Place.objects.create(folk=folk, address=former, organization=self.organization, finish=(self.now - timedelta(days=30)).date())
        self.organization.infos = {"settings": {"default_visitor_meet": self.meet.id}}
        self.organization.save()
        self.user.organization.refresh_from_db()

        rows = AttendeeService.attach_grid_columns([self.attendee], self.user, now=self.now)

        row = rows[0]
        assert row.attendingmeets == [{
            "attendingmeet_id": self.attendingmeet.id, "meet_slug": self.meet.slug,
            "attendingmeet_note": "car pool", "attendingmeet_category": self.attendingmeet.category_id,
        }], "only the live enrollment, with its note"
        assert row.folkcities == [{"locality__name": "Fremont", "address__raw": "1 Main St, Fremont, CA 94536", "places__id": str(place.id)}], "the current address only"
        assert row.visitor_since == ", ".join(sorted({
            ended.start.astimezone(timezone.utc).date().isoformat(),
            self.attendingmeet.start.astimezone(timezone.utc).date().isoformat(),
        })), "every visit, the ended one included"

        nobody = Attendee.objects.create(first_name="New", last_name="Comer", division=self.division, gender="unspecified")
        row = AttendeeService.attach_grid_columns([nobody], self.user, now=self.now)[0]
        assert (row.attendingmeets, row.folkcities, row.visitor_since) == ([], [], None)

    def test_the_attendee_page_gets_every_attending_with_its_registration(self):
        registration = Registration.objects.create(registrant=self.attendee, assembly=self.assembly)
        registered = Attending.objects.create(attendee=self.attendee, registration=registration)
        gone = Attending.objects.create(attendee=self.attendee)
        gone.is_removed = True
        gone.save()

        rows = AttendeeService.attach_attendings(self.attendee).attendingmeets

        assert rows == [
            {"attending_id": self.attending.id, "attending_is_removed": False, "registration_assembly": None, "registrant": ""},
            {"attending_id": registered.id, "attending_is_removed": False, "registration_assembly": "Test Assembly", "registrant": "John Doe"},
            {"attending_id": gone.id, "attending_is_removed": True, "registration_assembly": None, "registrant": ""},
        ]

    def test_field_convert(self):
        field = AttendeeService.field_convert("self_phone_numbers", [], self.user)
        assert field == "infos__contacts"

    def test_create_or_update_first_folk(self):
        folk = AttendeeService.create_or_update_first_folk(
            attendee=self.attendee,
            folk_name="Doe Family",
            category_id=self.family_category.id,
            role_id=self.relation.id
        )
        assert folk is not None
        assert folk.display_name == "Doe Family"
        assert FolkAttendee.objects.filter(folk=folk, attendee=self.attendee).exists()

    def test_add_past(self):
        AttendeeService.add_past(self.attendee, self.past_category.id, timezone.utc)
        assert Past.objects.filter(object_id=self.attendee.id, category=self.past_category).exists()

    def test_end_all_activities(self):
        # We must add a past first
        AttendeeService.add_past(self.attendee, self.past_category.id, timezone.utc)
        past = Past.objects.filter(object_id=self.attendee.id).first()
        
        AttendeeService.end_all_activities(self.attendee, str(uuid4()))
        
        self.attendingmeet.refresh_from_db()
        past.refresh_from_db()
        assert self.attendingmeet.finish <= datetime.now(timezone.utc)
        assert past.finish <= datetime.now(timezone.utc)

    def test_destroy_with_associations(self):
        # Add past to be sure it's deleted
        AttendeeService.add_past(self.attendee, self.past_category.id, timezone.utc)
        
        assert Attendee.objects.filter(id=self.attendee.id).exists()
        
        AttendeeService.destroy_with_associations(self.attendee)
        
        # Soft deleted
        self.attendee.refresh_from_db()
        assert self.attendee.is_removed is True
        
        # Pasts should be soft-deleted or deleted depending on logic
        assert not Past.objects.filter(object_id=self.attendee.id, is_removed=False).exists()
