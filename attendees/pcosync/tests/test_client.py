"""Client behaviours that were paid for in production.

Every test here corresponds to a comment in ``client.py`` explaining why the
behaviour exists. If one of these ever starts failing, read the comment before
changing the test -- the odds are the code regressed, not the expectation.

No sockets and no real sleeping: ``sleep`` and ``now`` are injected.
"""

import pytest
import requests

from attendees.pcosync.client import (
    MAX_MERGE_HOPS,
    PcoApiError,
    PcoGoneError,
    PcoMirrorClient,
    PcoNetworkError,
    PcoWriteIndeterminate,
    build_query_string,
    redact_headers,
)
from attendees.pcosync.tests.fake_mirror import (
    SHAPE_ABSOLUTE_LINKS,
    SHAPE_META_ONLY,
    SHAPE_NO_CURSOR,
    SHAPE_RELATIVE_LINKS,
    FakeMirror,
    FakeResponse,
    error_body,
)

BASE = "https://mirror.test/people/v2"
KEY = "pcm_abcd1234_secret"


class Clock:
    def __init__(self):
        self.slept = []

    def sleep(self, seconds):
        self.slept.append(seconds)


def make_client(mirror, **kwargs):
    clock = Clock()
    client = PcoMirrorClient(BASE, KEY, session=mirror, sleep=clock.sleep, **kwargs)
    client.clock = clock
    return client


def person(pid, **attrs):
    return {"type": "Person", "id": str(pid), "attributes": attrs or {}}


# --------------------------------------------------------------------------
# Query encoding
# --------------------------------------------------------------------------

def test_nested_filters_encode_with_literal_brackets():
    encoded = build_query_string(
        {"where": {"updated_at": {"gte": "2026-01-01"}}, "include": ["emails", "field_data"]}
    )
    assert "where[updated_at][gte]=2026-01-01" in encoded
    assert "include=emails%2Cfield_data" in encoded


def test_none_values_are_dropped_not_sent_as_the_string_none():
    assert build_query_string({"order": None, "per_page": 100}) == "per_page=100"


def test_booleans_encode_the_way_pco_expects():
    assert build_query_string({"where": {"child": True}}) == "where[child]=true"


def test_empty_query_is_empty():
    assert build_query_string(None) == ""
    assert build_query_string({}) == ""


# --------------------------------------------------------------------------
# Redaction: never let a credential into a trace
# --------------------------------------------------------------------------

def test_authorization_is_redacted():
    out = redact_headers({"Authorization": "Bearer pcm_secret", "Accept": "application/json"})
    assert out["Authorization"] == "[redacted]"
    assert out["Accept"] == "application/json"


def test_cookies_are_redacted_too():
    assert redact_headers({"Set-Cookie": "a=b"})["Set-Cookie"] == "[redacted]"


def test_the_key_never_appears_in_an_error_trace():
    mirror = FakeMirror().add("GET", "/people/1", FakeResponse(500, {"errors": []}))
    client = make_client(mirror, max_retries=0)
    with pytest.raises(PcoApiError) as caught:
        client.get("/people/1")
    assert KEY not in str(caught.value.request.headers)
    assert caught.value.request.headers["Authorization"] == "[redacted]"


def test_the_key_is_still_actually_sent():
    mirror = FakeMirror().add("GET", "/people/1", FakeResponse(200, {"data": person(1)}))
    make_client(mirror).get("/people/1")
    assert mirror.calls[0]["headers"]["Authorization"] == f"Bearer {KEY}"


# --------------------------------------------------------------------------
# Replay rules. The single most consequential part of this client.
# --------------------------------------------------------------------------

def test_post_is_never_retried_on_a_transport_error():
    """A create whose reply was lost must not be replayed: it may have landed."""
    mirror = FakeMirror()
    mirror.fail_once("POST", "/people",
                     exception=requests.ConnectionError("reset"), times=5)
    client = make_client(mirror)
    with pytest.raises(PcoNetworkError):
        client.post("/people", {"data": {}})
    assert mirror.count("POST", "/people") == 1


