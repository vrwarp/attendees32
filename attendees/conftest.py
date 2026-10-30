import pytest

from attendees.users.models import User
from attendees.users.tests.factories import UserFactory, enrol_second_factor

#: Where the end-to-end suite lives, relative to this file.
E2E_DIRECTORY = "tests/e2e"


@pytest.fixture(autouse=True)
def media_storage(settings, tmpdir):
    settings.MEDIA_ROOT = tmpdir.strpath


@pytest.fixture(autouse=True)
def clear_cache():
    """Isolate the process-wide cache between tests.

    A service that caches by primary key gets colliding keys on SQLite where it never would on
    Postgres: Postgres sequences are non-transactional, so every test's rows get fresh ids,
    while SQLite allocates rowids inside the transaction and reuses them once the test rolls
    back — each test builds its fixtures with the *same* ids and inherits whatever an earlier
    test cached under them. Clearing between tests removes the ordering dependency on both
    backends.
    """
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def user() -> User:
    return UserFactory()


@pytest.fixture
def admin_user(admin_user):
    """pytest-django's superuser, with the second factor every staff account must have."""
    return enrol_second_factor(admin_user)


def pytest_collection_modifyitems(items):
    """Run the end-to-end suite last.

    The e2e tests share one committed 350-person congregation, built once per
    session (see ``attendees/tests/conftest.py``) because rebuilding it per
    test would cost a minute each time.  Committed data is visible to every
    other test in the session, and the unit tests create fixtures with
    hard-coded primary keys that would then collide — so the golden data is
    built after every other test has finished, and flushed on the way out.
    """
    e2e, others = [], []
    for item in items:
        (e2e if E2E_DIRECTORY in str(item.fspath).replace("\\", "/") else others).append(
            item
        )
    items[:] = others + e2e
