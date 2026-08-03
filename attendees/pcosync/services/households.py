"""Families, which are the widest thing this sync touches.

A Planning Center ``Household`` corresponds to a ``Folk`` of the family
category, and a ``HouseholdMembership`` to a ``FolkAttendee``. Two things make
this harder than the person mapping:

**There is no join key.** People carry ``attendees_uuid``; households carry
nothing, because Planning Center has no custom-field tab for them. So
``PcoHouseholdLink`` *is* the key, and the only honest way to create a row is
co-membership. This module links a household to a family only when their
linkable members match **exactly**. A join that is wrong by one person quietly
merges two families' directory entries, and the directory is printed and posted
to people; that is not a mistake worth risking to save somebody a click.

**Memberships are never removed.** ``FolkAttendee`` carries ``start``/``finish``
dates and a soft delete, removing somebody from a family has consequences for
the directory and for attendance, and an upstream removal is at least as often
a mistake as an intention. So a membership that vanished on one side is
reported, never applied -- the household form of "a sync does not clear".

One API shape to know: ``HouseholdMembership`` is 404 at the top level and is
not includable from ``/people``. It has to be fetched per household, and the
membership records that come back carry no reference to the household they came
from, so the caller stamps it on.
"""

import logging

from django.db import transaction

from attendees.pcosync.mapping import trimmed
from attendees.pcosync.models import PcoDivergence, PcoHouseholdLink, PcoPersonLink
from attendees.persons.models import Attendee, Category, Folk, FolkAttendee, Relation

logger = logging.getLogger(__name__)

FAMILY_CATEGORY_ID = Attendee.FAMILY_CATEGORY  # 0
#: Roles that exist for the app's own bookkeeping. Never written from Planning
#: Center, and never read as a role to push back.
INTERNAL_RELATION_IDS = {0, -1}


def fetch_memberships(client, household_id):
    """One request per household, with the household id stamped on.

    The membership records come back describing a person and a role and nothing
    else, so without this the caller cannot tell which household answered.
    """
    memberships = []
    for record in client.paginate_records(
        f"/households/{household_id}/household_memberships",
        {"include": ["person"]}, per_page=100,
    ):
        attributes = record.get("attributes") or {}
        person_id = attributes.get("person_id")
        if not person_id:
            person = ((record.get("relationships") or {}).get("person")
                      or {}).get("data") or {}
            person_id = person.get("id")
        if not person_id:
            continue
        memberships.append({
            "id": str(record.get("id")),
            "household_id": str(household_id),
            "person_id": str(person_id),
            "role": attributes.get("household_role"),
            "pending": bool(attributes.get("pending")),
        })
    return memberships


def linkable_members(organization, memberships):
    """``{pco_person_id: (attendee, role)}`` for members we can place locally.

    People with no link are dropped, which is what makes the exact-match test
    below fair: a household containing somebody attendees32 has never heard of
    should still be able to match the family it obviously is.
    """
    person_ids = [m["person_id"] for m in memberships]
    links = PcoPersonLink.objects.filter(
        organization=organization, pco_person_id__in=person_ids,
        is_removed=False, attendee__isnull=False,
    ).select_related("attendee")
    by_person = {link.pco_person_id: link.attendee for link in links}
    return {
        m["person_id"]: (by_person[m["person_id"]], m["role"])
        for m in memberships
        if m["person_id"] in by_person
    }


def candidate_folks(attendees):
    """Families any of these attendees already belong to."""
    return Folk.objects.filter(
        category_id=FAMILY_CATEGORY_ID,
        is_removed=False,
        folkattendee__attendee__in=attendees,
        folkattendee__is_removed=False,
    ).distinct()


def match_folk(organization, members):
    """Find the one family whose members are exactly these, or nothing.

    Returns ``(folk, reason)``. A reason without a folk is something to report.
    """
    if not members:
        return None, "no member of this household is linked to an attendee"

    attendees = [attendee for attendee, _ in members.values()]
    wanted = {attendee.id for attendee in attendees}

    exact = []
    for folk in candidate_folks(attendees):
        actual = set(
            FolkAttendee.objects.filter(folk=folk, is_removed=False)
            .values_list("attendee_id", flat=True)
        )
        if actual == wanted:
            exact.append(folk)

    if len(exact) == 1:
        return exact[0], None
    if len(exact) > 1:
        return None, (
            "more than one family has exactly these members, so which one this "
            "household is cannot be decided here"
        )
    return None, (
        "no family has exactly these members; linking on a partial overlap "
        "would risk merging two families"
    )


def relation_for(role, config):
    relation_id = (config.household_role_to_relation_id or {}).get(role)
    if relation_id is None:
        return None
    if int(relation_id) in INTERNAL_RELATION_IDS:
        return None
    return Relation.objects.filter(pk=relation_id).first()


def role_for(relation_id, config):
    """The Planning Center role for a local relation, or None if internal."""
    if relation_id is None or int(relation_id) in INTERNAL_RELATION_IDS:
        return None
    return config.relation_id_to_household_role.get(int(relation_id))


def local_members(folk):
    """``{attendee_id: relation_id}`` for a family's live memberships."""
    return {
        str(attendee_id): relation_id
        for attendee_id, relation_id in FolkAttendee.objects.filter(
            folk=folk, is_removed=False
        ).values_list("attendee_id", "role_id")
    }


