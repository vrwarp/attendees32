"""Reading and writing baptized/believer, which are rows rather than columns.

attendees32 does not store these on the attendee. It stores a ``Past`` row of a
particular ``Category``, and the seed data spells the correspondence out in
``Organization.infos["settings"]["past_category_to_attendingmeet_meet"]``:

    {"4": 17, "5": 16, "19": 0, "21": 27, "37": 9}

Category 5 (*baptized*) drives Meet 16 (已受洗 baptized), and Category 4
(*receive*) drives Meet 17 (已信主 believer). So writing a ``Past`` is the
correct way in: the existing ``post_save`` signal in ``persons/signals.py``
creates the matching ``AttendingMeet`` exactly as it does when a coworker adds
the status by hand.

That signal has an escape hatch -- it skips when the past's comment contains
"importer" -- and this module deliberately does **not** use it. Suppressing the
signal would also suppress the ``Attending`` the mapping depends on, and would
make a synced status behave differently from a typed one for no reason anybody
could later reconstruct.
"""

from django.contrib.contenttypes.models import ContentType

from attendees.persons.models import Category, Past, Utility
from attendees.pcosync.mapping import CONTRADICTORY

#: Written into Past.infos["comment"] so a sync-created row is identifiable
#: later. Chosen not to contain "importer", which would trip the signal's skip.
SYNC_COMMENT = "created by the Planning Center sync"


def attendee_content_type():
    from attendees.persons.models import Attendee

    return ContentType.objects.get_for_model(Attendee)


def status_categories(config):
    """``{name: Category}`` for the three statuses this sync reads."""
    ids = {
        name: category_id
        for name, category_id in (config.status_category_ids or {}).items()
        if category_id is not None
    }
    found = Category.objects.filter(pk__in=ids.values())
    by_id = {category.id: category for category in found}
    return {
        name: by_id[int(category_id)]
        for name, category_id in ids.items()
        if int(category_id) in by_id
    }


def flags_for(attendee, config, categories=None):
    """Read baptized/believer as the tri-state the mapping expects.

    ``None`` means nobody wrote it down -- which is emphatically not the same as
    False. attendees32 has no way to record "not baptized" at all, so that field
    is only ever True or unknown.
    """
    categories = categories if categories is not None else status_categories(config)
    live = set(
        Past.objects.filter(
            content_type=attendee_content_type(),
            object_id=str(attendee.id),
            is_removed=False,
        ).values_list("category_id", flat=True)
    )
    return flags_from_category_ids(live, config)


def flags_from_category_ids(live_category_ids, config):
    """The pure half, so a caller can fetch every Past row in one query."""
    ids = config.status_category_ids or {}
    baptized_id = _as_int(ids.get("baptized"))
    believer_id = _as_int(ids.get("believer"))
    disbeliever_id = _as_int(ids.get("disbeliever"))
    live = {int(value) for value in live_category_ids if value is not None}

    flags = {}
    flags["baptized"] = True if baptized_id in live else None

    believes = believer_id in live
    disbelieves = disbeliever_id in live
    if believes and disbelieves:
        # The record contradicts itself. Comparing that against a boolean would
        # be meaningless, so it is reported and the field skipped both ways.
        flags["believer"] = CONTRADICTORY
    elif believes:
        flags["believer"] = True
    elif disbelieves:
        flags["believer"] = False
    else:
        flags["believer"] = None
    return flags


def apply_status(attendee, name, config, organization, categories=None):
    """Create the ``Past`` row for an affirmative status, once.

    Only ever creates. ``update=False`` means a row that already exists is left
    exactly as it is, including its ``when`` -- a date somebody entered by hand
    must not be flattened by a sync that does not know it.
    """
    categories = categories if categories is not None else status_categories(config)
    category = categories.get(name)
    if category is None:
        return None, False

    display_names = {"baptized": "已受洗 baptized", "believer": "已信主 believer"}
    return Utility.update_or_create_last(
        Past,
        update=False,
        filters={
            "organization": organization,
            "content_type": attendee_content_type(),
            "object_id": str(attendee.id),
            "category": category,
            "is_removed": False,
        },
        defaults={
            "display_name": display_names.get(name, name)[:50],
            # Planning Center's boolean carries no date, and inventing one would
            # be worse than leaving it for a person to fill in.
            "when": None,
            "infos": {**Utility.relationship_infos(), "comment": SYNC_COMMENT},
        },
    )


def _as_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
