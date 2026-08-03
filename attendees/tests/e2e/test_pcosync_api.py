"""The Planning Center sync surface, against the whole congregation.

``attendees/pcosync/tests/`` proves the sync logic — the client, the mapping,
the merge rules, the runner — on constructed rows.  What it does not cover is
the surface a person touches: who may open the Sync page, who may start a run
or settle a disagreement, and whether the manual matcher can actually find a
person among 350 of them.  That is what this module is for, and it is why the
golden dataset seeds a finished run and the questions it left behind.
"""

import pytest

from attendees.pcosync.models import PcoDivergence, PcoPersonLink, PcoSyncRun
from attendees.persons.models import Attendee

pytestmark = pytest.mark.django_db

DIVERGENCES = "/pcosync/api/divergences/"
SYNC_RUNS = "/pcosync/api/sync_runs/"


# ------------------------------------------------------------------ the report
class TestDivergenceReport:
    def test_the_open_questions_are_listed(self, golden, api_login):
        client = api_login("golden_data_organizer")
        response = client.get(DIVERGENCES)
        assert response.status_code == 200
        kinds = {row["kind"] for row in response.json()["data"]}
        assert {
            PcoDivergence.FIELD_CONFLICT,
            PcoDivergence.UNLINKED_PERSON,
            PcoDivergence.HOUSEHOLD_CONFLICT,
        } <= kinds

    def test_a_settled_question_is_out_of_the_default_view(self, golden, api_login):
        settled = golden.pco_divergences["already_settled"]
        client = api_login("golden_data_organizer")
        open_ids = {row["id"] for row in client.get(DIVERGENCES).json()["data"]}
        assert str(settled.id) not in open_ids

        every_id = {
            row["id"]
            for row in client.get(DIVERGENCES, {"resolution": "all"}).json()["data"]
        }
        assert str(settled.id) in every_id

    def test_the_report_filters_by_kind_and_severity(self, golden, api_login):
        client = api_login("golden_data_organizer")
        by_kind = client.get(DIVERGENCES, {"kind": PcoDivergence.UNLINKED_PERSON})
        assert by_kind.status_code == 200
        assert {row["kind"] for row in by_kind.json()["data"]} == {
            PcoDivergence.UNLINKED_PERSON
        }

        errors = client.get(DIVERGENCES, {"severity": PcoDivergence.ERROR})
        assert {row["severity"] for row in errors.json()["data"]} == {
            PcoDivergence.ERROR
        }

    def test_the_report_can_be_searched(self, golden, api_login):
        client = api_login("golden_data_organizer")
        # q matches the label or the pointer
        by_pointer = client.get(DIVERGENCES, {"q": "chinese_first_name"})
        assert by_pointer.status_code == 200
        assert by_pointer.json()["totalCount"] == 1

        by_label = client.get(DIVERGENCES, {"q": "household"})
        assert {row["kind"] for row in by_label.json()["data"]} == {
            PcoDivergence.HOUSEHOLD_CONFLICT
        }

    def test_another_organization_sees_none_of_it(self, golden, api_login):
        client = api_login("golden_outsider")
        assert client.get(DIVERGENCES).json()["totalCount"] == 0


# ------------------------------------------------------------- settling things
class TestResolving:
    def test_a_data_admin_keeps_the_local_value(self, golden, api_login):
        divergence = golden.pco_divergences["field_conflict"]
        client = api_login("golden_data_organizer")
        response = client.patch(
            f"{DIVERGENCES}{divergence.id}/resolve/",
            {"resolution": PcoDivergence.KEEP_LOCAL},
            format="json",
        )
        assert response.status_code == 200, response.content

        divergence.refresh_from_db()
        assert divergence.resolution == PcoDivergence.KEEP_LOCAL
        assert divergence.resolved_by.username == "golden_data_organizer"
        # Keeping the local value records what Planning Center held as the
        # agreed baseline, so the next run sees only attendees32 as moved.
        divergence.link.refresh_from_db()
        assert divergence.link.baseline["first_name2"] == "志銘"

    def test_ignoring_a_field_stops_it_being_reported(self, golden, api_login):
        divergence = golden.pco_divergences["field_conflict"]
        client = api_login("golden_data_organizer")
        response = client.patch(
            f"{DIVERGENCES}{divergence.id}/resolve/",
            {"resolution": PcoDivergence.IGNORED},
            format="json",
        )
        assert response.status_code == 200, response.content
        divergence.link.refresh_from_db()
        assert "first_name2" in divergence.link.infos["ignored_fields"]

    def test_an_ordinary_member_cannot_settle_anything(self, golden, api_login):
        divergence = golden.pco_divergences["field_conflict"]
        client = api_login("golden_member")
        response = client.patch(
            f"{DIVERGENCES}{divergence.id}/resolve/",
            {"resolution": PcoDivergence.KEEP_PCO},
            format="json",
        )
        assert response.status_code == 403
        divergence.refresh_from_db()
        assert divergence.resolution == PcoDivergence.OPEN

    def test_a_counselor_is_privileged_but_not_a_data_admin(self, golden, api_login):
        divergence = golden.pco_divergences["household_conflict"]
        client = api_login("golden_counselor")
        response = client.patch(
            f"{DIVERGENCES}{divergence.id}/resolve/",
            {"resolution": PcoDivergence.KEEP_LOCAL},
            format="json",
        )
        assert response.status_code == 403


