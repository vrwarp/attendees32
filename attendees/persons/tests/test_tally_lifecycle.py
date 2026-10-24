"""
The Tally integration's lifecycle on a minimal fixture: what it wrote, backing
up the connection, taking it down, and putting it back.

The ledger stands on one fact — the history context names the user behind
every change — so the first test proves that fact for a token client under
ASGI, which is how this server runs and where the middleware alone loses it.
"""
import json

import pghistory
import pytest
from asgiref.sync import async_to_sync
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import AsyncClient
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from attendees.persons.models import Attendee, Attending, Folk, FolkAttendee, Relation
from attendees.persons.models.attendee import AttendeesHistory
from attendees.persons.services.merge_service import AttendeeMergeService
from attendees.persons.services.tally_integration_service import (
    NoIntegration,
    TallyIntegrationService,
)
from attendees.persons.tests.test_tally_integration import meet, organization, vocabulary  # noqa: F401
from attendees.users.models import User
from attendees.whereabouts.models import Division, Organization

pytestmark = pytest.mark.django_db

PERSON = {
    "first_name": "Keanu",
    "last_name": "Visitor",
    "gender": "UNSPECIFIED",
    "infos": {"names": {}, "fixed": {}, "contacts": {}},
}


@pytest.fixture
def integration(organization, vocabulary, meet):  # noqa: F811
    call_command("setup_tally_integration", "--organization-slug", "testorg", "--readable-meet", meet.slug)
    user = User.objects.get(username="tally-integration")
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Token {user.auth_token.key}")
    division = Division.objects.get(slug="testorg_tally")
    return {"user": user, "client": client, "division": division, "meet": meet, "organization": organization}


@pytest.fixture
def pastor(organization, integration):
    """A person of the church who edits records by hand: the 'someone else'."""
    user = User.objects.create(username="pastor", email="pastor@example.org", organization=organization)
    Attendee.objects.create(
        division=integration["division"], user=user, first_name="Pastor", last_name="Chen",
        gender="UNSPECIFIED", infos={"names": {}, "fixed": {}, "contacts": {}},
    )
    return user


def as_tally(integration, **fields):
    """A person Tally pushed: created through the API with the token, family and all."""
    response = integration["client"].post(
        "/persons/api/datagrid_data_attendee/",
        {**PERSON, **fields, "division": integration["division"].id},
        format="json",
        HTTP_X_TARGET_ATTENDEE_ID="new",
        HTTP_X_ADD_FOLK="new",
        HTTP_X_FOLK_ROLE=str(Relation.objects.get(title="child").pk),
    )
    assert response.status_code in (200, 201), response.content
    return Attendee.objects.get(pk=response.json()["id"])


def touched_by(user, person, **fields):
    with pghistory.context(user=user.pk):
        for name, value in fields.items():
            setattr(person, name, value)
        person.save()


class TestHistoryNamesTheTokenUser:
    def test_a_token_write_over_wsgi(self, integration):
        person = as_tally(integration)
        first = AttendeesHistory.objects.filter(pgh_obj_id=person.id).order_by("pgh_id").first()
        assert first.pgh_context.metadata["user"] == integration["user"].pk

    def test_a_token_write_over_asgi(self, integration):
        # The production server. The middleware alone records nobody here;
        # TrackedTokenAuthentication is what names the user.
        client = AsyncClient()
        response = async_to_sync(client.post)(
            "/persons/api/datagrid_data_attendee/",
            data=json.dumps({**PERSON, "division": integration["division"].id}),
            content_type="application/json",
            headers={
                "Authorization": f"Token {integration['user'].auth_token.key}",
                "X-Target-Attendee-Id": "new",
            },
        )
        assert response.status_code in (200, 201), response.content
        first = AttendeesHistory.objects.filter(pgh_obj_id=response.json()["id"]).order_by("pgh_id").first()
        assert first.pgh_context.metadata["user"] == integration["user"].pk


class TestLedger:
    def test_what_tally_made_is_listed_with_its_families(self, integration):
        person = as_tally(integration)
        ledger = TallyIntegrationService.ledger(integration["user"])
        assert [row["id"] for row in ledger["attendees"]["made"]] == [str(person.id)]
        # The family the create asked for, and the hidden folk the signal makes.
        assert len(ledger["folks"]["made"]) == 2
        assert len(ledger["folk_attendees"]["made"]) == 2
        assert all(row["others_since"] is False for row in ledger["attendees"]["made"])

    def test_a_record_someone_else_edited_is_marked(self, integration, pastor):
        person = as_tally(integration)
        touched_by(pastor, person, last_name="Renamed")
        ledger = TallyIntegrationService.ledger(integration["user"])
        assert ledger["attendees"]["made"][0]["others_since"] is True

    def test_a_church_record_tally_edited_is_changed_not_made(self, integration, pastor):
        theirs = Attendee.objects.get(user=pastor)
        response = integration["client"].patch(
            f"/persons/api/datagrid_data_attendee/{theirs.id}/",
            {"first_name": "Pastor-Edited"},
            format="json",
            HTTP_X_TARGET_ATTENDEE_ID=str(theirs.id),
        )
        assert response.status_code == 200, response.content
        ledger = TallyIntegrationService.ledger(integration["user"])
        assert [row["id"] for row in ledger["attendees"]["changed"]] == [str(theirs.id)]
        assert ledger["attendees"]["made"] == []

    def test_a_merged_record_is_marked(self, integration):
        first, second = as_tally(integration), as_tally(integration, first_name="Keanu2")
        AttendeeMergeService.merge(second, first, by=str(Attendee.objects.get(user=integration["user"]).id))
        rows = {row["id"]: row for row in TallyIntegrationService.ledger(integration["user"])["attendees"]["made"]}
        assert rows[str(second.id)]["merged"] is True
        assert rows[str(first.id)]["merged"] is False


