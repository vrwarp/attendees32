"""Merging one attendee into another, and following the trail afterwards.

Duplicates are made by people and cleaned up by people: two coworkers add the
same visiting child on the same Sunday, a registration form is filled twice, a
family is entered once by a parent and once at a door. Until now the only
answer here was to soft-delete one of them, which loses the association between
the two ids -- and an id that has been handed out does not stop existing
because a row was removed. Integrations hold it, labels are printed with it,
Planning Center's ``attendees_uuid`` custom field carries it into another
system entirely.

So a merge here does what Planning Center's does, and reports it the same way:
the loser's record survives as a tombstone carrying a forwarding address, its
attendance and family memberships move to the survivor, and the API answers
``410 Gone`` with ``merged_into`` for anybody who asks for the old id. What a
caller does with that is their business -- follow it, record it, or stop.

Two rules carry the weight:

1. **A merge never destroys.** The loser is soft-deleted, never removed, and
   its history rows stay where they are. A merge performed by mistake has to be
   answerable, and pghistory can only answer about rows that still exist.

2. **A chain is followed to its end, and a cycle is not an error.** Merges are
   sequential and people are not careful: A into B on Sunday, B into C on
   Wednesday. Anybody asking for A wants C. Corrupt data can point in a circle,
   and the answer to that is "gone", not a hung request.
"""

from django.db import transaction

from attendees.persons.models import Attendee, Attending, FolkAttendee, Registration

#: Long enough for any tidy-up a human performs, short enough to bound a cycle.
#: Planning Center's own merge-following in Tally uses the same number, and for
#: the same reason: five hops is already a story worth reading in a log.
MAX_MERGE_HOPS = 5


class MergeRefused(Exception):
    """A merge that must not be performed, with a sentence saying why."""


class AttendeeMergeService:
    @staticmethod
    def survivor_of(attendee):
        """Follows an attendee's forwarding address to whoever holds them now.

        Returns the attendee itself when it has not been merged, the terminal
        survivor when it has, and ``None`` when the trail ends nowhere -- a
        survivor that was later deleted outright, or a cycle in data somebody
        edited by hand. ``None`` is the honest answer to "who is this now?"
        when nobody is.
        """
        seen = {attendee.pk}
        current = attendee

        for _ in range(MAX_MERGE_HOPS):
            if current.merged_into_id is None:
                return current
            if current.merged_into_id in seen:
                return None
            seen.add(current.merged_into_id)
            # `all_objects`: a survivor may itself have been merged, and the
            # tombstone of a merged record is soft-deleted by definition.
            current = Attendee.all_objects.filter(pk=current.merged_into_id).first()
            if current is None:
                return None

        return None

    @staticmethod
    def resolve(attendee_id):
        """``survivor_of`` for an id rather than an instance.

        Returns ``(attendee, was_merged)``. ``attendee`` is ``None`` for an id
        nothing here has ever held, and for one whose trail ends nowhere.
        """
        held = Attendee.all_objects.filter(pk=attendee_id).first()
        if held is None:
            return None, False
        if held.merged_into_id is None:
            return (None, False) if held.is_removed else (held, False)

        survivor = AttendeeMergeService.survivor_of(held)
        if survivor is None or survivor.is_removed:
            return None, True
        return survivor, True

    @staticmethod
    @transaction.atomic
    def merge(loser, survivor):
        """Merges ``loser`` into ``survivor``, and returns the survivor.

        Refuses the three merges that are wrong rather than merely unusual: a
        record into itself, a record into one in another organization, and a
        record into one that is itself merged away. The last would build a
        chain nobody asked for -- the caller means the person, so they should
        be told to name the person rather than have a hop invented for them.
        """
        if loser.pk == survivor.pk:
            raise MergeRefused("An attendee cannot be merged into themselves.")

        if loser.division.organization_id != survivor.division.organization_id:
            raise MergeRefused(
                "Those two attendees belong to different organizations, so one "
                "cannot absorb the other."
            )

        if survivor.merged_into_id is not None:
            raise MergeRefused(
                "That survivor has itself been merged away. Merge into whoever "
                "holds the record now."
            )

        if loser.merged_into_id is not None:
            raise MergeRefused("That attendee has already been merged.")

        AttendeeMergeService._move_associations(loser, survivor)

        loser.merged_into = survivor
        loser.is_removed = True
        loser.save(update_fields=["merged_into", "is_removed"])

        return survivor

    @staticmethod
    def _move_associations(loser, survivor):
        """Carries the loser's participation and memberships over.

        A merge that only redirected an id would leave the duplicate's
        attendance behind, and the whole reason a coworker merges two records
        is that they are one child who was at one gathering.

        Both association tables carry a partial unique constraint keyed on the
        attendee -- ``(attendee, registration)`` and ``(folk, attendee)``,
        where ``is_removed=False`` -- so a row cannot always be moved: when the
        survivor already has a live one for the same registration or the same
        folk, the pair *is* the duplication being cleaned up. That row is
        soft-deleted rather than moved. Moving it would raise; skipping it
        without removing it would leave a live membership pointing at a
        tombstone.
        """
        for attending in Attending.objects.filter(attendee=loser):
            # `registration_id is None` is not a clash, because Postgres does
            # not consider two NULLs equal in a unique constraint — a pair of
            # registration-less attendings for one person is a thing the
            # database allows and this schema creates. Treating it as a
            # duplicate retired the loser's attendance instead of moving it,
            # which is the one outcome a merge must never produce.
            already = attending.registration_id is not None and Attending.objects.filter(
                attendee=survivor, registration_id=attending.registration_id
            ).exists()
            if already:
                attending.is_removed = True
                attending.save(update_fields=["is_removed"])
            else:
                attending.attendee = survivor
                attending.save(update_fields=["attendee"])

        for membership in FolkAttendee.objects.filter(attendee=loser):
            already = FolkAttendee.objects.filter(
                attendee=survivor, folk_id=membership.folk_id
            ).exists()
            if already:
                membership.is_removed = True
                membership.save(update_fields=["is_removed"])
            else:
                membership.attendee = survivor
                membership.save(update_fields=["attendee"])

        # Registrations name a registrant rather than belonging to one, and the
        # field is nullable precisely because that person can go away. Pointed
        # at the survivor so a form somebody filled in is still attributed.
        Registration.objects.filter(registrant=loser).update(registrant=survivor)
