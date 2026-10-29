"""Nothing of ours escapes the history: every model is tracked and every manager is the tracked one."""
from django.apps import apps
from django.contrib.auth.models import Group, Permission

from attendees.history.querysets import TrackedQuerySet
from attendees.history.tracking import FRAMEWORK_MODELS, tracked_for, tracked_models
from attendees.persons.models import Note, Past
from attendees.users.models import User

OWN_APPS = {"persons", "occasions", "users", "whereabouts"}


def test_every_model_of_ours_is_tracked():
    untracked = [
        model._meta.label
        for model in apps.get_models(include_auto_created=True)
        if model._meta.app_label in OWN_APPS and tracked_for(model) is None
    ]
    assert untracked == []


def test_our_tracked_models_hand_out_tracked_querysets_from_every_manager():
    """``update()``, ``bulk_create()`` and ``bulk_update()`` are recorded only through these."""
    problems = []
    for tracked in tracked_models():
        if tracked.model._meta.app_label not in OWN_APPS or tracked.model._meta.auto_created:
            continue
        for manager in tracked.model._meta.managers:
            if not isinstance(manager.get_queryset(), TrackedQuerySet):
                problems.append(f"{tracked.label}.{manager.name}")
    assert problems == []


def test_the_framework_models_and_the_membership_tables_are_tracked():
    for label in FRAMEWORK_MODELS:
        assert tracked_for(apps.get_model(label)) is not None, label
    for through in (User.groups.through, Group.permissions.through, Note.viewers.through, Past.viewers.through):
        assert tracked_for(through) is not None, through
    assert tracked_for(Permission) is not None


def test_a_snapshot_never_holds_a_password():
    assert "password" not in tracked_for(User).attnames
    assert "id" in tracked_for(User).attnames
