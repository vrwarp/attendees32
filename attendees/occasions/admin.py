
from django.contrib import messages
from django.contrib import admin
from django.db import models

from django_celery_beat.models import CrontabSchedule
from django_json_widget.widgets import JSONEditorWidget
from schedule.admin import CalendarAdmin, CalendarRelationAdmin, EventAdmin, EventRelationAdmin, RuleAdmin
from schedule.models import Calendar, CalendarRelation, Event, EventRelation, Rule

from attendees.occasions.models import Attendance, MessageTemplate, Assembly, Price, Character, Meet, Gathering, Team, \
    MeetAllowedModel
from django.conf import settings
from attendees.persons.models import Category
from attendees.history.admin import HistoryPage
from attendees.whereabouts.models import Organization, Division


admin.site.unregister(CrontabSchedule)
@admin.register(CrontabSchedule)
class CrontabScheduleAdmin(HistoryPage, admin.ModelAdmin):
    pass  # to make original model admin shows HistoryPage


# from django_celery_beat.models import IntervalSchedule
# admin.site.unregister(IntervalSchedule)
# @admin.register(IntervalSchedule)   # Somehow Admin UI shows no history
# class IntervalScheduleAdmin(HistoryPage, admin.ModelAdmin):
#     pass  # to make original model admin shows HistoryPage


# from django_celery_beat.models import PeriodicTask
# from django_celery_beat.admin import PeriodicTaskAdmin
# admin.site.unregister(PeriodicTask)
# @admin.register(PeriodicTask)       # Somehow Admin UI shows no history
# class PeriodicTaskAdmin(HistoryPage, PeriodicTaskAdmin):
#     pass  # to make original model admin shows HistoryPage


admin.site.unregister(Calendar)
@admin.register(Calendar)
class CalendarAdmin(HistoryPage, CalendarAdmin):
    pass  # to make original model admin shows HistoryPage


admin.site.unregister(CalendarRelation)
@admin.register(CalendarRelation)
class CalendarAdmin(HistoryPage, CalendarRelationAdmin):
    pass  # to make original model admin shows HistoryPage


admin.site.unregister(Rule)
@admin.register(Rule)
class CalendarAdmin(HistoryPage, RuleAdmin):
    pass  # to make original model admin shows HistoryPage


admin.site.unregister(Event)
@admin.register(Event)
class CalendarAdmin(HistoryPage, EventAdmin):
    pass  # to make original model admin shows HistoryPage


admin.site.unregister(EventRelation)
@admin.register(EventRelation)
class CalendarAdmin(HistoryPage, EventRelationAdmin):
    pass  # to make original model admin shows HistoryPage

# class AssemblyContactAdmin(admin.ModelAdmin):
#     readonly_fields = ['id', 'created', 'modified']
#     list_display = ('assembly', 'contact', 'modified')


# class AssemblyContactInline(admin.TabularInline):
#     model = AssemblyContact
#     extra = 0


class MessageTemplateAdmin(HistoryPage, admin.ModelAdmin):
    formfield_overrides = {
        models.JSONField: {"widget": JSONEditorWidget},
    }
    readonly_fields = ["id", "created", "modified"]
    list_display = ("truncate_template", "type", "modified")

    def truncate_template(self, obj):
        return list(obj.templates.values())[0][:100] + "..."

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "organization":
            kwargs["queryset"] = Organization.objects.all() if request.user.is_superuser else Organization.objects.filter(pk=request.user.organization_pk())
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            if request.resolver_match.func.__name__ == "changelist_view":
                messages.info(
                    request,
                    "You are seeing all records across organizations as a superuser.",
                )
            return qs
        else:
            if request.resolver_match.func.__name__ == "changelist_view":
                messages.warning(
                    request,
                    "Not all, but only those records accessible to you will be listed here.",
                )
            return qs.filter(organization=request.user.organization)


class AssemblyAdmin(HistoryPage, admin.ModelAdmin):
    formfield_overrides = {
        models.JSONField: {"widget": JSONEditorWidget},
    }
    prepopulated_fields = {"slug": ("display_name",)}
    # inlines = (AssemblyContactInline,)
    list_display_links = ("display_name",)
    list_display = ("id", "division", "display_name", "display_order", "slug", "get_addresses")
    readonly_fields = ["id", "created", "modified"]

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "division":
            kwargs["queryset"] = Division.objects.all() if request.user.is_superuser else Division.objects.filter(organization=request.user.organization)
        if db_field.name == "category":
            kwargs["queryset"] = Category.objects.filter(type='assembly')
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            if request.resolver_match.func.__name__ == "changelist_view":
                messages.info(
                    request,
                    "You are seeing all records across organizations as a superuser.",
                )
            return qs
        else:
            if request.resolver_match.func.__name__ == "changelist_view":
                messages.warning(
                    request,
                    "Not all, but only those records accessible to you will be listed here.",
                )
            return qs.filter(division__organization=request.user.organization)


