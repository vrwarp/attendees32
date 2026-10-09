from io import StringIO

import pytest
from django.core.management import call_command
from rest_framework.test import APIClient

from attendees.occasions.models import Assembly, Character, Meet
from attendees.persons.models import Attendee, Category, Relation
from attendees.users.models import User
from attendees.whereabouts.models import Division, Organization

pytestmark = pytest.mark.django_db


@pytest.fixture
def organization():
    return Organization.objects.create(
        slug="testorg",
        display_name="Test Organization",
        infos={
            "acronym": "test",
            "contacts": {},
            "settings": {"attendee_to_attending": True},
            "counselor": [],
            "data_admins": [],
            "groups_see_all_meets_attendees": [],
            "default_time_zone": "America/Los_Angeles",
        },
    )


@pytest.fixture
def vocabulary():
    """The slice of fixtures/db_seed.json the command stands on."""
    Category.objects.get_or_create(
        pk=Attendee.FAMILY_CATEGORY, defaults={"type": "folk", "display_name": "family", "infos": {}}
    )
    Category.objects.get_or_create(
        pk=Attendee.NON_FAMILY_CATEGORY, defaults={"type": "folk", "display_name": "other", "infos": {}}
    )
    # Creating any attendee files them into a hidden non-family folk with Relation pk 0.
    Relation.objects.get_or_create(
        pk=Attendee.HIDDEN_ROLE,
        defaults={"title": "hidden", "gender": "UNSPECIFIED", "reciprocal_ids": []},
    )
    for title in ("child", "parent"):
        Relation.objects.get_or_create(
            title=title, defaults={"gender": "UNSPECIFIED", "emergency_contact": True, "reciprocal_ids": []}
        )


def setup(**options):
    out = StringIO()
    call_command("setup_tally_integration", "--organization-slug", "testorg", stdout=out, **options)
    return out.getvalue()


@pytest.fixture
def provisioned(organization, vocabulary):
    output = setup()
    user = User.objects.get(username="tally-integration")
    return {
        "output": output,
        "user": user,
        "token": user.auth_token.key,
        "attendee": Attendee.objects.get(user=user),
        "assembly": Assembly.objects.get(slug="testorg_tally_youth_ministry"),
        "meet": Meet.objects.get(slug="testorg_tally_gathering"),
    }


class TestSetupTallyIntegration:
    def test_provisions_the_user_attendee_meet_and_token(self, provisioned):
        user = provisioned["user"]
        assert user.groups.filter(name="tally_integration").exists()
        assert Division.objects.filter(slug="testorg_tally_youth").exists()
        assert Character.objects.filter(slug="testorg_tally_student").exists()
        assert f"A32_TOKEN={provisioned['token']}" in provisioned["output"]

    def test_grants_editing_but_not_counselor(self, provisioned):
        infos = Organization.objects.get(slug="testorg").infos
        assert "tally_integration" in infos["groups_see_all_meets_attendees"]
        assert "tally_integration" not in infos["counselor"]

    def test_running_it_again_changes_nothing(self, provisioned):
        def counts():
            return [model.objects.count() for model in (Division, Assembly, Meet, Character, User, Attendee)]

        before = counts()
        setup()
        assert counts() == before
        assert Organization.objects.get(slug="testorg").infos["groups_see_all_meets_attendees"] == ["tally_integration"]

    def test_warns_about_an_existing_counselor_grant(self, organization, vocabulary):
        organization.infos["counselor"] = ["tally_integration"]
        organization.save()
        assert "also in the organization's counselor list" in setup()

    def test_an_unknown_organization_is_refused(self, organization, vocabulary):
        from django.core.management.base import CommandError

        with pytest.raises(CommandError, match="No organization"):
            call_command("setup_tally_integration", "--organization-slug", "nope", stdout=StringIO())

    def test_the_token_reaches_every_endpoint_tally_reads(self, provisioned):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Token {provisioned['token']}")
        itself = {"HTTP_X_TARGET_ATTENDEE_ID": str(provisioned["attendee"].id)}
        reads = [
            ("/persons/api/datagrid_data_attendee/", {"take": 5}, {}),
            ("/persons/api/datagrid_data_attendee/", {"searchValue": "Tally"}, {}),
            ("/persons/api/attendee_attendings/", {}, itself),
            ("/persons/api/attendee_families/", {}, itself),
            ("/persons/api/datagrid_data_familyattendees/", {"categoryId": Attendee.FAMILY_CATEGORY}, itself),
            ("/occasions/api/organization_meets/", {"assemblies[]": provisioned["assembly"].id}, {}),
            ("/occasions/api/organization_team_gatherings/", {"meets[]": provisioned["meet"].slug}, {}),
            ("/occasions/api/organization_meet_character_attendances/", {"meets[]": provisioned["meet"].slug}, {}),
        ]
        for path, params, headers in reads:
            response = client.get(path, params, **headers)
            assert response.status_code == 200, f"{path} -> {response.status_code}"

    def test_the_relation_vocabulary_is_readable_without_counselor(self, provisioned):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Token {provisioned['token']}")
        response = client.get("/persons/api/all_relations/", {"category_id": Attendee.FAMILY_CATEGORY})
        assert response.status_code == 200
        assert {"child", "parent"} <= {row["title"] for row in response.json()["data"]}
