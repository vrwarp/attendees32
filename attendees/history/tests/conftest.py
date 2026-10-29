import pytest
from django.contrib.auth.models import Group

from attendees.persons.models import Attendee, Category, Relation
from attendees.persons.models.enum import GenderEnum
from attendees.whereabouts.models import Division, Organization


@pytest.fixture
def division(db):
    """An organization with one division and the rows an attendee needs to exist."""
    organization = Organization.objects.create(display_name="Test Organization", slug="test-org")
    group = Group.objects.create(name="Test Group")
    Relation.objects.get_or_create(id=0, defaults={"title": "self", "gender": GenderEnum.UNSPECIFIED.value})
    Category.objects.get_or_create(id=0, defaults={"display_name": "Family"})
    Category.objects.get_or_create(id=25, defaults={"display_name": "Non-family"})
    return Division.objects.create(
        organization=organization, display_name="Test Division", slug="test-division", audience_auth_group=group
    )


@pytest.fixture
def make_attendee(division):
    def factory(**fields):
        values = {"first_name": "Grace", "last_name": "Chen", "gender": GenderEnum.UNSPECIFIED.value, "division": division}
        values.update(fields)
        return Attendee.objects.create(**values)

    return factory
