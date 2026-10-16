"""The Planning Center sync page against the golden congregation."""

import pytest

pytestmark = pytest.mark.django_db


class TestPcosyncPage:
    def test_the_sync_page_shows_what_needs_settling(self, golden, login):
        client = login("golden_data_organizer")
        response = client.get("/pcosync/sync/")
        assert response.status_code == 200
        assert response.context["user_is_data_admin"] is True
        # Unconfigured, so the button explains itself rather than being live.
        assert response.context["pcosync_blocking_reason"]
        # The API key must never reach a template.
        assert "api_key" not in str(response.context["pcosync_config"]).lower() or (
            not response.context["pcosync_config"].get("api_key")
        )
        assert [run.id for run in response.context["pcosync_runs"]] == [
            golden.pco_run.id
        ]
        kinds = {row["kind"] for row in response.context["pcosync_open_counts"]}
        assert "field_conflict" in kinds