def add_membership(folk, attendee, relation):
    """Add somebody to a family, reviving a soft-deleted row if there is one.

    ``FolkAttendee.objects`` hides ``is_removed=True`` while the unique
    constraint is conditional on it, so a plain ``create()`` after a soft delete
    succeeds and leaves two rows for one person. Reviving keeps the row's
    history, which is the point of a soft delete.
    """
    existing = FolkAttendee.all_objects.filter(folk=folk, attendee=attendee).first()
    if existing is not None:
        if existing.is_removed:
            existing.is_removed = False
            if relation is not None:
                existing.role = relation
            existing.save()
            return existing, True
        if relation is not None and existing.role_id != relation.id:
            existing.role = relation
            existing.save()
        return existing, False

    highest = FolkAttendee.objects.filter(folk=folk).count()
    return FolkAttendee.objects.create(
        folk=folk, attendee=attendee,
        role=relation or Relation.objects.filter(pk=0).first(),
        display_order=highest + 1,
    ), True


class HouseholdSync:
    """Links households and merges their membership sets."""

    def __init__(self, runner):
        self.runner = runner
        self.organization = runner.organization
        self.config = runner.config
        self.client = runner.client
        self.recorder = runner.recorder
        self.run = runner.run

    def sync_household(self, household, memberships):
        household_id = str(household.get("id"))
        pointer = f"$.household[{household_id}]"
        members = linkable_members(self.organization, memberships)

        link = PcoHouseholdLink.objects.filter(
            organization=self.organization, pco_household_id=household_id,
            is_removed=False,
        ).first()

        if link is None or link.folk_id is None:
            folk, reason = match_folk(self.organization, members)
            if folk is None:
                self.recorder.record(
                    PcoDivergence.HOUSEHOLD_CONFLICT, f"{pointer}.members",
                    note=reason, severity=PcoDivergence.INFO,
                    label=trimmed((household.get("attributes") or {}).get("name"))
                    or f"household {household_id}",
                    pco_value=sorted(members),
                )
                self.run.bump("households_unmatched")
                return None
            link, _ = PcoHouseholdLink.objects.update_or_create(
                organization=self.organization, pco_household_id=household_id,
                is_removed=False,
                defaults={"folk": folk, "state": PcoHouseholdLink.LIVE},
            )
            self.run.bump("households_linked")

        self.merge_members(link, household, members)
        return link

    def merge_members(self, link, household, members):
        """Three-way over the member set, with removals reported not applied."""
        household_id = link.pco_household_id
        pointer = f"$.household[{household_id}]"
        baseline = dict((link.baseline or {}).get("members") or {})

        upstream = {
            person_id: role for person_id, (_, role) in members.items()
        }
        attendees_by_person = {
            person_id: attendee for person_id, (attendee, _) in members.items()
        }

        local_by_attendee = local_members(link.folk)
        # Resolve the family's own members through their person links, not
        # through the upstream membership list. Deriving it from what Planning
        # Center currently returns makes anyone it has dropped invisible here --
        # which is precisely the case the removal report exists to catch.
        local_person_ids = set(
            PcoPersonLink.objects.filter(
                organization=self.organization,
                attendee_id__in=list(local_by_attendee),
                is_removed=False,
            ).values_list("pco_person_id", flat=True)
        )

        added_upstream = set(upstream) - local_person_ids
        removed_upstream = local_person_ids - set(upstream)

        for person_id in sorted(added_upstream):
            if person_id in baseline:
                # It was agreed, and attendees32 no longer has it: somebody
                # removed them here. Report it; do not put them back.
                self.report_removal(link, pointer, person_id, "attendees32")
                continue
            if not self.run.writes_locally:
                self.recorder.record(
                    PcoDivergence.WOULD_WRITE, f"{pointer}.members[{person_id}]",
                    note="would add this person to the family",
                    severity=PcoDivergence.INFO,
                    attendee=attendees_by_person[person_id],
                )
                self.run.bump("would_write")
                continue
            relation = relation_for(upstream[person_id], self.config)
            with transaction.atomic():
                add_membership(link.folk, attendees_by_person[person_id], relation)
            self.run.bump("household_members_added")

        for person_id in sorted(removed_upstream):
            if person_id in baseline:
                self.report_removal(link, pointer, person_id, "Planning Center")
            # Not in the baseline either: added locally since the last sync.
            # Pushing it is a create upstream, which this version does not do.

        link.baseline = {
            "name": trimmed((household.get("attributes") or {}).get("name")),
            "members": upstream,
        }
        link.baseline_synced_at = self.runner.now()
        link.save()

    def report_removal(self, link, pointer, person_id, side):
        self.recorder.record(
            PcoDivergence.HOUSEHOLD_MEMBERSHIP_REMOVED,
            f"{pointer}.members[{person_id}]",
            note=f"{side} no longer has this person in the family; a sync does "
                 f"not remove somebody from a household",
            severity=PcoDivergence.WARNING,
            pco_person_id=person_id,
        )
        self.run.bump("household_removals_reported")

    def sync_all(self, limit=None):
        count = 0
        for household in self.client.paginate_records("/households", per_page=100):
            if self.run.cancel_requested:
                break
            household_id = str(household.get("id"))
            try:
                memberships = fetch_memberships(self.client, household_id)
                self.sync_household(household, memberships)
            except Exception as exc:  # noqa: BLE001 - one family, not the run
                logger.exception("pcosync failed on household %s", household_id)
                self.recorder.record(
                    PcoDivergence.HOUSEHOLD_CONFLICT,
                    f"$.household[{household_id}]",
                    note=f"the sync failed on this household: {exc}",
                    severity=PcoDivergence.ERROR,
                )
                self.run.bump("errors")
            count += 1
            self.run.bump("households_seen")
            if limit and count >= limit:
                break
        return count


def ensure_family_category():
    """The family category must exist; ``on_delete=SET(0)`` assumes it."""
    return Category.objects.filter(pk=FAMILY_CATEGORY_ID).first()
