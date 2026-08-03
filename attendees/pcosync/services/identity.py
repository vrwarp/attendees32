"""Deciding which attendee a Planning Center person is.

Three ways, in descending order of confidence, and only the first is a join:

1. The ``attendees_uuid`` custom field. Exact, and the reason that field exists.
2. An existing ``PcoPersonLink``, from a previous run or a human's choice.
3. A ranked guess, which is **reported and never acted on**. A person picks.

The uuid index is built by sweeping ``/field_data`` filtered to the one
definition, rather than by filtering ``/people``. That is not a style
preference: on ``/people`` each ``where[...]`` key compiles to its own
independent EXISTS, so asking for "a person with a datum of this definition and
a datum of this value" matches anyone who has both somewhere -- not necessarily
in the same datum. Reading the data directly has no such ambiguity, costs one
sweep, and gives the owner id straight off the relationship.
"""

import logging

from django.core.exceptions import ValidationError

from attendees.persons.models import Attendee
from attendees.pcosync.mapping import fold_name, trimmed
from attendees.pcosync.models import PcoPersonLink

logger = logging.getLogger(__name__)

#: Candidates offered per unmatched person. More than a handful is not a
#: shortlist, it is a search, and there is a search box for that.
MAX_SUGGESTIONS = 5


def build_uuid_index(client, definition_id):
    """``{attendees_uuid: pco_person_id}`` for the whole organization.

    One paginated sweep of the data for a single definition. At church scale
    that is a few requests, and it makes every identity lookup afterwards a
    dictionary hit rather than a request.
    """
    index = {}
    query = {"where": {"field_definition_id": definition_id}}
    for datum in client.paginate_records("/field_data", query, per_page=100):
        value = trimmed((datum.get("attributes") or {}).get("value"))
        if not value:
            continue
        customizable = (((datum.get("relationships") or {}).get("customizable")
                         or {}).get("data") or {})
        if customizable.get("type") != "Person":
            continue
        person_id = str(customizable.get("id") or "")
        if not person_id:
            continue
        if value in index and index[value] != person_id:
            # Two people claiming one attendee. Whoever wins here would be
            # arbitrary, so keep the first and let the caller report it.
            logger.warning("attendees_uuid %s claimed by people %s and %s",
                           value, index[value], person_id)
            continue
        index[value] = person_id
    return index


def attendee_for_uuid(value):
    """Look up by primary key, including soft-deleted rows.

    ``Attendee.objects`` hides ``is_removed=True``, so using it here would make
    a soft-deleted attendee invisible and the sync would cheerfully create a
    second one for somebody a coworker had deliberately removed. ``all_objects``
    sees them.

    The value comes from a text field upstream, so it may not be a UUID at all;
    a malformed one is an unmatched person, not an exception.
    """
    try:
        return Attendee.all_objects.filter(pk=value).first()
    except (ValueError, TypeError, ValidationError):
        return None


def existing_link(organization, pco_person_id):
    return PcoPersonLink.objects.filter(
        organization=organization, pco_person_id=str(pco_person_id),
        is_removed=False,
    ).first()


def link_for_attendee(organization, attendee):
    return PcoPersonLink.objects.filter(
        organization=organization, attendee=attendee,
        state=PcoPersonLink.LIVE, is_removed=False,
    ).first()


def ensure_link(organization, pco_person_id, attendee=None, source=None,
                state=None):
    """Create or update the link row for one Planning Center person."""
    link = existing_link(organization, pco_person_id)
    if link is None:
        return PcoPersonLink.objects.create(
            organization=organization,
            pco_person_id=str(pco_person_id),
            attendee=attendee,
            link_source=source or PcoPersonLink.BY_UUID,
            state=state or (PcoPersonLink.LIVE if attendee
                            else PcoPersonLink.UNCONFIRMED),
        ), True

    changed = False
    if attendee is not None and link.attendee_id != attendee.id:
        link.attendee = attendee
        changed = True
    if state and link.state != state:
        link.state = state
        changed = True
    elif attendee is not None and link.state == PcoPersonLink.UNCONFIRMED:
        link.state = PcoPersonLink.LIVE
        changed = True
    if source and link.link_source != source:
        link.link_source = source
        changed = True
    if changed:
        link.save()
    return link, False


def follow_merge(client, organization, link, error=None):
    """Repoint a link at the survivor of a merge, or mark it gone.

    The baseline is **reset** on a successful follow. It described a record that
    no longer exists; carrying it over would let the merge look like "only one
    side changed" and quietly overwrite the survivor's own values.

    A survivor that already belongs to a different attendee is not resolved
    here. Two local people are now one upstream, and only a human can say which.
    """
    survivor, resource = client.follow_person_link(link.pco_person_id,
                                                   from_error=error)
    if not survivor:
        link.state = PcoPersonLink.GONE
        link.save()
        return None, None, "gone"

    competing = PcoPersonLink.objects.filter(
        organization=organization, pco_person_id=str(survivor),
        state=PcoPersonLink.LIVE, is_removed=False,
    ).exclude(pk=link.pk).first()
    if competing and competing.attendee_id != link.attendee_id:
        return survivor, resource, "collision"

    link.merged_into_pco_id = link.pco_person_id
    link.pco_person_id = str(survivor)
    link.baseline = {}
    link.baseline_synced_at = None
    link.field_datum_ids = {}
    link.state = PcoPersonLink.LIVE if link.attendee_id \
        else PcoPersonLink.UNCONFIRMED
    link.save()
    return survivor, resource, "followed"


def suggest_matches(person_view, candidates, limit=MAX_SUGGESTIONS):
    """Rank local attendees that might be this Planning Center person.

    Deliberately advisory. Even a perfect score is offered rather than applied:
    siblings share surnames and birthdays, and a wrong automatic link is far
    more expensive to undo than an unanswered question is to answer.
    """
    from attendees.pcosync.mapping import (
        FIELDS_BY_KEY, canonical_birthday_from_pco,
    )

    target = {
        "first": fold_name(person_view.attributes.get("first_name")),
        "last": fold_name(person_view.attributes.get("last_name")),
        "first2": fold_name(FIELDS_BY_KEY["first_name2"].read_pco(person_view)),
        "last2": fold_name(FIELDS_BY_KEY["last_name2"].read_pco(person_view)),
        "birthday": canonical_birthday_from_pco(
            person_view.attributes.get("birthdate")
        ),
    }

    scored = []
    for attendee, birthday in candidates:
        score = 0
        if target["last"] and fold_name(attendee.last_name) == target["last"]:
            score += 3
        if target["first"] and fold_name(attendee.first_name) == target["first"]:
            score += 3
        if target["last2"] and fold_name(attendee.last_name2) == target["last2"]:
            score += 3
        if target["first2"] and fold_name(attendee.first_name2) == target["first2"]:
            score += 3
        # A birthday alone proves nothing -- plenty of people share one -- but
        # alongside a name it is what separates a parent from their child.
        if target["birthday"] and birthday and target["birthday"] == birthday:
            score += 4
        if score <= 0:
            continue
        scored.append({
            "attendee_id": str(attendee.id),
            "display_label": attendee.display_label,
            "score": score,
        })

    scored.sort(key=lambda entry: (-entry["score"], entry["display_label"]))
    return scored[:limit]
