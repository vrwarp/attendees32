"""Celery tasks for the history's daily routine; schedule them with django-celery-beat.

``anchor_history`` once a day, ``verify_history`` (full) once a night after
it, and ``verify_history_incremental`` whenever a quick check is wanted.
"""
from config import celery_app

from . import ledger


@celery_app.task()
def anchor_history():
    return ledger.anchor()


@celery_app.task()
def verify_history():
    audit = ledger.verify(full=True)
    return {"ok": audit.ok, "events": audit.events, "head_seq": audit.head_seq, "first_bad_seq": audit.first_bad_seq}


@celery_app.task()
def verify_history_incremental():
    audit = ledger.verify(full=False)
    return {"ok": audit.ok, "events": audit.events, "head_seq": audit.head_seq, "first_bad_seq": audit.first_bad_seq}
