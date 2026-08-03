"""The client against real recorded responses.

``test_client.py`` proves the client behaves correctly against shapes we
constructed. This file proves it understands shapes Planning Center actually
sent. The two fail differently: a hand-built fixture encodes what we believe the
API returns, and that belief is exactly what tends to be slightly wrong.
"""

import pytest

from attendees.pcosync.client import PcoApiError, PcoMirrorClient
from attendees.pcosync.tests.fake_mirror import FakeMirror

BASE = "https://mirror.test/people/v2"
KEY = "pcm_abcd1234_secret"

#: The tab this sync depends on, as recorded. Ids are sanitized but the slugs,
#: data types and the gap at sequence 4 are real.
EXPECTED_TAB = {
    "chinese_last_name": ("100001", "string", 1),
    "chinese_first_name": ("100002", "string", 2),
    "baptized": ("100003", "boolean", 3),
    "believer": ("100004", "boolean", 5),
    "congregation": ("100005", "select", 6),
    "attendees_uuid": ("100006", "string", 7),
}


def client_for(mirror):
    return PcoMirrorClient(BASE, KEY, session=mirror, sleep=lambda s: None)


def test_the_recorded_tab_is_the_one_this_sync_maps():
    mirror = FakeMirror().load_golden("field_definitions_collection")
    payload = client_for(mirror).get("/field_definitions", {"per_page": 25})
    by_slug = {
        r["attributes"]["slug"]: (r["id"], r["attributes"]["data_type"],
                                  r["attributes"]["sequence"])
        for r in payload["data"]
    }
    assert by_slug == EXPECTED_TAB


def test_sequence_numbers_are_not_contiguous():
    """Sequence 4 is missing upstream. Never index the tab by position."""
    sequences = sorted(seq for _, _, seq in EXPECTED_TAB.values())
    assert sequences == [1, 2, 3, 5, 6, 7]
    assert 4 not in sequences


def test_field_data_carries_its_owner_and_definition():
    """This is the shape identity resolution reads."""
    mirror = FakeMirror().load_golden("field_data_where_definition")
    payload = client_for(mirror).get(
        "/field_data", {"where": {"field_definition_id": "100001"}, "per_page": 25}
    )
    assert payload["data"], "the recording should not be empty"
    for datum in payload["data"]:
        rel = datum["relationships"]
        assert rel["customizable"]["data"]["type"] == "Person"
        assert rel["customizable"]["data"]["id"]
        assert rel["field_definition"]["data"]["id"] == "100001"
        assert "value" in datum["attributes"]


def test_a_single_field_datum_side_loads_its_definition():
    mirror = FakeMirror().load_golden("single_field_datum")
    payload = client_for(mirror).get("/field_data/100000001",
                                     {"include": ["field_definition"]})
    assert payload["data"]["type"] == "FieldDatum"
    included_types = {r["type"] for r in payload.get("included", [])}
    assert "FieldDefinition" in included_types


def test_a_person_page_side_loads_contacts_and_households():
    mirror = FakeMirror().load_golden("people_single_include_contacts")
    payload = client_for(mirror).get(
        "/people/100000001",
        {"include": ["emails", "phone_numbers", "households"]},
    )
    assert payload["data"]["type"] == "Person"
    assert "first_name" in payload["data"]["attributes"]
    # The included block is a flat list of mixed types; the mapping layer
    # indexes it by (type, id) rather than trusting order.
    for record in payload.get("included", []):
        assert record["type"] in {"Email", "PhoneNumber", "Household", "Address"}


def test_household_memberships_are_404_at_the_top_level():
    """They are reachable only under a household, which is why we walk per-household."""
    mirror = FakeMirror().load_golden("err_household_memberships_top_level")
    with pytest.raises(PcoApiError) as caught:
        client_for(mirror).get("/household_memberships", {"per_page": 5})
    assert caught.value.status == 404


def test_a_households_nested_walk_returns_people():
    mirror = FakeMirror().load_golden("households_nested_people")
    payload = client_for(mirror).get("/households/10000012/people",
                                     {"include": ["households"]})
    assert isinstance(payload["data"], list)
    for record in payload["data"]:
        assert record["type"] == "Person"


def test_a_recorded_error_envelope_parses_into_errors():
    mirror = FakeMirror().load_golden("err_unknown_collection")
    body = mirror.golden_body("err_unknown_collection")
    assert "errors" in body
    assert body["errors"][0]["detail"]


def test_a_recorded_multi_page_walk_is_followed_to_the_end():
    """Two real consecutive pages of a filtered collection."""
    mirror = FakeMirror()
    page_one = mirror.golden_body("people_child_filter_page1")
    page_two = mirror.golden_body("people_child_filter_page2")
    query = ("include=emails,phone_numbers,households&order=last_name"
             "&where[child]=true&per_page=25")
    from attendees.pcosync.tests.fake_mirror import FakeResponse

    mirror.add("GET", "/people", FakeResponse(200, page_one),
               query=f"{query}&offset=0")
    mirror.add("GET", "/people", FakeResponse(200, page_two),
               query=f"{query}&offset=25")
    mirror.add("GET", "/people",
               FakeResponse(200, {"data": [], "links": {}, "meta": {}}),
               query=f"{query}&offset=50")

    walked = list(client_for(mirror).paginate_records(
        "/people",
        {"include": ["emails", "phone_numbers", "households"],
         "order": "last_name", "where": {"child": True}},
        per_page=25, max_pages=3,
    ))
    assert len(walked) == 50
    assert len({r["id"] for r in walked}) == 50, "pages must not overlap"


def test_the_recorded_next_link_is_absolute_and_still_resolves():
    """These were recorded against PCO, which sends an absolute links.next."""
    mirror = FakeMirror()
    body = mirror.golden_body("people_child_filter_page1")
    assert body["links"]["next"].startswith("https://api.planningcenteronline.com")
    # urljoin against the serving URL keeps an absolute link intact, so the
    # client handles the mirror's relative form and PCO's absolute one alike.
    from urllib.parse import urljoin

    resolved = urljoin(f"{BASE}/people?offset=0", body["links"]["next"])
    assert resolved == body["links"]["next"]
