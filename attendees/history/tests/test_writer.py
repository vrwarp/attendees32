"""Every write lands as an event: saves, deletes, bulk writes and memberships."""
import pytest
from django.contrib.auth.models import Group

from attendees.history import events_for
from attendees.history.canonical import GENESIS, mac_for
from attendees.history.models import HistoryEvent, HistoryHead
from attendees.history.querysets import TrackedQuerySet
from attendees.persons.models import Attendee, Category, Relation
from attendees.persons.models.enum import GenderEnum

pytestmark = pytest.mark.django_db


class TestSaves:
    def test_a_creation_is_one_snapshot_of_the_whole_record(self, division, make_attendee):
        attendee = make_attendee()
        events = list(events_for(attendee))
        assert [event.label for event in events] == ["snapshot"]
        event = events[0]
        assert event.model == "persons.attendee" and event.object_id == str(attendee.pk)
        assert event.snapshot["first_name"] == "Grace"
        assert event.snapshot["division_id"] == division.pk  # foreign keys as ids
        assert isinstance(event.snapshot["created"], str)  # dates as text
        assert event.instance.division == division

    def test_a_save_that_changes_nothing_records_nothing(self):
        group = Group.objects.create(name="Choir")
        group.save()
        group.save()
        assert events_for(group).count() == 1

    def test_a_timestamped_model_records_every_save_because_modified_moves(self, make_attendee):
        attendee = make_attendee()
        attendee.save()
        assert events_for(attendee).count() == 2

    def test_a_change_records_the_row_as_the_database_holds_it(self, make_attendee):
        attendee = make_attendee()
        attendee.first_name = "Amazing"
        attendee.save(update_fields=["first_name"])
        latest = events_for(attendee).last()
        assert latest.snapshot["first_name"] == "Amazing"
        assert latest.snapshot["last_name"] == "Chen"  # the rest of the row is there too
        changes = latest.changes()
        assert changes["first_name"] == ("Grace", "Amazing")
        assert "last_name" not in changes

    def test_a_soft_delete_is_a_snapshot_and_a_hard_delete_keeps_the_record(self, make_attendee):
        attendee = make_attendee()
        attendee.delete()
        assert events_for(attendee).last().label == "snapshot"
        assert events_for(attendee).last().snapshot["is_removed"] is True
        key = attendee.pk
        attendee.delete(soft=False)
        last = HistoryEvent.objects.filter(model="persons.attendee", object_id=str(key)).order_by("seq").last()
        assert last.label == "before_delete" and last.snapshot["first_name"] == "Grace"
        assert not Attendee.all_objects.filter(pk=key).exists()

    def test_the_password_stays_out_of_a_users_events(self, django_user_model):
        user = django_user_model.objects.create_user(username="pat", email="pat@example.com", password="secret-pw")
        assert "password" not in events_for(user).get().snapshot
        assert events_for(user).get().snapshot["username"] == "pat"


class TestBulkWrites:
    def test_update_records_each_row_it_changed(self, make_attendee):
        grace, bob = make_attendee(), make_attendee(first_name="Bob")
        count = Attendee.objects.filter(pk__in=[grace.pk, bob.pk]).update(last_name="Lin")
        assert count == 2
        for attendee in (grace, bob):
            assert events_for(attendee).count() == 2
            assert events_for(attendee).last().snapshot["last_name"] == "Lin"
        Attendee.objects.filter(pk=grace.pk).update(last_name="Lin")  # nothing changes, nothing recorded
        assert events_for(grace).count() == 2

    def test_bulk_create_and_bulk_update_are_recorded(self):
        usher, greeter = Category.objects.bulk_create([Category(display_name="Usher"), Category(display_name="Greeter")])
        assert [event.label for event in events_for(usher)] == ["snapshot"]
        assert events_for(greeter).get().snapshot["display_name"] == "Greeter"
        usher.display_name = "Usher team"
        Category.objects.bulk_update([usher, greeter], ["display_name"])
        assert events_for(usher).last().snapshot["display_name"] == "Usher team"
        assert events_for(greeter).count() == 1

    def test_a_soft_delete_through_the_queryset_is_recorded(self, make_attendee):
        attendee = make_attendee()
        Attendee.objects.filter(pk=attendee.pk).delete()
        last = events_for(attendee).last()
        assert last.label == "snapshot" and last.snapshot["is_removed"] is True
        Attendee.all_objects.filter(pk=attendee.pk).delete()
        assert HistoryEvent.objects.filter(model="persons.attendee", object_id=str(attendee.pk)).order_by("seq").last().label == "before_delete"

    def test_the_managers_and_related_managers_hand_out_the_tracked_queryset(self, make_attendee):
        attendee = make_attendee()
        assert isinstance(Attendee.objects.all(), TrackedQuerySet)
        assert isinstance(Attendee.all_objects.all(), TrackedQuerySet)
        assert isinstance(Attendee.available_objects.all(), TrackedQuerySet)
        assert isinstance(attendee.folks.all(), TrackedQuerySet)
        assert isinstance(attendee.division.organization.division_set.all(), TrackedQuerySet)


