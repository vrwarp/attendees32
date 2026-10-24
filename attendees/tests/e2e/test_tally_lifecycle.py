"""The Tally integration's lifecycle against the whole golden congregation.

Tally writes through the API as the token, a leader edits one of those records
by hand, and then the integration is backed up, taken down with its untouched
records, restored, and undone — the way a church that stops using Tally, or
rebuilds its server, would do it.
"""

import json

import pytest
from django.core.management import call_command
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from attendees.persons.models import Attendee, Folk, FolkAttendee, Relation
from attendees.persons.services.tally_integration_service import TallyIntegrationService
from attendees.tests.golden.builder import GOLDEN_MEET_SLUGS
from attendees.tests.golden.constants import ORGANIZATION_SLUG
from attendees.users.models import User

pytestmark = pytest.mark.django_db

YOUTH_GROUP = GOLDEN_MEET_SLUGS["youth_group"]
ATTENDEE = "/persons/api/datagrid_data_attendee/"


@pytest.fixture
def tally(golden):
    call_command(
        "setup_tally_integration", organization_slug=ORGANIZATION_SLUG,
        readable_meet=[YOUTH_GROUP], verbosity=0,
    )
    user = User.objects.get(username="tally-integration")
    token, _ = Token.objects.get_or_create(user=user)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
    client.user = user
    client.division_id = Attendee.objects.get(user=user).division_id
    return client


def pushed(tally, golden, first_name, last_name="Tallyrun"):
    """A visitor Tally pushed: a new person with a family of their own, filed
    where Tally files everyone, its own division."""
    division = tally.division_id
    response = tally.post(
        ATTENDEE,
        {
            "first_name": first_name,
            "last_name": last_name,
            "gender": "UNSPECIFIED",
            "division": division,
            "infos": {"names": {}, "fixed": {}, "contacts": {}},
        },
        format="json",
        HTTP_X_TARGET_ATTENDEE_ID="new",
        HTTP_X_ADD_FOLK="new",
        HTTP_X_FOLK_ROLE=str(Relation.objects.get(title="child").pk),
    )
    assert response.status_code in (200, 201), response.content
    return Attendee.objects.get(pk=response.json()["id"])


def add_parent(tally, child, first_name, last_name="Tallyrun"):
    """What Tally's addParent does: a parent record, filed into the child's family."""
    family = Folk.objects.get(attendees=child, category_id=0)
    division = child.division_id
    response = tally.post(
        ATTENDEE,
        {
            "first_name": first_name, "last_name": last_name, "gender": "UNSPECIFIED",
            "division": division, "infos": {"names": {}, "fixed": {}, "contacts": {"phone1": "+15105550799"}},
        },
        format="json",
        HTTP_X_TARGET_ATTENDEE_ID="new",
    )
    assert response.status_code in (200, 201), response.content
    parent = Attendee.objects.get(pk=response.json()["id"])
    response = tally.post(
        "/persons/api/datagrid_data_familyattendees/",
        {"folk": str(family.id), "attendee": str(parent.id), "role": Relation.objects.get(title="parent").pk},
        format="json",
        HTTP_X_TARGET_ATTENDEE_ID=str(child.id),
    )
    assert response.status_code in (200, 201), response.content
    return parent, family


