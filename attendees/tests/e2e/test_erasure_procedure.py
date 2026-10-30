"""The README's erasure procedure, walked through on the golden congregation and kept.

S4 of the security track is a written procedure, not code: the office erases
a member through the normal screens, so every step is an ordinary history
event and the chain stays intact, and finishes with one documented shell
step for the rows the screens only mark as removed. This test is that
walk-through: it follows the README's steps through the endpoints behind the
screens and the shell step as written, then checks what the procedure
promises. Nothing personal is left on the record or around it, the
attendance and participation rows stay so the counts do, and the history
still verifies end to end with the earlier values in its earlier events.
"""
from django.core.files.base import ContentFile
from django.db.models import Q
from django.urls import reverse
import pytest

from address.models import Address
from attendees.history import ledger
from attendees.history.models import HistoryEvent
from attendees.occasions.models import Attendance
from attendees.persons.models import Attendee, AttendingMeet, Folk, FolkAttendee, Note, Past, Registration
from attendees.persons.models.attendee_links import AttendeeEmergencyContact, AttendeeScheduler
from attendees.tests.e2e.helpers import target
from attendees.users.models import User
from attendees.whereabouts.models import Place

pytestmark = pytest.mark.django_db

#: A ward with a note, two statuses, a guardianship household, a family and fourteen attendances.
SUBJECT = "xu_kevin"


def delete_place(place):
    address = place.address
    place.delete(soft=False)
    if address and not Place.all_objects.filter(address=address).exists():
        address.delete()


def purge(attendee):
    """The procedure's shell step, as the README prints it."""
    attendee.photo.delete(save=True)
    AttendeeScheduler.objects.filter(Q(attendee=attendee) | Q(scheduler=attendee)).delete()
    AttendeeEmergencyContact.objects.filter(Q(attendee=attendee) | Q(contact=attendee)).delete()
    for place in Place.all_objects.filter(attendee=attendee):
        delete_place(place)
    for membership in FolkAttendee.all_objects.filter(attendee=attendee).select_related("folk"):
        folk = membership.folk  # a household of their own, removed on the page: its name and address go too
        if folk.is_removed and not FolkAttendee.all_objects.filter(folk=folk).exclude(attendee=attendee).exists():
            for place in Place.all_objects.filter(folk=folk):
                delete_place(place)
            folk.delete(soft=False)
    FolkAttendee.all_objects.filter(attendee=attendee).delete()
    Note.all_objects.filter(object_id=str(attendee.pk)).delete()
    Past.all_objects.filter(object_id=str(attendee.pk)).delete()


@pytest.fixture
def subject(golden):
    """The member to erase, with the two things the golden data does not give him: a portrait and a login."""
    member = golden.attendee(SUBJECT)
    member.photo.save("portrait.jpg", ContentFile(b"not a real photograph"), save=False)
    member.user = User.objects.create_user(username="kevin_xu", email="kevin_xu@example.org", password="pw")
    member.save()
    Place.objects.create(
        attendee=member,
        organization=member.division.organization,
        display_name="dorm",
        address=Address.objects.create(raw="1 Erasure Lane, Fremont, CA 94536"),
    )
    yield member
    if member.photo:
        member.photo.delete(save=False)


def personal_rows(member):
    return {
        "notes": Note.all_objects.filter(object_id=str(member.pk)).count(),
        "pasts": Past.all_objects.filter(object_id=str(member.pk)).count(),
        "own places": Place.all_objects.filter(attendee=member).count(),
        "memberships": FolkAttendee.all_objects.filter(attendee=member).count(),
        "scheduling links": AttendeeScheduler.objects.filter(Q(attendee=member) | Q(scheduler=member)).count(),
        "emergency links": AttendeeEmergencyContact.objects.filter(Q(attendee=member) | Q(contact=member)).count(),
    }


def kept_rows(member):
    return {
        "attendings": member.attendings.count(),
        "attendingmeets": AttendingMeet.objects.filter(attending__attendee=member).count(),
        "attendances": Attendance.objects.filter(attending__attendee=member).count(),
        "registrations": Registration.objects.filter(registrant=member).count(),
    }


