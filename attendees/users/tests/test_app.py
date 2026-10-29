import pytest
from django.contrib.auth.models import Group, Permission
from attendees.history import events_for
from attendees.history.models import HistoryEvent
from attendees.users.models.user import User
from attendees.whereabouts.models import Organization

pytestmark = pytest.mark.django_db


def test_user_group_membership():
    org = Organization.objects.create(display_name="Test Org", slug="test-org")
    group = Group.objects.create(name="TestGroup")
    user = User.objects.create_user(username="groupuser", email="groupuser@example.com", password="pass1234", organization=org)
    user.groups.add(group)
    assert user.groups.filter(name="TestGroup").exists()
    assert group in user.groups.all()


def membership_events(through, **row):
    """The events of one membership row, by the through model and the pair it links."""
    link = through._base_manager.filter(**row).first()
    key = str(link.pk) if link is not None else None
    if key is None:  # removed: the last event of a row that linked the pair
        candidates = HistoryEvent.objects.filter(model=through._meta.label_lower)
        key = next(e.object_id for e in candidates.order_by("-seq") if all(e.snapshot.get(f"{k}_id") == v.pk for k, v in row.items()))
    return list(HistoryEvent.objects.filter(model=through._meta.label_lower, object_id=key).order_by("seq"))


def test_user_group_history_created():
    org = Organization.objects.create(display_name="Test Org", slug="test-org")
    group = Group.objects.create(name="HistoryGroup")
    user = User.objects.create_user(username="historygroupuser", email="historygroupuser@example.com", password="pass1234", organization=org)
    user.groups.add(group)
    events = membership_events(user.groups.through, user=user, group=group)
    assert [e.label for e in events] == ["snapshot"]
    assert events[0].snapshot["group_id"] == group.pk and events[0].snapshot["user_id"] == user.pk
    user.groups.remove(group)
    # The add and the removal are two events on the same membership row
    events = membership_events(user.groups.through, user=user, group=group)
    assert [e.label for e in events] == ["snapshot", "before_delete"]
    assert not user.groups.filter(pk=group.pk).exists()


def test_group_permission_history():
    group = Group.objects.create(name="PermGroup")
    perm = Permission.objects.first()
    group.permissions.add(perm)
    assert [e.label for e in membership_events(group.permissions.through, group=group, permission=perm)] == ["snapshot"]
    group.permissions.remove(perm)
    assert [e.label for e in membership_events(group.permissions.through, group=group, permission=perm)] == ["snapshot", "before_delete"]


def test_user_permissions_history():
    org = Organization.objects.create(display_name="Test Org", slug="test-org")
    user = User.objects.create_user(username="permuser", email="permuser@example.com", password="pass1234", organization=org)
    perm = Permission.objects.first()
    user.user_permissions.add(perm)
    assert [e.label for e in membership_events(user.user_permissions.through, user=user, permission=perm)] == ["snapshot"]
    user.user_permissions.remove(perm)
    assert [e.label for e in membership_events(user.user_permissions.through, user=user, permission=perm)] == ["snapshot", "before_delete"]


def test_group_history():
    group = Group.objects.create(name="HistoryTrackingGroup")

    # 1. A snapshot is recorded when the group is created
    assert [e.label for e in events_for(group)] == ["snapshot"]

    # 2. A save that changes nothing records nothing; a change does
    group.save()
    assert events_for(group).count() == 1
    group.name = "HistoryTrackingGroupRenamed"
    group.save()
    assert events_for(group).count() == 2
    assert events_for(group).last().instance.name == "HistoryTrackingGroupRenamed"

    # 3. The record is kept before it is deleted
    group_id = group.id
    group.delete()
    deleted = HistoryEvent.objects.filter(model="auth.group", object_id=str(group_id), label="before_delete")
    assert deleted.exists() and deleted.get().snapshot["name"] == "HistoryTrackingGroupRenamed"