@pytest.mark.parametrize("status", [500, 502, 503, 504])
def test_post_is_never_retried_on_a_server_error(status):
    mirror = FakeMirror()
    mirror.fail_once("POST", "/people", status=status, body={"errors": []}, times=5)
    client = make_client(mirror)
    with pytest.raises(PcoApiError):
        client.post("/people", {"data": {}})
    assert mirror.count("POST", "/people") == 1


def test_patch_is_retried_because_it_carries_a_fixed_attribute_set():
    mirror = FakeMirror().add("PATCH", "/people/1",
                              FakeResponse(200, {"data": person(1)}))
    mirror.fail_once("PATCH", "/people/1", status=503, body={"errors": []}, times=2)
    client = make_client(mirror)
    assert client.patch("/people/1", {"data": {}})["data"]["id"] == "1"
    assert mirror.count("PATCH", "/people/1") == 3


def test_get_is_retried_on_a_transport_error():
    mirror = FakeMirror().add("GET", "/people/1", FakeResponse(200, {"data": person(1)}))
    mirror.fail_once("GET", "/people/1",
                     exception=requests.ConnectionError("reset"), times=2)
    client = make_client(mirror)
    assert client.get("/people/1")["data"]["id"] == "1"
    assert mirror.count("GET", "/people/1") == 3


def test_429_is_retried_even_for_post():
    """A rate-limit refusal happens before anything could have been written."""
    mirror = FakeMirror().add("POST", "/people", FakeResponse(201, {"data": person(9)}))
    mirror.fail_once("POST", "/people", status=429, body={"errors": []},
                     headers={"Retry-After": "1"}, times=2)
    client = make_client(mirror)
    assert client.post("/people", {"data": {}})["data"]["id"] == "9"
    assert mirror.count("POST", "/people") == 3


def test_a_4xx_is_never_retried():
    mirror = FakeMirror()
    mirror.fail_once("GET", "/people/1", status=422,
                     body=error_body(422, "unprocessable"), times=5)
    client = make_client(mirror)
    with pytest.raises(PcoApiError) as caught:
        client.get("/people/1")
    assert caught.value.status == 422
    assert mirror.count("GET", "/people/1") == 1


def test_retries_give_up_after_max_retries():
    mirror = FakeMirror()
    mirror.fail_once("GET", "/people/1", status=503, body={"errors": []}, times=10)
    client = make_client(mirror, max_retries=2)
    with pytest.raises(PcoApiError):
        client.get("/people/1")
    assert mirror.count("GET", "/people/1") == 3  # the first try plus two retries


# --------------------------------------------------------------------------
# Backoff
# --------------------------------------------------------------------------

def test_backoff_doubles_and_is_capped():
    mirror = FakeMirror()
    mirror.fail_once("GET", "/people/1", status=503, body={"errors": []}, times=10)
    client = make_client(mirror, max_retries=8)
    with pytest.raises(PcoApiError):
        client.get("/people/1")
    assert client.clock.slept[:4] == [0.5, 1.0, 2.0, 4.0]
    assert max(client.clock.slept) <= 20.0


def test_retry_after_in_seconds_overrides_the_curve():
    mirror = FakeMirror().add("GET", "/people/1", FakeResponse(200, {"data": person(1)}))
    mirror.fail_once("GET", "/people/1", status=429, body={"errors": []},
                     headers={"Retry-After": "7"})
    client = make_client(mirror)
    client.get("/people/1")
    assert client.clock.slept == [7.0]


def test_retry_after_as_an_http_date_is_honoured():
    from datetime import datetime, timedelta, timezone

    now = datetime(2026, 8, 3, 12, 0, 0, tzinfo=timezone.utc)
    when = (now + timedelta(seconds=30)).strftime("%a, %d %b %Y %H:%M:%S GMT")
    mirror = FakeMirror().add("GET", "/people/1", FakeResponse(200, {"data": person(1)}))
    mirror.fail_once("GET", "/people/1", status=429, body={"errors": []},
                     headers={"Retry-After": when})
    client = make_client(mirror, now=lambda: now)
    client.get("/people/1")
    assert client.clock.slept == [30.0]


