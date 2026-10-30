"""Nothing readable leaves the building: error reports, log lines and the pages' libraries."""
import logging
import re
from pathlib import Path

from attendees.utils.logging import StripQueryString
from attendees.utils.sentry import strip_personal_data

TEMPLATES = Path(__file__).resolve().parents[1] / "templates"
ASSET_TAG = re.compile(r"<(?:script|link|img|iframe)\b[^>]*>", re.S)
OTHER_HOST = re.compile(r"""(?:src|href)=["']https?://""")


def test_an_error_report_keeps_the_trace_and_drops_the_person():
    event = {
        "exception": {
            "values": [
                {
                    "type": "KeyError",
                    "value": "'infos'",
                    "stacktrace": {"frames": [{"function": "get", "vars": {"attendee": "<Attendee: Grace Chen>"}}]},
                }
            ]
        },
        "user": {"id": 7, "username": "pastor", "ip_address": "10.0.0.9"},
        "request": {
            "method": "GET",
            "url": "https://attendees.example/persons/attendees/?search=Grace+Chen",
            "query_string": "search=Grace+Chen",
            "headers": {"Cookie": "sessionid=abc", "Authorization": "Token 123"},
            "cookies": {"sessionid": "abc"},
            "data": {"first_name": "Grace"},
            "env": {"REMOTE_ADDR": "10.0.0.9"},
        },
        "breadcrumbs": {"values": [{"message": "GET /persons/attendees/", "data": {"url": "/x?search=Grace"}}]},
        "tags": {"transaction": "persons:attendees_list_view"},
    }
    scrubbed = strip_personal_data(event, {})
    assert "user" not in scrubbed
    assert scrubbed["request"] == {"method": "GET", "url": "https://attendees.example/persons/attendees/"}
    assert scrubbed["breadcrumbs"]["values"] == [{"message": "GET /persons/attendees/"}]
    assert scrubbed["exception"]["values"][0]["stacktrace"]["frames"] == [{"function": "get"}]
    assert scrubbed["tags"] == {"transaction": "persons:attendees_list_view"}


def test_the_log_filter_cuts_the_query_string_from_the_message_and_its_arguments():
    message = logging.LogRecord(
        "django.request", logging.WARNING, __file__, 1,
        "Not Found: /persons/attendees/?search=Grace%20Chen", (), None,
    )
    assert StripQueryString().filter(message)
    assert message.getMessage() == "Not Found: /persons/attendees/"

    access = logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 1,
        '%s - "%s %s HTTP/%s" %d', ("10.0.0.9:1234", "GET", "/persons/attendees/?search=Grace&take=5", "1.1", 200), None,
    )
    StripQueryString().filter(access)
    assert access.getMessage() == '10.0.0.9:1234 - "GET /persons/attendees/ HTTP/1.1" 200'

    plain = logging.LogRecord("attendees", logging.INFO, __file__, 1, "ready? yes, %s", ("https://h/p?q=1 and more",), None)
    StripQueryString().filter(plain)
    assert plain.getMessage() == "ready? yes, https://h/p and more"


def test_no_page_loads_a_script_image_or_stylesheet_from_another_host():
    """Every library is served from static/vendor/ with its integrity hash; a member's browser talks to us alone."""
    offenders = [
        f"{path.relative_to(TEMPLATES)}: {tag.group(0)[:80]}"
        for path in sorted(TEMPLATES.rglob("*.html"))
        for tag in ASSET_TAG.finditer(path.read_text())
        if OTHER_HOST.search(tag.group(0))
    ]
    assert offenders == []
