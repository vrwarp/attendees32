"""The seal on the history: anchors kept where the database cannot reach them, and the verifier.

An anchor is the head of the chain (``seq``, ``mac``, time) appended to a
file on the encrypted volume and mailed to the officers. Someone who can
rewrite the table and holds the key can recompute a consistent chain, but
not the head that was already in two inboxes yesterday.
"""
import os

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

from . import replay
from .canonical import GENESIS, chain_key, mac_for
from .models import HistoryAudit, HistoryEvent, HistoryHead


def head(using=None):
    return HistoryHead.objects.using(using).filter(pk=1).first() or HistoryHead(seq=0, mac=GENESIS)


def anchor(using=None, send=True):
    """Record the head where the database cannot reach it; returns the anchor line."""
    current = head(using)
    now = timezone.now()
    line = f"{current.seq} {current.mac} {now.isoformat()}"
    path = getattr(settings, "HISTORY_ANCHOR_FILE", "")
    if path:
        with open(path, "a", encoding="utf-8") as anchors_file:
            anchors_file.write(line + "\n")
    recipients = getattr(settings, "HISTORY_ANCHOR_RECIPIENTS", [])
    if send and recipients:
        send_mail(
            subject=f"History anchor {current.seq}",
            message=(
                f"Head of the history chain at {now:%Y-%m-%d %H:%M} UTC:\n\n{line}\n\n"
                "Keep this message. The verifier compares the chain with the anchors, and this one is "
                "the proof that nothing before it was rewritten afterwards."
            ),
            from_email=None,
            recipient_list=list(recipients),
        )
    return line


def anchors():
    """``(seq, mac)`` pairs from the anchor file, oldest first; none when no file is configured."""
    path = getattr(settings, "HISTORY_ANCHOR_FILE", "")
    if not path or not os.path.exists(path):
        return []
    found = []
    with open(path, encoding="utf-8") as anchors_file:
        for line in anchors_file:
            parts = line.split()
            if len(parts) >= 2 and parts[0].isdigit():
                found.append((int(parts[0]), parts[1]))
    return found


def verify(full=True, using=None, compare=replay.compare):
    """Check the chain, the anchors and, when ``full``, the replay against the live tables.

    ``full`` walks every event; otherwise only those since the last clean
    run, chaining from the head that run recorded. The result is stored as
    a ``HistoryAudit`` and mailed to the data owner when something failed.
    """
    key = chain_key()
    problems = []
    first_bad = [None]

    def bad(seq, text):
        problems.append(f"#{seq}: {text}" if seq is not None else text)
        if seq is not None and (first_bad[0] is None or seq < first_bad[0]):
            first_bad[0] = seq

    start_seq, prev = 0, GENESIS
    if not full:
        last = HistoryAudit.objects.using(using).filter(ok=True).order_by("-created_at").first()
        if last is not None:
            start_seq, prev = last.head_seq, last.head_mac
    expected, checked = start_seq, 0
    events = (
        HistoryEvent.objects.using(using)
        .filter(seq__gt=start_seq)
        .order_by("seq")
        .values_list("seq", "model", "object_id", "label", "created_at", "snapshot", "prev_mac", "mac")
    )
    for seq, model, object_id, label, created_at, snapshot, prev_mac, mac in events.iterator(chunk_size=2000):
        expected += 1
        checked += 1
        if seq != expected:
            bad(seq, f"gap in seq: expected {expected}")
            expected = seq
        if prev_mac != prev:
            bad(seq, "prev_mac is not the previous event's mac")
        if mac_for(prev_mac, model, object_id, label, created_at, snapshot, key=key) != mac:
            bad(seq, "mac does not recompute from the row")
        prev = mac
    current = head(using)
    if current.seq != expected or current.mac != prev:
        bad(None, f"head is at {current.seq}, the last event at {expected}: the newest events differ from the head")
    for seq, mac in anchors():
        if seq <= start_seq and not full:
            continue
        recorded = HistoryEvent.objects.using(using).filter(seq=seq).values_list("mac", flat=True).first()
        if recorded is None:
            bad(seq, "anchored event is missing")
        elif recorded != mac:
            bad(seq, "anchored event's mac is not the anchor's")
    if full:
        for model, found in compare(using=using).items():
            bad(
                None,
                f"{model}: the replay differs from the live table: {len(found['missing'])} missing, "
                f"{len(found['extra'])} unrecorded, {len(found['changed'])} changed",
            )
    audit = HistoryAudit.objects.using(using).create(
        ok=not problems,
        full=full,
        events=checked,
        head_seq=current.seq,
        head_mac=current.mac,
        first_bad_seq=first_bad[0],
        report="\n".join(problems[:500]),
    )
    if problems:
        notify(audit)
    return audit


def notify(audit):
    recipients = getattr(settings, "HISTORY_AUDIT_RECIPIENTS", [])
    if not recipients:
        return
    where = f" The first bad event is #{audit.first_bad_seq}." if audit.first_bad_seq else ""
    send_mail(
        subject="History verification FAILED",
        message=f"The history verification of {audit.created_at:%Y-%m-%d %H:%M} UTC failed.{where}\n\n{audit.report}",
        from_email=None,
        recipient_list=list(recipients),
    )
