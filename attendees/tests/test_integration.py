import pytest
from datetime import timedelta
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.contrib.auth.models import Group
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework import status

from attendees.occasions.models import Meet, Assembly, Character, Gathering, Attendance
from attendees.persons.models import Category, Attendee, Attending, AttendingMeet
from attendees.whereabouts.models import Division, Organization


@pytest.mark.django_db
class TestIntegration:
    def setup_method(self):
        self.client = APIClient()
        self.user_model = get_user_model()

        # Setup Organization and Hierarchy
        self.organization = Organization.objects.create(
            display_name="Test Org", slug="test-org"
        )
        self.group = Group.objects.create(name="Test Group")
        self.organization.infos = {"groups_see_all_meets_attendees": ["Test Group"]}
        self.organization.save()

        self.division = Division.objects.create(
            display_name="Test Division",
            slug="test-division",
            organization=self.organization,
        )
        self.assembly = Assembly.objects.create(
            display_name="Test Assembly",
            slug="test-assembly",
            division=self.division,
        )

        # Setup User
        self.user = self.user_model.objects.create_user(
            username="testadmin", email="testadmin@example.com", password="password123"
        )
        self.user.organization = self.organization
        self.user.groups.add(self.group)
        self.user.save()

        # Setup Attendee for the User
        self.user_attendee = Attendee.objects.create(
            first_name="Admin", last_name="User", user=self.user
        )

        # Setup Meet
        self.character = Character.objects.create(
            assembly=self.assembly,
            display_name="Test Character",
            slug="test-character",
            type="normal",
        )
        self.meet = Meet.objects.create(
            assembly=self.assembly,
            display_name="Test Meet",
            slug="test-meet",
            start=timezone.now(),
            finish=timezone.now() + timedelta(days=365),
            site_type=ContentType.objects.get_for_model(Assembly),
            site_id=self.assembly.id,
            infos={"allowed_models": ["Attendance"]},
        )

        self.gathering = Gathering.objects.create(
            meet=self.meet,
            start=timezone.now(),
            finish=timezone.now() + timedelta(hours=1),
            display_name="Test Gathering",
            site_type=ContentType.objects.get_for_model(Assembly),
            site_id=self.assembly.id,
        )

    def test_full_attendance_flow(self):
        # 1. Login
        login_success = self.client.login(username="testadmin", password="password123")
        assert login_success is True

        # 2. Check if we can see the meet
        # URL pattern: api/user_assembly_meets
        # Note: We use hardcoded path because basenames in router are duplicated (e.g. 'meet'), making reverse() ambiguous.
        response = self.client.get("/occasions/api/user_assembly_meets/")
        assert (
            response.status_code == status.HTTP_200_OK
        ), f"Response: {response.content}"

        # 3. Create an Attendance (Simulate joining)
        # We need an Attending record first
        attending = Attending.objects.create(
            attendee=self.user_attendee, category="normal"
        )
        AttendingMeet.objects.create(
            attending=attending,
            meet=self.meet,
            character=self.character,
        )

        attendance = Attendance.objects.create(
            gathering=self.gathering,
            attending=attending,
            character=self.character,
            category=Category.objects.get_or_create(display_name="scheduled")[0],
            start=self.gathering.start,
            finish=self.gathering.finish,
        )

        # 4. Verify Attendance is listed
        # URL pattern: api/coworker_organization_attendances

        params = {
            "meet_slugs": ["test-meet"],
            "start": (timezone.now() - timedelta(hours=1)).isoformat(),
            "finish": (timezone.now() + timedelta(hours=2)).isoformat(),
        }

        response = self.client.get(
            "/occasions/api/coworker_organization_attendances/", params
        )

        assert response.status_code == status.HTTP_200_OK, (
            f"Coworker API failed with {response.status_code}: {response.content}"
        )
        assert len(response.data) > 0, "No attendance found"
        assert response.data[0]["id"] == attendance.id
