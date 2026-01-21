from django.test import TestCase
from django.contrib.auth.models import Group
from unittest.mock import patch, MagicMock
from attendees.persons.services.pco_service import PCOService
from attendees.persons.models import Attendee
from attendees.whereabouts.models import Division, Organization

class PCOServiceTest(TestCase):
    def setUp(self):
        self.group = Group.objects.create(name="Test Group")
        self.organization = Organization.objects.create(display_name="Test Org", slug="test-org")
        self.division = Division.objects.create(
            organization=self.organization,
            display_name="English Service",
            slug="eng",
            audience_auth_group=self.group
        )
        self.attendee = Attendee.objects.create(
            first_name="John",
            last_name="Doe",
            first_name2="Chun",
            last_name2="Chan",
            division=self.division,
            gender="MALE",
            infos={
                "names": {"romanization": "Chan Chun"},
                "contacts": {"email1": "john@example.com"},
                "fixed": {"nick_name": "Johnny"}
            }
        )
        self.service = PCOService(app_id="test", secret="test")

    @patch('attendees.persons.services.pco_service.requests.request')
    def test_ensure_custom_fields_creates_if_missing(self, mock_request):
        def side_effect(method, url, **kwargs):
            mock_resp = MagicMock()
            mock_resp.status_code = 200

            if "tabs" in url:
                if method == "GET":
                    mock_resp.json.return_value = {'data': []}
                elif method == "POST":
                    mock_resp.json.return_value = {'data': {'id': 'tab_1'}}
            elif "field_definitions" in url:
                if method == "GET":
                    mock_resp.json.return_value = {'data': []}
                elif method == "POST":
                    name = kwargs.get('json', {}).get('data', {}).get('attributes', {}).get('name')
                    mock_resp.json.return_value = {'data': {'id': f'field_{name}'}}
            return mock_resp

        mock_request.side_effect = side_effect

        self.service.ensure_custom_fields()

        self.assertEqual(self.service.field_definitions['Chinese Name'], 'field_Chinese Name')

    @patch('attendees.persons.services.pco_service.requests.request')
    def test_sync_attendee_creates_person_and_emails(self, mock_request):
        self.service.field_definitions = {'Chinese Name': '1', 'Romanized Name': '2'}

        def side_effect(method, url, **kwargs):
            mock_resp = MagicMock()
            mock_resp.status_code = 200

            params = kwargs.get('params') or {}

            # List campuses
            if "campuses" in url and method == "GET":
                mock_resp.json.return_value = {'data': [{'id': 'campus_1', 'attributes': {'name': 'English Service'}}]}
                return mock_resp

            # Search person
            if "people" in url and method == "GET" and "search_name_or_email" in params:
                mock_resp.json.return_value = {'data': []} # Not found
                return mock_resp

            # Create person
            if "people" in url and method == "POST" and "field_data" not in url and "emails" not in url:
                mock_resp.status_code = 201
                mock_resp.json.return_value = {'data': {'id': 'person_1'}}
                return mock_resp

            # Sync Emails
            if "emails" in url:
                if method == "GET":
                    mock_resp.json.return_value = {'data': []} # No existing emails
                if method == "POST":
                    # verify email payload
                    return mock_resp

            # Field Data
            if "field_data" in url:
                if method == "GET":
                    mock_resp.json.return_value = {'data': []} # No existing data
                return mock_resp

            mock_resp.json.return_value = {'data': []}
            return mock_resp

        mock_request.side_effect = side_effect

        self.service.sync_attendee(self.attendee)

        # Verify calls
        # Check email POST
        email_posts = [c for c in mock_request.call_args_list if c[0][0] == 'POST' and 'emails' in c[0][1]]
        self.assertTrue(email_posts)
        self.assertEqual(email_posts[0][1]['json']['data']['attributes']['address'], 'john@example.com')

        # Check campus caching
        # Should be called once for list campuses
        campus_gets = [c for c in mock_request.call_args_list if c[0][0] == 'GET' and 'campuses' in c[0][1]]
        self.assertEqual(len(campus_gets), 1)