class PriceAdmin(HistoryPage, admin.ModelAdmin):
    list_display = ("display_name", "price_type", "start", "price_value", "modified")

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "assembly":
            kwargs["queryset"] = Assembly.objects.all() if request.user.is_superuser else Assembly.objects.filter(division__organization=request.user.organization)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            if request.resolver_match.func.__name__ == "changelist_view":
                messages.info(
                    request,
                    "You are seeing all records across organizations as a superuser.",
                )
            return qs
        else:
            if request.resolver_match.func.__name__ == "changelist_view":
                messages.warning(
                    request,
                    "Not all, but only those records accessible to you will be listed here.",
                )
            return qs.filter(assembly__division__organization=request.user.organization)


class AttendanceAdmin(HistoryPage, admin.ModelAdmin):
    autocomplete_fields = ('attending', 'gathering',)
    formfield_overrides = {
        models.JSONField: {"widget": JSONEditorWidget},
    }
    list_display_links = ("get_attendee",)
    list_filter = (
        ("gathering", admin.RelatedOnlyFieldListFilter),
        ("character", admin.RelatedOnlyFieldListFilter),
        ("team", admin.RelatedOnlyFieldListFilter),
    )  # too many attendings even with ('attending', admin.RelatedOnlyFieldListFilter)
    list_display = (
        "id",
        "attendance_info",
        "get_attendee",
        "character",
        "team",
        "infos",
    )
    readonly_fields = ["id", "created", "modified"]
    fieldsets = (
        (
            None,
            {
                "fields": (
                    tuple(["start", "finish"]),
                    tuple(["gathering", "team"]),
                    tuple(["attending", "character"]),
                    tuple(["display_order", "category"]),
                    tuple(["id", "created", "modified"]),
                    tuple(["infos"]),
                ),
            },
        ),
    )

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "gathering":
            kwargs["queryset"] = Gathering.objects.all() if request.user.is_superuser else Gathering.objects.filter(meet__assembly__division__organization=request.user.organization)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            if request.resolver_match.func.__name__ == "changelist_view":
                messages.info(
                    request,
                    "You are seeing all records across organizations as a superuser.",
                )
            return qs
        else:
            if request.resolver_match.func.__name__ == "changelist_view" and not messages.get_messages(request):
                messages.warning(
                    request,
                    "Not all, but only those records accessible to you will be listed here.",
                )
            return qs.filter(gathering__meet__assembly__division__organization=request.user.organization)

    def get_attendee(self, obj):
        return obj.attending.attendee

    get_attendee.admin_order_field = "attendee"  # Allows column order sorting
    get_attendee.short_description = "attendee"  # Rename

    class Media:
        css = {"all": ("css/admin.css",)}
        js = ["js/admin/list_filter_collapse.js"]


class AttendanceInline(admin.StackedInline):
    model = Attendance
    extra = 0
    fieldsets = (
        (
            None,
            {
                "fields": (
                    tuple(["start", "finish", "free", "category"]),
                    tuple(["gathering", "team", "attending", "character"]),
                    tuple(["infos"]),
                ),
            },
        ),
    )
    #
    # def get_queryset(self, request):
    #     qs = super(AttendanceInline, self).get_queryset(request)
    #     return qs[:10]  # does not work


class CharacterAdmin(HistoryPage, admin.ModelAdmin):
    prepopulated_fields = {"slug": ("display_name",)}
    list_filter = ("assembly", "type")
    readonly_fields = ["id", "created", "modified"]
    list_display_links = ("display_name",)
    list_display = ("id", "assembly", "display_name", "slug", "display_order", "type")

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "assembly":
            kwargs["queryset"] = Assembly.objects.all() if request.user.is_superuser else Assembly.objects.filter(division__organization=request.user.organization)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            if request.resolver_match.func.__name__ == "changelist_view":
                messages.info(
                    request,
                    "You are seeing all records across organizations as a superuser.",
                )
            return qs
        else:
            if request.resolver_match.func.__name__ == "changelist_view" and not messages.get_messages(request):
                messages.warning(
                    request,
                    "Not all, but only those records accessible to you will be listed here.",
                )
            return qs.filter(assembly__division__organization=request.user.organization)

    class Media:
        css = {"all": ("css/admin.css",)}
        js = ["js/admin/list_filter_collapse.js"]


