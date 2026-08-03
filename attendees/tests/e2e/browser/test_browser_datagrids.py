"""The datagrids.

Every roster screen in this application is an empty ``<div>`` server-side that
DevExtreme fills over AJAX.  The HTTP suite proves the endpoints answer; only a
browser proves the screen asks them the right question and renders the answer.
"""

import pytest

pytestmark = pytest.mark.django_db

ROSTER_GRID = "div.dataAttendees"
DATA_ROW = ".dx-data-row"


def wait_for_rows(page, container):
    page.wait_for_selector(f"{container} .dx-datagrid")
    page.wait_for_selector(f"{container} {DATA_ROW}")
    return page.locator(f"{container} {DATA_ROW}")


class TestAttendeeRoster:
    def test_the_grid_fills_with_the_congregation(self, sign_in, visit, page):
        sign_in("golden_data_organizer")
        visit("/persons/attendees/")
        rows = wait_for_rows(page, ROSTER_GRID)
        assert rows.count() > 0
        # DevExtreme's pager reports the whole result set: the 350-person
        # roster minus 陳桂枝, who died four years ago — this grid leaves the
        # dead out unless asked for them.
        pager = page.locator(f"{ROSTER_GRID} .dx-datagrid-pager")
        pager.wait_for()
        assert "349 items" in pager.inner_text().replace(",", "")

    def test_searching_a_han_name_narrows_the_grid(self, sign_in, visit, page):
        sign_in("golden_data_organizer")
        visit("/persons/attendees/")
        wait_for_rows(page, ROSTER_GRID)
        search = page.locator(f"{ROSTER_GRID} .dx-datagrid-search-panel input")
        search.wait_for()
        search.fill("陳明恩")
        page.wait_for_function(
            "([selector, before]) =>"
            " document.querySelectorAll(selector).length > 0"
            " && document.querySelectorAll(selector).length < before",
            arg=[f"{ROSTER_GRID} {DATA_ROW}", 20],
        )
        assert "Grace" in page.locator(ROSTER_GRID).inner_text()

    def test_an_ordinary_member_is_not_offered_the_add_button(
        self, sign_in, visit, page
    ):
        sign_in("golden_member")
        visit("/persons/attendees/")
        page.wait_for_selector(f"{ROSTER_GRID} .dx-datagrid")
        assert page.locator("a.add-attendee").count() == 0

    def test_a_data_admin_is_offered_the_add_button(self, sign_in, visit, page):
        sign_in("golden_data_organizer")
        visit("/persons/attendees/")
        page.wait_for_selector("a.add-attendee")
        assert page.locator("a.add-attendee").is_visible()


class TestAttendeePage:
    def test_the_family_grid_shows_the_household(self, sign_in, visit, page, golden):
        sign_in("golden_data_organizer")
        visit(f"/persons/attendee/{golden.attendee('chen_grace').id}")
        rows = wait_for_rows(page, "#family-attendee-datagrid-container")
        text = page.locator("#family-attendee-datagrid-container").inner_text()
        assert rows.count() >= 4  # father, mother, brother, grandfather, herself
        assert "Zhiming" in text
        assert "Joshua" in text

    def test_the_participation_grid_shows_the_meets_she_joined(
        self, sign_in, visit, page, golden
    ):
        sign_in("golden_data_organizer")
        visit(f"/persons/attendee/{golden.attendee('chen_grace').id}")
        wait_for_rows(page, "#attendingmeet-datagrid-container")
        text = page.locator("#attendingmeet-datagrid-container").inner_text()
        assert "崇拜" in text or "Sunday Service" in text

    def test_the_form_is_filled_from_the_record(self, sign_in, visit, page, golden):
        sign_in("golden_data_organizer")
        visit(f"/persons/attendee/{golden.attendee('chen_grace').id}")
        page.wait_for_selector("div.datagrid-attendee-update .dx-texteditor-input")
        values = page.locator(
            "div.datagrid-attendee-update .dx-texteditor-input"
        ).all_inner_texts()
        inputs = page.eval_on_selector_all(
            "div.datagrid-attendee-update input",
            "nodes => nodes.map(n => n.value).filter(Boolean)",
        )
        assert any("Grace" == value or "Grace" in value for value in inputs + values)

    def test_a_guardianship_shows_up_in_the_relationship_grid(
        self, sign_in, visit, page, golden
    ):
        """Kevin's guardians are not his parents — the "other" folk grid."""
        sign_in("golden_counselor")
        visit(f"/persons/attendee/{golden.attendee('xu_kevin').id}")
        wait_for_rows(page, "#relationship-datagrid-container")
        assert "guardian" in page.locator(
            "#relationship-datagrid-container"
        ).inner_text().lower()


class TestOtherGrids:
    def test_the_enrollment_grid_boots(self, sign_in, visit, page):
        sign_in("golden_data_organizer")
        visit("/persons/attendingmeets/")
        page.wait_for_selector("#attendingmeets-datagrid-container .dx-datagrid")

    def test_the_roster_grid_boots(self, sign_in, visit, page):
        sign_in("golden_children_organizer")
        visit("/occasions/roster/")
        page.wait_for_selector("#attendances-datagrid-container .dx-datagrid")

    def test_the_statistics_grid_boots(self, sign_in, visit, page):
        sign_in("golden_data_organizer")
        visit("/occasions/attendance_statistics/")
        page.wait_for_selector("#attendances-datagrid-container .dx-datagrid")
