import time, pytz
from django.conf import settings
from django.contrib.postgres.aggregates.general import JSONBAgg
from django.db.models import Func, Value
from django.db.models.expressions import F
from django.db.models.functions import Concat, Trim
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet
from urllib import parse
from attendees.occasions.models import Gathering, Meet
from attendees.persons.models import (  # , Relationship
    Attendee,
    Folk,
    FolkAttendee,
    Relation,
)
from attendees.persons.serializers import AttendeeMinimalSerializer
from attendees.persons.services import (
    AttendeeMergeService,
    AttendeeService,
    AttendingMeetService,
    MergeRefused,
)


class AttendeeMergedAway(APIException):
    """410, with the forwarding address in the body.

    A merged attendee is soft-deleted, so without this the id a caller holds
    would simply 404 -- indistinguishable from a typo, and silent about the
    fact that the person still exists under a different id. Planning Center
    answers this case with a 410 carrying the survivor, and an integration that
    can follow one can follow the other.
    """

    status_code = status.HTTP_410_GONE
    default_code = "merged_away"

    def __init__(self, merged_into):
        super().__init__(
            {
                "detail": "That attendee was merged into another record.",
                "merged_into": str(merged_into),
            }
        )


class AttendeeGone(APIException):
    """410 for a trail that ends nowhere.

    Distinct from the above and deliberately without a forwarding address: the
    record was merged and the survivor was later deleted, or somebody edited a
    chain into a circle. "Gone, and nobody holds them now" is a different
    answer from "gone, ask over there", and a caller that cannot tell them
    apart will keep chasing.
    """

    status_code = status.HTTP_410_GONE
    default_code = "gone"
    default_detail = "That attendee is gone, and no record holds them now."


