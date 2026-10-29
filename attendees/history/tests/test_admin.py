"""The history in the admin: a record's page, the list of events by user, and restore."""
import pytest
from django.urls import reverse

from attendees.history import context, events_for
from attendees.history.models import HistoryEvent
from attendees.persons.models import Attendee

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin(django_user_model, client, division):
    """A superuser of the organization; the admin's querysets are scoped to the user's organization."""
    user = django_user_model.objects.create_superuser(
        username="admin", email="admin@example.com", password="pw", organization=division.organization
    )
    client.force_login(user)
    return user


def test_the_history_page_lists_the_records_events_with_who_made_them(admin, client, make_attendee):
    with context("manual fix", user=admin):
        attendee = make_attendee()
        attendee.first_name = "Amazing"
        attendee.save()
    response = client.get(reverse("admin:persons_attendee_history", args=[attendee.pk]))
    assert response.status_code == 200
    body = response.content.decode()
    assert "by admin" in body and "manual fix" in body
    assert "Amazing" in body and "Grace" in body  # the change, before and after
    assert body.count("snapshot") >= 2


def test_the_event_list_filters_by_user_and_model(admin, client, make_attendee):
    with context("edit", user=admin):
        attendee = make_attendee()
    response = client.get(
        reverse("admin:history_historyevent_changelist"), {"context__user__id__exact": admin.pk, "model": "persons.attendee"}
    )
    assert response.status_code == 200
    assert str(attendee.pk) in response.content.decode()


def test_restoring_a_version_puts_the_record_back_and_records_the_restore(admin, client, make_attendee):
    attendee = make_attendee()
    first = events_for(attendee).get()
    attendee.first_name = "Wrong"
    attendee.save()
    response = client.post(
        reverse("admin:history_historyevent_changelist"),
        {"action": "restore_version", "_selected_action": [first.seq]},
        follow=True,
    )
    assert response.status_code == 200
    attendee.refresh_from_db()
    assert attendee.first_name == "Grace"
    restored = events_for(attendee).last()
    assert restored.label == "snapshot" and restored.snapshot["first_name"] == "Grace"
    assert restored.context.user == admin and "POST" in restored.context.label


def test_a_hard_deleted_record_comes_back_under_its_old_key(make_attendee):
    attendee = make_attendee()
    key = attendee.pk
    attendee.delete(soft=False)
    gone = HistoryEvent.objects.get(model="persons.attendee", object_id=str(key), label="before_delete")
    gone.restore()
    assert Attendee.all_objects.filter(pk=key, first_name="Grace").exists()
    assert events_for(Attendee.all_objects.get(pk=key)).last().label == "snapshot"
