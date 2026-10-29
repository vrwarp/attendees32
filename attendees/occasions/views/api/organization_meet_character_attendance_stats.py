import time, ast

from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from rest_framework import viewsets
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.response import Response
from rest_framework.utils import json

from attendees.occasions.serializers import AttendanceStatsSerializer
from attendees.occasions.services import AttendanceService


@method_decorator([login_required], name="dispatch")
class ApiOrganizationMeetCharacterAttendanceStatsViewSet(viewsets.ModelViewSet):
    """
    API endpoint that allows Stats of Attendance to be returned, currently not support sorting
    and search only support attendee's names
    """

    serializer_class = AttendanceStatsSerializer

    def count_params(self):
        params = self.request.query_params
        return dict(
            user_organization=self.request.user.organization,
            meet_slugs=params.getlist("meets[]", []),
            character_slugs=params.getlist("characters[]", []),
            team_ids=params.getlist("teams[]", []),
            category_ids=params.getlist("categories[]", []),
            start=params.get("start"),
            finish=params.get("finish"),
            name_search=ast.literal_eval(params.get("filter", "[[None]]")),
        )

    def get_queryset(self):
        if self.request.user.organization:
            orderby_list = json.loads(
                self.request.query_params.get(
                    "sort",
                    '[{"selector":"count","desc":true},{"selector":"attending_name","desc":false}]',
                )
            )
            # The start/finish will filter on Gathering instead of Attendance!!
            return AttendanceService.attendance_count(orderbys=orderby_list, **self.count_params())

        else:
            time.sleep(2)
            raise AuthenticationFailed(
                detail="Has your account assigned an organization?"
            )

    def list(self, request, *args, **kwargs):
        """The characters and teams columns are filled once the page is known."""
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        rows = page if page is not None else list(queryset)
        AttendanceService.attach_characters_and_teams(
            rows, AttendanceService.attendance_count_filters(**self.count_params())
        )
        serializer = self.get_serializer(rows, many=True)
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)


api_organization_meet_character_attendance_stats_viewset = ApiOrganizationMeetCharacterAttendanceStatsViewSet
