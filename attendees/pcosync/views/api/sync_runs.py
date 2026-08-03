from django.db.models import Count
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from attendees.pcosync.models import PcoDivergence, PcoSyncRun
from attendees.pcosync.serializers import PcoSyncRunSerializer, StartRunSerializer
from attendees.pcosync.services.config import config_for
from attendees.pcosync.tasks import pcosync_run


class ApiPcoSyncRunsViewSet(viewsets.ModelViewSet):
    """Start a run, watch it, stop it."""

    serializer_class = PcoSyncRunSerializer
    permission_classes = (IsAuthenticated,)
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        # Scoped to the caller's own organization. Runs carry counts and log
        # lines about real people, so this is a data boundary, not tidiness.
        return PcoSyncRun.objects.filter(
            organization=self.request.user.organization
        ).order_by("-created")

    def create(self, request, *args, **kwargs):
        organization = request.user.organization
        if organization is None:
            return Response({"detail": "you belong to no organization"},
                            status=status.HTTP_403_FORBIDDEN)
        if not request.user.is_data_admin():
            return Response({"detail": "only a data admin can start a sync"},
                            status=status.HTTP_403_FORBIDDEN)

        config = config_for(organization)
        reason = config.blocking_reason()
        if reason:
            return Response({"detail": reason},
                            status=status.HTTP_400_BAD_REQUEST)

        live = PcoSyncRun.objects.filter(
            organization=organization, state__in=PcoSyncRun.LIVE_STATES
        ).first()
        if live is not None:
            return Response(
                {"detail": "a sync is already running for this organization",
                 "run": PcoSyncRunSerializer(live).data},
                status=status.HTTP_409_CONFLICT,
            )

        form = StartRunSerializer(data=request.data)
        form.is_valid(raise_exception=True)
        run = PcoSyncRun.objects.create(
            organization=organization, started_by=request.user,
            mode=form.validated_data["mode"],
        )
        pcosync_run.delay(str(run.id))
        return Response(PcoSyncRunSerializer(run).data,
                        status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        """Ask a run to stop at the next person.

        Cooperative rather than a kill: stopping mid-person could leave an
        attendee written and its baseline unstamped, which reads as a conflict
        on the next run.
        """
        run = self.get_object()
        run.cancel_requested = True
        run.save()
        return Response(PcoSyncRunSerializer(run).data)

    @action(detail=False, methods=["get"])
    def summary(self, request):
        organization = request.user.organization
        counts = (
            PcoDivergence.objects.filter(
                organization=organization, resolution=PcoDivergence.OPEN,
                is_removed=False,
            )
            .values("kind", "severity")
            .annotate(total=Count("id"))
            .order_by("-total")
        )
        latest = self.get_queryset().first()
        return Response({
            "config": config_for(organization).redacted() if organization else {},
            "open_divergences": list(counts),
            "latest_run": PcoSyncRunSerializer(latest).data if latest else None,
        })


api_pco_sync_runs_viewset = ApiPcoSyncRunsViewSet
