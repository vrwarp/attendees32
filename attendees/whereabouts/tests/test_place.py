import pytest
from uuid import UUID
from datetime import date
from attendees.whereabouts.models.campus import Campus
from attendees.whereabouts.models.organization import Organization
from attendees.whereabouts.models.place import Place
from address.models import Address, Locality, State, Country

@pytest.mark.django_db
class TestPlace:
    def setup_method(self):
        self.organization = Organization.objects.create(
            slug="test-org",
            display_name="Test Organization",
        )
        self.campus = Campus.objects.create(organization=self.organization, display_name="Main campus", slug="main-campus")
        
        self.country = Country.objects.create(name="United States", code="US")
        self.state = State.objects.create(name="California", code="CA", country=self.country)
        self.locality = Locality.objects.create(name="Los Angeles", postal_code="90001", state=self.state)
        self.address = Address.objects.create(raw="123 Main St", locality=self.locality)

        self.place = Place.objects.create(
            campus=self.campus,
            organization=self.organization,
            address=self.address,
            display_name="Main Office",
            display_order=1,
            start=date(2020, 1, 1),
        )

    def test_create_place(self):
        assert self.place.pk is not None
        assert isinstance(self.place.pk, UUID)
        assert self.place.organization == self.organization
        assert self.place.subject == self.campus
        assert self.place.subject_field == "campus"
        assert self.place.object_id == str(self.campus.id)
        assert self.place.content_type.model == "campus"
        assert self.place.address == self.address
        assert self.place.display_name == "Main Office"
        assert self.place.display_order == 1
        assert self.place.start == date(2020, 1, 1)

    def test_str(self):
        assert str(self.place) == f"{self.address} {self.campus}"

    def test_street_property(self):
        assert self.place.street == str(self.address)