class ApiDatagridDataAttendeeViewSet(ModelViewSet):  # from GenericAPIView
    """
    API endpoint that allows single attendee to be viewed or edited.
    """

    serializer_class = AttendeeMinimalSerializer
    # queryset = Attendee.objects.all()

    # def retrieve(self, request, *args, **kwargs):
    #     attendee_id = self.kwargs.get('pk')
    #     attendee =  Attendee.objects.annotate(
    #                 attendingmeets=JSONBAgg(
    #                     Func(
    #                         Value('attendingmeet_id'), 'attendings__attendingmeet__id',
    #                         Value('attending_finish'), 'attendings__attendingmeet__finish',
    #                         Value('attending_start'), 'attendings__attendingmeet__start',
    #                         Value('meet_name'), 'attendings__meets__display_name',
    #                         function='jsonb_build_object'
    #                     ),
    #                 ),
    #                 # contacts=ArrayAgg('attendings__meets__slug', distinct=True),
    #            ).filter(pk=attendee_id)
    #     serializer = AttendeeMinimalSerializer(attendee)
    #     return Response(serializer.data)

    def retrieve(self, request, *args, **kwargs):
        """Answers for an id whose record has been merged away.

        The ordinary path is untouched: a live attendee is served by the
        default implementation reading `get_queryset`. This only decides what
        happens when that finds nothing, which used to be a bare 404 for three
        genuinely different situations -- never existed, deleted, merged. Only
        the last has anything useful to say, and it is the one an integration
        holding an old id actually hits.
        """
        if self.get_queryset().filter(pk=self.kwargs.get("pk")).exists():
            return super().retrieve(request, *args, **kwargs)

        held = Attendee.all_objects.filter(
            pk=self.kwargs.get("pk"),
            division__organization=request.user.organization,
        ).first()
        if held is not None and held.merged_into_id is not None:
            survivor = AttendeeMergeService.survivor_of(held)
            if survivor is None or survivor.is_removed:
                raise AttendeeGone()
            raise AttendeeMergedAway(survivor.pk)

        return super().retrieve(request, *args, **kwargs)

    @action(detail=True, methods=["post"], url_path="merge")
    def merge(self, request, pk=None):
        """Merges this attendee into the one named in the body.

        `POST /persons/api/datagrid_data_attendee/<loser>/merge/`
        with `{"survivor": "<uuid>"}`.

        Deliberately a POST to the *loser*: the thing being changed is this
        record, and the survivor is where it is going. Guarded by the same
        `privileged_to_edit` check as an ordinary edit, because a merge is a
        much larger edit than a rename -- it moves a person's attendance.
        """
        survivor_id = request.data.get("survivor")
        if not survivor_id:
            raise ValidationError({"survivor": "Name the attendee to merge into."})

        organization = request.user.organization
        loser = get_object_or_404(
            Attendee.all_objects, pk=pk, division__organization=organization
        )
        survivor = get_object_or_404(
            Attendee.all_objects, pk=survivor_id, division__organization=organization
        )

        if not request.user.privileged_to_edit(loser.id):
            time.sleep(2)
            raise PermissionDenied(detail="Not allowed to merge that attendee.")

        try:
            AttendeeMergeService.merge(loser, survivor)
        except MergeRefused as refusal:
            raise ValidationError({"survivor": str(refusal)})

        return Response(
            {"merged_into": str(survivor.pk)}, status=status.HTTP_200_OK
        )

    def get_queryset(self):
        """
        attendingmeets annotation is used by datagrid_assembly_data_attendees.js & datagrid_attendee_update_view.js

        Todo 20210704 rewrite following in DRF nested serializer to avoid manual screening of is_removed
        :return:
        """
        current_user = (
            self.request.user
        )  # Todo: guard this API so only admin or scheduler can call it.
        querying_attendee_id = self.kwargs.get("pk")
        querying_term = self.request.query_params.get("searchValue")

        if querying_attendee_id:
            qs = Attendee.objects.annotate(
                organization_slug=F("division__organization__slug"),
                attendingmeets=JSONBAgg(
                    Func(
                        Value("attending_id"),
                        "attendings__id",
                        Value("attending_is_removed"),
                        "attendings__is_removed",
                        Value("registration_assembly"),
                        "attendings__registration__assembly__display_name",
                        Value("registrant"),
                        Trim(
                            Concat(
                                Trim(
                                    Concat(
                                        "attendings__registration__registrant__first_name",
                                        Value(" "),
                                        "attendings__registration__registrant__last_name",
                                    )
                                ),
                                Value(" "),
                                Trim(
                                    Concat(
                                        "attendings__registration__registrant__last_name2",
                                        "attendings__registration__registrant__first_name2",
                                    )
                                ),
                            )
                        ),
                        function="jsonb_build_object",
                    ),
                ),
                # contacts=ArrayAgg('attendings__meets__slug', distinct=True),
            ).filter(
                division__organization=current_user.organization,
                pk=querying_attendee_id,
            )
        elif querying_term:
            qs = Attendee.objects.filter(
                infos__icontains=querying_term,
            )
        else:
            # A bare list is the caller's whole organization, paginated. It used
            # to raise UnboundLocalError (HTTP 500); integrations such as Tally
            # sweep the org roster this way. Ordered so take/skip pages are
            # stable between requests.
            qs = Attendee.objects.all().order_by("id")

        return qs.filter(division__organization=current_user.organization)

    def perform_create(self, serializer):
        """
        Some post processing can be added for a new attendee just created.  Gathering_id is higher priority than meet.
        """
        instance = serializer.save()
        raw_folk_id = self.request.META.get("HTTP_X_ADD_FOLK")
        role_id = self.request.META.get("HTTP_X_FOLK_ROLE")
        meet_id = self.request.META.get("HTTP_X_JOIN_MEET")
        character_slug = self.request.META.get("HTTP_X_JOIN_CHARACTER")
        gathering_id = self.request.META.get("HTTP_X_JOIN_GATHERING")

        meet = Meet.objects.filter(pk=meet_id).first()

        if raw_folk_id == "new" and role_id:
            folk = Folk.objects.create(
                category_id=0,  # family
                division=instance.division,
                display_name=f'{(instance.last_name + " ") if instance.last_name else ""}{instance.infos.get("names", {}).get("original", "")} family'
            )
            folk_id = folk.id
        else:
            folk_id = raw_folk_id

        if folk_id and role_id:
            FolkAttendee.objects.create(
                folk=get_object_or_404(Folk, pk=folk_id),
                attendee=instance,
                role=get_object_or_404(Relation, pk=role_id),
            )

        if gathering_id:  # elif is needed since using the very same function to add attendingmeet by gathering or meet
            gathering = get_object_or_404(Gathering, pk=gathering_id)
            attendee_to_attendingmeets_cache = AttendingMeetService.flip_attendingmeet_by_existing_attending(self.request.user, [instance], gathering.meet.id, True, None)
            # AttendanceService.join_attendance([instance], gathering, attendee_to_attendingmeets_cache)
        elif meet and meet.assembly.division.organization == self.request.user.organization:
            AttendingMeetService.flip_attendingmeet_by_existing_attending(self.request.user, [instance], meet_id, True, character_slug)

    def perform_update(self, serializer):
        target_attendee = get_object_or_404(
            Attendee, pk=self.request.META.get("HTTP_X_TARGET_ATTENDEE_ID")
        )
        tzname = (
            self.request.COOKIES.get("timezone")
            or target_attendee.division.organization.infos.get("default_time_zone")
            or settings.CLIENT_DEFAULT_TIME_ZONE
        )

        if self.request.user.privileged_to_edit(
            target_attendee.id
        ):  # intentionally forbid user delete him/herself
            instance = serializer.save()
            if self.request.META.get("HTTP_X_END_ALL_ATTENDEE_ACTIVITIES"):  # passed away
                AttendeeService.end_all_activities(instance, self.request.user.attendee_uuid_str())

            if self.request.META.get("HTTP_X_ADD_PAST"):
                AttendeeService.add_past(instance, self.request.META.get("HTTP_X_ADD_PAST"), pytz.timezone(parse.unquote(tzname)))

        else:
            time.sleep(2)
            raise PermissionDenied(
                detail=f"Not allowed to update {target_attendee.__class__.__name__}"
            )

    def perform_destroy(self, instance):
        target_attendee = get_object_or_404(
            Attendee, pk=self.request.META.get("HTTP_X_TARGET_ATTENDEE_ID")
        )
        if self.request.user.privileged_to_edit(
            target_attendee.id
        ):  # intentionally forbid user delete him/herself
            AttendeeService.destroy_with_associations(instance)
        else:
            time.sleep(2)
            raise PermissionDenied(
                detail=f"Not allowed to delete {instance.__class__.__name__}"
            )


api_datagrid_data_attendee_viewset = ApiDatagridDataAttendeeViewSet