# --------------------------------------------------------------- matching people
class TestManualLinking:
    def test_an_unmatched_person_can_be_pointed_at_an_attendee(
        self, golden, api_login
    ):
        divergence = golden.pco_divergences["unlinked_person"]
        newcomer = golden.attendee("feng_ruian")  # nobody has linked him yet
        client = api_login("golden_data_organizer")
        response = client.patch(
            f"{DIVERGENCES}{divergence.id}/link/",
            {"attendee_id": str(newcomer.id)},
            format="json",
        )
        assert response.status_code == 200, response.content

        link = PcoPersonLink.objects.get(pco_person_id="199003050")
        assert link.attendee_id == newcomer.id
        assert link.link_source == PcoPersonLink.BY_MATCH
        # Never agreed on anything yet, so the next run treats every field as a
        # first look rather than assuming a history that did not happen.
        assert link.baseline == {}

    def test_linking_an_already_linked_attendee_is_refused(self, golden, api_login):
        divergence = golden.pco_divergences["unlinked_person"]
        taken = golden.attendee("chen_zhiming")  # already has a live link
        client = api_login("golden_data_organizer")
        response = client.patch(
            f"{DIVERGENCES}{divergence.id}/link/",
            {"attendee_id": str(taken.id)},
            format="json",
        )
        assert response.status_code == 409

    def test_linking_someone_from_another_organization_is_refused(
        self, golden, api_login
    ):
        divergence = golden.pco_divergences["unlinked_person"]
        client = api_login("golden_data_organizer")
        response = client.patch(
            f"{DIVERGENCES}{divergence.id}/link/",
            {"attendee_id": "00000000-0000-0000-0000-000000000000"},
            format="json",
        )
        assert response.status_code == 404

    def test_only_an_unmatched_row_can_be_linked(self, golden, api_login):
        divergence = golden.pco_divergences["field_conflict"]
        client = api_login("golden_data_organizer")
        response = client.patch(
            f"{DIVERGENCES}{divergence.id}/link/",
            {"attendee_id": str(golden.attendee("feng_ruian").id)},
            format="json",
        )
        assert response.status_code == 400


class TestAttendeeSearch:
    def test_a_short_term_returns_nothing(self, golden, api_login):
        client = api_login("golden_data_organizer")
        response = client.get(f"{DIVERGENCES}attendee_search/", {"q": "L"})
        assert response.status_code == 200
        assert response.json() == []

    def test_a_romanised_surname_finds_the_han_spelling(self, golden, api_login):
        """The docstring's own claim: typing "Tsai" finds 蔡."""
        client = api_login("golden_data_organizer")
        response = client.get(f"{DIVERGENCES}attendee_search/", {"q": "Tsai"})
        assert response.status_code == 200
        labels = " ".join(row["display_label"] for row in response.json())
        assert "蔡" in labels

    def test_searching_the_han_characters_works_too(self, golden, api_login):
        client = api_login("golden_data_organizer")
        response = client.get(f"{DIVERGENCES}attendee_search/", {"q": "陳明恩"})
        assert str(golden.attendee("chen_grace").id) in {
            row["attendee_id"] for row in response.json()
        }

    def test_the_picker_is_capped_and_scoped(self, golden, api_login):
        client = api_login("golden_data_organizer")
        response = client.get(f"{DIVERGENCES}attendee_search/", {"q": "en"})
        rows = response.json()
        assert 0 < len(rows) <= 25
        organization_ids = set(
            str(pk)
            for pk in Attendee.objects.filter(
                division__organization=golden.user("golden_data_organizer").organization
            ).values_list("id", flat=True)
        )
        assert {row["attendee_id"] for row in rows} <= organization_ids

    def test_someone_elses_organization_finds_nobody(self, golden, api_login):
        client = api_login("golden_outsider")
        response = client.get(f"{DIVERGENCES}attendee_search/", {"q": "Chen"})
        assert response.json() == []


# ------------------------------------------------------------------- the runs
class TestSyncRuns:
    def test_past_runs_are_listed(self, golden, api_login):
        client = api_login("golden_data_organizer")
        response = client.get(SYNC_RUNS)
        assert response.status_code == 200
        assert str(golden.pco_run.id) in {row["id"] for row in response.json()["data"]}

    def test_runs_are_scoped_to_the_callers_organization(self, golden, api_login):
        client = api_login("golden_outsider")
        assert client.get(SYNC_RUNS).json()["totalCount"] == 0

    def test_an_ordinary_member_cannot_start_a_sync(self, golden, api_login):
        client = api_login("golden_member")
        response = client.post(
            SYNC_RUNS, {"mode": PcoSyncRun.DRY_RUN}, format="json"
        )
        assert response.status_code == 403
        assert PcoSyncRun.objects.count() == 1  # only the golden one

    def test_an_unconfigured_organization_cannot_start_a_sync(self, golden, api_login):
        """CFCCH has no Planning Center credentials, and the button says so.

        Every default in the config means "does nothing", so a half-finished
        setup is an inert button rather than a surprise write into a live
        church database.
        """
        client = api_login("golden_data_organizer")
        response = client.post(
            SYNC_RUNS, {"mode": PcoSyncRun.DRY_RUN}, format="json"
        )
        assert response.status_code == 400, response.content
        assert response.json()["detail"]
        assert PcoSyncRun.objects.count() == 1

    def test_a_login_without_an_organization_is_refused(self, golden, api_login):
        client = api_login("golden_outsider")
        response = client.post(
            SYNC_RUNS, {"mode": PcoSyncRun.DRY_RUN}, format="json"
        )
        assert response.status_code == 403
