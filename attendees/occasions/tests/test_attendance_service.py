import pytest
from datetime import datetime, timedelta, timezone
from django.contrib.contenttypes.models import ContentType
from django.contrib.auth.models import Group
from attendees.occasions.models import Meet, Assembly, Character, Gathering, Attendance
from attendees.persons.models import Category, Attendee, Attending, AttendingMeet
from attendees.whereabouts.models import Division, Organization
from attendees.occasions.services import AttendanceService
from django.utils import timezone as django_timezone

@pytest.mark.django_db
class TestAttendanceService:
    def setup_method(self):
        self.group = Group.objects.create(name="Test Group")
        self.organization = Organization.objects.create(display_name="Test Organization", slug="test-org")
        self.division = Division.objects.create(display_name="Test Division", slug="test-division", organization=self.organization, audience_auth_group=self.group)
        self.category = Category.objects.create(display_name="Test Category", type="test", display_order=1)
        self.assembly = Assembly.objects.create(
            display_name="Test Assembly",
            slug="test-assembly",
            division=self.division,
            category=self.category,
        )
        self.character = Character.objects.create(
            assembly=self.assembly,
            display_name="Test Character",
            display_order=1,
            slug="test-character",
            type="normal",
        )
        self.site_type = ContentType.objects.get_for_model(Assembly)
        self.site_id = str(self.assembly.id)
        self.start = django_timezone.now()
        self.finish = self.start + timedelta(hours=2)

        self.meet = Meet.objects.create(
            assembly=self.assembly,
            major_character=self.character,
            shown_audience=True,
            audience_editable=True,
            start=self.start,
            finish=self.finish,
            display_name="Test Meet",
            slug="test-meet",
            infos={"info": "Test info", "url": "https://example.com", "attendance": {"key": "value"}},
            site_type=self.site_type,
            site_id=self.site_id,
        )

        self.gathering = Gathering.objects.create(
            meet=self.meet,
            start=self.start,
            finish=self.finish,
            display_name="Test Gathering",
            slug="test-gathering",
            site_type=self.site_type,
            site_id=self.site_id,
            infos={"generate_attendance": True},
        )

        self.attendee = Attendee.objects.create(
            first_name="Test",
            last_name="Attendee",
            display_label="Test Attendee",
        )

        self.attending = Attending.objects.create(
            attendee=self.attendee,
            category="normal",
        )

        self.attending_meet = AttendingMeet.objects.create(
            attending=self.attending,
            meet=self.meet,
            character=self.character,
            category=self.category,
        )

    def test_by_assembly_meets_characters_gathering_intervals(self):
        Attendance.objects.create(
            gathering=self.gathering,
            attending=self.attending,
            character=self.character,
            category=self.category,
            start=self.start,
            finish=self.finish,
        )

        results = AttendanceService.by_assembly_meets_characters_gathering_intervals(
            assembly_slug="test-assembly",
            meet_slugs=["test-meet"],
            gathering_start=self.start,
            gathering_finish=self.finish,
            character_slugs=["test-character"],
        )

        assert results.count() == 1
        assert results.first().gathering == self.gathering
        assert results.first().character == self.character

    def test_batch_create(self):
        # Ensure no attendance initially
        assert Attendance.objects.count() == 0

        # Call batch_create
        # Dates should cover the gathering time
        begin_str = (self.start - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%S.%f%z")
        end_str = (self.finish + timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%S.%f%z")

        results = AttendanceService.batch_create(
            begin=begin_str,
            end=end_str,
            meet_slug="test-meet",
            meet=self.meet,
            user_time_zone=timezone.utc,
        )

        assert results["success"] is True
        assert results["attendance_created"] == 1
        assert Attendance.objects.count() == 1
        attendance = Attendance.objects.first()
        assert attendance.gathering == self.gathering
        assert attendance.attending == self.attending
        assert attendance.character == self.character
        assert attendance.infos == {"key": "value"}

    def test_batch_create_no_overlap(self):
        # Call batch_create with non-overlapping time
        begin_str = (self.finish + timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%S.%f%z")
        end_str = (self.finish + timedelta(minutes=60)).strftime("%Y-%m-%dT%H:%M:%S.%f%z")

        results = AttendanceService.batch_create(
            begin=begin_str,
            end=end_str,
            meet_slug="test-meet",
            meet=self.meet,
            user_time_zone=timezone.utc,
        )

        assert results["success"] is True
        assert results["attendance_created"] == 0
        assert Attendance.objects.count() == 0

    def test_batch_create_existing_attendance(self):
        Attendance.objects.create(
            gathering=self.gathering,
            attending=self.attending,
            character=self.character,
            category=self.category,
            start=self.start,
            finish=self.finish,
        )
        assert Attendance.objects.count() == 1

        begin_str = (self.start - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%S.%f%z")
        end_str = (self.finish + timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%S.%f%z")

        results = AttendanceService.batch_create(
            begin=begin_str,
            end=end_str,
            meet_slug="test-meet",
            meet=self.meet,
            user_time_zone=timezone.utc,
        )

        assert results["success"] is True
        assert results["attendance_created"] == 0
        assert Attendance.objects.count() == 1
