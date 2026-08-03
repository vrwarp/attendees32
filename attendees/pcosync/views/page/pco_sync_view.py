from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.utils.decorators import method_decorator
from django.views.generic.list import ListView

from attendees.pcosync.models import PcoDivergence, PcoSyncRun
from attendees.pcosync.services.config import config_for
from attendees.users.authorization import RouteGuard


@method_decorator([login_required], name="dispatch")
class PcoSyncView(RouteGuard, ListView):
    """The Sync page.

    RouteGuard reads the Menu table, so this page is a bare 403 until the
    accompanying migration has seeded a Menu row and granted it to a group.
    """

    queryset = []
    template_name = "pcosync/pco_sync_view.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        organization = self.request.user.organization
        config = config_for(organization) if organization else None

        context.update({
            # redacted(): the API key never reaches a template. It is in the
            # organization's infos and therefore in its history, which is bad
            # enough without also rendering it into a page.
            "pcosync_config": config.redacted() if config else {},
            "pcosync_blocking_reason": (
                config.blocking_reason() if config
                else "you belong to no organization"
            ),
            "pcosync_runs": PcoSyncRun.objects.filter(
                organization=organization).order_by("-created")[:10],
            "pcosync_open_counts": list(
                PcoDivergence.objects.filter(
                    organization=organization,
                    resolution=PcoDivergence.OPEN, is_removed=False,
                ).values("kind", "severity").annotate(total=Count("id"))
                .order_by("-total")
            ),
            "pcosync_runs_endpoint": "/pcosync/api/sync_runs/",
            "pcosync_divergences_endpoint": "/pcosync/api/divergences/",
            "pcosync_attendee_search_endpoint":
                "/pcosync/api/divergences/attendee_search/",
            "user_is_data_admin": self.request.user.is_data_admin(),
        })
        return context


pco_sync_view = PcoSyncView.as_view()