# --------------------------------------------------------------------------
# The mirror's two gifts: 410 forwarding and an honest 504
# --------------------------------------------------------------------------

def test_410_exposes_the_survivor():
    mirror = FakeMirror().add(
        "GET", "/people/1",
        FakeResponse(410, error_body(410, "gone", {"merged_into": 2,
                                                   "deleted_at": "2026-01-01T00:00:00Z",
                                                   "tombstone_reason": "merged"})),
    )
    client = make_client(mirror)
    with pytest.raises(PcoGoneError) as caught:
        client.get("/people/1")
    assert caught.value.merged_into == "2"       # coerced to str, PCO sends both
    assert caught.value.tombstone_reason == "merged"


def test_410_without_a_forwarding_address():
    mirror = FakeMirror().add("GET", "/people/1",
                              FakeResponse(410, error_body(410, "gone",
                                                           {"deleted_at": "x"})))
    client = make_client(mirror)
    with pytest.raises(PcoGoneError) as caught:
        client.get("/people/1")
    assert caught.value.merged_into is None


def test_504_write_indeterminate_is_its_own_error_and_is_never_retried():
    body = error_body(504, "the write may or may not have been applied",
                      {"write_indeterminate": True, "safe_to_retry": False,
                       "code": "upstream_response_lost"})
    mirror = FakeMirror()
    mirror.fail_once("PATCH", "/people/1", status=504, body=body, times=5)
    client = make_client(mirror)
    with pytest.raises(PcoWriteIndeterminate) as caught:
        client.patch("/people/1", {"data": {}})
    assert caught.value.safe_to_retry is False
    # PATCH is normally replayable; write_indeterminate outranks that.
    assert mirror.count("PATCH", "/people/1") == 1


def test_a_plain_504_is_still_an_ordinary_gateway_error_for_a_get():
    mirror = FakeMirror().add("GET", "/people/1", FakeResponse(200, {"data": person(1)}))
    mirror.fail_once("GET", "/people/1", status=504, body={"errors": []}, times=2)
    client = make_client(mirror)
    assert client.get("/people/1")["data"]["id"] == "1"
    assert mirror.count("GET", "/people/1") == 3


# --------------------------------------------------------------------------
# Failure bodies that are not JSON
# --------------------------------------------------------------------------

def test_a_html_error_page_is_preserved_rather_than_exploding():
    html = "<html><head><title>504 Gateway Time-out</title></head></html>"
    mirror = FakeMirror().add("GET", "/people/1",
                              FakeResponse(502, text=html,
                                           headers={"Content-Type": "text/html"}))
    client = make_client(mirror, max_retries=0)
    with pytest.raises(PcoApiError) as caught:
        client.get("/people/1")
    assert "Gateway Time-out" in caught.value.response.body
    assert caught.value.errors == []


def test_a_very_long_failure_body_is_truncated():
    mirror = FakeMirror().add("GET", "/people/1",
                              FakeResponse(500, text="x" * 10_000))
    client = make_client(mirror, max_retries=0)
    with pytest.raises(PcoApiError) as caught:
        client.get("/people/1")
    assert caught.value.response.body_truncated is True
    assert len(caught.value.response.body) == 4000


def test_a_204_is_not_a_json_decode_error():
    mirror = FakeMirror().add("DELETE", "/field_data/5", FakeResponse(204))
    assert make_client(mirror).delete("/field_data/5") == {}


# --------------------------------------------------------------------------
# Pagination: all four cursor shapes
# --------------------------------------------------------------------------

@pytest.mark.parametrize("shape", [SHAPE_RELATIVE_LINKS, SHAPE_ABSOLUTE_LINKS,
                                   SHAPE_META_ONLY, SHAPE_NO_CURSOR])
def test_every_cursor_shape_walks_the_whole_collection(shape):
    records = [person(i) for i in range(250)]
    mirror = FakeMirror().add_collection("/people", records, per_page=100, shape=shape)
    client = make_client(mirror)
    walked = list(client.paginate_records("/people", per_page=100))
    assert [r["id"] for r in walked] == [str(i) for i in range(250)]


