from django.urls import include, path
from rest_framework import routers

from attendees.pcosync.views import (
    ApiPcoDivergencesViewSet,
    ApiPcoSyncRunsViewSet,
    pco_sync_view,
)

app_name = "pcosync"

router = routers.DefaultRouter()
router.register(r"sync_runs", ApiPcoSyncRunsViewSet, basename="sync_runs")
router.register(r"divergences", ApiPcoDivergencesViewSet, basename="divergences")

urlpatterns = [
    path("api/", include(router.urls)),
    path("sync/", view=pco_sync_view, name="pco_sync_view"),
]