class TestBackup:
    def test_describes_the_connection_without_the_token(self, integration):
        backup = TallyIntegrationService.backup()
        assert backup["organization"] == "testorg"
        assert backup["division"] == "testorg_tally"
        assert backup["division_created"] is True
        assert backup["readable_meets"] == [integration["meet"].slug]
        assert backup["token"] is None

    def test_includes_the_token_on_request(self, integration):
        assert TallyIntegrationService.backup(with_token=True)["token"] == integration["user"].auth_token.key

    def test_the_command_writes_a_file(self, integration, tmp_path):
        out = tmp_path / "backup.json"
        call_command("backup_tally_integration", "--out", str(out))
        assert json.loads(out.read_text())["format"] == "tally-integration-backup/1"

    def test_refuses_without_an_integration(self, organization, vocabulary):
        with pytest.raises(CommandError, match="No user"):
            call_command("backup_tally_integration")


class TestDelete:
    def test_a_dry_run_changes_nothing(self, integration):
        as_tally(integration)
        call_command("delete_tally_integration", "--purge")
        assert Token.objects.filter(user=integration["user"]).exists()
        assert Attendee.objects.count() == 2

    def test_takes_the_connection_down(self, integration, tmp_path):
        receipt = TallyIntegrationService.delete()
        user = User.objects.get(username="tally-integration")
        assert not user.is_active
        assert not user.groups.exists()
        assert not Token.objects.filter(user=user).exists()
        organization = Organization.objects.get(slug="testorg")
        assert "tally_integration" not in organization.infos["groups_see_all_meets_attendees"]
        assert "tally_integration" not in organization.infos["counselor"]
        integration["meet"].refresh_from_db()
        assert "tally_integration" not in integration["meet"].infos["allowed_groups"]
        assert Attendee.all_objects.get(user=user).is_removed
        assert Division.all_objects.get(slug="testorg_tally").is_removed
        assert receipt["connection"]["division_removed"] is True
        assert receipt["connection"]["token"] == receipt["backup"]["token"]

    def test_the_token_is_refused_afterwards(self, integration):
        TallyIntegrationService.delete()
        response = integration["client"].get("/persons/api/datagrid_data_attendee/", {"take": 1})
        assert response.status_code in (401, 403)

    def test_without_purge_the_records_stay(self, integration):
        person = as_tally(integration)
        TallyIntegrationService.delete()
        assert Attendee.objects.filter(pk=person.id).exists()
        # Somebody still lives in the division, so it stays too.
        assert not Division.all_objects.get(slug="testorg_tally").is_removed

    def test_purge_removes_only_what_nobody_else_touched(self, integration, pastor):
        gone, kept = as_tally(integration), as_tally(integration, first_name="Kept")
        touched_by(pastor, kept, last_name="Edited")
        receipt = TallyIntegrationService.delete(purge=True)
        assert Attendee.all_objects.get(pk=gone.id).is_removed
        assert not Attendee.all_objects.get(pk=kept.id).is_removed
        assert [row["id"] for row in receipt["kept"]["attendees"]] == [str(kept.id)]
        assert receipt["removed"]["attendees"] == [str(gone.id)]
        # Their families, memberships and attendings went with them.
        assert not Folk.objects.filter(attendees=gone).exists()
        assert not FolkAttendee.objects.filter(attendee=gone).exists()
        assert not Attending.objects.filter(attendee=gone).exists()
        # A family someone still lives in stays, with its memberships.
        assert Folk.objects.filter(attendees=kept).count() == 2
        assert FolkAttendee.objects.filter(attendee=kept).count() == 2
        assert {row["id"] for row in receipt["kept"]["folks"]} == {str(f.id) for f in Folk.objects.filter(attendees=kept)}

    def test_purge_leaves_a_merged_record_unless_told_to_unmerge(self, integration):
        first, second = as_tally(integration), as_tally(integration, first_name="Keanu2")
        AttendeeMergeService.merge(second, first, by=str(Attendee.objects.get(user=integration["user"]).id))
        receipt = TallyIntegrationService.delete(purge=True)
        assert [row["id"] for row in receipt["kept"]["attendees"]] == [str(second.id)]
        assert receipt["removed"]["attendees"] == [str(first.id)]
        TallyIntegrationService.undo(receipt)

        receipt = TallyIntegrationService.delete(purge=True, unmerge=True)
        assert sorted(receipt["removed"]["attendees"]) == sorted([str(first.id), str(second.id)])
        assert receipt["unmerged"] == [str(second.id)]
        assert Attendee.all_objects.get(pk=second.id).merged_into_id is None

    def test_the_command_writes_a_receipt_and_undoes_from_it(self, integration, tmp_path):
        person = as_tally(integration)
        receipt = tmp_path / "receipt.json"
        call_command("delete_tally_integration", "--force", "--purge", "--receipt", str(receipt))
        assert Attendee.all_objects.get(pk=person.id).is_removed
        assert not User.objects.get(username="tally-integration").is_active

        call_command("delete_tally_integration", "--undo", str(receipt))
        assert not Attendee.all_objects.get(pk=person.id).is_removed
        user = User.objects.get(username="tally-integration")
        assert user.is_active
        assert user.auth_token.key == json.loads(receipt.read_text())["connection"]["token"]

    def test_refuses_without_an_integration(self, organization, vocabulary):
        with pytest.raises(CommandError, match="No user"):
            call_command("delete_tally_integration", "--force")
        with pytest.raises(NoIntegration):
            TallyIntegrationService.delete()


