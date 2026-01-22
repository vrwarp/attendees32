import logging
from config import celery_app
from attendees.persons.models import Attendee
from attendees.persons.services.pco_service import PCOService

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=3)
def pco_sync_task(self, limit=None):
    """
    Celery task to sync attendees to Planning Center Online.
    """
    try:
        logger.info("Starting PCO Sync Task...")
        service = PCOService()

        attendees = Attendee.objects.filter(is_removed=False)
        if limit:
            attendees = attendees[:limit]

        count = 0
        for attendee in attendees:
            try:
                service.sync_attendee(attendee)
                count += 1
            except Exception as e:
                logger.error(f"Failed to sync {attendee.id}: {e}")

        logger.info(f"PCO Sync Task completed. Synced {count} attendees.")
        return f"Synced {count} attendees"

    except Exception as exc:
        logger.error(f"PCO Sync Task failed: {exc}")
        # Retry with exponential backoff
        raise self.retry(exc=exc, countdown=2 ** self.request.retries)
