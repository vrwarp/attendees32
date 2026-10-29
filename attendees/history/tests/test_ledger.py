"""The seal: what the verifier catches, what the anchors add, and what gets mailed."""
import pytest
from django.contrib.auth.models import Group
from django.core import mail
from django.db import connection
from django.utils import timezone

from attendees.history import events_for, ledger
from attendees.history.canonical import mac_for
from attendees.history.models import HistoryAudit, HistoryEvent, HistoryHead

pytestmark = pytest.mark.django_db


@pytest.fixture
def anchor_file(tmp_path, settings):
    path = tmp_path / "history-anchors.txt"
    settings.HISTORY_ANCHOR_FILE = str(path)
    return path


def groups(count=3, prefix="Group"):
    return [Group.objects.create(name=f"{prefix} {number}") for number in range(count)]


def forge(event, **changes):
    HistoryEvent.objects.filter(pk=event.pk).update(snapshot={**event.snapshot, **changes})


def test_a_clean_history_verifies_and_the_run_is_kept():
    groups()
    audit = ledger.verify(full=True)
    assert audit.ok, audit.report
    assert audit.full and audit.events == HistoryEvent.objects.count()
    assert audit.head_seq == HistoryHead.objects.get(pk=1).seq
    assert HistoryAudit.objects.filter(pk=audit.pk, ok=True).exists()


def test_an_edited_event_no_longer_recomputes():
    first, _second = groups(2)
    target = events_for(first).get()
    forge(target, name="Forged")
    audit = ledger.verify(full=False)
    assert not audit.ok
    assert audit.first_bad_seq == target.seq
    assert "mac does not recompute" in audit.report


def test_a_deleted_event_leaves_a_gap():
    _first, middle, _last = groups(3)
    gone = events_for(middle).get()
    HistoryEvent.objects.filter(pk=gone.pk).delete()
    audit = ledger.verify(full=False)
    assert not audit.ok
    assert audit.first_bad_seq == gone.seq + 1
    assert "gap in seq" in audit.report


def test_a_forged_event_breaks_the_chain():
    groups(1)
    head = HistoryHead.objects.get(pk=1)
    HistoryEvent.objects.create(
        seq=head.seq + 1, model="auth.group", object_id="999", label="snapshot", created_at=timezone.now(),
        snapshot={"id": 999, "name": "Ghost"}, prev_mac=head.mac, mac="f" * 64,
    )
    audit = ledger.verify(full=False)
    assert not audit.ok
    assert audit.first_bad_seq == head.seq + 1
    assert "mac does not recompute" in audit.report


def test_removing_the_newest_events_is_caught_by_the_head():
    groups(2)
    newest = HistoryEvent.objects.order_by("-seq").first()
    HistoryEvent.objects.filter(pk=newest.pk).delete()
    audit = ledger.verify(full=False)
    assert not audit.ok
    assert "newest events differ from the head" in audit.report


def test_an_anchor_catches_a_chain_rewritten_by_someone_holding_the_key(anchor_file):
    first, _second, _third = groups(3)
    line = ledger.anchor(send=False)
    assert anchor_file.read_text().strip() == line
    # Rewrite the chain consistently from one event on, as someone with the key could.
    target = events_for(first).get()
    previous = target.prev_mac
    for event in HistoryEvent.objects.filter(seq__gte=target.seq).order_by("seq"):
        snapshot = {**event.snapshot, "name": "Forged"} if event.seq == target.seq else event.snapshot
        mac = mac_for(previous, event.model, event.object_id, event.label, event.created_at, snapshot)
        HistoryEvent.objects.filter(pk=event.pk).update(snapshot=snapshot, prev_mac=previous, mac=mac)
        previous = mac
    HistoryHead.objects.filter(pk=1).update(mac=previous)

    audit = ledger.verify(full=False)
    assert not audit.ok
    assert "anchored event's mac is not the anchor's" in audit.report
    # Without the anchor the rewritten chain would pass.
    anchor_file.unlink()
    assert ledger.verify(full=False).ok


def test_a_failed_verification_is_mailed_with_the_first_bad_event(settings):
    settings.HISTORY_AUDIT_RECIPIENTS = ["owner@example.com"]
    (group,) = groups(1)
    target = events_for(group).get()
    forge(target, name="Forged")
    ledger.verify(full=False)
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["owner@example.com"]
    assert "FAILED" in mail.outbox[0].subject
    assert f"#{target.seq}" in mail.outbox[0].body


def test_an_incremental_check_starts_where_the_last_clean_one_ended():
    groups(1)
    assert ledger.verify(full=False).ok
    oldest = HistoryEvent.objects.order_by("seq").first()
    groups(1, prefix="Later")
    forge(oldest, forged=True)
    assert ledger.verify(full=False).ok  # only the events since the clean run are walked
    assert not ledger.verify(full=True).ok


def test_the_anchor_is_mailed_to_the_officers(settings, anchor_file):
    settings.HISTORY_ANCHOR_RECIPIENTS = ["chair@example.com", "clerk@example.com"]
    groups(1)
    line = ledger.anchor()
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["chair@example.com", "clerk@example.com"]
    assert mail.outbox[0].subject.startswith("History anchor")
    assert line in mail.outbox[0].body


def test_a_full_verification_includes_the_replay_against_the_live_tables():
    (group,) = groups(1)
    with connection.cursor() as cursor:
        cursor.execute("UPDATE auth_group SET name = %s WHERE id = %s", ["Sneaky", group.pk])
    audit = ledger.verify(full=True)
    assert not audit.ok
    assert "auth.group: the replay differs from the live table: 0 missing, 0 unrecorded, 1 changed" in audit.report