class TestUndo:
    def test_puts_the_whole_connection_back(self, integration, pastor):
        person = as_tally(integration)
        key = integration["user"].auth_token.key
        receipt = TallyIntegrationService.delete(purge=True)
        TallyIntegrationService.undo(receipt)

        user = User.objects.get(username="tally-integration")
        assert user.is_active and user.groups.filter(name="tally_integration").exists()
        assert user.auth_token.key == key
        organization = Organization.objects.get(slug="testorg")
        assert "tally_integration" in organization.infos["groups_see_all_meets_attendees"]
        assert "tally_integration" in organization.infos["counselor"]
        integration["meet"].refresh_from_db()
        assert "tally_integration" in integration["meet"].infos["allowed_groups"]
        assert not Attendee.all_objects.get(user=user).is_removed
        assert not Division.all_objects.get(slug="testorg_tally").is_removed
        assert not Attendee.all_objects.get(pk=person.id).is_removed
        assert Folk.objects.filter(attendees=person).count() == 2
        assert Attending.objects.filter(attendee=person).exists()
        # And the token works again.
        assert integration["client"].get("/persons/api/datagrid_data_attendee/", {"take": 1}).status_code == 200

    def test_refuses_a_file_that_is_not_a_receipt(self, integration, tmp_path):
        path = tmp_path / "not-a-receipt.json"
        path.write_text(json.dumps({"format": "something-else"}))
        with pytest.raises(CommandError, match="Could not undo"):
            call_command("delete_tally_integration", "--undo", str(path))


class TestRestore:
    def test_setup_from_a_backup_brings_the_same_token_back(self, integration, tmp_path):
        key = integration["user"].auth_token.key
        out = tmp_path / "backup.json"
        call_command("backup_tally_integration", "--out", str(out), "--with-token")
        TallyIntegrationService.delete()

        call_command("setup_tally_integration", "--from", str(out))
        user = User.objects.get(username="tally-integration")
        assert user.is_active
        assert user.auth_token.key == key
        assert "tally_integration" in Organization.objects.get(slug="testorg").infos["counselor"]
        integration["meet"].refresh_from_db()
        assert "tally_integration" in integration["meet"].infos["allowed_groups"]
        assert not Attendee.all_objects.get(user=user).is_removed
        assert not Division.all_objects.get(slug="testorg_tally").is_removed
        assert integration["client"].get("/persons/api/datagrid_data_attendee/", {"take": 1}).status_code == 200

    def test_setup_from_a_backup_without_a_token_mints_a_new_one(self, integration, tmp_path):
        key = integration["user"].auth_token.key
        out = tmp_path / "backup.json"
        call_command("backup_tally_integration", "--out", str(out))
        TallyIntegrationService.delete()
        call_command("setup_tally_integration", "--from", str(out))
        assert User.objects.get(username="tally-integration").auth_token.key != key

    def test_refuses_a_file_that_is_not_a_backup(self, organization, vocabulary, tmp_path):
        path = tmp_path / "x.json"
        path.write_text(json.dumps({"format": "tally-integration-receipt/1"}))
        with pytest.raises(CommandError, match="not a backup"):
            call_command("setup_tally_integration", "--from", str(path))

    def test_setup_needs_an_organization_or_a_file(self, organization, vocabulary):
        with pytest.raises(CommandError, match="organization-slug is required"):
            call_command("setup_tally_integration")
