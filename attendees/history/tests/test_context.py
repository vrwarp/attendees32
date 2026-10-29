"""Who an event is attributed to: the request, the task, or the shell."""
import getpass

import pytest
from django.contrib.auth.models import AnonymousUser, Group
from django.http import HttpResponse
from django.test import RequestFactory

from attendees.history import context, events_for
from attendees.history.middleware import HistoryContextMiddleware
from attendees.history.models import HistoryContext

pytestmark = pytest.mark.django_db


def test_a_write_outside_any_request_is_a_shell_write_by_the_operating_system_user():
    group = Group.objects.create(name="Ushers")
    event = events_for(group).get()
    assert event.context.label == "shell"
    assert event.context.user is None
    assert event.context.user_name == getpass.getuser()


def test_the_middleware_names_the_request_and_reads_the_user_when_the_first_event_is_written(user):
    request = RequestFactory().post("/persons/api/datagrid_data_attendees/")
    request.user = AnonymousUser()  # as the session middleware leaves a token-authenticated API call

    def view(request):
        request.user = user  # REST Framework authenticates inside the view
        Group.objects.create(name="Ushers")
        Group.objects.create(name="Greeters")
        return HttpResponse()

    HistoryContextMiddleware(view)(request)
    ushers, greeters = events_for(Group.objects.get(name="Ushers")).get(), events_for(Group.objects.get(name="Greeters")).get()
    assert ushers.context.label == "POST /persons/api/datagrid_data_attendees/"
    assert ushers.context.user == user and ushers.context.user_name == user.username
    assert greeters.context_id == ushers.context_id  # one context per request


def test_a_request_that_writes_nothing_leaves_no_context():
    before = HistoryContext.objects.count()
    HistoryContextMiddleware(lambda request: HttpResponse())(RequestFactory().get("/"))
    assert HistoryContext.objects.count() == before


def test_a_task_names_itself_and_who_it_works_for(user):
    @context("batch create gatherings", user=user)
    def job():
        return Group.objects.create(name="Ushers")

    event = events_for(job()).get()
    assert event.context.label == "batch create gatherings"
    assert event.context.user == user and event.context.user_name == user.username


def test_contexts_nest_and_end_where_they_began():
    with context("outer"):
        outer = Group.objects.create(name="Outer")
        with context("inner"):
            inner = Group.objects.create(name="Inner")
        again = Group.objects.create(name="Outer again")
    after = Group.objects.create(name="After")
    assert events_for(outer).get().context.label == "outer"
    assert events_for(inner).get().context.label == "inner"
    assert events_for(again).get().context_id == events_for(outer).get().context_id
    assert events_for(after).get().context.label == "shell"
