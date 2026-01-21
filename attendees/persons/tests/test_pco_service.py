import sys
import importlib.util
from unittest import TestCase
from unittest.mock import MagicMock, patch

# 1. Mock Django & Project Modules
mock_django = MagicMock()
mock_django.conf.settings.configured = True
mock_django.conf.settings.PCO_APP_ID = 'test'
mock_django.conf.settings.PCO_SECRET = 'test'
mock_django.conf.settings.PCO_INFOS = {}

mock_conf = MagicMock()
mock_conf.settings = mock_django.conf.settings
sys.modules['django.conf'] = mock_conf

sys.modules['django'] = mock_django
mock_django.conf = mock_conf

mock_module = MagicMock(spec=[])
sys.modules['django.db'] = mock_module
sys.modules['django.db.models'] = mock_module
sys.modules['attendees'] = mock_module
sys.modules['attendees.persons'] = mock_module

# FIX: Ensure models module has Attendee attribute
mock_persons_models = MagicMock()
mock_persons_models.Attendee = MagicMock() # Needs to exist
sys.modules['attendees.persons.models'] = mock_persons_models

sys.modules['attendees.whereabouts'] = mock_module
mock_whereabouts_models = MagicMock()
mock_whereabouts_models.Division = MagicMock() # Needs to exist
sys.modules['attendees.whereabouts.models'] = mock_whereabouts_models

# 2. Load the Service Module manually
spec = importlib.util.spec_from_file_location("pco_service_module", "attendees/persons/services/pco_service.py")
pco_module = importlib.util.module_from_spec(spec)
sys.modules["pco_service_module"] = pco_module
spec.loader.exec_module(pco_module)

PCOService = pco_module.PCOService

class PCOServiceTest(TestCase):
    def setUp(self):
        self.service = PCOService(app_id="test", secret="test")

        self.attendee = MagicMock()
        self.attendee.first_name = "John"
        self.attendee.last_name = "Doe"
        self.attendee.first_name2 = "Chun"
        self.attendee.last_name2 = "Chan"
        self.attendee.division.display_name = "English Service"
        self.attendee.division.infos = {}
        self.attendee.gender = "MALE"
        self.attendee.actual_birthday = None
        self.attendee.infos = {
            "names": {"romanization": "Chan Chun"},
            "contacts": {"email1": "john@example.com"},
            "fixed": {"nick_name": "Johnny"}
        }

    @patch('pco_service_module.requests.request')
    def test_ensure_custom_fields_creates_if_missing(self, mock_request):
        def side_effect(method, url, **kwargs):
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            if "tabs" in url:
                if method == "GET": mock_resp.json.return_value = {'data': []}
                elif method == "POST": mock_resp.json.return_value = {'data': {'id': 'tab_1'}}
            elif "field_definitions" in url:
                if method == "GET": mock_resp.json.return_value = {'data': []}
                elif method == "POST":
                    name = kwargs.get('json', {}).get('data', {}).get('attributes', {}).get('name')
                    mock_resp.json.return_value = {'data': {'id': f'field_{name}'}}
            return mock_resp
        mock_request.side_effect = side_effect

        self.service.ensure_custom_fields()
        self.assertEqual(self.service.field_definitions['Chinese Name'], 'field_Chinese Name')

    @patch('pco_service_module.requests.request')
    def test_sync_attendee_creates_person_and_emails(self, mock_request):
        self.service.field_definitions = {'Chinese Name': '1', 'Romanized Name': '2'}

        def side_effect(method, url, **kwargs):
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            params = kwargs.get('params') or {}

            if "campuses" in url and method == "GET":
                mock_resp.json.return_value = {'data': [{'id': 'campus_1', 'attributes': {'name': 'English Service'}}]}
            elif "people" in url and method == "GET" and "search_name_or_email" in params:
                mock_resp.json.return_value = {'data': []}
            elif "people" in url and method == "POST" and "field_data" not in url and "emails" not in url:
                mock_resp.status_code = 201
                mock_resp.json.return_value = {'data': {'id': 'person_1'}}
            elif "emails" in url:
                mock_resp.json.return_value = {'data': []}
            else:
                mock_resp.json.return_value = {'data': []}
            return mock_resp

        mock_request.side_effect = side_effect
        self.service.sync_attendee(self.attendee)

        email_posts = [c for c in mock_request.call_args_list if c[0][0] == 'POST' and 'emails' in c[0][1]]
        self.assertTrue(email_posts)
        self.assertEqual(email_posts[0][1]['json']['data']['attributes']['address'], 'john@example.com')