class TestMemberships:
    def test_adding_and_removing_a_scheduler_is_recorded_on_the_link_row(self, make_attendee):
        grace, bob = make_attendee(), make_attendee(first_name="Bob")
        grace.schedulers.add(bob)
        link = grace.schedulers.through.objects.get(attendee=grace, scheduler=bob)
        events = HistoryEvent.objects.filter(model="persons.attendeescheduler", object_id=str(link.pk))
        assert [event.label for event in events] == ["snapshot"]
        assert events.get().snapshot == {"id": link.pk, "attendee_id": str(grace.pk), "scheduler_id": str(bob.pk)}
        grace.schedulers.remove(bob)
        assert [event.label for event in events.order_by("seq")] == ["snapshot", "before_delete"]

    def test_an_auto_made_membership_table_is_tracked_too(self, django_user_model):
        user = django_user_model.objects.create_user(username="pat", email="pat@example.com", password="pw")
        group = Group.objects.create(name="Ushers")
        user.groups.add(group)
        link = user.groups.through.objects.get(user=user, group=group)
        events = HistoryEvent.objects.filter(model="users.user_groups", object_id=str(link.pk))
        assert events.get().snapshot == {"id": link.pk, "user_id": user.pk, "group_id": group.pk}
        user.groups.clear()
        assert [event.label for event in events.order_by("seq")] == ["snapshot", "before_delete"]

    def test_a_membership_added_from_the_other_side_is_recorded(self, django_user_model):
        user = django_user_model.objects.create_user(username="pat", email="pat@example.com", password="pw")
        group = Group.objects.create(name="Ushers")
        group.user_set.add(user)
        link = user.groups.through.objects.get(user=user, group=group)
        assert HistoryEvent.objects.filter(model="users.user_groups", object_id=str(link.pk)).count() == 1

    def test_reciprocal_relations_record_each_direction_added(self):
        father = Relation.objects.create(title="father", gender=GenderEnum.MALE.value)
        son = Relation.objects.create(title="son", gender=GenderEnum.MALE.value)
        father.reciprocals.add(son)
        son.reciprocals.add(father)
        rows = Relation.reciprocals.through.objects.all()
        assert rows.count() == 2
        for row in rows:
            assert HistoryEvent.objects.filter(model="persons.relation_reciprocals", object_id=str(row.pk)).count() == 1


class TestChain:
    def test_every_event_seals_the_one_before_it_and_the_head_follows(self, make_attendee):
        make_attendee()
        events = list(HistoryEvent.objects.order_by("seq"))
        assert events
        previous = GENESIS
        expected_seq = 0
        for event in events:
            expected_seq += 1
            assert event.seq == expected_seq
            assert event.prev_mac == previous
            assert event.mac == mac_for(previous, event.model, event.object_id, event.label, event.created_at, event.snapshot)
            previous = event.mac
        head = HistoryHead.objects.get(pk=1)
        assert (head.seq, head.mac) == (events[-1].seq, events[-1].mac)

    def test_a_batch_shares_one_context_and_consecutive_seqs(self):
        before = HistoryHead.objects.get(pk=1).seq
        Category.objects.bulk_create([Category(display_name=f"Team {n}") for n in range(3)])
        events = list(HistoryEvent.objects.filter(seq__gt=before).order_by("seq"))
        assert [event.seq - before for event in events] == [1, 2, 3]
        assert len({event.context_id for event in events}) == 1
