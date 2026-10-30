"""Writes the request's access entries after the response, in a transaction of their own."""
import logging

from django.db import transaction

from .models import AccessLog

log = logging.getLogger(__name__)


class AccessLogMiddleware:
    """Sits before AtomicWritesMiddleware, so the rows land after the request's own transaction."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        entries = getattr(request, "_access_entries", None)
        if entries and 200 <= response.status_code < 300:
            try:
                self.write(request, entries)
            except Exception:  # the page was served; a failed log line must not turn it into an error
                log.exception("access log: could not write %d entries for %s", len(entries), request.path)
        return response

    @staticmethod
    def write(request, entries):
        user = getattr(request, "user", None)
        user_id = user.pk if user is not None and getattr(user, "is_authenticated", False) else None
        user_name = user.get_username() if user_id else ""
        address = request.META.get("REMOTE_ADDR") or None
        with transaction.atomic():
            AccessLog.objects.bulk_create(
                [
                    AccessLog(
                        user_id=user_id,
                        user_name=user_name,
                        model=entry["model"],
                        object_id=entry["object_id"],
                        how=entry["how"],
                        endpoint=entry["endpoint"],
                        address=address,
                        details=entry["details"],
                    )
                    for entry in entries
                ]
            )
