from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from attendees.pcosync.models import PcoDivergence, PcoPersonLink
from attendees.pcosync.serializers import (
    LinkSerializer,
    PcoDivergenceSerializer,
    ResolveSerializer,
)
from attendees.persons.models import Attendee


class ApiPcoDivergencesViewSet(viewsets.ModelViewSet):
    """The report, and the two things a person can do about a row."""

    serializer_class = PcoDivergenceSerializer
    permission_classes = (IsAuthenticated,)
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        queryset = PcoDivergence.objects.filter(
            organization=self.request.user.organization, is_removed=False,
        ).select_related("attendee", "link")

        resolution = self.request.query_params.get("resolution", "open")
        if resolution != "all":
            queryset = queryset.filter(resolution=resolution)
        kind = self.request.query_params.get("kind")
        if kind:
            queryset = queryset.filter(kind=kind)
        severity = self.request.query_params.get("severity")
        if severity:
            queryset = queryset.filter(severity=severity)
        search = self.request.query_params.get("q")
        if search:
            queryset = queryset.filter(
                Q(label__icontains=search) | Q(pointer__icontains=search)
                | Q(pco_person_id=search)
            )
        return queryset.order_by("severity", "kind", "pointer")

    @action(detail=True, methods=["patch", "post"])
    def resolve(self, request, pk=None):
        """Settle one disagreement by moving the baseline.

        Recording the *losing* side as the last agreement makes the next
        ordinary run see exactly one side as changed, and it applies the winner
        through the same code path as everything else. Nothing is written here.
        """
        divergence = self.get_object()
        if not request.user.is_data_admin():
            return Response({"detail": "only a data admin can resolve these"},
                            status=status.HTTP_403_FORBIDDEN)

        form = ResolveSerializer(data=request.data)
        form.is_valid(raise_exception=True)
        resolution = form.validated_data["resolution"]

        link = divergence.link
        field_key = _field_key_for(divergence.pointer)

        with transaction.atomic():
            if link is not None and field_key:
                if resolution == PcoDivergence.IGNORED:
                    infos = dict(link.infos or {})
                    ignored = set(infos.get("ignored_fields") or [])
                    ignored.add(field_key)
                    infos["ignored_fields"] = sorted(ignored)
                    link.infos = infos
                else:
                    baseline = dict(link.baseline or {})
                    # Keep local -> record what Planning Center holds as agreed,
                    # so next run sees only attendees32 as having moved.
                    baseline[field_key] = (
                        divergence.pco_value
                        if resolution == PcoDivergence.KEEP_LOCAL
                        else divergence.local_value
                    )
                    link.baseline = baseline
                link.save()

            divergence.resolution = resolution
            divergence.resolved_by = request.user
            divergence.resolved_at = timezone.now()
            divergence.save()

        return Response(PcoDivergenceSerializer(divergence).data)

    @action(detail=True, methods=["patch", "post"])
    def link(self, request, pk=None):
        """Say which attendee an unmatched Planning Center person is.

        The manual half of matching. Suggestions are offered by the sync but
        never acted on, because a wrong automatic link costs far more to undo
        than an unanswered question costs to answer.
        """
        divergence = self.get_object()
        if not request.user.is_data_admin():
            return Response({"detail": "only a data admin can link people"},
                            status=status.HTTP_403_FORBIDDEN)
        if divergence.kind != PcoDivergence.UNLINKED_PERSON:
            return Response({"detail": "this row is not an unmatched person"},
                            status=status.HTTP_400_BAD_REQUEST)

        form = LinkSerializer(data=request.data)
        form.is_valid(raise_exception=True)
        attendee = Attendee.objects.filter(
            pk=form.validated_data["attendee_id"],
            division__organization=request.user.organization,
        ).first()
        if attendee is None:
            return Response({"detail": "no such attendee in your organization"},
                            status=status.HTTP_404_NOT_FOUND)

        with transaction.atomic():
            already = PcoPersonLink.objects.filter(
                organization=request.user.organization, attendee=attendee,
                state=PcoPersonLink.LIVE, is_removed=False,
            ).exclude(pco_person_id=divergence.pco_person_id).first()
            if already is not None:
                return Response(
                    {"detail": f"that attendee is already linked to Planning "
                               f"Center person {already.pco_person_id}"},
                    status=status.HTTP_409_CONFLICT,
                )

            link = divergence.link or PcoPersonLink.objects.filter(
                organization=request.user.organization,
                pco_person_id=divergence.pco_person_id, is_removed=False,
            ).first()
            if link is None:
                link = PcoPersonLink(
                    organization=request.user.organization,
                    pco_person_id=divergence.pco_person_id,
                )
            link.attendee = attendee
            link.state = PcoPersonLink.LIVE
            link.link_source = PcoPersonLink.BY_MATCH
            # No baseline: the two have never agreed on anything yet, so the
            # next run treats every field as a first look rather than assuming
            # a history that did not happen.
            link.baseline = {}
            link.save()

            divergence.attendee = attendee
            divergence.link = link
            divergence.resolution = PcoDivergence.RESOLVED_ELSEWHERE
            divergence.resolved_by = request.user
            divergence.resolved_at = timezone.now()
            divergence.save()

        return Response(PcoDivergenceSerializer(divergence).data)

    @action(detail=False, methods=["get"])
    def attendee_search(self, request):
        """Feed the manual picker.

        Searches the derived name forms as well as the columns, because
        ``Attendee.save()`` keeps romanized and converted spellings in
        ``infos["names"]`` -- which is how somebody typing "Tsai" finds 蔡.
        """
        term = (request.query_params.get("q") or "").strip()
        if len(term) < 2:
            return Response([])
        matches = Attendee.objects.filter(
            Q(first_name__icontains=term) | Q(last_name__icontains=term)
            | Q(first_name2__icontains=term) | Q(last_name2__icontains=term)
            | Q(infos__names__original__icontains=term)
            | Q(infos__names__romanization__icontains=term),
            division__organization=request.user.organization,
        ).select_related("division")[:25]
        return Response([
            {"attendee_id": str(attendee.id),
             "display_label": attendee.display_label,
             "division": attendee.division_label}
            for attendee in matches
        ])


def _field_key_for(pointer):
    """``$.person.first_name`` -> ``first_name``."""
    from attendees.pcosync.mapping import PERSON_FIELDS

    for field in PERSON_FIELDS:
        if field.pointer == pointer:
            return field.key
    return None


api_pco_divergences_viewset = ApiPcoDivergencesViewSet
