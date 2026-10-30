"""The access log: who looked at which record, or took which export, when and from where."""
from django.conf import settings
from django.db import models
from django.utils import timezone


class AccessLog(models.Model):
    DETAIL = "detail"
    EXPORT = "export"
    PRINT = "print"
    HOW = ((DETAIL, "detail page"), (EXPORT, "export"), (PRINT, "print"))

    when = models.DateTimeField(default=timezone.now, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="accesses"
    )
    user_name = models.CharField(max_length=150, blank=True, help_text="The username at the time")
    model = models.CharField(max_length=100, blank=True, help_text='The record\'s model, as "persons.attendee"; empty for an export')
    object_id = models.CharField(max_length=36, blank=True, help_text="The record's key as text")
    how = models.CharField(max_length=10, choices=HOW)
    endpoint = models.CharField(max_length=200, help_text="The route name, or the path")
    address = models.GenericIPAddressField(null=True, blank=True)
    details = models.JSONField(null=True, blank=True, help_text="An export's or print's filters; stored and shown, never filtered on")

    class Meta:
        db_table = "access_log"
        ordering = ("-when",)
        indexes = [
            models.Index(fields=["model", "object_id", "when"], name="access_log_record"),
            models.Index(fields=["user", "when"], name="access_log_user"),
        ]
        default_permissions = ("view",)  # never added, changed or deleted by hand

    def __str__(self):
        what = f"{self.model} {self.object_id}" if self.model else self.endpoint
        return f"{self.user_name or 'nobody'} {self.how} {what} at {self.when:%Y-%m-%d %H:%M}"
