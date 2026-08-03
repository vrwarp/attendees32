"""The endpoints behind the Sync page.

Driven through ``APIRequestFactory`` rather than the URL conf, so these test the
viewsets' own rules -- who may act, and what resolving actually does -- without
depending on the whole project's routing being importable.
"""

import pytest
from django.contrib.auth.models import Group
from rest_framework.test import APIRequestFactory, force_authenticate

from attendees.pcosync.models import PcoDivergence, PcoPersonLink, PcoSyncRun
from attendees.pcosync.services.config import write_config
from attendees.pcosync.views import ApiPcoDivergencesViewSet, ApiPcoSyncRunsViewSet
from attendees.persons.models import Attendee, Category, GenderEnum, Relation
from attendees.users.models import User
from attendees.whereabouts.models import Division, Organization

BASE = "https://mirror.test/people/v2"
KEY = "pcm_test_key"


@pytest.mark.django_db
class TestApi:
    def setup_method(self):
        self.factory = APIRequestFactory()
        self.organization = Organization.objects.create(
            display_name="Test Organization", slug="testorg")
        self.admin_group = Group.objects.create(name="data_organizer")
        self.division = Division.objects.create(
            organization=self.organization, display_name="Chinese Ministry",
            slug="chinese-ministry", audience_auth_group=self.admin_group)
        Category.objects.create(id=25, display_name="other", type="generic")
        Relation.objects.create(id=0, title="hidden",
                                gender=GenderEnum.UNSPECIFIED.value)

        write_config(self.organization, {
            "enabled": True, "dry_run": True, "base_url": BASE,
            "api_key": KEY, "field_definition_tab_id": "183466",
        })
        self.organization.refresh_from_db()
        infos = dict(self.organization.infos)
        infos["data_admins"] = ["data_organizer"]
        self.organization.infos = infos
        self.organization.save()

        # Distinct emails: the User model has a unique constraint on it, and
        # two blanks collide.
        self.admin = User.objects.create_user(
            username="admin", email="admin@example.com", password="x",
            organization=self.organization)
        self.admin.groups.add(self.admin_group)
        self.viewer = User.objects.create_user(
            username="viewer", email="viewer@example.com", password="x",
            organization=self.organization)

    def attendee(self, first_name="Ann", last_name="Lee"):
        person = Attendee(first_name=first_name, last_name=last_name,
                          division=self.division,
                          gender=GenderEnum.UNSPECIFIED.value)
        person.save()
        return person

    def call(self, viewset, action_map, method, path, user, data=None,
             **kwargs):
        request = getattr(self.factory, method)(path, data, format="json")
        force_authenticate(request, user=user)
        view = viewset.as_view(action_map)
        return view(request, **kwargs)

    # -- starting a run --------------------------------------------------

    def test_a_non_admin_cannot_start_a_run(self):
        response = self.call(ApiPcoSyncRunsViewSet, {"post": "create"},
                             "post", "/pcosync/api/sync_runs/", self.viewer,
                             {"mode": "dry_run"})
        assert response.status_code == 403
        assert not PcoSyncRun.objects.exists()

    def test_a_second_run_is_refused_while_one_is_live(self):
        PcoSyncRun.objects.create(organization=self.organization,
                                  state=PcoSyncRun.RUNNING)
        response = self.call(ApiPcoSyncRunsViewSet, {"post": "create"},
                             "post", "/pcosync/api/sync_runs/", self.admin,
                             {"mode": "dry_run"})
        assert response.status_code == 409

    def test_an_unconfigured_organization_is_refused_with_a_reason(self):
        write_config(self.organization, {"base_url": "", "api_key": ""})
        response = self.call(ApiPcoSyncRunsViewSet, {"post": "create"},
                             "post", "/pcosync/api/sync_runs/", self.admin,
                             {"mode": "dry_run"})
        assert response.status_code == 400
        assert "base_url" in response.data["detail"]

    def test_runs_from_another_organization_are_invisible(self):
        other = Organization.objects.create(display_name="Elsewhere",
                                            slug="elsewhere")
        PcoSyncRun.objects.create(organization=other)
        mine = PcoSyncRun.objects.create(organization=self.organization)

        response = self.call(ApiPcoSyncRunsViewSet, {"get": "list"},
                             "get", "/pcosync/api/sync_runs/", self.admin)
        ids = {row["id"] for row in response.data}
        assert ids == {str(mine.id)}

    def test_cancel_is_a_request_not_a_kill(self):
        run = PcoSyncRun.objects.create(organization=self.organization,
                                        state=PcoSyncRun.RUNNING)
        response = self.call(ApiPcoSyncRunsViewSet, {"post": "cancel"},
                             "post", f"/pcosync/api/sync_runs/{run.id}/cancel/",
                             self.admin, pk=str(run.id))
        run.refresh_from_db()
        assert response.status_code == 200
        assert run.cancel_requested is True
        # Still running: it stops at the next person, so a half-written
        # attendee cannot be left with an unstamped baseline.
        assert run.state == PcoSyncRun.RUNNING

    def test_the_summary_never_carries_the_api_key(self):
        response = self.call(ApiPcoSyncRunsViewSet, {"get": "summary"},
                             "get", "/pcosync/api/sync_runs/summary/",
                             self.admin)
        assert KEY not in str(response.data)
        assert response.data["config"]["api_key_set"] is True

    # -- resolving -------------------------------------------------------

    def conflict(self, attendee, field="last_name", local="Li", pco="Leigh"):
        link = PcoPersonLink.objects.create(
            organization=self.organization, pco_person_id="900",
            attendee=attendee, baseline={field: "Lee"})
        return PcoDivergence.objects.create(
            organization=self.organization, link=link, attendee=attendee,
            pco_person_id="900", kind=PcoDivergence.FIELD_CONFLICT,
            pointer=f"$.person.{field}",
            dedupe_key=PcoDivergence.build_dedupe_key(
                f"$.person.{field}", "900", attendee.id),
            local_value=local, pco_value=pco,
        ), link

    def test_a_non_admin_cannot_resolve(self):
        divergence, _ = self.conflict(self.attendee())
        response = self.call(
            ApiPcoDivergencesViewSet, {"patch": "resolve"}, "patch",
            f"/pcosync/api/divergences/{divergence.id}/resolve/", self.viewer,
            {"resolution": "keep_pco"}, pk=str(divergence.id))
        assert response.status_code == 403

    def test_keep_local_records_the_planning_center_value_as_agreed(self):
        """So the next ordinary run sees only attendees32 as having moved."""
        divergence, link = self.conflict(self.attendee())
        self.call(ApiPcoDivergencesViewSet, {"patch": "resolve"}, "patch",
                  f"/pcosync/api/divergences/{divergence.id}/resolve/",
                  self.admin, {"resolution": "keep_local"},
                  pk=str(divergence.id))

        link.refresh_from_db()
        divergence.refresh_from_db()
        assert link.baseline["last_name"] == "Leigh"
        assert divergence.resolution == PcoDivergence.KEEP_LOCAL
        assert divergence.resolved_by_id == self.admin.id

    def test_keep_pco_records_the_local_value_as_agreed(self):
        divergence, link = self.conflict(self.attendee())
        self.call(ApiPcoDivergencesViewSet, {"patch": "resolve"}, "patch",
                  f"/pcosync/api/divergences/{divergence.id}/resolve/",
                  self.admin, {"resolution": "keep_pco"},
                  pk=str(divergence.id))

        link.refresh_from_db()
        assert link.baseline["last_name"] == "Li"

    def test_ignoring_a_field_records_it_on_the_link(self):
        divergence, link = self.conflict(self.attendee())
        self.call(ApiPcoDivergencesViewSet, {"patch": "resolve"}, "patch",
                  f"/pcosync/api/divergences/{divergence.id}/resolve/",
                  self.admin, {"resolution": "ignored"},
                  pk=str(divergence.id))

        link.refresh_from_db()
        assert link.infos["ignored_fields"] == ["last_name"]
        assert link.baseline["last_name"] == "Lee", "the baseline is untouched"

    def test_resolving_writes_nothing_to_the_attendee(self):
        """Resolution moves a baseline; the next run does the writing."""
        attendee = self.attendee(last_name="Li")
        divergence, _ = self.conflict(attendee)
        self.call(ApiPcoDivergencesViewSet, {"patch": "resolve"}, "patch",
                  f"/pcosync/api/divergences/{divergence.id}/resolve/",
                  self.admin, {"resolution": "keep_pco"},
                  pk=str(divergence.id))

        attendee.refresh_from_db()
        assert attendee.last_name == "Li"

    def test_an_unknown_resolution_is_rejected(self):
        divergence, _ = self.conflict(self.attendee())
        response = self.call(
            ApiPcoDivergencesViewSet, {"patch": "resolve"}, "patch",
            f"/pcosync/api/divergences/{divergence.id}/resolve/", self.admin,
            {"resolution": "just_do_what_i_mean"}, pk=str(divergence.id))
        assert response.status_code == 400

    # -- manual matching -------------------------------------------------

    def unlinked(self):
        link = PcoPersonLink.objects.create(
            organization=self.organization, pco_person_id="901",
            attendee=None, state=PcoPersonLink.UNCONFIRMED)
        return PcoDivergence.objects.create(
            organization=self.organization, link=link, pco_person_id="901",
            kind=PcoDivergence.UNLINKED_PERSON, pointer="$.person[901]",
            dedupe_key=PcoDivergence.build_dedupe_key("$.person[901]", "901"),
            suggestion={"candidates": []},
        ), link

    def test_a_person_can_be_matched_by_hand(self):
        attendee = self.attendee("Ben", "Tsai")
        divergence, link = self.unlinked()
        response = self.call(
            ApiPcoDivergencesViewSet, {"patch": "link"}, "patch",
            f"/pcosync/api/divergences/{divergence.id}/link/", self.admin,
            {"attendee_id": str(attendee.id)}, pk=str(divergence.id))

        assert response.status_code == 200
        link.refresh_from_db()
        assert link.attendee_id == attendee.id
        assert link.state == PcoPersonLink.LIVE
        assert link.link_source == PcoPersonLink.BY_MATCH
        assert link.baseline == {}, \
            "a fresh match has no history, so nothing is assumed agreed"

    def test_matching_an_already_linked_attendee_is_refused(self):
        attendee = self.attendee("Ben", "Tsai")
        PcoPersonLink.objects.create(
            organization=self.organization, pco_person_id="900",
            attendee=attendee, state=PcoPersonLink.LIVE)
        divergence, _ = self.unlinked()

        response = self.call(
            ApiPcoDivergencesViewSet, {"patch": "link"}, "patch",
            f"/pcosync/api/divergences/{divergence.id}/link/", self.admin,
            {"attendee_id": str(attendee.id)}, pk=str(divergence.id))
        assert response.status_code == 409

    def test_matching_an_attendee_from_another_organization_is_refused(self):
        other = Organization.objects.create(display_name="Elsewhere",
                                            slug="elsewhere")
        other_division = Division.objects.create(
            organization=other, display_name="Theirs", slug="theirs",
            audience_auth_group=self.admin_group)
        stranger = Attendee(first_name="Not", last_name="Ours",
                            division=other_division,
                            gender=GenderEnum.UNSPECIFIED.value)
        stranger.save()
        divergence, _ = self.unlinked()

        response = self.call(
            ApiPcoDivergencesViewSet, {"patch": "link"}, "patch",
            f"/pcosync/api/divergences/{divergence.id}/link/", self.admin,
            {"attendee_id": str(stranger.id)}, pk=str(divergence.id))
        assert response.status_code == 404

    def test_only_an_unmatched_row_can_be_linked(self):
        divergence, _ = self.conflict(self.attendee())
        response = self.call(
            ApiPcoDivergencesViewSet, {"patch": "link"}, "patch",
            f"/pcosync/api/divergences/{divergence.id}/link/", self.admin,
            {"attendee_id": str(self.attendee().id)}, pk=str(divergence.id))
        assert response.status_code == 400

    # -- the picker ------------------------------------------------------

    def test_attendee_search_finds_the_romanized_form(self):
        """Attendee.save() keeps it, which is how "Tsai" finds a CJK name."""
        self.attendee("Ben", "Tsai")
        response = self.call(
            ApiPcoDivergencesViewSet, {"get": "attendee_search"}, "get",
            "/pcosync/api/divergences/attendee_search/?q=Tsai", self.admin)
        assert any("Tsai" in row["display_label"] for row in response.data)

    def test_attendee_search_ignores_a_one_character_query(self):
        self.attendee("Ben", "Tsai")
        response = self.call(
            ApiPcoDivergencesViewSet, {"get": "attendee_search"}, "get",
            "/pcosync/api/divergences/attendee_search/?q=T", self.admin)
        assert response.data == []

    def test_divergences_from_another_organization_are_invisible(self):
        other = Organization.objects.create(display_name="Elsewhere",
                                            slug="elsewhere")
        PcoDivergence.objects.create(
            organization=other, kind=PcoDivergence.FIELD_CONFLICT,
            pointer="$.person.first_name", dedupe_key="x")
        divergence, _ = self.conflict(self.attendee())

        response = self.call(ApiPcoDivergencesViewSet, {"get": "list"}, "get",
                             "/pcosync/api/divergences/", self.admin)
        ids = {row["id"] for row in response.data}
        assert ids == {str(divergence.id)}
