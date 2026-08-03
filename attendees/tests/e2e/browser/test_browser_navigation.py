"""Signing in, moving around, and being turned away — in a real browser."""

import pytest

pytestmark = pytest.mark.django_db


class TestSignIn:
    def test_a_member_signs_in_through_the_real_form(self, sign_in, page):
        sign_in("golden_member")
        assert "/accounts/login" not in page.url
        assert "Sign Out" in page.locator("nav").inner_text()

    def test_a_wrong_password_is_refused(self, page, visit, golden, db):
        visit("/accounts/login/")
        page.fill("input[name='login']", "golden_member")
        page.fill("input[name='password']", "not-the-password")
        page.click("button[type='submit'], input[type='submit']")
        page.wait_for_selector(".alert-danger, .errorlist, [role='alert']")
        assert "/accounts/login" in page.url

    def test_signing_out_ends_the_session(self, sign_in, visit, page):
        sign_in("golden_member")
        visit("/accounts/logout/")
        page.click("button[type='submit'], input[type='submit']")
        page.wait_for_load_state("domcontentloaded")
        visit("/persons/attendees/")
        assert "/accounts/login" in page.url

    def test_an_anonymous_visitor_is_sent_to_the_login_page(self, visit, page):
        visit("/persons/attendees/")
        assert "/accounts/login" in page.url


class TestNavigation:
    def test_the_menu_is_built_from_the_users_groups(self, sign_in, visit, page):
        """``users.Menu`` drives the navbar, so a member sees fewer links."""
        member_links = set(
            sign_in("golden_member").locator("nav a").all_inner_texts()
        )
        assert any("自身資料" in link or "self info" in link for link in member_links)

    def test_a_coworker_sees_more_of_the_menu_than_a_member(
        self, sign_in, visit, page
    ):
        organizer_links = set(
            sign_in("golden_data_organizer").locator("nav a").all_inner_texts()
        )
        joined = " ".join(organizer_links)
        assert "通訊錄" in joined or "directory" in joined.lower()

    def test_the_home_page_renders_for_anyone(self, visit, page):
        visit("/")
        assert page.locator("body").is_visible()


class TestGuardsInTheBrowser:
    def test_a_member_is_told_when_a_page_is_not_theirs(self, sign_in, visit, page):
        sign_in("golden_member")
        visit("/occasions/attendance_statistics/")
        assert "does not have permissions to visit such route" in (
            page.locator("body").inner_text()
        )

    def test_a_member_cannot_open_a_stranger(self, sign_in, visit, page, golden):
        sign_in("golden_member")
        visit(f"/persons/attendee/{golden.attendee('lee_peter').id}")
        assert "not allowed to access this page" in (
            page.locator("body").inner_text().lower()
        )

    def test_a_parent_can_open_the_child_they_schedule(
        self, sign_in, visit, page, golden
    ):
        sign_in("golden_member")
        visit(f"/persons/attendee/{golden.attendee('chen_joshua').id}")
        page.wait_for_selector("div.datagrid-attendee-update")
        assert "not allowed" not in page.locator("body").inner_text().lower()


class TestPrintedPages:
    def test_the_directory_preview_renders_a_household(
        self, sign_in, visit, page, golden
    ):
        sign_in("golden_counselor")
        visit(f"/persons/directory_preview/{golden.attendee('chen_zhiming').id}")
        body = page.locator("body").inner_text()
        assert "Zhiming" in body
        assert "Guizhi" not in body  # she died four years ago

    def test_the_directory_pdf_page_is_paginated_by_pagedjs(
        self, sign_in, visit, page
    ):
        """Paged.js has to actually run, or the directory prints as one slab.

        The polyfill used to be loaded from a URL that answers with HTML, so
        the browser parsed a web page as JavaScript, threw a SyntaxError and
        left the document unpaginated — invisible to any test that only reads
        the server's response.
        """
        sign_in("golden_data_organizer")
        visit("/persons/directory_report/?divisionSelector=1&divisionSelector=2"
              "&divisionSelector=3&directoryHeader=CFCCH")
        page.wait_for_selector(".pagedjs_pages .pagedjs_page")
        assert page.locator(".pagedjs_page").count() >= 2, (
            "350 people do not fit on one printed page"
        )
        assert "CFCCH" in page.locator(".pagedjs_pages").inner_text()

    def test_the_participation_report_is_paginated_too(self, sign_in, visit, page):
        sign_in("golden_data_organizer")
        visit("/persons/attendingmeet_report/"
              "?meet=d7c8Fd_cfcch_congregation_directory"
              "&divisions=cfcch_chinese_ministry&reportTitle=CFCCH")
        page.wait_for_selector(".pagedjs_pages .pagedjs_page")
        assert "CFCCH" in page.locator(".pagedjs_pages").inner_text()

    def test_the_calendar_page_boots(self, sign_in, visit, page):
        sign_in("golden_member")
        visit("/occasions/calendars/")
        page.wait_for_selector("body")