class TestLifecycle:
    def test_what_tally_wrote_is_told_apart_from_the_congregation(self, tally, golden, api_login):
        child = pushed(tally, golden, "Keanu")
        parent, family = add_parent(tally, child, "Lani")
        # Tally also edits a church record: a profile edit on a golden youth.
        hannah = golden.attendee("liu_hannah")
        response = tally.patch(
            f"{ATTENDEE}{hannah.id}/", {"first_name2": "Hannah"}, format="json",
            HTTP_X_TARGET_ATTENDEE_ID=str(hannah.id),
        )
        assert response.status_code == 200, response.content
        # And a leader corrects the parent's name by hand, in the app.
        leader = api_login("golden_data_organizer")
        response = leader.patch(
            f"{ATTENDEE}{parent.id}/", {"last_name": "Tallyrun-Hsu"}, format="json",
            HTTP_X_TARGET_ATTENDEE_ID=str(parent.id),
        )
        assert response.status_code == 200, response.content

        ledger = TallyIntegrationService.ledger(tally.user)
        made = {row["id"]: row for row in ledger["attendees"]["made"]}
        assert set(made) == {str(child.id), str(parent.id)}
        assert made[str(child.id)]["others_since"] is False
        assert made[str(parent.id)]["others_since"] is True
        assert [row["id"] for row in ledger["attendees"]["changed"]] == [str(hannah.id)]
        assert str(family.id) in {row["id"] for row in ledger["folks"]["made"]}
        # The congregation itself is not Tally's.
        assert len(made) == 2
        assert Attendee.objects.count() > 300

    def test_backup_delete_restore_round_trip(self, tally, golden, tmp_path):
        child = pushed(tally, golden, "Keanu")
        key = tally.user.auth_token.key
        backup = tmp_path / "backup.json"
        call_command("backup_tally_integration", "--out", str(backup), "--with-token", verbosity=0)
        data = json.loads(backup.read_text())
        assert data["readable_meets"] == [YOUTH_GROUP]
        # A division of Tally's own, made by the setup.
        assert data["division"] == f"{ORGANIZATION_SLUG}_tally"
        assert data["division_created"] is True

        receipt = tmp_path / "receipt.json"
        call_command("delete_tally_integration", "--force", "--receipt", str(receipt), verbosity=0)
        assert tally.get(ATTENDEE, {"take": 1}).status_code in (401, 403)
        # The person Tally made stays: no --purge.
        assert Attendee.objects.filter(pk=child.id).exists()
        # The division was made by the setup, but the child still lives in it, so it stays.
        child.division.refresh_from_db()
        assert not child.division.is_removed

        call_command("setup_tally_integration", "--from", str(backup), verbosity=0)
        assert User.objects.get(username="tally-integration").auth_token.key == key
        assert tally.get(ATTENDEE, {"take": 1}).status_code == 200
        response = tally.get("/occasions/api/organization_meets/", {"take": 100, "skip": 0})
        assert [row["slug"] for row in response.json()["data"]] == [YOUTH_GROUP]

    def test_purge_takes_tallys_untouched_records_and_nothing_else(self, tally, golden, api_login, tmp_path):
        child = pushed(tally, golden, "Keanu")
        parent, family = add_parent(tally, child, "Lani")
        edited = pushed(tally, golden, "Kept")
        leader = api_login("golden_data_organizer")
        leader.patch(f"{ATTENDEE}{edited.id}/", {"last_name": "Edited"}, format="json", HTTP_X_TARGET_ATTENDEE_ID=str(edited.id))
        hannah = golden.attendee("liu_hannah")
        tally.patch(f"{ATTENDEE}{hannah.id}/", {"first_name2": "Hannah"}, format="json", HTTP_X_TARGET_ATTENDEE_ID=str(hannah.id))
        before = Attendee.objects.count()

        receipt = tmp_path / "receipt.json"
        call_command("delete_tally_integration", "--force", "--purge", "--receipt", str(receipt), verbosity=0)

        assert Attendee.all_objects.get(pk=child.id).is_removed
        assert Attendee.all_objects.get(pk=parent.id).is_removed
        assert Folk.all_objects.get(pk=family.id).is_removed
        assert not FolkAttendee.objects.filter(folk=family).exists()
        # Edited by a leader since: kept. Edited by Tally, but the church's: kept.
        assert not Attendee.all_objects.get(pk=edited.id).is_removed
        assert not Attendee.all_objects.get(pk=hannah.id).is_removed
        assert Attendee.objects.get(pk=hannah.id).first_name2 == "Hannah"
        # Two people and the integration's own attendee went; nobody else.
        assert Attendee.objects.count() == before - 3

        call_command("delete_tally_integration", "--undo", str(receipt), verbosity=0)
        assert Attendee.objects.count() == before
        assert Folk.objects.filter(pk=family.id, attendees=parent).exists()
        assert tally.get(ATTENDEE, {"take": 1}).status_code == 200
