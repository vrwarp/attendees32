"""
The Tally integration's lifecycle: what it is made of, what it wrote, and
taking it down again.

Two different things live here. The *connection* is the group, user, token,
privilege grants and division that ``setup_tally_integration`` makes; it is
small, and a backup of it is a short JSON file. The *records* are what Tally
wrote through the API: people, families and memberships. They are the
church's own data, and the one question asked about them is whose they are.

That question has an exact answer. The history context names the user behind every
tracked change (see users/authentication.py), so a record Tally made is one whose
first history event carries the integration user, and a record someone else
has touched since is one with a later event carrying another user. No marker
has to be left on the rows themselves.
"""
from django.contrib.auth.models import Group
from django.db import transaction
from django.utils import timezone
from rest_framework.authtoken.models import Token

from attendees.occasions.models import Meet
from attendees.persons.models import Attendee, Attending, Folk, FolkAttendee
from attendees.persons.models.attendee import AttendeesHistory
from attendees.persons.models.folk import FolksHistory
from attendees.persons.models.folk_attendee import FolkAttendeesHistory
from attendees.persons.services.merge_service import AttendeeMergeService
from attendees.users.models import User
from attendees.whereabouts.models import Division, Organization

PROVENANCE_KEY = "tally"
USERNAME = "tally-integration"
GROUP = "tally_integration"
PRIVILEGE_KEYS = ("groups_see_all_meets_attendees", "counselor")
BACKUP_FORMAT = "tally-integration-backup/1"
RECEIPT_FORMAT = "tally-integration-receipt/1"

# What Tally writes, and the history table that remembers who wrote it.
LEDGER = (
    ("attendees", Attendee, AttendeesHistory),
    ("folks", Folk, FolksHistory),
    ("folk_attendees", FolkAttendee, FolkAttendeesHistory),
)


class NoIntegration(Exception):
    """There is no integration user to work on."""


