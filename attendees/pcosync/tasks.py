"""The Celery side of the Sync button.

``CELERY_TASK_SOFT_TIME_LIMIT`` is 60 seconds for good reason -- it protects
every other task in the project -- so this does not raise it globally. It sets
its own limits and, more importantly, keeps progress in the database rather than
in the worker's memory, so a restart resumes instead of starting a
full-organization sweep again.
"""

import logging

import pghistory
from celery.exceptions import Ignore, SoftTimeLimitExceeded
from django.core.cache import cache
from django.utils import timezone

from attendees.pcosync.models import PcoSyncRun
from attendees.pcosync.services.runner import run_sync
from config import celery_app

logger = logging.getLogger(__name__)

LOCK_PREFIX = "pcosync:run"
LOCK_TTL_SECONDS = 60 * 60


def lock_key(organization_id):
    return f"{LOCK_PREFIX}:{organization_id}"


def acquire_lock(organization_id, run_id):
    """One live run per organization.

    Belt and braces: the view also checks for a live run row, but two people
    pressing the button at the same moment can both pass that check, and two
    concurrent syncs would race each other's baselines.
    """
    return cache.add(lock_key(organization_id), str(run_id), LOCK_TTL_SECONDS)


def release_lock(organization_id, run_id):
    if cache.get(lock_key(organization_id)) == str(run_id):
        cache.delete(lock_key(organization_id))


@celery_app.task(bind=True, soft_time_limit=600, time_limit=900, max_retries=0)
def pcosync_run(self, run_id):
    """Execute one run.

    The per-task limits are set here rather than by raising the global ones,
    which exist to stop a stuck task holding a worker.
    """
    run = PcoSyncRun.objects.filter(pk=run_id).first()
    if run is None:
        logger.warning("pcosync run %s no longer exists", run_id)
        return {"state": "missing"}

    if not acquire_lock(run.organization_id, run.id):
        run.state = PcoSyncRun.CANCELLED
        run.error = "another sync is already running for this organization"
        run.add_log(run.error, "warning", timezone.now())
        run.save()
        return {"state": run.state, "error": run.error}

    try:
        with pghistory.context(modifier="pcomirror sync", run=str(run.id)):
            run_sync(run)
    except SoftTimeLimitExceeded:
        # Persist what we know before the hard limit arrives, so the next run
        # picks up from here rather than from the beginning.
        run.refresh_from_db()
        run.state = PcoSyncRun.FAILED
        run.error = "the sync ran out of time and stopped part-way"
        run.add_log(run.error, "error", timezone.now())
        run.finished_at = timezone.now()
        run.save()
        raise Ignore()
    finally:
        release_lock(run.organization_id, run.id)

    run.refresh_from_db()
    return {"state": run.state, "counts": run.counts, "id": str(run.id)}
