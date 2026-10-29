"""Keep pghistory 2.4's generated event models correct under Django 5.

pghistory builds each event model's fields by deep-copying the tracked model's fields and then
setting ``related_name`` to ``"+"`` (``pghistory.models._generate_history_field``). Since Django
5.1, ``ForeignObjectRel.hidden`` and ``accessor_name`` are cached properties, so a copy made after
the original field was used carries the original's cached values: the copy claims a visible
reverse accessor with the original's name. Django then reports fields.E304/E305 clashes for every
history model of a third-party table (schedule, allauth, auth, address, django-celery-beat) and
would install the history model's reverse descriptor over the real one.

The shim clears the cached values on the copied relation before the event model class is built,
so Django computes them from the ``"+"`` that pghistory set. It lives in a models module because
Django imports models in ``INSTALLED_APPS`` order: this app is listed before the apps that track
models, which is the first point at which pghistory can be imported and still precedes every event
model. Phase 5 of the portability plan removes pghistory, and this module with it.

This module defines no models.
"""
import functools

import pghistory.models
from django.db.models.fields.related import RelatedField
from django.utils.functional import cached_property

_generate_history_field = pghistory.models._generate_history_field


def _forget_cached_relation_state(relation):
    for klass in type(relation).__mro__:
        for name, attribute in vars(klass).items():
            if isinstance(attribute, (cached_property, functools.cached_property)):
                relation.__dict__.pop(name, None)


def _generate_history_field_with_fresh_relation(tracked_model, field):
    generated = _generate_history_field(tracked_model, field)
    if isinstance(generated, RelatedField):
        _forget_cached_relation_state(generated.remote_field)
    return generated


if pghistory.models._generate_history_field is _generate_history_field:
    pghistory.models._generate_history_field = _generate_history_field_with_fresh_relation
