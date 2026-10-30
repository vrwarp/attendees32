"""Only a request that writes runs in a transaction; a read holds none."""
import pytest
from django.contrib.auth.models import Group
from django.db import connection, transaction
from django.http import HttpResponse
from django.test import RequestFactory

from attendees.middleware import AtomicWritesMiddleware

pytestmark = pytest.mark.django_db(transaction=True)


def saw_a_transaction(method):
    """Run a request of ``method`` through the middleware and report whether the view was inside one."""
    seen = {}

    def view(request):
        seen["atomic"] = connection.in_atomic_block
        return HttpResponse()

    AtomicWritesMiddleware(view)(getattr(RequestFactory(), method.lower())("/anything/"))
    return seen["atomic"]


def test_writes_run_in_a_transaction_and_reads_do_not():
    assert all(saw_a_transaction(method) for method in ("POST", "PUT", "PATCH", "DELETE"))
    assert not any(saw_a_transaction(method) for method in ("GET", "HEAD", "OPTIONS"))


def test_a_write_request_that_fails_leaves_nothing_behind():
    def view(request):
        Group.objects.create(name="Half done")
        raise RuntimeError("the second step failed")

    with pytest.raises(RuntimeError):
        AtomicWritesMiddleware(view)(RequestFactory().post("/anything/"))
    assert not Group.objects.filter(name="Half done").exists()


def test_a_read_request_commits_as_it_goes():
    """A GET handler that writes keeps what it wrote before failing; step 3 of the plan is what keeps such handlers rare."""

    def view(request):
        Group.objects.create(name="Written on a read")
        raise RuntimeError("after the write")

    with pytest.raises(RuntimeError):
        AtomicWritesMiddleware(view)(RequestFactory().get("/anything/"))
    assert Group.objects.filter(name="Written on a read").exists()


def test_the_settings_no_longer_open_a_transaction_per_request(settings):
    assert settings.DATABASES["default"]["ATOMIC_REQUESTS"] is False
    assert settings.MIDDLEWARE[-1] == "attendees.middleware.AtomicWritesMiddleware"
    assert transaction.get_autocommit()  # outside a write request the connection is in autocommit