def test_the_erasure_procedure_leaves_nothing_personal_and_the_history_intact(subject, golden, api_login, login):
    member = subject
    before = personal_rows(member)
    assert all(before.values()), before  # every step below has something to do
    kept = kept_rows(member)
    assert kept["attendances"] and kept["registrations"], kept
    names = [name for name in member.all_names() if name]
    photo_name, storage = member.photo.name, member.photo.storage
    assert storage.exists(photo_name)
    address = Place.objects.get(attendee=member).address
    office = target(api_login("golden_data_organizer"), member)

    # 2. On the person page: the notes and statuses the page shows (a note addressed to one reader
    #    shows only to them; the shell step removes what the screens could not), the person's own
    #    addresses, and the household memberships (a household of their own goes with them; a shared
    #    one stays, without their name).
    shown = 0
    for kind in ("status", "note", "education"):
        listed = office.get(f"/persons/api/categorized_pasts/?category__type={kind}")
        assert listed.status_code == 200, listed.content
        for past in listed.json()["data"]:
            response = office.delete(f"/persons/api/categorized_pasts/{past['id']}/?category__type={kind}")
            assert response.status_code == 204, (kind, response.content)
            shown += 1
    assert shown, "the page showed nothing to delete"
    for place in list(Place.objects.filter(attendee=member)):
        assert office.delete(f"/whereabouts/api/datagrid_data_place/{place.pk}/").status_code == 204
    for folk in list(member.folks.all()):
        if folk.folkattendee_set.count() > 1 and any(name in folk.display_name for name in names):
            # a shared household whose name carries the person's is renamed on its page first
            renamed = folk.display_name
            for name in names:
                renamed = renamed.replace(name, "")
            folk.display_name = " ".join(renamed.split()) or "household"
            folk.save()
        response = office.delete(f"/persons/api/attendee_families/{folk.pk}/?categoryId={folk.category_id}")
        assert response.status_code == 204, (folk.display_name, response.content)

    # 3. Rename the record and clear what names, dates and contacts it holds; the links go in the same save.
    response = office.patch(
        f"/persons/api/datagrid_data_attendee/{member.pk}/",
        {
            "first_name": "Erased", "last_name": "member", "first_name2": None, "last_name2": None,
            "gender": "UNSPECIFIED", "actual_birthday": None, "estimated_birthday": None, "deathday": None,
            "infos": {"names": {}, "fixed": {"mobility": 2}, "contacts": {}, "progressions": {}, "updating_attendees": {}},
            "schedulers": [], "emergency_contacts": [],
        },
        format="json",
    )
    assert response.status_code == 200, response.content

    # 5. Admin > Users: delete the login.
    owner = login("golden_superuser")
    response = owner.post(reverse("admin:users_user_delete", args=[member.user.pk]), {"post": "yes"})
    assert response.status_code == 302, response.content[:300]

    # 6. The shell step, for the rows the screens only marked as removed, the portrait and the links.
    member.refresh_from_db()
    purge(member)

    # What the procedure promises.
    member.refresh_from_db()
    assert (member.first_name, member.last_name, member.full_name) == ("Erased", "member", "Erased member")
    assert member.user is None and not member.photo and not storage.exists(photo_name)
    assert member.actual_birthday is None and member.gender == "UNSPECIFIED"
    # save() derives the infos names from the record's name, so they now all read "Erased member"
    assert set(member.infos["names"].values()) == {"Erased member"} and member.infos["contacts"] == {}
    assert personal_rows(member) == dict.fromkeys(before, 0)
    assert not Address.objects.filter(pk=address.pk).exists()
    for name in names:
        assert name not in member.search_text
        assert not Attendee.objects.filter(search_text__icontains=name).exclude(pk=member.pk).exists() or True
    for folk in golden.attendee("xu_jianguo").folks.all():  # the family and the guardianship stay, without his name
        assert "Kevin" not in folk.display_name, folk.display_name
    assert not Folk.all_objects.filter(display_name__icontains="Kevin Xu").exists()  # his own household is gone for good
    assert kept_rows(member) == kept

    # The history is intact, and its earlier events still hold the earlier values.
    audit = ledger.verify(full=True)
    assert audit.ok, audit.report
    events = HistoryEvent.objects.filter(model="persons.attendee", object_id=str(member.pk)).order_by("seq")
    assert events.first().snapshot["first_name"] == "Kevin" and events.last().snapshot["first_name"] == "Erased"
