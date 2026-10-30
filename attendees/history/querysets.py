"""Querysets and managers whose bulk writes reach the history.

Signals never fire for ``update()``, ``bulk_create()`` and ``bulk_update()``,
so a tracked model's managers hand out these querysets, which record one
event per row they touched. ``Tracked`` and ``TrackedSoftDeletable`` are
the abstract bases a model lists first to get the managers; ``User`` and
``Menu`` build theirs from the managers their frameworks require.
"""
from django.contrib.auth.models import UserManager
from django.db import connections, models, transaction
from model_utils.managers import SoftDeletableManagerMixin, SoftDeletableQuerySetMixin
from mptt.managers import TreeManager


class TrackedQuerySet(models.QuerySet):
    def update(self, **kwargs):
        """Lock the matching rows, change them, then record each as it now stands."""
        from .tracking import record_rows

        with transaction.atomic(using=self.db, savepoint=False):
            locked = self.select_for_update(of=("self",)) if connections[self.db].features.has_select_for_update_of else self.select_for_update()
            pks = list(locked.values_list("pk", flat=True))
            if not pks:
                return 0
            count = models.QuerySet.update(self.model._base_manager.using(self.db).filter(pk__in=pks), **kwargs)
            record_rows(self.model, pks, using=self.db)
            return count

    update.alters_data = True

    def bulk_create(self, objs, *args, **kwargs):
        from .tracking import record_rows

        created = super().bulk_create(objs, *args, **kwargs)
        pks = [obj.pk for obj in created if obj.pk is not None]
        if pks:
            record_rows(self.model, pks, using=self.db, created=True)
        return created

    bulk_create.alters_data = True

    def bulk_update(self, objs, fields, *args, **kwargs):
        from .tracking import record_rows

        count = super().bulk_update(objs, fields, *args, **kwargs)
        record_rows(self.model, [obj.pk for obj in objs if obj.pk is not None], using=self.db)
        return count

    bulk_update.alters_data = True


class TrackedSoftDeletableQuerySet(SoftDeletableQuerySetMixin, TrackedQuerySet):
    """Soft deletes are an ``update(is_removed=True)``, so they are recorded too."""


class TrackedManager(models.Manager.from_queryset(TrackedQuerySet)):
    pass


class TrackedSoftDeletableManager(SoftDeletableManagerMixin, TrackedManager):
    _queryset_class = TrackedSoftDeletableQuerySet


class TrackedUserManager(UserManager.from_queryset(TrackedQuerySet)):
    """``User.objects``: Django's user manager (``create_user`` and friends) over the tracked queryset."""


class TrackedTreeManager(TreeManager.from_queryset(TrackedQuerySet)):
    """``Menu.objects``: mptt's tree manager over the tracked queryset."""


class Tracked(models.Model):
    """A tracked model with the plain manager."""

    objects = TrackedManager()

    class Meta:
        abstract = True


class TrackedSoftDeletable(models.Model):
    """A tracked model with model_utils' three soft-delete managers, listed first among the bases."""

    objects = TrackedSoftDeletableManager()
    available_objects = TrackedSoftDeletableManager()
    all_objects = TrackedManager()

    class Meta:
        abstract = True