def test_a_full_page_with_no_cursor_does_not_stop_the_walk():
    """The case that silently truncated an organization when guessed wrong."""
    records = [person(i) for i in range(200)]
    mirror = FakeMirror().add_collection("/people", records, per_page=100,
                                         shape=SHAPE_NO_CURSOR)
    client = make_client(mirror)
    assert len(list(client.paginate_records("/people", per_page=100))) == 200


def test_a_short_page_ends_the_walk():
    records = [person(i) for i in range(150)]
    mirror = FakeMirror().add_collection("/people", records, per_page=100,
                                         shape=SHAPE_NO_CURSOR)
    client = make_client(mirror)
    assert len(list(client.paginate_records("/people", per_page=100))) == 150
    assert mirror.count("GET", "/people") == 2


def test_a_collection_that_is_exactly_one_full_page_costs_one_extra_request():
    """Cheaper than the alternative: assuming the end and losing everyone after."""
    records = [person(i) for i in range(100)]
    mirror = FakeMirror().add_collection("/people", records, per_page=100,
                                         shape=SHAPE_NO_CURSOR)
    client = make_client(mirror)
    assert len(list(client.paginate_records("/people", per_page=100))) == 100
    assert mirror.count("GET", "/people") == 2  # the second comes back empty


def test_an_empty_collection_is_one_request():
    mirror = FakeMirror().add_collection("/people", [], per_page=100)
    client = make_client(mirror)
    assert list(client.paginate_records("/people", per_page=100)) == []
    assert mirror.count("GET", "/people") == 1


def test_a_relative_links_next_resolves_against_the_serving_url():
    """Resolving against base_url instead loses the query string on page two."""
    body_one = {
        "data": [person(1)],
        "links": {"next": "/people/v2/people?per_page=1&offset=1&include=emails"},
        "meta": {"total_count": 2},
    }
    body_two = {"data": [person(2)], "links": {}, "meta": {"total_count": 2}}
    mirror = FakeMirror()
    mirror.add("GET", "/people", FakeResponse(200, body_one),
               query="per_page=1&offset=0&include=emails")
    mirror.add("GET", "/people", FakeResponse(200, body_two),
               query="per_page=1&offset=1&include=emails")
    # Page two is also "full" at per_page=1, so the client probes once more.
    mirror.add("GET", "/people",
               FakeResponse(200, {"data": [], "links": {}, "meta": {}}),
               query="per_page=1&offset=2&include=emails")
    client = make_client(mirror)
    walked = list(client.paginate_records("/people", {"include": ["emails"]}, per_page=1))
    assert [r["id"] for r in walked] == ["1", "2"]


def test_a_repeated_cursor_terminates_instead_of_looping():
    body = {"data": [person(1)],
            "links": {"next": "/people/v2/people?per_page=1&offset=0"},
            "meta": {}}
    mirror = FakeMirror().add("GET", "/people", FakeResponse(200, body),
                              query="per_page=1&offset=0")
    client = make_client(mirror)
    assert len(list(client.paginate_records("/people", per_page=1))) == 1


def test_max_pages_refuses_to_run_away():
    mirror = FakeMirror()
    # Every page is full and cursor-less, so the walk would never end on its own.
    for offset in range(0, 1000, 10):
        mirror.add("GET", "/people",
                   FakeResponse(200, {"data": [person(i) for i in range(10)],
                                      "links": {}, "meta": {}}),
                   query=f"per_page=10&offset={offset}")
    client = make_client(mirror)
    with pytest.raises(PcoApiError, match="exceeded"):
        list(client.paginate_records("/people", per_page=10, max_pages=3))


def test_a_meta_offset_that_does_not_advance_is_ignored():
    """A server insisting the next page is the current one must not loop us."""
    body = {"data": [person(i) for i in range(10)],
            "links": {}, "meta": {"next": {"offset": 0}}}
    mirror = FakeMirror().add("GET", "/people", FakeResponse(200, body),
                              query="per_page=10&offset=0")
    mirror.add("GET", "/people",
               FakeResponse(200, {"data": [], "links": {}, "meta": {}}),
               query="per_page=10&offset=10")
    client = make_client(mirror)
    # Falls through to stepping the offset itself rather than re-reading page one.
    assert len(list(client.paginate_records("/people", per_page=10))) == 10


