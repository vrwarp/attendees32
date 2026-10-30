"""``/persons/api/datagrid_data_attendees/`` against the golden congregation."""

import json

import pytest

from attendees.tests.golden.constants import MeetSlugs

pytestmark = pytest.mark.django_db


class TestDatagridDataAttendees:
    def test_the_datagrid_roster_filters_by_meet(self, golden, api_login):
        client = api_login("golden_data_organizer")
        response = client.get(
            "/persons/api/datagrid_data_attendees/",
            {
                "filter": json.dumps(
                    ["attendings__meets__slug", "=", MeetSlugs.ENGLISH_SERVICE]
                )
            },
        )
        assert response.status_code == 200
        # 135 people are on the English service roster (100 adults, 25 youth and
        # the 10 bilingual attenders); the datagrid counts only participations
        # that have not finished, so the 15 inactive ones drop out.
        assert response.json()["totalCount"] == 120

    def test_the_datagrid_roster_accepts_a_devextreme_filter(self, golden, api_login):
        client = api_login("golden_data_organizer")
        response = client.get(
            "/persons/api/datagrid_data_attendees/",
            {"filter": json.dumps(["last_name", "=", "Tsai"])},
        )
        assert response.status_code == 200
        assert response.json()["totalCount"] >= 4

    def test_the_search_box_term_is_answered_for_every_column(self, golden, api_login):
        """The roster's search box ORs the term across all columns, visitor_since and folkcities
        included, which are built in Python; their share of the filter is answered from the
        enrollments and places they are built from, and a city name finds its households."""
        client = api_login("golden_data_organizer")
        columns = (
            "infos.names", "folks__display_name", "id", "first_name", "last_name", "last_name2",
            "first_name2", "visitor_since", "folkcities", "infos.contacts",
        )

        def search(term, searched=columns):
            clauses = []
            for column in searched:
                if clauses:
                    clauses.append("or")
                clauses.append([column, "=" if column in ("visitor_since", "folkcities") else "contains", term])
            if len(clauses) == 1:
                clauses = clauses[0]  # one clause is sent flat, as the grid does
            response = client.get("/persons/api/datagrid_data_attendees/", {"take": 50, "filter": json.dumps(clauses)})
            assert response.status_code == 200, response.content
            return response.json()["data"]

        by_name = search("陳明恩")  # 明恩 is a common given name: Grace is one of several it finds
        assert "Grace Chen 陳明恩" in {row["full_name"] for row in by_name}
        assert all("陳明恩" in row["full_name"] for row in by_name)
        # The name column alone finds a whole Han name, on every backend: it is answered from the
        # search column, not from the JSON the names live in (SQLite stores that with ASCII escapes).
        assert {row["full_name"] for row in search("馮瑞安", searched=("infos.names",))} == {"Ruian Feng 馮瑞安"}
        assert search("Castro Valley"), "the whole search box finds the city too"
        by_city = search("Castro Valley", searched=("folkcities",))
        assert by_city and all(
            any(city["locality__name"] == "Castro Valley" for city in row["folkcities"]) for row in by_city
        )
        assert search("2025-13") == []

    def test_the_dead_are_excluded_unless_asked_for(self, golden, api_login):
        client = api_login("golden_data_organizer")
        without = client.get("/persons/api/datagrid_data_attendees/").json()["totalCount"]
        with_dead = client.get(
            "/persons/api/datagrid_data_attendees/?include_dead=true"
        ).json()["totalCount"]
        assert with_dead > without
