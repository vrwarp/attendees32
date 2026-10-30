"""The nightly prune of the access log; schedule it with django-celery-beat."""
from django.core.management import call_command

from config import celery_app


@celery_app.task()
def prune_access_log(months=12):
    call_command("prune_access_log", months=months)