# --------------------------------------------------------------------------
# Merge chains
# --------------------------------------------------------------------------

def test_follow_person_link_walks_to_the_survivor():
    mirror = FakeMirror()
    mirror.add("GET", "/people/1",
               FakeResponse(410, error_body(410, "gone", {"merged_into": "2"})))
    mirror.add("GET", "/people/2",
               FakeResponse(410, error_body(410, "gone", {"merged_into": "3"})))
    mirror.add("GET", "/people/3", FakeResponse(200, {"data": person(3, first_name="Ann")}))
    client = make_client(mirror)
    survivor, resource = client.follow_person_link("1")
    assert survivor == "3"
    assert resource["attributes"]["first_name"] == "Ann"


def test_follow_person_link_reuses_the_error_the_caller_already_holds():
    mirror = FakeMirror().add("GET", "/people/2",
                              FakeResponse(200, {"data": person(2)}))
    client = make_client(mirror)
    held = PcoGoneError("gone", status=410, path="/people/1",
                        errors=[{"meta": {"merged_into": "2"}}])
    survivor, _ = client.follow_person_link("1", from_error=held)
    assert survivor == "2"
    assert mirror.count("GET", "/people/1") == 0  # no wasted request


def test_a_merge_cycle_does_not_hang():
    mirror = FakeMirror()
    mirror.add("GET", "/people/1",
               FakeResponse(410, error_body(410, "gone", {"merged_into": "2"})))
    mirror.add("GET", "/people/2",
               FakeResponse(410, error_body(410, "gone", {"merged_into": "1"})))
    client = make_client(mirror)
    assert client.follow_person_link("1") == (None, None)


def test_a_dead_end_is_not_a_survivor():
    mirror = FakeMirror().add("GET", "/people/1",
                              FakeResponse(410, error_body(410, "gone", {})))
    client = make_client(mirror)
    assert client.follow_person_link("1") == (None, None)


def test_a_404_is_not_a_survivor_either():
    mirror = FakeMirror().add("GET", "/people/1",
                              FakeResponse(404, error_body(404, "not found")))
    client = make_client(mirror)
    assert client.follow_person_link("1") == (None, None)


def test_a_chain_longer_than_the_hop_cap_gives_up():
    mirror = FakeMirror()
    for i in range(1, MAX_MERGE_HOPS + 4):
        mirror.add("GET", f"/people/{i}",
                   FakeResponse(410, error_body(410, "gone", {"merged_into": str(i + 1)})))
    client = make_client(mirror)
    assert client.follow_person_link("1") == (None, None)


# --------------------------------------------------------------------------
# Mirror freshness, which is what the staleness guard reads
# --------------------------------------------------------------------------

def test_the_client_notes_how_stale_the_mirror_says_it_is():
    body = {"data": [], "meta": {"mirror": {"source": "mirror",
                                            "oldest_last_synced_at": "2026-08-03T11:00:00Z"}}}
    mirror = FakeMirror().add("GET", "/people", FakeResponse(200, body))
    client = make_client(mirror)
    client.get("/people")
    assert client.last_mirror_oldest_synced_at == "2026-08-03T11:00:00Z"


# --------------------------------------------------------------------------
# Construction
# --------------------------------------------------------------------------

@pytest.mark.parametrize("base,key", [("", KEY), (BASE, ""), (None, KEY), (BASE, None)])
def test_a_client_without_a_base_url_or_key_refuses_to_exist(base, key):
    with pytest.raises(ValueError):
        PcoMirrorClient(base, key)


def test_a_trailing_slash_on_the_base_url_does_not_double_up():
    mirror = FakeMirror().add("GET", "/people/1", FakeResponse(200, {"data": person(1)}))
    client = PcoMirrorClient(BASE + "/", KEY, session=mirror)
    client.get("/people/1")
    assert "//people" not in mirror.calls[0]["url"].replace("https://", "")
