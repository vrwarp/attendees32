import time

from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.contenttypes.models import ContentType
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.generics import ListAPIView

from attendees.whereabouts.serializers import ContentTypeSerializer


class ApiContentTypeListAPIView(LoginRequiredMixin, ListAPIView):
    """
    Restricted endpoint that allows ContentType to be viewed, need search params of 'query' to filter the models.
    """

    serializer_class = ContentTypeSerializer
    model = ContentType

    def get_queryset(self):
        if self.request.user.organization:
            genre = self.request.query_params.get("query")
            if not genre:
                return ContentType.objects.none()
            types = (
                ContentType.objects.select_related("extra")
                .filter(extra__genres=genre)
                .order_by("extra__display_order")
            )
            content_type_id = self.kwargs.get("pk")
            return types.filter(pk=content_type_id) if content_type_id else types
        else:
            time.sleep(2)
            raise AuthenticationFailed(
                detail="Have your account assigned an organization?"
            )


content_type_list_api_view = ApiContentTypeListAPIView