class TallyIntegrationService:
    @staticmethod
    def find(username=USERNAME):
        """The connection as it stands, or NoIntegration."""
        user = User.objects.filter(username=username).first()
        if user is None:
            raise NoIntegration(f"No user '{username}'. Was setup_tally_integration run?")
        attendee = Attendee.all_objects.filter(user=user).first()
        provenance = dict(((attendee.infos if attendee else None) or {}).get(PROVENANCE_KEY) or {})
        group_name = provenance.get("group") or GROUP
        division = None
        if provenance.get("division"):
            division = Division.all_objects.filter(slug=provenance["division"]).first()
        if division is None and attendee is not None:
            division = attendee.division
        return {
            "user": user,
            "attendee": attendee,
            "organization": user.organization,
            "group_name": group_name,
            "division": division,
            "token": Token.objects.filter(user=user).first(),
            "provenance": provenance,
        }

    @staticmethod
    def ledger(user):
        """
        Every record Tally made or changed, by table.

        ``made`` rows began with the integration user; ``others_since`` says
        whether anyone else has touched one since, which is what keeps it
        from being removed. ``changed`` rows are the church's own that Tally
        edited; they are listed and never removed.
        """
        ledger = {}
        for name, model, history in LEDGER:
            touched = set(
                history.objects.filter(pgh_context__metadata__user=user.pk).values_list("pgh_obj_id", flat=True)
            )
            events = history.objects.filter(pgh_obj_id__in=touched).order_by("pgh_obj_id", "pgh_id").values_list(
                "pgh_obj_id", "pgh_context__metadata", "pgh_created_at"
            )
            by_object = {}
            for obj_id, metadata, at in events:
                by_object.setdefault(obj_id, []).append(((metadata or {}).get("user"), at))
            live = {str(pk): removed for pk, removed in model.all_objects.filter(pk__in=touched).values_list("pk", "is_removed")}
            merged = set()
            if model is Attendee:
                merged = {str(pk) for pk in Attendee.all_objects.filter(pk__in=touched, merged_into__isnull=False).values_list("pk", flat=True)}
            made, changed = [], []
            for obj_id, trail in by_object.items():
                key = str(obj_id)
                if key not in live:
                    continue  # hard-deleted since; nothing to do or undo
                row = {
                    "id": key,
                    "first_at": trail[0][1].isoformat(),
                    "last_tally_at": max(at for who, at in trail if who == user.pk).isoformat(),
                    "removed": live[key],
                }
                if trail[0][0] == user.pk:
                    row["others_since"] = any(who != user.pk for who, _ in trail[1:])
                    if model is Attendee:
                        row["merged"] = key in merged
                    made.append(row)
                else:
                    changed.append(row)
            made.sort(key=lambda r: r["first_at"])
            changed.sort(key=lambda r: r["first_at"])
            ledger[name] = {"made": made, "changed": changed}
        return ledger

    @classmethod
    def backup(cls, username=USERNAME, with_token=False, now=None):
        found = cls.find(username)
        provenance = found["provenance"]
        return {
            "format": BACKUP_FORMAT,
            "at": (now or timezone.now()).isoformat(),
            "organization": found["organization"].slug if found["organization"] else None,
            "username": username,
            "group": found["group_name"],
            "division": found["division"].slug if found["division"] else None,
            "division_created": bool(provenance.get("division_created")),
            "readable_meets": list(provenance.get("readable_meets") or []),
            "attendee": str(found["attendee"].id) if found["attendee"] else None,
            "token": found["token"].key if (with_token and found["token"]) else None,
            "ledger": cls.ledger(found["user"]),
        }

    @classmethod
    def plan(cls, username=USERNAME, purge=False, unmerge=False):
        """What delete would do, without doing it: the ledger sorted into goes and stays."""
        backup = cls.backup(username, with_token=False)
        removed = {name: [] for name, *_ in LEDGER}
        kept = {name: [] for name, *_ in LEDGER}
        if purge:
            for name, *_ in LEDGER:
                for row in backup["ledger"][name]["made"]:
                    if row["others_since"]:
                        kept[name].append(row)
                    elif row.get("merged"):
                        # A merged-away record is a tombstone already; it goes
                        # only if its merge is undone first.
                        (removed if unmerge else kept)[name].append(row)
                    elif not row["removed"]:
                        removed[name].append(row)
            cls._keep_families_still_lived_in(removed, kept)
        return {"backup": backup, "removed": removed, "kept": kept}

    @staticmethod
    def _keep_families_still_lived_in(removed, kept):
        """A membership of a person who stays, and a family anyone still lives
        in, stay too: the people are what matter, not Tally's bookkeeping."""
        going_people = {row["id"] for row in removed["attendees"]}
        edges = {
            str(pk): (str(attendee_id), str(folk_id))
            for pk, attendee_id, folk_id in FolkAttendee.objects.filter(
                pk__in=[row["id"] for row in removed["folk_attendees"]]
            ).values_list("pk", "attendee_id", "folk_id")
        }
        still_going = []
        for row in removed["folk_attendees"]:
            attendee_id, _ = edges.get(row["id"], (None, None))
            if attendee_id is None or attendee_id in going_people:
                still_going.append(row)
            else:
                kept["folk_attendees"].append({**row, "in_use": True})
        removed["folk_attendees"] = still_going

        going_edges = {row["id"] for row in removed["folk_attendees"]}
        folks_going = []
        for row in removed["folks"]:
            lived_in = (
                FolkAttendee.objects.filter(folk_id=row["id"])
                .exclude(pk__in=going_edges)
                .exclude(attendee_id__in=going_people)
                .exists()
            )
            if lived_in:
                kept["folks"].append({**row, "in_use": True})
            else:
                folks_going.append(row)
        removed["folks"] = folks_going

    @classmethod
    @transaction.atomic
    def delete(cls, username=USERNAME, purge=False, unmerge=False, now=None):
        """
        Takes the connection down, and with ``purge`` the records Tally made
        that nobody else has touched. Returns a receipt that ``undo`` reads.
        """
        found = cls.find(username)
        user, attendee = found["user"], found["attendee"]
        at = now or timezone.now()
        plan = cls.plan(username, purge=purge, unmerge=unmerge)
        receipt = {
            "format": RECEIPT_FORMAT,
            "at": at.isoformat(),
            "backup": {**plan["backup"], "token": found["token"].key if found["token"] else None},
            "removed": {name: [] for name, *_ in LEDGER},
            "kept": plan["kept"],
            "attendings": [],
            "unmerged": [],
            "connection": {},
        }

        if purge:
            for row in plan["removed"]["attendees"]:
                person = Attendee.all_objects.get(pk=row["id"])
                if person.merged_into_id is not None:
                    AttendeeMergeService.unmerge(person)
                    person.refresh_from_db()
                    receipt["unmerged"].append(row["id"])
                for attending in Attending.objects.filter(attendee=person):
                    attending.delete()
                    receipt["attendings"].append(attending.id)
                person.delete()
                receipt["removed"]["attendees"].append(row["id"])
            for row in plan["removed"]["folk_attendees"]:
                FolkAttendee.all_objects.get(pk=row["id"]).delete()
                receipt["removed"]["folk_attendees"].append(row["id"])
            for row in plan["removed"]["folks"]:
                folk = Folk.all_objects.get(pk=row["id"])
                for edge in FolkAttendee.objects.filter(folk=folk):
                    edge.delete()
                    receipt["removed"]["folk_attendees"].append(str(edge.id))
                folk.delete()
                receipt["removed"]["folks"].append(row["id"])

        connection = receipt["connection"]
        if found["token"] is not None:
            connection["token"] = found["token"].key
            found["token"].delete()
        group = Group.objects.filter(name=found["group_name"]).first()
        if group is not None:
            user.groups.remove(group)
        user.is_active = False
        user.save(update_fields=["is_active"])

        organization = found["organization"]
        connection["privileges"] = []
        if organization is not None:
            infos = organization.infos or {}
            for key in PRIVILEGE_KEYS:
                names = infos.get(key) or []
                if found["group_name"] in names:
                    infos[key] = [name for name in names if name != found["group_name"]]
                    connection["privileges"].append(key)
            if connection["privileges"]:
                organization.infos = infos
                organization.save(update_fields=["infos"])

        connection["meets"] = []
        for slug in found["provenance"].get("readable_meets") or []:
            meet = Meet.objects.filter(slug=slug).first()
            if meet is None:
                continue
            allowed = meet.infos.get("allowed_groups") or []
            if found["group_name"] in allowed:
                meet.infos = {**meet.infos, "allowed_groups": [name for name in allowed if name != found["group_name"]]}
                meet.save(update_fields=["infos"])
                connection["meets"].append(slug)

        if attendee is not None and not attendee.is_removed:
            attendee.delete()
            connection["attendee"] = str(attendee.id)

        division = found["division"]
        connection["division_removed"] = False
        if (
            division is not None
            and found["provenance"].get("division_created")
            and not division.is_removed
            and not Attendee.objects.filter(division=division).exists()
        ):
            division.delete()
            connection["division_removed"] = True

        return receipt

    @classmethod
    @transaction.atomic
    def undo(cls, receipt):
        """Puts back what ``delete`` took: the connection, and the records it removed."""
        if receipt.get("format") != RECEIPT_FORMAT:
            raise ValueError("Not a delete receipt.")
        backup, connection = receipt["backup"], receipt["connection"]

        user = User.objects.get(username=backup["username"])
        user.is_active = True
        user.save(update_fields=["is_active"])
        group, _ = Group.objects.get_or_create(name=backup["group"])
        user.groups.add(group)

        organization = Organization.objects.filter(slug=backup["organization"]).first()
        if organization is not None and connection.get("privileges"):
            infos = organization.infos or {}
            for key in connection["privileges"]:
                names = infos.get(key) or []
                if backup["group"] not in names:
                    infos[key] = [*names, backup["group"]]
            organization.infos = infos
            organization.save(update_fields=["infos"])

        for slug in connection.get("meets") or []:
            meet = Meet.objects.filter(slug=slug).first()
            if meet is None:
                continue
            allowed = meet.infos.get("allowed_groups") or []
            if backup["group"] not in allowed:
                meet.infos = {**meet.infos, "allowed_groups": [*allowed, backup["group"]]}
                meet.save(update_fields=["infos"])

        if connection.get("division_removed") and backup.get("division"):
            Division.all_objects.filter(slug=backup["division"]).update(is_removed=False)
        if connection.get("attendee"):
            Attendee.all_objects.filter(pk=connection["attendee"]).update(is_removed=False)

        if connection.get("token"):
            Token.objects.filter(user=user).delete()
            Token.objects.create(user=user, key=connection["token"])

        for name, model, _ in LEDGER:
            ids = receipt["removed"].get(name) or []
            if ids:
                model.all_objects.filter(pk__in=ids).update(is_removed=False)
        if receipt.get("attendings"):
            Attending.all_objects.filter(pk__in=receipt["attendings"]).update(is_removed=False)
        # A merge that was undone to remove a record stays undone: both records
        # are back, as two people, which is the honest state to leave them in.