class TeamAdmin(HistoryPage, admin.ModelAdmin):
    prepopulated_fields = {"slug": ("display_name",)}
    readonly_fields = ["id", "created", "modified"]
    list_display_links = ("display_name",)
    list_display = ("id", "display_name", "slug", "meet", "display_order", "site")

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "meet":
            kwargs["queryset"] = Meet.objects.all() if request.user.is_superuser else Meet.objects.filter(assembly__division__organization=request.user.organization)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            if request.resolver_match.func.__name__ == "changelist_view":
                messages.info(
                    request,
                    "You are seeing all records across organizations as a superuser.",
                )
            return qs
        else:
            if request.resolver_match.func.__name__ == "changelist_view":
                messages.warning(
                    request,
                    "Not all, but only those records accessible to you will be listed here.",
                )
            return qs.filter(meet__assembly__division__organization=request.user.organization)


class MeetAllowedModelInline(admin.TabularInline):
    model = MeetAllowedModel
    extra = 0
    verbose_name = "page the meet is listed on"
    verbose_name_plural = "pages the meet is listed on"


class MeetAdmin(HistoryPage, admin.ModelAdmin):
    formfield_overrides = {
        models.JSONField: {"widget": JSONEditorWidget},
    }
    prepopulated_fields = {"slug": ("display_name",)}
    filter_horizontal = ("allowed_groups",)
    inlines = (MeetAllowedModelInline,)
    search_fields = ("display_name",)
    list_filter = ("assembly",)
    list_display_links = ("display_name",)
    list_display = ("id", "display_name", "slug", "assembly", "site")
    readonly_fields = ["schedule_text", "id", "created", "modified"]
    fieldsets = (
        (
            None,
            {
                "fields": (
                    tuple(["start", "finish", "slug"]),
                    tuple(
                        [
                            "display_name",
                            "major_character",
                            "infos",
                            "shown_audience",
                            "audience_editable",
                        ]
                    ),
                    tuple(["allowed_groups"]),
                    tuple(["site_type", "assembly", "site_id"]),
                    tuple(["id", "created", "modified"]),
                    tuple(["schedule_text"]),
                ),
            },
        ),
    )

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "assembly":
            kwargs["queryset"] = Assembly.objects.all() if request.user.is_superuser else Assembly.objects.filter(division__organization=request.user.organization)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def schedule_text(self, obj):
        schedules = obj.schedule_text(timezone_name=settings.CLIENT_DEFAULT_TIME_ZONE)
        return f"Please {'change' if schedules else 'add'} in the 'Event Relations' section. {schedules}"

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            if request.resolver_match.func.__name__ == "changelist_view":
                messages.info(
                    request,
                    "You are seeing all records across organizations as a superuser.",
                )
            return qs
        else:
            if request.resolver_match.func.__name__ == "changelist_view":
                messages.warning(
                    request,
                    "Not all, but only those records accessible to you will be listed here.",
                )
            return qs.filter(assembly__division__organization=request.user.organization)

    class Media:
        css = {"all": ("css/admin.css",)}
        js = ["js/admin/list_filter_collapse.js"]


class GatheringAdmin(HistoryPage, admin.ModelAdmin):
    formfield_overrides = {
        models.JSONField: {"widget": JSONEditorWidget},
    }
    # inlines = (AttendanceInline,)  # too many and haven't found easy way to limit inline models
    list_display_links = ("display_name",)
    search_fields = ("meet__display_name", "display_name")
    list_filter = ("meet",)
    list_display = ("id", "meet", "start", "display_name", "site", "infos")
    readonly_fields = ["id", "created", "modified"]
    fieldsets = (
        (
            None,
            {
                "fields": (
                    tuple(["start", "finish"]),
                    tuple(["display_name", "infos"]),
                    tuple(["site_type", "meet", "site_id"]),
                    tuple(["id", "created", "modified"]),
                ),
            },
        ),
    )

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "meet":
            kwargs["queryset"] = Meet.objects.all() if request.user.is_superuser else Meet.objects.filter(assembly__division__organization=request.user.organization)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            messages.info(
                request,
                "You are seeing all records across organizations as a superuser.",
            )
            return qs
        else:
            if request.resolver_match.func.__name__ == "changelist_view":
                messages.warning(
                    request,
                    "Not all, but only those records accessible to you will be listed here.",
                )
            return qs.filter(meet__assembly__division__organization=request.user.organization)

    class Media:
        css = {"all": ("css/admin.css",)}
        js = ["js/admin/list_filter_collapse.js"]


admin.site.register(MessageTemplate, MessageTemplateAdmin)
admin.site.register(Assembly, AssemblyAdmin)
admin.site.register(Price, PriceAdmin)
admin.site.register(Character, CharacterAdmin)
admin.site.register(Meet, MeetAdmin)
admin.site.register(Gathering, GatheringAdmin)
admin.site.register(Team, TeamAdmin)
admin.site.register(Attendance, AttendanceAdmin)
