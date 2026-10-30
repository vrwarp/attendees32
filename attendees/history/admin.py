"""The history in the admin: a record's events on its history page, every event on one list
that filters by who and when, and the restore action."""
import json

from django.contrib import admin, messages
from django.contrib.admin.utils import unquote
from django.utils.html import format_html, format_html_join

from .canonical import diff
from .models import HistoryAudit, HistoryEvent
from .tracking import SNAPSHOT, events_for


def rows_for(record, using=None):
    """The record's events with who made each and what each changed, oldest first."""
    rows, before = [], {}
    for event in events_for(record, using=using).select_related("context", "context__user"):
        rows.append(
            {
                "event": event,
                "who": event.context.who if event.context else "",
                "where": event.context.label if event.context else "",
                "changes": diff(before, event.snapshot),
                "snapshot": json.dumps(event.snapshot, indent=2, ensure_ascii=False, sort_keys=True),
            }
        )
        before = event.snapshot if event.label == SNAPSHOT else {}
    return rows


class HistoryPage:
    """Mixin for a ModelAdmin: its history page lists the record's events from the history table."""

    object_history_template = "admin/history/object_history.html"

    def history_view(self, request, object_id, extra_context=None):
        record = self.get_object(request, unquote(object_id))
        extra_context = dict(extra_context or {})
        extra_context["object_history"] = rows_for(record) if record is not None else []
        return super().history_view(request, object_id, extra_context=extra_context)


@admin.register(HistoryEvent)
class HistoryEventAdmin(admin.ModelAdmin):
    """Every event; filter by user and pick a period to see what one person changed."""

    list_display = ("seq", "created_at", "model", "object_id", "label", "who", "where")
    list_filter = ("model", "label", ("context__user", admin.RelatedOnlyFieldListFilter))
    date_hierarchy = "created_at"
    search_fields = ("object_id", "context__user_name", "context__label")
    list_select_related = ("context", "context__user")
    ordering = ("-seq",)
    fields = ("seq", "created_at", "model", "object_id", "label", "who", "where", "changed", "record", "prev_mac", "mac")
    readonly_fields = fields
    actions = ["restore_version"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_restore_permission(self, request):
        return request.user.has_perm("history.restore_historyevent")

    @admin.display(description="by")
    def who(self, event):
        return event.context.who if event.context else ""

    @admin.display(description="from")
    def where(self, event):
        return event.context.label if event.context else ""

    @admin.display(description="changed")
    def changed(self, event):
        changes = event.changes()
        if not changes:
            return "nothing recorded before this event"
        return format_html(
            "<table>{}</table>",
            format_html_join("", "<tr><th>{}</th><td>{}</td><td>→</td><td>{}</td></tr>", ((field, old, new) for field, (old, new) in changes.items())),
        )

    @admin.display(description="record")
    def record(self, event):
        return format_html("<pre>{}</pre>", json.dumps(event.snapshot, indent=2, ensure_ascii=False, sort_keys=True))

    @admin.action(description="Restore the record to this version", permissions=["restore"])
    def restore_version(self, request, queryset):
        if queryset.count() != 1:
            self.message_user(request, "Select exactly one event to restore.", messages.ERROR)
            return
        event = queryset.get()
        try:
            event.restore()
        except Exception as error:  # the save path raises whatever the record's validation raises
            self.message_user(request, f"Could not restore: {error}", messages.ERROR)
            return
        self.message_user(
            request,
            f"Restored {event.model} {event.object_id} to its version of {event.created_at:%Y-%m-%d %H:%M}; the restore is recorded as a new event.",
            messages.SUCCESS,
        )


@admin.register(HistoryAudit)
class HistoryAuditAdmin(admin.ModelAdmin):
    list_display = ("created_at", "ok", "full", "events", "head_seq", "first_bad_seq")
    list_filter = ("ok", "full")
    readonly_fields = ("created_at", "ok", "full", "events", "head_seq", "head_mac", "first_bad_seq", "report")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
