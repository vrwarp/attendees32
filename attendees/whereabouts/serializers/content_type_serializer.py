from django.contrib.contenttypes.models import ContentType
from rest_framework import serializers


class ContentTypeSerializer(serializers.ModelSerializer):
    """A content type as the site picker lists it, with the endpoint and hint from its extra."""

    endpoint = serializers.CharField(source="extra.endpoint", read_only=True)
    hint = serializers.CharField(source="extra.hint", read_only=True)

    class Meta:
        model = ContentType
        fields = ["id", "model", "endpoint", "hint"]
