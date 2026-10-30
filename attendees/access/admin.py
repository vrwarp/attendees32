"""The review pages: who viewed this person, who exported the directory. Read-only, for the data owner."""
import json

from django.contrib import admin
from django.utils.html import format_html

from .models import AccessLog


@admin.register(AccessLog)
class AccessLogAdmin(admin.ModelAdmin):
    list_display = ("when", "user_name", "how", "model", "object_id", "endpoint", "address")
    list_filter = ("how", "model", ("user", admin.RelatedOnlyFieldListFilter))
    date_hierarchy = "when"
    search_fields = ("object_id", "user_name", "endpoint")
    list_select_related = ("user",)
    fields = ("when", "user", "user_name", "how", "model", "object_id", "endpoint", "address", "filters")
    readonly_fields = fields

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="filters")
    def filters(self, entry):
        if not entry.details:
            return ""
        return format_html("<pre>{}</pre>", json.dumps(entry.details, indent=2, ensure_ascii=False, sort_keys=True))
