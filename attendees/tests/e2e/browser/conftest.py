"""Real browsers driving the real pages.

Everything else in ``attendees/tests/e2e`` talks HTTP: it proves the routing,
the guards, the serializers and the queries.  None of it proves the screens
work, because every datagrid in this application is an empty shell server-side
that fills itself over AJAX once DevExtreme has booted.  These tests open the
pages in Chromium and WebKit and wait for the grids to have rows in them.

Playwright is driven directly rather than through ``pytest-playwright`` so that
both engines run on a bare ``pytest`` with no extra command-line flags — the
``browser`` fixture is parametrised, so every test here runs twice.

If the browsers are not installed the tests skip, unless
``ATTENDEES_REQUIRE_BROWSERS`` is set — CI sets it, so a broken image fails the
build instead of quietly testing nothing.
"""

import os

import pytest

REQUIRE_BROWSERS = os.environ.get("ATTENDEES_REQUIRE_BROWSERS") == "1"

#: Both engines. WebKit is not just "Safari": it is the one that finds the
#: date-input, flexbox and Intl differences Chromium forgives.
BROWSER_ENGINES = ("chromium", "webkit")

#: Enough room for the datagrids to render their toolbars and columns.
VIEWPORT = {"width": 1440, "height": 1000}

#: The pages load DevExtreme (4 MB), jQuery plugins and Bootstrap from public
#: CDNs. Fetching those once per session instead of once per page load takes
#: the suite from minutes to seconds, and the bytes are passed through
#: unchanged so the subresource-integrity hashes in the templates still check
#: out — which is itself worth knowing.
CDN_TIMEOUT_MS = 60_000


def _unavailable(reason):
    if REQUIRE_BROWSERS:
        pytest.fail(f"ATTENDEES_REQUIRE_BROWSERS is set but {reason}")
    pytest.skip(f"{reason}; run `playwright install chromium webkit`")


@pytest.fixture(scope="session")
def playwright_driver():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:  # pragma: no cover - depends on the environment
        _unavailable("playwright is not installed")

    # Playwright's synchronous API drives an event loop under the covers, so
    # Django's async_unsafe guard fires on any ORM call made while it is
    # running — including pytest-django rolling a test back. The loop is not
    # actually doing concurrent ORM work; this is the documented escape hatch.
    previous = os.environ.get("DJANGO_ALLOW_ASYNC_UNSAFE")
    os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "1"
    try:
        with sync_playwright() as driver:
            yield driver
    finally:
        if previous is None:
            os.environ.pop("DJANGO_ALLOW_ASYNC_UNSAFE", None)
        else:
            os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = previous


@pytest.fixture(scope="session")
def cdn(playwright_driver):
    """Fetch each third-party asset once, then serve it from memory."""
    request_context = playwright_driver.request.new_context()
    cache = {}

    def fetch(url):
        if url not in cache:
            response = request_context.get(url, timeout=CDN_TIMEOUT_MS)
            cache[url] = {
                "status": response.status,
                "content_type": response.headers.get(
                    "content-type", "application/octet-stream"
                ),
                "body": response.body(),
            }
        return cache[url]

    yield fetch
    request_context.dispose()


@pytest.fixture(scope="session")
def app_server(django_db_setup, django_db_blocker, golden):
    """A real HTTP server for the browsers to talk to.

    Deliberately *not* pytest-django's ``live_server``: that fixture pulls in
    ``transactional_db``, which truncates every table after each test — and the
    golden congregation, committed once for the whole session, is exactly what
    gets truncated.  A plain ``LiveServerThread`` reads the same committed data
    over its own connection and leaves it alone.

    The consequence is that anything the *server* writes is committed for real,
    so the specs here stay read-only.
    """
    from django.contrib.staticfiles.handlers import StaticFilesHandler
    from django.test.testcases import LiveServerThread
    from django.test.utils import modify_settings

    host = "localhost"
    allowed_hosts = modify_settings(ALLOWED_HOSTS={"append": host})
    allowed_hosts.enable()

    thread = LiveServerThread(host, static_handler=StaticFilesHandler)
    thread.daemon = True
    with django_db_blocker.unblock():
        thread.start()
        thread.is_ready.wait()
        if thread.error:
            allowed_hosts.disable()
            raise thread.error

        class Server:
            url = f"http://{host}:{thread.port}"

        yield Server()

        thread.terminate()
    allowed_hosts.disable()


#: Chromium runs as root inside the project's container, where the sandbox is
#: unavailable and /dev/shm is small; both switches are the usual CI answer.
LAUNCH_ARGS = {
    "chromium": ["--no-sandbox", "--disable-dev-shm-usage"],
    "webkit": [],
}


@pytest.fixture(scope="session", params=BROWSER_ENGINES)
def browser(request, playwright_driver):
    engine = request.param
    try:
        instance = getattr(playwright_driver, engine).launch(
            args=LAUNCH_ARGS[engine]
        )
    except Exception as error:  # pragma: no cover - depends on the environment
        _unavailable(f"{engine} could not launch ({type(error).__name__})")
    yield instance
    instance.close()


@pytest.fixture
def page(browser, app_server, cdn):
    context = browser.new_context(viewport=VIEWPORT, base_url=app_server.url)
    context.set_default_timeout(30_000)
    context.set_default_navigation_timeout(30_000)

    def route_third_party(route, request):
        if request.url.startswith(app_server.url):
            route.continue_()
            return
        try:
            cached = cdn(request.url)
        except Exception:  # pragma: no cover - the asset is simply unavailable
            route.abort()
            return
        route.fulfill(
            status=cached["status"],
            body=cached["body"],
            headers={
                "content-type": cached["content_type"],
                # The script tags are crossorigin="anonymous", so a fulfilled
                # response still has to answer the CORS preflight rules.
                "access-control-allow-origin": "*",
                "cache-control": "public, max-age=86400",
            },
        )

    context.route("**/*", route_third_party)

    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    yield page
    context.close()
    ignorable = ("ResizeObserver",)
    fatal = [error for error in errors if not any(w in error for w in ignorable)]
    assert not fatal, f"the page raised JavaScript errors: {fatal}"


@pytest.fixture(autouse=True)
def reset_login_rate_limits():
    """Keep one test's bad password from locking the next test out.

    ``ACCOUNT_RATE_LIMITS = {"login_failed": "3/10m"}`` counts per IP, and every
    test here arrives from 127.0.0.1. allauth keeps the counters in the Django
    cache, and it answers a rate-limited attempt with the same "username and/or
    password are not correct" message as a genuinely wrong one — so without
    this, a suite that tests a failed login mysteriously fails every login
    after it.
    """
    from django.core.cache import cache

    cache.clear()
    yield


@pytest.fixture
def visit(page):
    """Navigate without waiting on every last third-party subresource."""

    def _visit(path):
        page.goto(path, wait_until="domcontentloaded")
        return page

    return _visit


@pytest.fixture
def sign_in(page, visit, golden, db):
    """Sign in through the real allauth form, as the golden personas do."""
    from attendees.tests.golden import PERSONA_PASSWORD

    def _sign_in(username):
        visit("/accounts/login/")
        page.fill("input[name='login']", username)
        page.fill("input[name='password']", PERSONA_PASSWORD)
        with page.expect_navigation(wait_until="domcontentloaded"):
            page.click("button[type='submit'], input[type='submit']")
        assert "/accounts/login" not in page.url, (
            f"{username} was not signed in: still on {page.url}"
        )
        return page

    return _sign_in
