import requests
import logging
from django.conf import settings
from attendees.persons.models import Attendee

logger = logging.getLogger(__name__)


class PCOService:
    BASE_URL = "https://api.planningcenteronline.com/people/v2"

    def __init__(self, app_id=None, secret=None):
        self.app_id = app_id or getattr(settings, 'PCO_APP_ID', None)
        self.secret = secret or getattr(settings, 'PCO_SECRET', None)

        if not self.app_id or not self.secret:
            logger.warning("PCO credentials not found in settings (PCO_APP_ID, PCO_SECRET).")

        self.auth = (self.app_id, self.secret)
        self.field_definitions = {}  # Cache for field definitions: {'Name': id}
        self.campuses = {}  # Cache for campuses: {'Name': id}

    def _request(self, method, endpoint, params=None, json=None):
        url = f"{self.BASE_URL}/{endpoint.lstrip('/')}"
        response = requests.request(
            method,
            url,
            auth=self.auth,
            params=params,
            json=json,
            headers={"Content-Type": "application/json"}
        )
        try:
            response.raise_for_status()
            if response.status_code == 204:
                return None
            return response.json()
        except requests.exceptions.HTTPError as e:
            logger.error(f"PCO API Error: {e.response.text}")
            raise

    def ensure_custom_fields(self):
        """
        Ensures that 'Bilingual Info' tab and 'Chinese Name', 'Romanized Name' fields exist.
        Populates self.field_definitions.
        """
        tab_id = self._ensure_tab("Bilingual Info")
        self.field_definitions['Chinese Name'] = self._ensure_field(tab_id, "Chinese Name", "string")
        self.field_definitions['Romanized Name'] = self._ensure_field(tab_id, "Romanized Name", "string")

    def _ensure_tab(self, tab_name):
        response = self._request("GET", "tabs")
        for datum in response.get('data', []):
            if datum['attributes']['name'] == tab_name:
                return datum['id']

        payload = {
            "data": {
                "type": "Tab",
                "attributes": {"name": tab_name, "sequence": 1}
            }
        }
        response = self._request("POST", "tabs", json=payload)
        return response['data']['id']

    def _ensure_field(self, tab_id, field_name, field_type):
        response = self._request("GET", "field_definitions", params={"where[tab_id]": tab_id})
        for datum in response.get('data', []):
            if datum['attributes']['name'] == field_name:
                return datum['id']

        payload = {
            "data": {
                "type": "FieldDefinition",
                "attributes": {
                    "name": field_name,
                    "data_type": field_type,
                    "sequence": 1
                },
                "relationships": {
                    "tab": {"data": {"type": "Tab", "id": tab_id}}
                }
            }
        }
        response = self._request("POST", "field_definitions", json=payload)
        return response['data']['id']

    def sync_attendee(self, attendee: Attendee):
        if not self.field_definitions:
            self.ensure_custom_fields()

        # 1. Find or Create Person
        pco_id = self._find_person_id(attendee)
        if pco_id:
            self._update_person(pco_id, attendee)
        else:
            pco_id = self._create_person(attendee)

        # 2. Sync Emails (Critical for future matching)
        self._sync_emails(pco_id, attendee)

        # 3. Update Custom Fields
        chinese_name = f"{attendee.last_name2 or ''}{attendee.first_name2 or ''}".strip()
        if chinese_name:
            self._update_field_data(pco_id, self.field_definitions['Chinese Name'], chinese_name)

        romanized = attendee.infos.get('names', {}).get('romanization')
        if romanized:
            self._update_field_data(pco_id, self.field_definitions['Romanized Name'], romanized)

    def _find_person_id(self, attendee):
        email = attendee.infos.get('contacts', {}).get('email1')
        if not email:
            return None

        response = self._request("GET", "people", params={"where[search_name_or_email]": email})
        for person in response.get('data', []):
            # Verify name match to avoid cross-family mixup
            pco_first = person['attributes']['given_name']
            pco_last = person['attributes']['last_name']

            if (pco_first or "").lower() == (attendee.first_name or "").lower() and \
               (pco_last or "").lower() == (attendee.last_name or "").lower():
                return person['id']
        return None

    def _create_person(self, attendee):
        attributes = {
            "given_name": attendee.first_name,
            "last_name": attendee.last_name,
        }
        if attendee.infos.get('fixed', {}).get('nick_name'):
            attributes['nickname'] = attendee.infos['fixed']['nick_name']

        if attendee.actual_birthday:
            attributes['birthdate'] = attendee.actual_birthday.isoformat()

        if attendee.gender:
            if attendee.gender == 'MALE':
                attributes['gender'] = 'M'
            elif attendee.gender == 'FEMALE':
                attributes['gender'] = 'F'

        payload = {
            "data": {
                "type": "Person",
                "attributes": attributes
            }
        }

        campus_id = self._get_campus_id(attendee.division)
        if campus_id:
            payload['data']['relationships'] = {
                "primary_campus": {
                    "data": {"type": "Campus", "id": campus_id}
                }
            }

        response = self._request("POST", "people", json=payload)
        return response['data']['id']

    def _update_person(self, pco_id, attendee):
        attributes = {
            "given_name": attendee.first_name,
            "last_name": attendee.last_name,
        }
        if attendee.infos.get('fixed', {}).get('nick_name'):
            attributes['nickname'] = attendee.infos['fixed']['nick_name']

        if attendee.actual_birthday:
            attributes['birthdate'] = attendee.actual_birthday.isoformat()

        if attendee.gender:
            if attendee.gender == 'MALE':
                attributes['gender'] = 'M'
            elif attendee.gender == 'FEMALE':
                attributes['gender'] = 'F'

        payload = {
            "data": {
                "type": "Person",
                "id": pco_id,
                "attributes": attributes
            }
        }

        campus_id = self._get_campus_id(attendee.division)
        if campus_id:
            payload['data']['relationships'] = {
                "primary_campus": {
                    "data": {"type": "Campus", "id": campus_id}
                }
            }

        self._request("PATCH", f"people/{pco_id}", json=payload)

    def _sync_emails(self, pco_id, attendee):
        email = attendee.infos.get('contacts', {}).get('email1')
        if not email:
            return

        # List existing emails
        response = self._request("GET", f"people/{pco_id}/emails")
        existing_emails = response.get('data', [])

        for mail in existing_emails:
            if mail['attributes']['address'].lower() == email.lower():
                return

        # Create email
        payload = {
            "data": {
                "type": "Email",
                "attributes": {
                    "address": email,
                    "location": "Home",
                    "primary": True
                }
            }
        }
        self._request("POST", f"people/{pco_id}/emails", json=payload)

    def _load_campuses(self):
        response = self._request("GET", "campuses")
        for datum in response.get('data', []):
            name = datum['attributes']['name']
            self.campuses[name] = datum['id']

    def _get_campus_id(self, division):
        if not self.campuses:
            self._load_campuses()

        if division.infos and 'pco_campus_id' in division.infos:
            return str(division.infos['pco_campus_id'])

        return self.campuses.get(division.display_name)

    def _update_field_data(self, person_id, field_def_id, value):
        response = self._request(
            "GET",
            f"people/{person_id}/field_data",
            params={"where[field_definition_id]": field_def_id}
        )

        if response['data']:
            datum_id = response['data'][0]['id']
            payload = {
                "data": {
                    "type": "FieldDatum",
                    "id": datum_id,
                    "attributes": {"value": value}
                }
            }
            self._request("PATCH", f"field_data/{datum_id}", json=payload)
        else:
            payload = {
                "data": {
                    "type": "FieldDatum",
                    "attributes": {"value": value},
                    "relationships": {
                        "field_definition": {"data": {"type": "FieldDefinition", "id": field_def_id}},
                        "person": {"data": {"type": "Person", "id": person_id}}
                    }
                }
            }
            self._request("POST", f"people/{person_id}/field_data", json=payload)
