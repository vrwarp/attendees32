"""A place's subject as a typed key, and as the content type and id the API still speaks."""
import importlib

import pytest
from address.models import Address, Country, Locality, State
from django.apps import apps
from django.contrib.auth.models import Group
from django.contrib.contenttypes.models import ContentType
from django.db import IntegrityError, transaction

from attendees.persons.models import Attendee, Category, Folk, Relation
from attendees.persons.models.enum import GenderEnum
from attendees.whereabouts.models import ContentTypeExtra, Organization, Place
from attendees.whereabouts.serializers import PlaceMinimalSerializer, PlaceSerializer
from attendees.whereabouts.models import Division


@pytest.mark.django_db
class TestPlaceSubjects:
    def setup_method(self):
        self.organization = Organization.objects.create(display_name="Test Organization", slug="test-org")
        group = Group.objects.create(name="Test Group")
        self.division = Division.objects.create(
            organization=self.organization, display_name="Test Division", slug="test-division", audience_auth_group=group
        )
        Relation.objects.create(id=0, title="self", gender=GenderEnum.UNSPECIFIED.value)
        Category.objects.create(id=0, display_name="Family")
        Category.objects.create(id=25, display_name="Non-family")
        country = Country.objects.create(name="USA", code="US")
        state = State.objects.create(name="California", code="CA", country=country)
        locality = Locality.objects.create(name="Fremont", postal_code="94536", state=state)
        self.address = Address.objects.create(raw="1 Main St, Fremont, CA 94536", locality=locality)
        self.attendee = Attendee.objects.create(first_name="Grace", last_name="Chen", division=self.division, gender="unspecified")
        self.family = Folk.objects.create(division=self.division, category_id=0, display_name="Chen family")
        self.family.folkattendee_set.create(attendee=self.attendee, role_id=0)

    def test_the_key_answers_as_content_type_and_object_id(self):
        place = Place.objects.create(folk=self.family, organization=self.organization, address=self.address)
        assert place.subject == self.family and place.subject_field == "folk"
        assert place.content_type == ContentType.objects.get_for_model(Folk)
        assert place.object_id == str(self.family.id)
        assert list(self.family.places.all()) == [place]
        assert Place.subject_field_for(ContentType.objects.get_for_model(Attendee)) == "attendee"
        with pytest.raises(ValueError):
            Place.subject_field_for(Organization)

    def test_exactly_one_subject_is_enforced_by_the_database(self):
        with pytest.raises(IntegrityError), transaction.atomic():
            Place.objects.create(organization=self.organization, address=self.address)
        with pytest.raises(IntegrityError), transaction.atomic():
            Place.objects.create(folk=self.family, attendee=self.attendee, organization=self.organization, address=self.address)

    def test_one_live_place_per_subject_and_address(self):
        Place.objects.create(attendee=self.attendee, organization=self.organization, address=self.address)
        with pytest.raises(IntegrityError), transaction.atomic():
            Place.objects.create(attendee=self.attendee, organization=self.organization, address=self.address, display_name="again")
        # another subject at the same address is fine
        Place.objects.create(folk=self.family, organization=self.organization, address=self.address)

    def test_the_api_names_the_subject_by_content_type_and_id_both_ways(self):
        attendee_type = ContentType.objects.get_for_model(Attendee)
        serializer = PlaceMinimalSerializer(data={
            "content_type": attendee_type.pk, "object_id": str(self.attendee.id),
            "organization": self.organization.id, "display_name": "dorm",
        })
        assert serializer.is_valid(), serializer.errors
        place = serializer.save()
        assert place.attendee == self.attendee and place.folk_id is None
        data = PlaceSerializer(place).data
        assert (data["content_type"], data["object_id"], data["attendee_id"]) == (attendee_type.pk, str(self.attendee.id), str(self.attendee.id))

        refused = PlaceMinimalSerializer(data={
            "content_type": ContentType.objects.get_for_model(Organization).pk, "object_id": "1",
            "organization": self.organization.id,
        })
        assert not refused.is_valid() and "content_type" in refused.errors

    def test_the_backfill_turns_the_old_link_into_a_key_and_refuses_a_dangling_one(self):
        """The migration's function, fed the rows as they stood: a content type and an object id."""
        migration = importlib.import_module("attendees.whereabouts.migrations.0016_place_subjects_backfill")
        folk_type = ContentType.objects.get_for_model(Folk)

        class Row:
            def __init__(self, pk, content_type_id, object_id):
                self.pk, self.content_type_id, self.object_id = pk, content_type_id, object_id
                self.saved = {}

            def __setattr__(self, name, value):
                object.__setattr__(self, name, value)

            def save(self, update_fields):
                self.saved = {field: getattr(self, f"{field}_id") for field in update_fields}

        class Frozen:
            def __init__(self, rows):
                self.rows = rows
                self._default_manager = self

            def all(self):
                return self

            def iterator(self, chunk_size):
                return iter(self.rows)

        good = Row("p1", folk_type.pk, str(self.family.id))
        places, history = Frozen([good]), Frozen([Row("h1", folk_type.pk, str(self.family.id)), Row("h2", folk_type.pk, "gone")])

        class Apps:
            @staticmethod
            def get_model(app, name):
                return {("whereabouts", "Place"): places, ("whereabouts", "PlacesHistory"): history}.get(
                    (app, name), apps.get_model(app, name)
                )

        migration.copy_place_subjects(Apps(), None)
        assert good.saved == {"folk": self.family.id}
        assert history.rows[0].saved == {"folk": self.family.id}, "history rows get their key without checks"
        assert history.rows[1].saved == {}, "a history row naming nothing that parses is left alone"

        dangling = Row("p2", folk_type.pk, "00000000-0000-0000-0000-000000000000")
        places.rows = [dangling]
        with pytest.raises(RuntimeError, match="no longer exist"):
            migration.copy_place_subjects(Apps(), None)
        foreign = Row("p3", ContentType.objects.get_for_model(Organization).pk, "1")
        places.rows = [foreign]
        with pytest.raises(RuntimeError, match="no place can have"):
            migration.copy_place_subjects(Apps(), None)


@pytest.mark.django_db
class TestContentTypeExtras:
    def test_the_command_fills_the_extras_and_the_picker_reads_them(self, client):
        from django.core.management import call_command
        from attendees.users.models import User

        call_command("update_content_types", verbosity=0)
        rooms = ContentTypeExtra.objects.get(content_type=ContentType.objects.get_for_model(apps.get_model("whereabouts", "Room")))
        assert (rooms.genres, rooms.display_order, rooms.endpoint, rooms.hint) == ("location", 2, "/whereabouts/api/organizational_rooms/", "single room/office")
        call_command("update_content_types", verbosity=0)  # idempotent
        assert ContentTypeExtra.objects.filter(genres="location").count() == 7

        organization = Organization.objects.create(display_name="Test Organization", slug="test-org")
        user = User.objects.create_user(username="picker", password="x", organization=organization)
        client.force_login(user)
        response = client.get("/whereabouts/api/content_type_models/", {"query": "location"})
        assert response.status_code == 200
        rows = response.json()["data"]
        assert [row["model"] for row in rows] == ["room", "suite", "property", "campus", "division", "organization", "address"]
        assert rows[0]["endpoint"] == "/whereabouts/api/organizational_rooms/" and rows[0]["hint"] == "single room/office"
        assert client.get("/whereabouts/api/content_type_models/", {"query": "nothing"}).json()["data"] == []
