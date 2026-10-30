"""Every detail page, export and print of personal data writes an access row."""
import pytest
from django.contrib.auth.models import Group
from django.urls import reverse

from attendees.access.models import AccessLog
from attendees.tests.e2e.helpers import target
from attendees.tests.golden.constants import MeetSlugs
from attendees.users.tests.factories import enrol_second_factor

pytestmark = pytest.mark.django_db


def rows(**filters):
    return list(AccessLog.objects.filter(**filters).order_by("when"))


class TestDetailPages:
    def test_the_person_page_logs_the_person_viewed(self, golden, login):
        grace = golden.attendee("chen_grace")
        client = login("golden_data_organizer")
        response = client.get(f"/persons/attendee/{grace.pk}")
        assert response.status_code == 200
        (row,) = rows(model="persons.attendee", object_id=str(grace.pk), how=AccessLog.DETAIL)
        assert row.user.username == "golden_data_organizer" and row.user_name == "golden_data_organizer"
        assert row.endpoint == "persons:attendee_update_view"
        assert row.address

    def test_the_single_person_api_logs_the_person_served(self, golden, api_login):
        grace = golden.attendee("chen_grace")
        client = target(api_login("golden_data_organizer"), grace)
        assert client.get(f"/persons/api/datagrid_data_attendee/{grace.pk}/").status_code == 200
        assert len(rows(model="persons.attendee", object_id=str(grace.pk), how=AccessLog.DETAIL)) == 1

    def test_a_token_client_is_logged_under_its_user(self, golden, token_client):
        grace = golden.attendee("chen_grace")
        client = target(token_client("golden_data_organizer"), grace)
        assert client.get(f"/persons/api/datagrid_data_attendee/{grace.pk}/").status_code == 200
        (row,) = rows(model="persons.attendee", object_id=str(grace.pk))
        assert row.user.username == "golden_data_organizer"

    def test_a_refused_request_logs_nothing(self, golden, api_login):
        grace = golden.attendee("chen_grace")
        client = target(api_login("golden_outsider"), grace)  # authenticated, but outside the organization
        assert client.get(f"/persons/api/datagrid_data_attendee/{grace.pk}/").status_code in {403, 404}
        assert rows(model="persons.attendee", object_id=str(grace.pk)) == []

    def test_a_place_detail_logs_the_place(self, golden, api_login):
        grace = golden.attendee("chen_grace")
        place = grace.places.first() or grace.folks.first().places.first()
        client = target(api_login("golden_data_organizer"), grace)
        assert client.get(f"/whereabouts/api/datagrid_data_place/{place.pk}/").status_code == 200
        assert len(rows(model="whereabouts.place", object_id=str(place.pk), how=AccessLog.DETAIL)) == 1

    def test_lists_are_not_logged(self, golden, api_login):
        client = api_login("golden_data_organizer")
        assert client.get("/persons/api/datagrid_data_attendees/", {"take": 5}).status_code == 200
        assert AccessLog.objects.count() == 0


class TestExportsAndPrints:
    def test_the_directory_report_logs_the_job_and_its_filters(self, golden, login):
        client = login("golden_data_organizer")
        division = golden.attendee("chen_grace").division
        response = client.get(
            reverse("persons:directory_report_list_view"),
            {"divisionSelector": [division.pk], "directoryHeader": "CFCCH 通訊錄 2026", "indexRowPerPage": 26},
        )
        assert response.status_code == 200
        (row,) = rows(how=AccessLog.PRINT, endpoint="persons:directory_report_list_view")
        assert row.model == "" and row.details["divisionSelector"] == [str(division.pk)]
        assert row.details["directoryHeader"] == ["CFCCH 通訊錄 2026"]

    @pytest.mark.parametrize(
        "name, params",
        [
            ("persons:attendingmeet_report_list_view", {"meet": MeetSlugs.CHINESE_SERVICE, "showPaused": "false"}),
            ("persons:attendingmeet_envelopes_list_view", {"meet": MeetSlugs.CHINESE_SERVICE}),
        ],
    )
    def test_the_participation_report_and_the_envelopes_log_a_print(self, golden, login, name, params):
        client = login("golden_data_organizer")
        response = client.get(reverse(name), params)
        assert response.status_code == 200, response.content[:200]
        (row,) = rows(how=AccessLog.PRINT, endpoint=name)
        assert row.details["meet"] == [params["meet"]]

    def test_the_directory_preview_logs_a_print_of_the_household(self, golden, login):
        grace = golden.attendee("chen_grace")
        client = login("golden_data_organizer")
        response = client.get(reverse("persons:person_directory_preview", kwargs={"attendee_id": grace.pk}))
        assert response.status_code == 200
        (row,) = rows(how=AccessLog.PRINT, endpoint="persons:person_directory_preview")
        assert row.object_id == str(grace.pk)


class TestReviewAndRetention:
    def test_only_a_viewer_of_the_log_may_read_it_and_nobody_edits_it(self, golden, login, django_user_model):
        grace = golden.attendee("chen_grace")
        organizer = login("golden_data_organizer")
        organizer.get(f"/persons/attendee/{grace.pk}")
        owner = enrol_second_factor(
            django_user_model.objects.create_superuser(username="owner", email="owner@example.com", password="pw")
        )
        from django.test import Client

        client = Client()
        client.force_login(owner)
        listing = client.get(reverse("admin:access_accesslog_changelist"), {"object_id": str(grace.pk)})
        assert listing.status_code == 200 and "golden_data_organizer" in listing.content.decode()
        assert client.get(reverse("admin:access_accesslog_add")).status_code == 403
        entry = AccessLog.objects.first()
        assert client.post(reverse("admin:access_accesslog_delete", args=[entry.pk]), {"post": "yes"}).status_code == 403

    def test_old_rows_are_pruned_after_twelve_months(self, golden, login):
        from datetime import timedelta

        from django.core.management import call_command
        from django.utils import timezone

        grace = golden.attendee("chen_grace")
        login("golden_data_organizer").get(f"/persons/attendee/{grace.pk}")
        AccessLog.objects.update(when=timezone.now() - timedelta(days=400))
        call_command("prune_access_log")
        assert AccessLog.objects.count() == 0
